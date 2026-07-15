"""Geometry の配列確保を事前検査する session 共通 resource budget。"""

from __future__ import annotations

import contextlib
import contextvars
import operator
from dataclasses import dataclass
from typing import Iterator


DEFAULT_MAX_OUTPUT_VERTICES = 10_000_000
DEFAULT_MAX_OUTPUT_LINES = 2_000_000
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
_MAX_INT32 = (1 << 31) - 1


class ResourceLimitError(ValueError):
    """operation の見積もりが許可された resource budget を超えた。"""


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """1 operation が生成してよい geometry の上限。

    UI の slider range とは異なり、この値はコードから直接渡された引数にも適用する。
    ``max_output_bytes`` は最終 ``coords(float32[N,3])`` と
    ``offsets(int32[M+1])`` の最低必要量を検査する。operation 固有の scratch 配列は
    ``ensure_geometry_output(..., scratch_bytes=...)`` で追加できる。
    """

    max_output_vertices: int = DEFAULT_MAX_OUTPUT_VERTICES
    max_output_lines: int = DEFAULT_MAX_OUTPUT_LINES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for name, value in (
            ("max_output_vertices", self.max_output_vertices),
            ("max_output_lines", self.max_output_lines),
            ("max_output_bytes", self.max_output_bytes),
        ):
            if isinstance(value, bool):
                raise TypeError(f"{name} は整数である必要がある")
            try:
                normalized = operator.index(value)
            except TypeError as exc:
                raise TypeError(f"{name} は整数である必要がある") from exc
            if normalized < 0:
                raise ValueError(f"{name} は 0 以上である必要がある")
            object.__setattr__(self, name, int(normalized))


DEFAULT_RESOURCE_BUDGET = ResourceBudget()
_CURRENT_RESOURCE_BUDGET: contextvars.ContextVar[ResourceBudget] = contextvars.ContextVar(
    "grafix_resource_budget",
    default=DEFAULT_RESOURCE_BUDGET,
)


def current_resource_budget() -> ResourceBudget:
    """現在の evaluation context に適用される budget を返す。"""

    return _CURRENT_RESOURCE_BUDGET.get()


@contextlib.contextmanager
def resource_budget_context(budget: ResourceBudget) -> Iterator[None]:
    """この context 内の operation に ``budget`` を適用する。"""

    if not isinstance(budget, ResourceBudget):
        raise TypeError("budget は ResourceBudget である必要がある")
    token = _CURRENT_RESOURCE_BUDGET.set(budget)
    try:
        yield
    finally:
        _CURRENT_RESOURCE_BUDGET.reset(token)


def _estimated_geometry_bytes(*, vertices: int, lines: int, scratch_bytes: int) -> int:
    # Python の int で計算し、NumPy の固定幅整数へ落とす前に検査する。
    return int(vertices) * 3 * 4 + (int(lines) + 1) * 4 + int(scratch_bytes)


def ensure_geometry_output(
    op: str,
    *,
    vertices: int,
    lines: int,
    scratch_bytes: int = 0,
    hint: str | None = None,
) -> None:
    """大規模配列を確保する前に output plan を共通上限で検査する。"""

    vertices_i = int(vertices)
    lines_i = int(lines)
    scratch_i = int(scratch_bytes)
    if vertices_i < 0 or lines_i < 0 or scratch_i < 0:
        raise ValueError(
            f"{op}: output plan は 0 以上である必要があります: "
            f"vertices={vertices_i}, lines={lines_i}, scratch_bytes={scratch_i}"
        )

    budget = current_resource_budget()
    estimated_bytes = _estimated_geometry_bytes(
        vertices=vertices_i,
        lines=lines_i,
        scratch_bytes=scratch_i,
    )

    exceeded: list[str] = []
    if vertices_i > _MAX_INT32:
        exceeded.append(f"vertices={vertices_i:,} > int32 capacity {_MAX_INT32:,}")
    if lines_i + 1 > _MAX_INT32:
        exceeded.append(f"offsets={lines_i + 1:,} > int32 capacity {_MAX_INT32:,}")
    if vertices_i > int(budget.max_output_vertices):
        exceeded.append(
            f"vertices={vertices_i:,} > {int(budget.max_output_vertices):,}"
        )
    if lines_i > int(budget.max_output_lines):
        exceeded.append(f"lines={lines_i:,} > {int(budget.max_output_lines):,}")
    if estimated_bytes > int(budget.max_output_bytes):
        exceeded.append(
            f"estimated_bytes={estimated_bytes:,} > {int(budget.max_output_bytes):,}"
        )
    if not exceeded:
        return

    suffix = "" if not hint else f"; {hint}"
    raise ResourceLimitError(
        f"{op}: resource budget を超えるため配列を確保しません: "
        + ", ".join(exceeded)
        + suffix
    )


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_MAX_OUTPUT_LINES",
    "DEFAULT_MAX_OUTPUT_VERTICES",
    "DEFAULT_RESOURCE_BUDGET",
    "ResourceBudget",
    "ResourceLimitError",
    "current_resource_budget",
    "ensure_geometry_output",
    "resource_budget_context",
]
