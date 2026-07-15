# どこで: `src/grafix/interactive/runtime/video_recorder.py`。
# 何を: ffmpeg に raw RGB フレームを流し、動画として保存する最小録画器を提供する。
# なぜ: interactive プレビューを滑らかな動画として残せるようにするため。

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from grafix.core.output_paths import output_path_for_draw


DEFAULT_VIDEO_FINALIZE_TIMEOUT_S = 30.0
_DEFAULT_PROCESS_ABORT_TIMEOUT_S = 4.0
_MAX_PROCESS_ABORT_RESERVE_S = 1.0
_MIN_PROCESS_REAP_GRACE_S = 0.5


class VideoPublishError(RuntimeError):
    """完成した動画を final path へ公開できなかったことを表す。

    ``recovery_path`` は encoder 完了・file fsync 済みの staging であり、
    呼び出し側が回収・改名・削除の所有権を持つ。
    """

    def __init__(self, message: str, *, recovery_path: Path) -> None:
        super().__init__(message)
        self.recovery_path = Path(recovery_path)


def default_video_output_path(
    draw: Callable[[float], object], *, run_id: str | None = None, ext: str = "mp4"
) -> Path:
    """draw の定義元に基づく動画の既定保存パスを返す。

    Notes
    -----
    パスは `output/{kind}/` 配下で sketch_dir のサブディレクトリ構造をミラーする。
    """

    suffix = str(ext).lstrip(".") or "mp4"
    return output_path_for_draw(kind="video", ext=suffix, draw=draw, run_id=run_id)


def _ffmpeg_command(
    *,
    output_path: Path,
    size: tuple[int, int],
    fps: float,
) -> list[str]:
    width, height = size
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-video_size",
        f"{int(width)}x{int(height)}",
        "-framerate",
        str(float(fps)),
        "-i",
        "-",
        "-vf",
        "vflip,pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]


def _temporary_video_output_path(output_path: Path) -> Path:
    """最終出力と同じディレクトリに、コンテナ拡張子を保った一時パスを作る。"""

    suffix = output_path.suffix or ".tmp"
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{output_path.stem}.recording-",
        suffix=suffix,
        dir=output_path.parent,
    )
    os.close(fd)
    return Path(raw_path)


def _fsync_file(path: Path) -> None:
    """encoder が閉じた完成 temp の内容を publish 前に永続化する。"""

    with path.open("rb") as file_obj:
        os.fsync(file_obj.fileno())


def _fsync_directory(path: Path) -> None:
    """rename/link による directory entry を best-effort ではなく確定する。"""

    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _abort_process(
    proc: subprocess.Popen[bytes],
    *,
    timeout_s: float = _DEFAULT_PROCESS_ABORT_TIMEOUT_S,
) -> None:
    """encoder を best-effort で停止・回収し、pipe descriptor も閉じる。"""

    timeout = float(timeout_s)
    if not math.isfinite(timeout) or timeout < 0.0:
        timeout = 0.0
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    # communicate() 自体が KeyboardInterrupt / I/O error で失敗した場合にも、
    # ffmpeg を orphan/zombie として残さない。cleanup error は元の error を隠さない。
    if getattr(proc, "returncode", None) is None:
        try:
            proc.terminate()
        except BaseException:
            pass
    try:
        # terminate が無視されても kill/reap 用に半分の budget を残す。
        proc.wait(timeout=remaining() / 2.0)
    except BaseException:
        pass
    if getattr(proc, "returncode", None) is None:
        try:
            proc.kill()
        except BaseException:
            pass
        try:
            proc.wait(timeout=remaining())
        except BaseException:
            pass

    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(proc, name, None)
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except BaseException:
                pass


def _unlink_if_identity(path: Path, expected: tuple[int, int]) -> None:
    """今回 publish した inode のままなら rollback する。"""

    try:
        result = path.stat(follow_symlinks=False)
        if (int(result.st_dev), int(result.st_ino)) == expected:
            path.unlink()
    except BaseException:
        pass


class VideoRecorder:
    """raw RGB フレーム列を動画へ保存する録画器。

    入力 frame は ``size`` どおりの RGB24 とし、H.264 側では必要な場合だけ右端・下端を
    1 px pad して、yuv420p が要求する偶数寸法へ揃える。
    """

    def __init__(
        self,
        *,
        output_path: Path,
        size: tuple[int, int],
        fps: float,
        no_clobber: bool = False,
    ) -> None:
        """録画器を初期化して ffmpeg を起動する。"""

        _output_path = Path(output_path)
        _output_path.parent.mkdir(parents=True, exist_ok=True)

        _fps = float(fps)
        if not math.isfinite(_fps) or _fps <= 0:
            raise ValueError("fps は有限の正の値である必要がある")

        width, height = size
        if int(width) <= 0 or int(height) <= 0:
            raise ValueError("size は正の (width, height) である必要がある")

        self.path = _output_path
        self.size = (int(width), int(height))
        self.fps = _fps
        self.no_clobber = bool(no_clobber)
        self._frame_bytes = self.size[0] * self.size[1] * 3
        self._proc: subprocess.Popen[bytes] | None = None
        # ffmpeg は最終ファイルを直接開かない。正常終了後に同一ファイルシステム上で
        # atomic replace することで、録画途中や encoder 失敗時も既存動画を保持する。
        temporary_path = _temporary_video_output_path(self.path)
        self._temporary_path: Path | None = temporary_path

        cmd = _ffmpeg_command(
            output_path=temporary_path,
            size=self.size,
            fps=self.fps,
        )
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            self._remove_temporary_output()
            raise RuntimeError("ffmpeg が見つかりません（PATH を確認してください）") from e
        except BaseException:
            self._remove_temporary_output()
            raise

        if self._proc.stdin is None:
            _abort_process(self._proc)
            self._proc = None
            self._remove_temporary_output()
            raise RuntimeError("ffmpeg stdin pipe の作成に失敗しました")

    def _remove_temporary_output(self) -> None:
        """未確定の録画ファイルを best-effort で削除する。"""

        temporary_path = self._temporary_path
        self._temporary_path = None
        if temporary_path is None:
            return
        try:
            temporary_path.unlink(missing_ok=True)
        except BaseException:
            # cleanup 失敗で元の encoder error を隠さない。dotfile の一時ファイルは
            # 最終成果物と区別でき、次回録画が同じ名前を再利用することもない。
            pass

    def write_frame_rgb24(self, frame: bytes) -> None:
        """1 フレーム分の RGB24 バイト列を書き込む。"""

        proc = self._proc
        if proc is None:
            raise RuntimeError("録画は終了しています")
        if len(frame) != self._frame_bytes:
            raise ValueError(
                f"frame bytes が想定サイズと一致しません: got={len(frame)}, expected={self._frame_bytes}"
            )
        stdin = proc.stdin
        if stdin is None:
            raise RuntimeError("ffmpeg stdin pipe が閉じられています")
        try:
            stdin.write(frame)
        except (BrokenPipeError, OSError) as e:
            width, height = self.size
            raise RuntimeError(
                "ffmpeg への frame 書き込みに失敗しました"
                f": path={self.path}, input_size={width}x{height}, fps={self.fps:g}"
            ) from e

    def abort(self) -> None:
        """未確定の録画を公開せず停止し、process/temp を回収する。"""

        proc = self._proc
        self._proc = None
        if proc is not None:
            _abort_process(proc)
        self._remove_temporary_output()

    def _finish_encoding(
        self,
        *,
        timeout_s: float = DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
    ) -> Path | None:
        """ffmpeg を正常終了させ、fsync 済み staging path を返す。"""

        timeout = float(timeout_s)
        if not math.isfinite(timeout) or timeout < 0.0:
            raise ValueError("timeout_s は有限の 0 以上である必要があります")

        proc = self._proc
        if proc is None:
            return None
        # communicate に全budgetを渡すと、期限ちょうどのTimeoutExpired後に
        # kill済みprocessをreapする時間が0になりzombieを残し得る。通常は
        # timeoutの一部（最大1秒）をabort/reap用に予約する。timeout=0でも
        # resource cleanupだけは短い固定grace内で完了を試す。
        abort_reserve = min(_MAX_PROCESS_ABORT_RESERVE_S, timeout / 2.0)
        communicate_timeout = max(0.0, timeout - abort_reserve)
        deadline = time.monotonic() + timeout

        def abort_budget() -> float:
            remaining = min(
                _DEFAULT_PROCESS_ABORT_TIMEOUT_S,
                max(0.0, deadline - time.monotonic()),
            )
            return max(_MIN_PROCESS_REAP_GRACE_S, remaining)

        try:
            # communicate() は stdin を flush してから close する。
            # 先に stdin.close() すると Python 3.12 では flush-of-closed で落ちる場合があるため、
            # ここでは input=b"" で EOF を送って終了させる。
            _stdout, stderr = proc.communicate(input=b"", timeout=communicate_timeout)
        except subprocess.TimeoutExpired as exc:
            # encoder の hang で UI shutdown を無限に塞がない。完成していない
            # temp は公開せず、process は terminate/kill/wait で回収を試みる。
            _abort_process(proc, timeout_s=abort_budget())
            self._remove_temporary_output()
            width, height = self.size
            raise TimeoutError(
                "ffmpeg の終了がタイムアウトしました"
                f": timeout={timeout:g}s, path={self.path},"
                f" input_size={width}x{height}, fps={self.fps:g}"
            ) from exc
        except BaseException:
            _abort_process(proc, timeout_s=abort_budget())
            self._remove_temporary_output()
            raise
        finally:
            self._proc = None

        if proc.returncode != 0:
            self._remove_temporary_output()
            details = ""
            if stderr:
                details = stderr.decode("utf-8", errors="replace").strip()
            width, height = self.size
            raise RuntimeError(
                "ffmpeg が失敗しました"
                f" (code={proc.returncode}, path={self.path},"
                f" input_size={width}x{height}, fps={self.fps:g}). {details}".strip()
            )

        temporary_path = self._temporary_path
        if temporary_path is None:
            raise RuntimeError("録画の一時出力パスが失われました")
        try:
            # ffmpeg の正常終了だけでは、直後の電源断に対する file durability は
            # 保証されない。完成 temp を fsync してから呼び出し側へ渡す。
            _fsync_file(temporary_path)
        except BaseException as exc:
            self._remove_temporary_output()
            if isinstance(exc, OSError):
                raise RuntimeError(
                    f"録画ファイルの永続化に失敗しました: path={self.path}"
                ) from exc
            raise
        return temporary_path

    def close_to_staging(
        self,
        *,
        timeout_s: float = DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
    ) -> Path | None:
        """録画を終了し、完成 temp の所有権を呼び出し側へ移す。

        capture manifest と同じ no-clobber generation transaction で公開したい
        application layer 向け。返した path は呼び出し側が必ず publish または削除する。
        """

        temporary_path = self._finish_encoding(timeout_s=timeout_s)
        if temporary_path is None:
            return None
        self._temporary_path = None
        return temporary_path

    def close(
        self,
        *,
        timeout_s: float = DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
    ) -> None:
        """録画を終了し、ffmpeg を待って完成品を公開する。"""

        temporary_path = self._finish_encoding(timeout_s=timeout_s)
        if temporary_path is None:
            return
        linked_identity: tuple[int, int] | None = None
        link_committed = False
        try:
            if self.no_clobber:
                # Versioned capture は allocation 後に同名 path が作られても上書きしない。
                # sibling temp からの hard link は atomic な no-clobber publish になる。
                result = temporary_path.stat(follow_symlinks=False)
                linked_identity = (int(result.st_dev), int(result.st_ino))
                os.link(temporary_path, self.path, follow_symlinks=False)
                link_committed = True
                # final link の durability が確定するまで、fsync 済み temp を
                # recovery copy として残す。成功後の temp unlink は成果物の
                # durability に関与しない cleanup なので best-effort とする。
                _fsync_directory(self.path.parent)
                self._remove_temporary_output()
            else:
                # 後方互換の直接利用では、従来どおり成功時に完成品を atomic replace する。
                os.replace(temporary_path, self.path)
                self._temporary_path = None
                _fsync_directory(self.path.parent)
        except BaseException as exc:
            # no-clobber publish の directory durability が確定しなかった場合は、
            # 外部から差し替えられていない今回の inode だけを rollback する。
            if (
                linked_identity is not None
                and (link_committed or not isinstance(exc, OSError))
            ):
                _unlink_if_identity(self.path, linked_identity)
                try:
                    _fsync_directory(self.path.parent)
                except BaseException:
                    pass
            if isinstance(exc, OSError):
                if self.no_clobber and temporary_path.exists():
                    # encode と file fsync は完了済み。late collision や
                    # directory fsync 失敗でこれを削除すると、長時間の録画を
                    # 回収できない。exception とともに所有権を caller へ移す。
                    self._temporary_path = None
                    raise VideoPublishError(
                        "録画ファイルの確定に失敗しました"
                        f": path={self.path}, recovery={temporary_path}",
                        recovery_path=temporary_path,
                    ) from exc
                self._remove_temporary_output()
                raise RuntimeError(
                    f"録画ファイルの確定に失敗しました: path={self.path}"
                ) from exc
            self._remove_temporary_output()
            raise
