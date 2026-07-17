# どこで: `src/grafix/core/parameters/meta.py`。
# 何を: ParamMeta（GUI 表示/検証のためのメタ情報）を提供する。
# なぜ: GUI 生成と値検証に必要な型・レンジ情報を一元管理するため。

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

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

    kind: str  # "float" | "int" | "bool" | "str" | "font" | "choice" | "vec3" | "rgb"
    ui_min: Any | None = None
    ui_max: Any | None = None
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

        if self.choices is not None:
            object.__setattr__(
                self,
                "choices",
                tuple(str(choice) for choice in self.choices),
            )

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


__all__ = ["ParamMeta", "ParamScale"]
