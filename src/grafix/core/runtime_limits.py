"""runtime 全体の既存 resource 上限を小さな immutable profile に束ねる。"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import SupportsIndex, cast

from grafix.core.preview_quality import PreviewQuality
from grafix.core.resource_budget import DEFAULT_RESOURCE_BUDGET, ResourceBudget

DEFAULT_CPU_CACHE_BYTES = 256 * 1024 * 1024
DEFAULT_CPU_CACHE_ENTRIES = 4096
DEFAULT_GPU_CACHE_BYTES = 256 * 1024 * 1024
DEFAULT_CAPTURE_QUEUE_PENDING_JOBS = 16
DEFAULT_CAPTURE_QUEUE_BYTES = int(DEFAULT_RESOURCE_BUDGET.max_output_bytes)


def _non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} は整数である必要があります")
    try:
        normalized = operator.index(cast(SupportsIndex, value))
    except TypeError as exc:
        raise TypeError(f"{name} は整数である必要があります") from exc
    if normalized < 0:
        raise ValueError(f"{name} は 0 以上である必要があります")
    return int(normalized)


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    """1 quality profile の operation/scene/cache/capture 上限。"""

    per_operation: ResourceBudget = DEFAULT_RESOURCE_BUDGET
    scene: ResourceBudget = DEFAULT_RESOURCE_BUDGET
    cpu_cache_bytes: int = DEFAULT_CPU_CACHE_BYTES
    cpu_cache_entries: int = DEFAULT_CPU_CACHE_ENTRIES
    gpu_cache_bytes: int = DEFAULT_GPU_CACHE_BYTES
    capture_queue_pending_jobs: int = DEFAULT_CAPTURE_QUEUE_PENDING_JOBS
    capture_queue_bytes: int = DEFAULT_CAPTURE_QUEUE_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.per_operation, ResourceBudget):
            raise TypeError("per_operation は ResourceBudget である必要があります")
        if not isinstance(self.scene, ResourceBudget):
            raise TypeError("scene は ResourceBudget である必要があります")
        for name in (
            "cpu_cache_bytes",
            "cpu_cache_entries",
            "gpu_cache_bytes",
            "capture_queue_pending_jobs",
            "capture_queue_bytes",
        ):
            object.__setattr__(
                self,
                name,
                _non_negative_int(getattr(self, name), name=name),
            )

    @property
    def gpu_candidate_cache_bytes(self) -> int:
        """GPU mesh cache 手前の index candidate 用上限を返す。"""

        return int(self.gpu_cache_bytes) // 4


@dataclass(frozen=True, slots=True)
class RuntimeLimitProfiles:
    """interactive preview と final capture の独立した上限 profile。"""

    preview: RuntimeLimits
    final: RuntimeLimits

    def __post_init__(self) -> None:
        if not isinstance(self.preview, RuntimeLimits):
            raise TypeError("preview は RuntimeLimits である必要があります")
        if not isinstance(self.final, RuntimeLimits):
            raise TypeError("final は RuntimeLimits である必要があります")

    def for_quality(self, quality: PreviewQuality) -> RuntimeLimits:
        """指定 quality に対応する profile を返す。"""

        if quality == "draft":
            return self.preview
        if quality == "final":
            return self.final
        raise ValueError(f"unknown quality: {quality!r}")


DEFAULT_PREVIEW_RUNTIME_LIMITS = RuntimeLimits()
DEFAULT_FINAL_RUNTIME_LIMITS = RuntimeLimits()
DEFAULT_RUNTIME_LIMIT_PROFILES = RuntimeLimitProfiles(
    preview=DEFAULT_PREVIEW_RUNTIME_LIMITS,
    final=DEFAULT_FINAL_RUNTIME_LIMITS,
)


def profiles_for_resource_budget(
    budget: ResourceBudget,
) -> RuntimeLimitProfiles:
    """旧来の operation budget を両 quality の operation/scene 上限へ写像する。"""

    if not isinstance(budget, ResourceBudget):
        raise TypeError("budget は ResourceBudget である必要があります")
    preview = RuntimeLimits(per_operation=budget, scene=budget)
    final = RuntimeLimits(per_operation=budget, scene=budget)
    return RuntimeLimitProfiles(preview=preview, final=final)


__all__ = [
    "DEFAULT_CAPTURE_QUEUE_BYTES",
    "DEFAULT_CAPTURE_QUEUE_PENDING_JOBS",
    "DEFAULT_CPU_CACHE_BYTES",
    "DEFAULT_CPU_CACHE_ENTRIES",
    "DEFAULT_FINAL_RUNTIME_LIMITS",
    "DEFAULT_GPU_CACHE_BYTES",
    "DEFAULT_PREVIEW_RUNTIME_LIMITS",
    "DEFAULT_RUNTIME_LIMIT_PROFILES",
    "RuntimeLimitProfiles",
    "RuntimeLimits",
    "profiles_for_resource_budget",
]
