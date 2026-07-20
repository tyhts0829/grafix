# どこで: `src/grafix/core/parameters/view.py`。
# 何を: ParamStore スナップショットから UI 行モデルを生成し、UI 入力を正規化する純粋関数群を提供する。
# なぜ: DPG 依存部と切り離し、型変換・検証を単体テスト可能に保つため。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

from .key import ParameterKey
from .meta import ParamMeta, ParamScale
from .state import ParamStateSnapshot
from .validation import validate_parameter_value


@dataclass(frozen=True, slots=True)
class ParameterRow:
    """GUI 表示用の行モデル。"""

    label: str
    op: str
    site_id: str
    arg: str
    kind: str
    ui_value: Any
    ui_min: Any | None
    ui_max: Any | None
    choices: Sequence[str] | None
    cc_key: int | tuple[int | None, int | None, int | None] | None
    override: bool
    ordinal: int
    display_name: str | None = None
    description: str | None = None
    unit: str | None = None
    step: float | None = None
    format: str | None = None
    scale: ParamScale | None = None
    category: str | None = None
    advanced: bool = False
    recommended_range: tuple[float, float] | None = None
    favorite: bool = False
    # 1 GUI frame だけ有効な command。永続 state ではなく store bridge が消費する。
    reset_to_code: bool = False


def rows_from_snapshot(
    snapshot: Mapping[
        ParameterKey,
        tuple[ParamMeta, ParamStateSnapshot, int, str | None],
    ],
) -> list[ParameterRow]:
    """Snapshot から ParameterRow を生成し、op→ordinal→arg の順で並べる。"""

    rows: list[ParameterRow] = []
    for key, (meta, state, ordinal, _label) in snapshot.items():
        rows.append(
            ParameterRow(
                label=f"{ordinal}:{key.arg}",
                op=key.op,
                site_id=key.site_id,
                arg=key.arg,
                kind=meta.kind,
                ui_value=state.ui_value,
                ui_min=meta.ui_min,
                ui_max=meta.ui_max,
                choices=meta.choices,
                cc_key=state.cc_key,
                override=state.override,
                ordinal=ordinal,
                display_name=meta.display_name,
                description=meta.description,
                unit=meta.unit,
                step=meta.step,
                format=meta.format,
                scale=meta.scale,
                category=meta.category,
                advanced=meta.advanced,
                recommended_range=meta.recommended_range,
            )
        )
    rows.sort(key=lambda r: (r.op, r.ordinal, r.arg))
    return rows


def normalize_input(value: Any, meta: ParamMeta) -> tuple[Any | None, str | None]:
    """canonical widget value を検証し、変換せず返す。"""

    try:
        return (
            validate_parameter_value(
                value,
                kind=meta.kind,
                choices=meta.choices,
            ),
            None,
        )
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def canonicalize_ui_value(value: Any, meta: ParamMeta) -> Any:
    """meta.kind の canonical UI value を検証して返す。"""

    return validate_parameter_value(
        value,
        kind=meta.kind,
        choices=meta.choices,
    )


def canonicalize_ui_value_for_meta_change(
    stored_value: Any,
    base_value: Any,
    stored_meta: ParamMeta,
    current_meta: ParamMeta,
) -> Any:
    """同一 kind の保存値を維持し、kind 変更時だけ現在の code 値を採用する。"""

    if stored_meta.kind == current_meta.kind:
        return canonicalize_ui_value(stored_value, current_meta)
    return canonicalize_ui_value(base_value, current_meta)
