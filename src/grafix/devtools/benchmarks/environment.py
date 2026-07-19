"""Benchmark の source/environment/case fingerprint を収集する。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from grafix.devtools.benchmarks.schema import (
    CaseSpec,
    EnvironmentFingerprint,
    SourceIdentity,
    case_compatibility_key,
    environment_compatibility_key,
)

_DEPENDENCIES = (
    "grafix",
    "numpy",
    "numba",
    "moderngl",
    "pyglet",
    "shapely",
    "pyclipper",
)
_ENVIRONMENT_VARIABLES = (
    "GRAFIX_CONFIG",
    "GRAFIX_PERF",
    "GRAFIX_PERF_GPU_FINISH",
    "MKL_NUM_THREADS",
    "NUMBA_CACHE_DIR",
    "NUMBA_CPU_FEATURES",
    "NUMBA_CPU_NAME",
    "NUMBA_DISABLE_JIT",
    "NUMBA_NUM_THREADS",
    "NUMBA_THREADING_LAYER",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPYCACHEPREFIX",
    "PYTHONHASHSEED",
    "PYTHONMALLOC",
    "PYTHONOPTIMIZE",
    "PYTHONPATH",
    "VECLIB_MAXIMUM_THREADS",
)


def collect_source_identity(root: str | Path | None = None) -> SourceIdentity:
    """Git commit と working-tree diff を source identity として返す。"""

    cwd = Path.cwd() if root is None else Path(root)
    try:
        repository_root = Path(
            _git(cwd, "rev-parse", "--show-toplevel").strip()
        ).resolve()
        commit = _git(repository_root, "rev-parse", "HEAD").strip()
        status = _git_bytes(
            repository_root,
            "status",
            "--porcelain=v1",
            "-z",
        )
        tracked_diff = _git_bytes(
            repository_root,
            "diff",
            "--binary",
            "HEAD",
            "--",
        )
        untracked = _git_bytes(
            repository_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SourceIdentity(
            commit=None,
            dirty=None,
            diff_sha256=None,
            unavailable_reason=f"{type(exc).__name__}: {exc}",
        )

    digest = hashlib.sha256()
    digest.update(tracked_diff)
    digest.update(status)
    _hash_untracked_files(digest, cwd=repository_root, paths=untracked)
    dirty = bool(status)
    return SourceIdentity(
        commit=commit or None,
        dirty=dirty,
        diff_sha256=digest.hexdigest() if dirty else hashlib.sha256(b"").hexdigest(),
    )


def collect_environment_fingerprint(
    *,
    environment_overrides: Mapping[str, str | None] | None = None,
) -> EnvironmentFingerprint:
    """source identity を含めない比較用 environment fingerprint を返す。"""

    overrides = {} if environment_overrides is None else dict(environment_overrides)
    unavailable: dict[str, str] = {}
    dependency_versions: dict[str, str] = {}
    for distribution in _DEPENDENCIES:
        try:
            dependency_versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            unavailable[f"dependency.{distribution}"] = "distribution is not installed"

    cpu = _cpu_name()
    if cpu is None:
        unavailable["cpu"] = "processor name is unavailable"
    ram = _ram_bytes()
    if ram is None:
        unavailable["ram_bytes"] = "physical memory size is unavailable"
    gpu = _gpu_name()
    if gpu is None:
        unavailable["gpu"] = "GPU name is unavailable without a supported system profiler"
    macos_build = _macos_build()
    if sys.platform == "darwin" and macos_build is None:
        unavailable["platform.macos_build"] = "macOS build version is unavailable"
    logical_cpu_count = os.cpu_count()
    if logical_cpu_count is None:
        unavailable["hardware.logical_cpu_count"] = "logical CPU count is unavailable"

    values: dict[str, Any] = {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "abi": getattr(sys, "abiflags", ""),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "macos": platform.mac_ver()[0] or None,
            "macos_build": macos_build,
        },
        "hardware": {
            "cpu": cpu,
            "logical_cpu_count": logical_cpu_count,
            "ram_bytes": ram,
            "gpu": gpu,
        },
        "dependencies": dependency_versions,
        "backends": {
            "geos": _geos_version(unavailable),
        },
        "environment": {
            name: (
                overrides[name]
                if name in overrides
                else os.environ.get(name)
            )
            for name in _ENVIRONMENT_VARIABLES
        },
    }
    compatibility_key = environment_compatibility_key(values, unavailable)
    return EnvironmentFingerprint(
        compatibility_key=compatibility_key,
        values=values,
        unavailable=unavailable,
    )


def _geos_version(unavailable: dict[str, str]) -> str | None:
    """Shapely が実際に使用する GEOS version を返す。"""

    try:
        import shapely  # type: ignore[import-not-found, import-untyped]
    except (ImportError, OSError) as exc:
        unavailable["backend.geos"] = f"{type(exc).__name__}: {exc}"
        return None

    value = getattr(shapely, "geos_version_string", None)
    if value is None:
        try:
            from shapely import geos  # type: ignore[attr-defined]
        except (ImportError, OSError) as exc:
            unavailable["backend.geos"] = f"{type(exc).__name__}: {exc}"
            return None
        value = getattr(geos, "geos_version_string", None)

    if value is None:
        unavailable["backend.geos"] = "GEOS version is unavailable"
        return None
    return str(value)


def make_case_spec(
    *,
    case_id: str,
    version: int,
    label: str,
    category: str,
    suite: str,
    fixture: str,
    parameters: Mapping[str, Any],
    seed: int,
    implementation: Callable[..., object] | tuple[Callable[..., object], ...],
    support_source_files: tuple[str | Path, ...] = (),
    tags: tuple[str, ...] = (),
    checksum_policy: str = "exact",
    self_sampling: bool = False,
) -> CaseSpec:
    """case 定義と workload source から CaseSpec を作る。"""

    implementations = (
        implementation
        if isinstance(implementation, tuple)
        else (implementation,)
    )
    digest = hashlib.sha256(b"grafix.benchmark.case-source.v1\0")
    for function in implementations:
        try:
            source = inspect.getsource(function).encode("utf-8")
        except (OSError, TypeError):
            code = getattr(function, "__code__", None)
            source = repr(getattr(code, "co_code", function)).encode("utf-8")
        _update_framed_hash(
            digest,
            f"{function.__module__}.{function.__qualname__}".encode("utf-8"),
        )
        _update_framed_hash(digest, source)
    for source_path in sorted(
        (Path(path).resolve() for path in support_source_files),
        key=lambda path: str(path),
    ):
        _update_framed_hash(digest, source_path.name.encode("utf-8"))
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            content = f"<unavailable:{type(exc).__name__}:{exc}>".encode("utf-8")
        _update_framed_hash(digest, content)
    source_sha256 = digest.hexdigest()
    return CaseSpec(
        case_id=str(case_id),
        version=int(version),
        label=str(label),
        category=str(category),
        suite=str(suite),
        fixture=str(fixture),
        parameters=dict(parameters),
        seed=int(seed),
        source_sha256=source_sha256,
        compatibility_key=case_compatibility_key(
            case_id=case_id,
            version=version,
            fixture=fixture,
            parameters=dict(parameters),
            seed=seed,
            source_sha256=source_sha256,
            checksum_policy=checksum_policy,
            self_sampling=self_sampling,
        ),
        checksum_policy=str(checksum_policy),
        tags=tuple(str(tag) for tag in tags),
        self_sampling=bool(self_sampling),
    )


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _update_framed_hash(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _git_bytes(cwd: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _hash_untracked_files(digest: Any, *, cwd: Path, paths: bytes) -> None:
    """Git が列挙した untracked file の path と内容を hash する。"""

    for record in paths.split(b"\0"):
        if not record:
            continue
        relative = os.fsdecode(record)
        path = cwd / relative
        digest.update(record)
        if not path.is_file():
            digest.update(b"<not-a-file>")
            continue
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            digest.update(f"<unreadable:{type(exc).__name__}>".encode("ascii"))


def _cpu_name() -> str | None:
    if sys.platform == "darwin":
        try:
            return _command_text(["sysctl", "-n", "machdep.cpu.brand_string"])
        except (OSError, subprocess.SubprocessError):
            pass
    processor = platform.processor().strip()
    if processor:
        return processor
    cpuinfo = Path("/proc/cpuinfo")
    try:
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[-1].strip() or None
    except OSError:
        pass
    return None


def _ram_bytes() -> int | None:
    if sys.platform == "darwin":
        try:
            return int(_command_text(["sysctl", "-n", "hw.memsize"]))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError):
        return None
    return page_size * page_count


def _gpu_name() -> str | None:
    explicit = os.environ.get("GRAFIX_BENCH_GPU")
    if explicit:
        return explicit
    if sys.platform != "darwin":
        return None
    try:
        payload = json.loads(
            subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5.0,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    displays = payload.get("SPDisplaysDataType", [])
    if not isinstance(displays, list):
        return None
    names = sorted(
        str(item.get("sppci_model", "")).strip()
        for item in displays
        if isinstance(item, dict) and str(item.get("sppci_model", "")).strip()
    )
    return " | ".join(names) if names else None


def _macos_build() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        return _command_text(["sw_vers", "-buildVersion"]) or None
    except (OSError, subprocess.SubprocessError):
        return None


def _command_text(argv: list[str]) -> str:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    ).stdout.strip()


__all__ = [
    "collect_environment_fingerprint",
    "collect_source_identity",
    "make_case_spec",
]
