# どこで: `src/grafix/interactive/runtime/recording_system.py`。
# 何を: V キー録画の開始/停止/フレーム書き込みを担当する。
# なぜ: DrawWindowSystem の状態変数群を分離し、責務を明確化するため。

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from grafix.core.capture_manifest import RecordingManifest
from grafix.interactive.runtime.frame_clock import RecordingClock
from grafix.interactive.runtime.video_recorder import (
    DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
    VideoRecorder,
)


@dataclass(frozen=True, slots=True)
class StagedVideoCapture:
    """encode 完了済みで、まだ final name へ公開していない動画。"""

    staging_path: Path
    output_path: Path
    framebuffer_size: tuple[int, int]
    recording: RecordingManifest


class VideoRecordingSystem:
    """動画録画の最小ステートマシン。"""

    def __init__(self, *, output_path: Path, fps: float) -> None:
        self._output_path = Path(output_path)
        self._fps = float(fps)
        self._recorder: VideoRecorder | None = None
        self._clock: RecordingClock | None = None
        self._size = (0, 0)
        self._dropped_frame_count = 0
        self._duplicated_frame_count = 0
        self._error_count = 0
        self._last_error: str | None = None

    @property
    def is_recording(self) -> bool:
        """録画中なら True を返す。"""

        return self._recorder is not None

    def t(self) -> float:
        """録画タイムライン上の `t`（秒）を返す。"""

        clock = self._clock
        if clock is None:
            raise RuntimeError("録画は開始されていません")
        return float(clock.t())

    @property
    def frame_index(self) -> int:
        """正常に encoder へ渡した frame 数を返す。"""

        clock = self._clock
        return 0 if clock is None else int(clock.frame_index)

    def start(
        self,
        *,
        framebuffer_size: tuple[int, int],
        t0: float,
        output_path: Path | None = None,
    ) -> None:
        """録画を開始する。"""

        if self._recorder is not None:
            return
        if not math.isfinite(self._fps) or self._fps <= 0:
            raise ValueError("録画には有限の fps > 0 が必要です")

        w, h = framebuffer_size
        size = (int(w), int(h))
        start_t = float(t0)
        if not math.isfinite(start_t):
            raise ValueError("録画開始時刻 t0 は有限値である必要があります")

        # clock/input validation を encoder 起動より先に済ませる。後続初期化が
        # 失敗して、起動済み ffmpeg だけが state 外へ leak する経路を作らない。
        clock = RecordingClock(t0=start_t, fps=self._fps)
        recorder = VideoRecorder(
            output_path=self._output_path if output_path is None else Path(output_path),
            size=size,
            fps=self._fps,
            # 呼び出し側が予約した versioned path は、録画中の後着衝突でも上書きしない。
            no_clobber=output_path is not None,
        )
        self._size = size
        self._clock = clock
        self._recorder = recorder
        self._dropped_frame_count = 0
        self._duplicated_frame_count = 0
        self._error_count = 0
        self._last_error = None
        # user-visible notification も acquisition transaction に含める。stdout error/
        # KeyboardInterrupt がここで起きても、呼び出し側から見えない encoder を残さない。
        try:
            print(f"Started video recording: {recorder.path} (fps={self._fps:g})")
        except BaseException:
            self._recorder = None
            self._clock = None
            self._size = (0, 0)
            self._reset_statistics()
            recorder.abort()
            raise

    def write_frame(self, screen: object) -> None:
        """現在の screen 内容を 1 フレームとして書き込む。"""

        recorder = self._recorder
        clock = self._clock
        if recorder is None or clock is None:
            return

        w, h = self._size
        try:
            frame = screen.read(  # type: ignore[attr-defined]
                viewport=(0, 0, int(w), int(h)),
                components=3,
                alignment=1,
            )
            recorder.write_frame_rgb24(frame)
        except Exception as exc:
            self.pause_frame(f"{type(exc).__name__}: {exc}")
            raise
        clock.tick()

    def pause_frame(self, error: str) -> None:
        """失敗した scene を動画へ書かず、録画 clock も進めずに記録する。"""

        if self._recorder is None or self._clock is None:
            return
        detail = str(error).strip() or "unknown recording frame error"
        self._dropped_frame_count += 1
        self._error_count += 1
        self._last_error = detail

    def _manifest(
        self,
        *,
        frame_count: int,
        stop_reason: str,
        abort_reason: str | None = None,
    ) -> RecordingManifest:
        """現在の統計を immutable manifest payload へ固定する。"""

        return RecordingManifest(
            fps=self._fps,
            frame_count=int(frame_count),
            dropped_frame_count=self._dropped_frame_count,
            duplicated_frame_count=self._duplicated_frame_count,
            error_count=self._error_count,
            error_policy="pause",
            stop_reason=str(stop_reason),
            abort_reason=abort_reason,
            last_error=self._last_error,
        )

    def _reset_statistics(self) -> None:
        self._dropped_frame_count = 0
        self._duplicated_frame_count = 0
        self._error_count = 0
        self._last_error = None

    def stop(
        self,
        *,
        timeout_s: float = DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
        stop_reason: str = "user_stop",
    ) -> Path | None:
        """録画を終了し、正常に確定した動画 path を返す。"""

        recorder = self._recorder
        clock = self._clock
        if recorder is None:
            # invariant が壊れて clock だけ残っていても次回 start を汚さない。
            self._clock = None
            self._size = (0, 0)
            self._reset_statistics()
            return None

        self._recorder = None
        frames = 0 if clock is None else int(clock.frame_index)
        manifest = self._manifest(frame_count=frames, stop_reason=stop_reason)
        seconds = frames / float(self._fps) if self._fps > 0 else 0.0
        try:
            recorder.close(timeout_s=timeout_s)
        finally:
            self._clock = None
            self._size = (0, 0)
            self._reset_statistics()
        print(
            f"Saved video: {recorder.path} (frames={frames}, seconds={seconds:.3f}, "
            f"dropped={manifest.dropped_frame_count}, errors={manifest.error_count})"
        )
        return Path(recorder.path)

    def stop_to_staging(
        self,
        *,
        timeout_s: float = DEFAULT_VIDEO_FINALIZE_TIMEOUT_S,
        stop_reason: str = "user_stop",
        abort_reason: str | None = None,
    ) -> StagedVideoCapture | None:
        """録画を終了し、artifact+manifest transaction 用の staging を返す。"""

        recorder = self._recorder
        if recorder is None:
            self._clock = None
            self._size = (0, 0)
            self._reset_statistics()
            return None

        self._recorder = None
        clock = self._clock
        frame_count = 0 if clock is None else int(clock.frame_index)
        size = self._size
        manifest = self._manifest(
            frame_count=frame_count,
            stop_reason=stop_reason,
            abort_reason=abort_reason,
        )
        try:
            staging_path = recorder.close_to_staging(timeout_s=timeout_s)
        finally:
            self._clock = None
            self._size = (0, 0)
            self._reset_statistics()
        if staging_path is None:
            return None
        return StagedVideoCapture(
            staging_path=Path(staging_path),
            output_path=Path(recorder.path),
            framebuffer_size=size,
            recording=manifest,
        )


__all__ = ["StagedVideoCapture", "VideoRecordingSystem"]
