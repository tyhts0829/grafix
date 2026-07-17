"""capture manifest v2 に渡す再現情報を main process で固定する。"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from grafix.core.parameters.codec import encode_param_store
from grafix.core.parameters.runtime import LoadProvenance
from grafix.core.parameters.store import ParamStore
from grafix.core.runtime_config import RuntimeConfig

_HASH_ALGORITHM = "sha256"
_GIT_TIMEOUT_S = 2.0


def _normalize_seed(seed: object, *, parameter_name: str) -> int | None:
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TypeError(f"{parameter_name} は int または None である必要があります")
    return seed


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_value(value: object) -> object:
    """既知の runtime 値を決定的な JSON value へ射影する。"""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0.0 else "-Infinity"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_json_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(items, key=lambda item: _canonical_json(item))
        return items

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_value(item())
        except (TypeError, ValueError):
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_value(tolist())
        except (TypeError, ValueError):
            pass
    return repr(value)


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """draw callable と、その hash 対象。"""

    module: str | None
    qualname: str | None
    path: Path | None
    sha256: str | None
    hash_scope: Literal["validated_source_bytes", "file", "callable_source"] | None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.sha256 is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "module": self.module,
            "qualname": self.qualname,
            "path": None if self.path is None else str(self.path),
            "hash": (
                None
                if self.sha256 is None
                else {"algorithm": _HASH_ALGORITHM, "value": self.sha256}
            ),
            "hash_scope": self.hash_scope,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class GitProvenance:
    """source を含む Git repository の取得結果。"""

    available: bool
    root: Path | None = None
    commit: str | None = None
    dirty: bool | None = None
    unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "root": None if self.root is None else str(self.root),
            "commit": self.commit,
            "dirty": self.dirty,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class ConfigProvenance:
    """effective RuntimeConfig の immutable JSON snapshot。"""

    path: Path | None
    effective_json: str
    sha256: str

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> ConfigProvenance:
        effective_json = _canonical_json(config)
        return cls(
            path=config.config_path,
            effective_json=effective_json,
            sha256=_sha256(effective_json.encode("utf-8")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "path": None if self.path is None else str(self.path),
            "effective": json.loads(self.effective_json),
            "snapshot_hash": {
                "algorithm": _HASH_ALGORITHM,
                "value": self.sha256,
            },
        }


@dataclass(frozen=True, slots=True)
class SessionProvenance:
    """RenderSession または interactive run の開始時に一度だけ探索する情報。"""

    grafix_version: str
    source: SourceProvenance
    git: GitProvenance
    config: ConfigProvenance
    parameter_source: str
    parameter_store_path: Path | None
    parameter_load_provenance: LoadProvenance
    seed: int | None


@dataclass(frozen=True, slots=True)
class ParameterSnapshotProvenance:
    """1 frame の実効 parameter snapshot を識別する hash。"""

    revision: int
    entry_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FrameProvenance:
    """評価済み frame と parameter snapshot の結び付き。"""

    t: float
    frame_index: int | None
    quality: Literal["draft", "final"]
    origin: Literal["headless", "interactive"]
    parameters: ParameterSnapshotProvenance


@dataclass(frozen=True, slots=True)
class CaptureProvenance:
    """worker が再探索せず manifest へ直列化できる完全 provenance。"""

    session: SessionProvenance
    frame: FrameProvenance

    def manifest_sections(self) -> dict[str, object]:
        session = self.session
        parameters = self.frame.parameters
        return {
            "grafix": {"version": session.grafix_version},
            "source": session.source.as_dict(),
            "git": session.git.as_dict(),
            "config": session.config.as_dict(),
            "parameters": {
                "source": session.parameter_source,
                "store_path": (
                    None
                    if session.parameter_store_path is None
                    else str(session.parameter_store_path)
                ),
                "load_provenance": session.parameter_load_provenance,
                "revision": parameters.revision,
                "entry_count": parameters.entry_count,
                "snapshot_hash": {
                    "algorithm": _HASH_ALGORITHM,
                    "value": parameters.sha256,
                },
            },
            "seed": session.seed,
            "frame": {
                "t": self.frame.t,
                "index": self.frame.frame_index,
                "quality": self.frame.quality,
                "origin": self.frame.origin,
            },
        }


def _snapshot_source(draw: Callable[[float], object]) -> SourceProvenance:
    draw_type = type(draw)
    module = getattr(draw, "__module__", getattr(draw_type, "__module__", None))
    qualname = getattr(
        draw,
        "__qualname__",
        getattr(draw, "__name__", getattr(draw_type, "__qualname__", None)),
    )
    explicit_path = getattr(draw, "__grafix_source_path__", None)
    path: Path | None = None
    if explicit_path is not None:
        explicit_text = str(explicit_path).strip()
        if explicit_text and not (
            explicit_text.startswith("<") and explicit_text.endswith(">")
        ):
            path = Path(explicit_text).expanduser().resolve(strict=False)

    validated_source = getattr(draw, "__grafix_source_bytes__", None)
    if isinstance(validated_source, (bytes, bytearray, memoryview)):
        payload = bytes(validated_source)
        return SourceProvenance(
            module=None if module is None else str(module),
            qualname=None if qualname is None else str(qualname),
            path=path,
            sha256=_sha256(payload),
            hash_scope="validated_source_bytes",
        )

    code = getattr(draw, "__code__", None)
    filename = getattr(code, "co_filename", None)
    if path is None and filename and not (
        str(filename).startswith("<") and str(filename).endswith(">")
    ):
        path = Path(str(filename)).expanduser().resolve(strict=False)
    elif path is None:
        try:
            found = inspect.getsourcefile(draw) or inspect.getfile(draw)
        except (OSError, TypeError):
            found = None
        if found:
            path = Path(found).expanduser().resolve(strict=False)

    if path is not None:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            file_error = f"source file could not be read: {type(exc).__name__}"
        else:
            return SourceProvenance(
                module=None if module is None else str(module),
                qualname=None if qualname is None else str(qualname),
                path=path,
                sha256=_sha256(payload),
                hash_scope="file",
            )
    else:
        file_error = "source file is unavailable"

    try:
        source = inspect.getsource(draw)
    except (OSError, TypeError):
        return SourceProvenance(
            module=None if module is None else str(module),
            qualname=None if qualname is None else str(qualname),
            path=path,
            sha256=None,
            hash_scope=None,
            unavailable_reason=file_error,
        )
    return SourceProvenance(
        module=None if module is None else str(module),
        qualname=None if qualname is None else str(qualname),
        path=path,
        sha256=_sha256(source.encode("utf-8")),
        hash_scope="callable_source",
    )


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=_GIT_TIMEOUT_S,
    )


def _snapshot_git(source_path: Path | None) -> GitProvenance:
    if source_path is None:
        return GitProvenance(
            available=False,
            unavailable_reason="source path is unavailable",
        )
    cwd = source_path.parent
    try:
        root_result = _run_git("rev-parse", "--show-toplevel", cwd=cwd)
        if root_result.returncode != 0:
            return GitProvenance(
                available=False,
                unavailable_reason="source is not inside an accessible Git repository",
            )
        root = Path(root_result.stdout.strip()).resolve(strict=False)
        commit_result = _run_git("rev-parse", "HEAD", cwd=root)
        status_result = _run_git("status", "--porcelain", cwd=root)
    except (OSError, subprocess.SubprocessError) as exc:
        return GitProvenance(
            available=False,
            unavailable_reason=f"Git metadata lookup failed: {type(exc).__name__}",
        )
    if commit_result.returncode != 0 or status_result.returncode != 0:
        return GitProvenance(
            available=False,
            root=root,
            unavailable_reason="Git commit or status could not be read",
        )
    return GitProvenance(
        available=True,
        root=root,
        commit=commit_result.stdout.strip(),
        dirty=bool(status_result.stdout.strip()),
    )


def _grafix_version() -> str:
    try:
        return version("grafix")
    except PackageNotFoundError:
        return "unknown"


def _parameter_snapshot(store: ParamStore) -> ParameterSnapshotProvenance:
    runtime = store._runtime_ref()
    effective_entries = [
        {
            "op": key.op,
            "site_id": key.site_id,
            "arg": key.arg,
            "value": _json_value(value),
            "source": (
                None
                if runtime.last_source_by_key.get(key) is None
                else runtime.last_source_by_key[key]
            ),
        }
        for key, value in sorted(
            runtime.last_effective_by_key.items(),
            key=lambda item: (item[0].op, item[0].site_id, item[0].arg),
        )
    ]
    # draw が parameter を使わない場合も、空 snapshot を一意に識別する。永続 store
    # payload も含め、未観測 UI state の違いを同じ hash と誤認しない。
    payload = {
        "effective": effective_entries,
        "store": encode_param_store(store, preserve_explicit_overrides=True),
    }
    text = _canonical_json(payload)
    return ParameterSnapshotProvenance(
        revision=int(store.revision),
        entry_count=len(effective_entries),
        sha256=_sha256(text.encode("utf-8")),
    )


class CaptureProvenanceBuilder:
    """filesystem/Git/config探索を構築時だけ行い、frame snapshotは純粋に作る。"""

    def __init__(
        self,
        draw: Callable[[float], object],
        *,
        config: RuntimeConfig,
        parameter_source: str | Path,
        parameter_store_path: Path | None,
        parameter_load_provenance: LoadProvenance,
        seed: int | None = None,
    ) -> None:
        seed = _normalize_seed(seed, parameter_name="seed")
        source = _snapshot_source(draw)
        self._session = SessionProvenance(
            grafix_version=_grafix_version(),
            source=source,
            git=_snapshot_git(source.path),
            config=ConfigProvenance.from_config(config),
            parameter_source=str(parameter_source),
            parameter_store_path=(
                None if parameter_store_path is None else Path(parameter_store_path)
            ),
            parameter_load_provenance=parameter_load_provenance,
            seed=seed,
        )
        # Parameter snapshot は immutable であり、store の永続状態と
        # effective/source の両 revision が同じ間は安全に共有できる。
        # 複数 store を跨いだ誤 hit を防ぐため identity も key に含める。
        self._parameter_cache_store: ParamStore | None = None
        self._parameter_cache_store_revision = -1
        self._parameter_cache_effective_revision = -1
        self._parameter_cache_snapshot: ParameterSnapshotProvenance | None = None

    @property
    def session(self) -> SessionProvenance:
        return self._session

    def _parameter_snapshot_for_store(
        self, store: ParamStore
    ) -> ParameterSnapshotProvenance:
        runtime = store._runtime_ref()
        store_revision = int(store.revision)
        effective_revision = int(runtime.effective_revision)
        cached = self._parameter_cache_snapshot
        if (
            cached is not None
            and self._parameter_cache_store is store
            and self._parameter_cache_store_revision == store_revision
            and self._parameter_cache_effective_revision == effective_revision
        ):
            return cached

        snapshot = _parameter_snapshot(store)
        self._parameter_cache_store = store
        self._parameter_cache_store_revision = store_revision
        self._parameter_cache_effective_revision = effective_revision
        self._parameter_cache_snapshot = snapshot
        return snapshot

    def frame(
        self,
        store: ParamStore,
        *,
        t: float,
        frame_index: int | None,
        quality: Literal["draft", "final"],
        origin: Literal["headless", "interactive"],
        provenance_seed: int | None | Literal["session"] = "session",
    ) -> CaptureProvenance:
        """main process の確定済み store から immutable frame provenance を返す。

        ``provenance_seed`` が ``"session"`` なら構築時の session seed を使う。
        int/None はこの frame の provenance だけを明示的に上書きし、
        source/Git/config の再探索や乱数 global state の変更は行わない。
        """

        session = self._session
        if provenance_seed != "session":
            session = replace(
                session,
                seed=_normalize_seed(
                    provenance_seed,
                    parameter_name="provenance_seed",
                ),
            )

        return CaptureProvenance(
            session=session,
            frame=FrameProvenance(
                t=float(t),
                frame_index=None if frame_index is None else int(frame_index),
                quality=quality,
                origin=origin,
                parameters=self._parameter_snapshot_for_store(store),
            ),
        )


def unavailable_capture_provenance(*, t: float) -> CaptureProvenance:
    """旧/internal caller用に、欠落理由を明示した provenance を返す。"""

    empty_json = _canonical_json({})
    session = SessionProvenance(
        grafix_version=_grafix_version(),
        source=SourceProvenance(
            module=None,
            qualname=None,
            path=None,
            sha256=None,
            hash_scope=None,
            unavailable_reason="frame did not provide source provenance",
        ),
        git=GitProvenance(
            available=False,
            unavailable_reason="frame did not provide Git provenance",
        ),
        config=ConfigProvenance(
            path=None,
            effective_json=empty_json,
            sha256=_sha256(empty_json.encode("utf-8")),
        ),
        parameter_source="unavailable",
        parameter_store_path=None,
        parameter_load_provenance="primary",
        seed=None,
    )
    return CaptureProvenance(
        session=session,
        frame=FrameProvenance(
            t=float(t),
            frame_index=None,
            quality="final",
            origin="headless",
            parameters=ParameterSnapshotProvenance(
                revision=0,
                entry_count=0,
                sha256=_sha256(_canonical_json([]).encode("utf-8")),
            ),
        ),
    )


__all__ = [
    "CaptureProvenance",
    "CaptureProvenanceBuilder",
    "ConfigProvenance",
    "FrameProvenance",
    "GitProvenance",
    "ParameterSnapshotProvenance",
    "SessionProvenance",
    "SourceProvenance",
    "unavailable_capture_provenance",
]
