"""capture manifest に渡す再現情報を main process で固定する。"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from grafix.core.parameters.codec import encode_param_store
from grafix.core.parameters.runtime import LoadProvenance
from grafix.core.parameters.store import ParamStore
from grafix.core.runtime_config import RuntimeConfig
from grafix.core.value_validation import (
    exact_bool,
    exact_integer,
    exact_string,
    exact_string_choice,
    finite_real,
)

_HASH_ALGORITHM = "sha256"
_GIT_TIMEOUT_S = 2.0


def _normalize_seed(seed: object, *, parameter_name: str) -> int | None:
    if seed is None:
        return None
    return exact_integer(seed, name=parameter_name)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_value(value: object) -> object:
    """owned provenance schema の値を strict JSON value へ射影する。"""

    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("provenance JSON numbers must be finite")
        return value
    if isinstance(value, Path):
        return str(value)
    if type(value) is dict:
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("provenance JSON object keys must be exact strings")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        if type(value) not in {list, tuple}:
            raise TypeError(
                f"unsupported provenance JSON sequence: {type(value)!r}"
            )
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported provenance JSON value: {type(value)!r}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        allow_nan=False,
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

    def __post_init__(self) -> None:
        for name in ("module", "qualname", "sha256", "unavailable_reason"):
            value = getattr(self, name)
            if value is not None:
                exact_string(value, name=name)
        if self.path is not None and not isinstance(self.path, Path):
            raise TypeError("path は Path または None である必要があります")
        if self.hash_scope is not None:
            exact_string_choice(
                self.hash_scope,
                name="hash_scope",
                choices=("validated_source_bytes", "file", "callable_source"),
            )

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

    def __post_init__(self) -> None:
        exact_bool(self.available, name="available")
        if self.root is not None and not isinstance(self.root, Path):
            raise TypeError("root は Path または None である必要があります")
        for name in ("commit", "unavailable_reason"):
            value = getattr(self, name)
            if value is not None:
                exact_string(value, name=name)
        if self.dirty is not None:
            exact_bool(self.dirty, name="dirty")

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

    def __post_init__(self) -> None:
        if self.path is not None and not isinstance(self.path, Path):
            raise TypeError("path は Path または None である必要があります")
        exact_string(self.effective_json, name="effective_json")
        exact_string(self.sha256, name="sha256")

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> ConfigProvenance:
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config は RuntimeConfig である必要があります")
        effective_json = _canonical_json(asdict(config))
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

    def __post_init__(self) -> None:
        exact_string(self.grafix_version, name="grafix_version")
        if not isinstance(self.source, SourceProvenance):
            raise TypeError("source は SourceProvenance である必要があります")
        if not isinstance(self.git, GitProvenance):
            raise TypeError("git は GitProvenance である必要があります")
        if not isinstance(self.config, ConfigProvenance):
            raise TypeError("config は ConfigProvenance である必要があります")
        exact_string(self.parameter_source, name="parameter_source")
        if self.parameter_store_path is not None and not isinstance(
            self.parameter_store_path,
            Path,
        ):
            raise TypeError("parameter_store_path は Path または None である必要があります")
        exact_string_choice(
            self.parameter_load_provenance,
            name="parameter_load_provenance",
            choices=("primary", "session_recovery", "quarantined"),
        )
        object.__setattr__(
            self,
            "seed",
            _normalize_seed(self.seed, parameter_name="seed"),
        )


@dataclass(frozen=True, slots=True)
class ParameterSnapshotProvenance:
    """1 frame の実効 parameter snapshot を識別する hash。"""

    revision: int
    entry_count: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "revision",
            exact_integer(self.revision, name="revision", minimum=0),
        )
        object.__setattr__(
            self,
            "entry_count",
            exact_integer(self.entry_count, name="entry_count", minimum=0),
        )
        exact_string(self.sha256, name="sha256")


@dataclass(frozen=True, slots=True)
class FrameProvenance:
    """評価済み frame と parameter snapshot の結び付き。"""

    t: float
    frame_index: int | None
    quality: Literal["draft", "final"]
    origin: Literal["headless", "interactive"]
    parameters: ParameterSnapshotProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "t", finite_real(self.t, name="t"))
        if self.frame_index is not None:
            object.__setattr__(
                self,
                "frame_index",
                exact_integer(self.frame_index, name="frame_index", minimum=0),
            )
        object.__setattr__(
            self,
            "quality",
            exact_string_choice(
                self.quality,
                name="quality",
                choices=("draft", "final"),
            ),
        )
        object.__setattr__(
            self,
            "origin",
            exact_string_choice(
                self.origin,
                name="origin",
                choices=("headless", "interactive"),
            ),
        )
        if not isinstance(self.parameters, ParameterSnapshotProvenance):
            raise TypeError(
                "parameters は ParameterSnapshotProvenance である必要があります"
            )


@dataclass(frozen=True, slots=True)
class CaptureProvenance:
    """worker が再探索せず manifest へ直列化できる完全 provenance。"""

    session: SessionProvenance
    frame: FrameProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionProvenance):
            raise TypeError("session は SessionProvenance である必要があります")
        if not isinstance(self.frame, FrameProvenance):
            raise TypeError("frame は FrameProvenance である必要があります")

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
        revision=store.revision,
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
        if not callable(draw):
            raise TypeError("draw は callable である必要があります")
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config は RuntimeConfig である必要があります")
        if type(parameter_source) is str:
            parameter_source_text = exact_string(
                parameter_source,
                name="parameter_source",
            )
        elif isinstance(parameter_source, Path):
            parameter_source_text = str(parameter_source)
        else:
            raise TypeError("parameter_source は str または Path である必要があります")
        if parameter_store_path is not None and not isinstance(
            parameter_store_path,
            Path,
        ):
            raise TypeError(
                "parameter_store_path は Path または None である必要があります"
            )
        seed = _normalize_seed(seed, parameter_name="seed")
        source = _snapshot_source(draw)
        self._session = SessionProvenance(
            grafix_version=_grafix_version(),
            source=source,
            git=_snapshot_git(source.path),
            config=ConfigProvenance.from_config(config),
            parameter_source=parameter_source_text,
            parameter_store_path=parameter_store_path,
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
        store_revision = store.revision
        effective_revision = runtime.effective_revision
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

        if not isinstance(store, ParamStore):
            raise TypeError("store は ParamStore である必要があります")
        if provenance_seed == "session" and type(provenance_seed) is not str:
            raise TypeError("provenance_seed は int、None、または 'session' である必要があります")
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
                t=t,
                frame_index=frame_index,
                quality=quality,
                origin=origin,
                parameters=self._parameter_snapshot_for_store(store),
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
]
