"""operation 評価中の silent degradation を小さな immutable payload で記録する。"""

from __future__ import annotations

import contextlib
import contextvars
import math
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal, TypeAlias

OperationDiagnosticSeverity = Literal["info", "warning", "error"]
OperationDiagnosticScalar: TypeAlias = None | bool | int | float | str
OperationDiagnosticValue: TypeAlias = (
    OperationDiagnosticScalar | tuple[OperationDiagnosticScalar, ...]
)


def _normalize_value(value: object, *, field: str) -> OperationDiagnosticValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        if len(value) > 16:
            raise ValueError(f"{field} は最大 16 要素である必要があります")
        normalized: list[OperationDiagnosticScalar] = []
        for item in value:
            if item is not None and not isinstance(item, (bool, int, float, str)):
                raise TypeError(
                    f"{field} の要素は scalar である必要があります: {item!r}"
                )
            normalized.append(item)
        return tuple(normalized)
    raise TypeError(f"{field} は小さな scalar/tuple である必要があります")


def _identity_value(value: OperationDiagnosticValue) -> object:
    """NaN/Infinity を含んでも同じ payload が dedupe される表現へ変換する。"""

    if isinstance(value, tuple):
        return tuple(_identity_value(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return ("float", "nan")
        return ("float", "inf" if value > 0.0 else "-inf")
    return value


@dataclass(frozen=True, slots=True)
class OperationDiagnostic:
    """1 operation の要求値と実効値の差、および理由。"""

    op: str
    original_value: OperationDiagnosticValue
    effective_value: OperationDiagnosticValue
    reason: str
    severity: OperationDiagnosticSeverity = "warning"

    def __post_init__(self) -> None:
        op = str(self.op).strip()
        reason = str(self.reason).strip()
        if not op:
            raise ValueError("op は空にできません")
        if not reason:
            raise ValueError("reason は空にできません")
        if self.severity not in {"info", "warning", "error"}:
            raise ValueError(f"未対応の severity: {self.severity!r}")
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "original_value",
            _normalize_value(self.original_value, field="original_value"),
        )
        object.__setattr__(
            self,
            "effective_value",
            _normalize_value(self.effective_value, field="effective_value"),
        )

    def identity(self) -> tuple[object, ...]:
        """frame内/DiagnosticCenter間のdedupeに使う安定identity。"""

        return (
            self.op,
            _identity_value(self.original_value),
            _identity_value(self.effective_value),
            self.reason,
            self.severity,
        )


class OperationDiagnosticBuffer:
    """1 evaluation 内を insertion order で dedupe する小さな buffer。"""

    def __init__(self) -> None:
        self._items: OrderedDict[tuple[object, ...], OperationDiagnostic] = OrderedDict()

    def add(self, diagnostic: OperationDiagnostic) -> None:
        if not isinstance(diagnostic, OperationDiagnostic):
            raise TypeError("diagnostic は OperationDiagnostic である必要があります")
        self._items.setdefault(diagnostic.identity(), diagnostic)

    def extend(self, diagnostics: Iterable[OperationDiagnostic]) -> None:
        for diagnostic in diagnostics:
            self.add(diagnostic)

    def snapshot(self) -> tuple[OperationDiagnostic, ...]:
        return tuple(self._items.values())

    def __len__(self) -> int:
        return len(self._items)


_operation_diagnostics_var: contextvars.ContextVar[
    OperationDiagnosticBuffer | None
] = contextvars.ContextVar("operation_diagnostics", default=None)


def emit_operation_diagnostic(
    *,
    op: str,
    original_value: OperationDiagnosticValue,
    effective_value: OperationDiagnosticValue,
    reason: str,
    severity: OperationDiagnosticSeverity = "warning",
) -> OperationDiagnostic:
    """payload を作り、evaluation context があればその frame へ記録する。"""

    diagnostic = OperationDiagnostic(
        op=op,
        original_value=original_value,
        effective_value=effective_value,
        reason=reason,
        severity=severity,
    )
    buffer = _operation_diagnostics_var.get()
    if buffer is not None:
        buffer.add(diagnostic)
    return diagnostic


def extend_operation_diagnostics(
    diagnostics: Iterable[OperationDiagnostic],
) -> None:
    """worker 等で収集済みの payload を現在 evaluation へマージする。"""

    buffer = _operation_diagnostics_var.get()
    if buffer is not None:
        buffer.extend(diagnostics)


def current_operation_diagnostics() -> tuple[OperationDiagnostic, ...]:
    """現在 evaluation の immutable snapshot を返す。context外では空。"""

    buffer = _operation_diagnostics_var.get()
    return () if buffer is None else buffer.snapshot()


@contextlib.contextmanager
def operation_diagnostic_context() -> Iterator[OperationDiagnosticBuffer]:
    """operation diagnostics を evaluation 単位に隔離して収集する。"""

    buffer = OperationDiagnosticBuffer()
    token = _operation_diagnostics_var.set(buffer)
    try:
        yield buffer
    finally:
        _operation_diagnostics_var.reset(token)


__all__ = [
    "OperationDiagnostic",
    "OperationDiagnosticBuffer",
    "OperationDiagnosticSeverity",
    "OperationDiagnosticValue",
    "current_operation_diagnostics",
    "emit_operation_diagnostic",
    "extend_operation_diagnostics",
    "operation_diagnostic_context",
]
