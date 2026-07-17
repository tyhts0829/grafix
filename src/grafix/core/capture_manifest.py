"""保存した capture と、その再現 metadata を安全に一世代として公開する。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Final

from grafix.core.capture_provenance import (
    CaptureProvenance,
    unavailable_capture_provenance,
)

CAPTURE_MANIFEST_SCHEMA_VERSION = 2
_UTF8: Final = "utf-8"


@dataclass(frozen=True, slots=True)
class RecordingManifest:
    """動画 recording の終端統計と明示 error policy。"""

    fps: float
    frame_count: int
    dropped_frame_count: int = 0
    duplicated_frame_count: int = 0
    error_count: int = 0
    error_policy: str = "pause"
    stop_reason: str | None = None
    abort_reason: str | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        fps = float(self.fps)
        if not isfinite(fps) or fps <= 0.0:
            raise ValueError("recording fps は正の有限値である必要があります")
        object.__setattr__(self, "fps", fps)
        for name in (
            "frame_count",
            "dropped_frame_count",
            "duplicated_frame_count",
            "error_count",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} は 0 以上である必要があります")
            object.__setattr__(self, name, value)
        policy = str(self.error_policy).strip().casefold()
        if policy != "pause":
            raise ValueError("recording error_policy は 'pause' である必要があります")
        object.__setattr__(self, "error_policy", policy)

    def as_dict(self) -> dict[str, object]:
        return {
            "fps": self.fps,
            "frame_count": self.frame_count,
            "dropped_frame_count": self.dropped_frame_count,
            "duplicated_frame_count": self.duplicated_frame_count,
            "error_count": self.error_count,
            "error_policy": self.error_policy,
            "stop_reason": self.stop_reason,
            "abort_reason": self.abort_reason,
            "last_error": self.last_error,
        }


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    """1 回の capture に対応する JSON 化可能な manifest v2。"""

    t: float
    canvas_size: tuple[int, int]
    format: str
    artifact_paths: tuple[Path, ...]
    provenance: CaptureProvenance | None = None
    output_size: tuple[int, int] | None = None
    recording: RecordingManifest | None = None

    def __post_init__(self) -> None:
        capture_t = float(self.t)
        if not isfinite(capture_t):
            raise ValueError("t は有限値である必要がある")

        canvas_size = (int(self.canvas_size[0]), int(self.canvas_size[1]))
        if canvas_size[0] <= 0 or canvas_size[1] <= 0:
            raise ValueError("canvas_size は正の (width, height) である必要がある")

        artifact_format = str(self.format).strip().lstrip(".").lower()
        if not artifact_format:
            raise ValueError("format は空でない必要がある")

        artifact_paths = tuple(Path(path) for path in self.artifact_paths)
        if not artifact_paths:
            raise ValueError("artifact_paths は 1 件以上必要です")
        if any(not path.name for path in artifact_paths):
            raise ValueError("artifact_paths はファイル名を含む必要がある")

        output_size = self.output_size
        if output_size is not None:
            output_size = (int(output_size[0]), int(output_size[1]))
            if output_size[0] <= 0 or output_size[1] <= 0:
                raise ValueError("output_size は正の (width, height) である必要があります")

        provenance = self.provenance
        if provenance is not None and float(provenance.frame.t) != capture_t:
            raise ValueError("provenance.frame.t は manifest.t と一致する必要があります")

        object.__setattr__(self, "t", capture_t)
        object.__setattr__(self, "canvas_size", canvas_size)
        object.__setattr__(self, "format", artifact_format)
        object.__setattr__(self, "artifact_paths", artifact_paths)
        object.__setattr__(self, "output_size", output_size)

    def as_dict(self) -> dict[str, object]:
        """安定した JSON schema の dict を返す。"""

        width, height = self.canvas_size
        provenance = self.provenance or unavailable_capture_provenance(t=self.t)
        sections = provenance.manifest_sections()
        output: dict[str, object] = {
            "format": self.format,
            "artifact_paths": [str(path) for path in self.artifact_paths],
            "canvas_size": {"width": width, "height": height},
            "size": (
                None
                if self.output_size is None
                else {"width": self.output_size[0], "height": self.output_size[1]}
            ),
        }
        payload = {
            "schema_version": CAPTURE_MANIFEST_SCHEMA_VERSION,
            # v1 の top-level identity は diff/readability のため v2 でも保持する。
            "t": self.t,
            "canvas_size": {"width": width, "height": height},
            "format": self.format,
            "artifact_paths": [str(path) for path in self.artifact_paths],
            **sections,
            "output": output,
            "recording": None if self.recording is None else self.recording.as_dict(),
        }
        return payload


@dataclass(frozen=True, slots=True)
class PublishedCaptureGeneration:
    """一括公開に成功した成果物群と manifest。"""

    artifact_paths: tuple[Path, ...]
    manifest_path: Path


def capture_manifest_path_for(artifact_path: str | Path) -> Path:
    """成果物の拡張子も残した sibling manifest path を返す。"""

    artifact = Path(artifact_path)
    if not artifact.name:
        raise ValueError("artifact_path はファイル名を含む必要がある")
    return artifact.with_name(f"{artifact.name}.capture.json")


def _manifest_payload(manifest: CaptureManifest) -> bytes:
    text = json.dumps(
        manifest.as_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (text + "\n").encode(_UTF8)


def _stage_manifest(*, directory: Path, manifest: CaptureManifest) -> Path:
    """manifest を fsync 済みの private sibling file として作る。"""

    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        dir=directory,
        prefix=".grafix-capture-manifest-",
        suffix=".tmp",
    )
    staged_path = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_manifest_payload(manifest))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        staged_path.unlink(missing_ok=True)
        raise
    return staged_path


def _regular_file_identity(path: Path) -> tuple[int, int]:
    """通常ファイルであることを確認し、rollback 用 identity を返す。"""

    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"staged capture が通常ファイルではありません: {path}")
    stat_result = path.stat(follow_symlinks=False)
    return int(stat_result.st_dev), int(stat_result.st_ino)


def _unlink_if_identity(path: Path, expected: tuple[int, int]) -> None:
    """今回公開した inode のままなら unlink する。外部差し替えは保持する。"""

    try:
        stat_result = path.stat(follow_symlinks=False)
        identity = (int(stat_result.st_dev), int(stat_result.st_ino))
        if identity == expected:
            path.unlink()
    except OSError:
        pass


def _private_backup_path(path: Path) -> Path:
    """overwrite transaction 用の一意な sibling backup path を返す。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".grafix-capture-backup-{path.name}-",
        suffix=".tmp",
    )
    os.close(fd)
    backup = Path(name)
    backup.unlink()
    return backup


def _publish_capture_generation_overwrite(
    *,
    sources: tuple[Path, ...],
    targets: tuple[Path, ...],
    source_identities: tuple[tuple[int, int], ...],
) -> None:
    """既存 generation を退避し、失敗時に元へ戻して置換する。"""

    backups: list[tuple[Path, Path]] = []
    committed: list[tuple[Path, tuple[int, int]]] = []
    directories = tuple(path.parent for path in targets)
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not os.path.lexists(target):
                continue
            if target.is_dir() and not target.is_symlink():
                raise IsADirectoryError(f"capture の公開先が directory です: {target}")
            backup = _private_backup_path(target)
            os.replace(target, backup)
            backups.append((target, backup))

        for source, target, identity in zip(
            sources,
            targets,
            source_identities,
            strict=True,
        ):
            os.link(source, target, follow_symlinks=False)
            committed.append((target, identity))
        _fsync_directories(directories, best_effort=False)
    except BaseException:
        for target, identity in reversed(committed):
            _unlink_if_identity(target, identity)
        for target, backup in reversed(backups):
            # transaction 外から同名 path が作られた場合は上書きしない。通常の
            # rollback では target は空いており、元 generation を atomic に戻せる。
            if not os.path.lexists(target) and os.path.lexists(backup):
                os.replace(backup, target)
        _fsync_directories(directories, best_effort=True)
        raise
    else:
        for _target, backup in backups:
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                # generation は既に公開済み。private backup の後始末失敗を
                # publish failure と誤報して、呼び出し側に再試行させない。
                pass
        _fsync_directories(directories, best_effort=True)


def _fsync_directories(directories: tuple[Path, ...], *, best_effort: bool) -> None:
    """重複を除いた publish directory を同期する。"""

    seen: set[str] = set()
    for directory in directories:
        key = os.path.normcase(os.path.abspath(os.fspath(directory)))
        if key in seen:
            continue
        seen.add(key)
        fd: int | None = None
        try:
            flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
            fd = os.open(directory, flags)
            os.fsync(fd)
        except OSError:
            if not best_effort:
                raise
        finally:
            if fd is not None:
                os.close(fd)


def publish_capture_generation(
    *,
    staged_artifact_paths: tuple[Path, ...],
    artifact_paths: tuple[Path, ...],
    manifest_path: str | Path,
    manifest: CaptureManifest,
    overwrite: bool = False,
) -> PublishedCaptureGeneration:
    """成果物と manifest を no-clobber generation として公開する。

    全ファイルは完成済み sibling staging から ``os.link`` で排他的に公開する。
    途中で late collision や I/O error が起きた場合は、この呼び出しが公開した inode
    だけを逆順で rollback する。したがって allocation 後に外部 process が作成・
    差し替えたファイルを上書きも削除もしない。

    複数 path を filesystem として完全に同時に見せることはできないが、正常 return
    では成果物と manifest が全て存在し、例外 return では今回分を残さない。
    process crash の回復 journal は別機能として扱う。
    """

    staged = tuple(Path(path) for path in staged_artifact_paths)
    finals = tuple(Path(path) for path in artifact_paths)
    target_manifest = Path(manifest_path)
    if not staged or len(staged) != len(finals):
        raise ValueError("staged_artifact_paths と artifact_paths は同じ非ゼロ件数が必要です")
    if tuple(manifest.artifact_paths) != finals:
        raise ValueError("manifest.artifact_paths は公開先 artifact_paths と一致する必要があります")
    all_targets = (*finals, target_manifest)
    normalized_targets = {
        os.path.normcase(os.path.abspath(os.fspath(path))) for path in all_targets
    }
    if len(normalized_targets) != len(all_targets):
        raise ValueError("capture generation の公開先 path は全て一意である必要があります")

    # manifest の staging は target と同じ directory に作り、hard-link publish が
    # cross-device にならないようにする。artifact staging も通常は同じ sibling dir。
    staged_manifest = _stage_manifest(
        directory=target_manifest.parent,
        manifest=manifest,
    )
    sources = (*staged, staged_manifest)
    committed: list[tuple[Path, tuple[int, int]]] = []
    target_directories = tuple(path.parent for path in all_targets)
    try:
        source_identities = tuple(_regular_file_identity(path) for path in sources)
        # writer が close 済みでも durability を揃えるため、artifact も publish 前に fsync。
        for source in staged:
            with source.open("rb") as stream:
                os.fsync(stream.fileno())

        if overwrite:
            _publish_capture_generation_overwrite(
                sources=sources,
                targets=all_targets,
                source_identities=source_identities,
            )
        else:
            for source, target, identity in zip(
                sources,
                all_targets,
                source_identities,
                strict=True,
            ):
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target, follow_symlinks=False)
                committed.append((target, identity))
            _fsync_directories(target_directories, best_effort=False)
    except BaseException:
        for target, identity in reversed(committed):
            _unlink_if_identity(target, identity)
        # rollback directory entry も可能な範囲で durability を揃える。元の例外を優先。
        _fsync_directories(target_directories, best_effort=True)
        raise
    finally:
        staged_manifest.unlink(missing_ok=True)

    return PublishedCaptureGeneration(
        artifact_paths=finals,
        manifest_path=target_manifest,
    )


def write_capture_manifest(path: str | Path, manifest: CaptureManifest) -> Path:
    """manifest を上書きせず atomic に公開し、その path を返す。

    既存 path（broken symlink を含む）がある場合は ``FileExistsError`` を送出し、
    その内容には触れない。capture artifact と一括確定する場合は
    :func:`publish_capture_generation` を使う。
    """

    target = Path(path)
    staged = _stage_manifest(directory=target.parent, manifest=manifest)
    identity = _regular_file_identity(staged)
    committed = False
    try:
        os.link(staged, target, follow_symlinks=False)
        committed = True
        _fsync_directories((target.parent,), best_effort=False)
    except BaseException:
        if committed:
            _unlink_if_identity(target, identity)
            _fsync_directories((target.parent,), best_effort=True)
        raise
    finally:
        staged.unlink(missing_ok=True)
    return target


__all__ = [
    "CAPTURE_MANIFEST_SCHEMA_VERSION",
    "CaptureManifest",
    "PublishedCaptureGeneration",
    "RecordingManifest",
    "capture_manifest_path_for",
    "publish_capture_generation",
    "write_capture_manifest",
]
