# どこで: `src/grafix/core/parameters/runtime.py`。
# 何を: ParamStore の実行時情報（loaded/observed/reconcile-applied）を保持する。
# なぜ: 永続データと混ぜずに、reconcile/prune の判断材料を分離するため。

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .key import ParameterKey
from .reconcile import ReconcileOrphan
from .source import ValueSource

LoadProvenance = Literal["primary", "session_recovery", "quarantined"]


@dataclass(frozen=True, slots=True)
class ParamStoreLoadDiagnostic:
    """ParamStore load で発生した user-facing 診断材料。"""

    code: str
    summary: str
    details: str = ""
    backup_path: Path | None = None


@dataclass(slots=True)
class ParamStoreRuntime:
    """ParamStore の実行時情報。"""

    loaded_groups: set[tuple[str, str]] = field(default_factory=set)
    observed_groups: set[tuple[str, str]] = field(default_factory=set)
    reconcile_applied: set[tuple[tuple[str, str], tuple[str, str]]] = field(
        default_factory=set
    )
    display_order_by_group: dict[tuple[str, str], int] = field(default_factory=dict)
    next_display_order: int = 1
    last_effective_by_key: dict[ParameterKey, object] = field(default_factory=dict)
    warned_unknown_args: set[tuple[str, str]] = field(default_factory=set)
    # 新 field は従来 positional field の末尾に追加し、
    # ParamStoreRuntime(..., warned_unknown_args) の位置互換を保つ。
    last_source_by_key: dict[ParameterKey, ValueSource] = field(default_factory=dict)
    load_provenance: LoadProvenance = "primary"
    load_diagnostics: tuple[ParamStoreLoadDiagnostic, ...] = ()
    reconcile_orphans: dict[tuple[str, str], ReconcileOrphan] = field(
        default_factory=dict
    )
    # effective/source の最終 snapshot が変わった frame ごとに 1 回だけ進む。
    # 永続 store の revision と分け、毎 frame 更新され得る provenance/GUI cache の
    # 無効化に使う。
    effective_revision: int = 0


__all__ = [
    "LoadProvenance",
    "ParamStoreLoadDiagnostic",
    "ParamStoreRuntime",
]
