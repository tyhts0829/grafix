# どこで: `src/grafix/core/parameters/meta.py`。
# 何を: ParamMeta（GUI 表示/検証のためのメタ情報）を提供する。
# なぜ: GUI 生成と値検証に必要な型・レンジ情報を一元管理するため。

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from .validation import (
    ParamKind,
    validate_param_choices,
    validate_param_kind,
    validate_param_range,
)

ParamScale = Literal["linear", "log"]


def _finite_number(value: object, *, field: str) -> float:
    """metadata の有限な数値を float へ正規化する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} は有限な数値である必要があります")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} は有限な数値である必要があります")
    return normalized


def _validate_optional_text(value: object, *, field: str) -> None:
    """optional text metadata の型だけを検証する。"""

    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field} は str または None である必要があります")


@dataclass(frozen=True, slots=True)
class ParamMeta:
    """パラメータの UI/検証用メタ情報。

    ``ui_min`` / ``ui_max`` はスライダー初期レンジを示すだけで、実値を
    クランプしない。その他の optional field は、表示名や単位、推奨範囲などを
    GUI・stub generator へ伝える semantic hint である。
    """

    kind: ParamKind
    ui_min: int | float | None = None
    ui_max: int | float | None = None
    choices: Sequence[str] | None = None
    display_name: str | None = None
    description: str | None = None
    unit: str | None = None
    step: float | None = None
    format: str | None = None
    scale: ParamScale | None = None
    category: str | None = None
    advanced: bool = False
    recommended_range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        """semantic hint を検証・正規化し、可変参照を残さない。"""

        kind = validate_param_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "choices",
            validate_param_choices(kind, self.choices),
        )
        ui_min, ui_max = validate_param_range(
            kind,
            self.ui_min,
            self.ui_max,
        )
        object.__setattr__(self, "ui_min", ui_min)
        object.__setattr__(self, "ui_max", ui_max)

        for field, value in (
            ("display_name", self.display_name),
            ("description", self.description),
            ("unit", self.unit),
            ("format", self.format),
            ("category", self.category),
        ):
            _validate_optional_text(value, field=field)

        if not isinstance(self.advanced, bool):
            raise TypeError("advanced は bool である必要があります")

        if self.scale is not None:
            if not isinstance(self.scale, str):
                raise TypeError("scale は str または None である必要があります")
            if self.scale not in {"linear", "log"}:
                raise ValueError("scale は 'linear'、'log'、または None である必要があります")

        if self.step is not None:
            step = _finite_number(self.step, field="step")
            if step <= 0.0:
                raise ValueError("step は 0 より大きい必要があります")
            object.__setattr__(self, "step", step)

        if self.recommended_range is not None:
            raw_range = self.recommended_range
            if isinstance(raw_range, (str, bytes)) or not isinstance(raw_range, Sequence):
                raise TypeError("recommended_range は 2 要素の数値列である必要があります")
            if len(raw_range) != 2:
                raise ValueError("recommended_range は 2 要素である必要があります")
            lower = _finite_number(raw_range[0], field="recommended_range[0]")
            upper = _finite_number(raw_range[1], field="recommended_range[1]")
            if lower >= upper:
                raise ValueError("recommended_range は lower < upper である必要があります")
            object.__setattr__(self, "recommended_range", (lower, upper))


def _code_owned_fields(meta: ParamMeta) -> tuple[object, ...]:
    """ParamMeta から GUI-owned range を除く比較用タプルを返す。"""

    return (
        meta.kind,
        meta.choices,
        meta.display_name,
        meta.description,
        meta.unit,
        meta.step,
        meta.format,
        meta.scale,
        meta.category,
        meta.advanced,
        meta.recommended_range,
    )


def merge_code_meta_with_stored_gui_meta(
    code_meta: ParamMeta,
    stored_meta: ParamMeta,
) -> ParamMeta:
    """現在の code-owned metadata と保存済み GUI range を統合する。

    ``kind``、``choices``、説明などは現在のコードを正とする。一方、
    ``ui_min`` / ``ui_max`` は GUI が調整して永続化する値なので保存値を維持する。
    """

    if code_meta is stored_meta:
        return stored_meta
    if _code_owned_fields(code_meta) == _code_owned_fields(stored_meta):
        return stored_meta
    if code_meta.kind == stored_meta.kind:
        return replace(
            code_meta,
            ui_min=stored_meta.ui_min,
            ui_max=stored_meta.ui_max,
        )
    return code_meta


__all__ = [
    "ParamMeta",
    "ParamScale",
    "merge_code_meta_with_stored_gui_meta",
]
