# どこで: `src/grafix/core/parameters/meta.py`。
# 何を: ParamMeta（GUI 表示/検証のためのメタ情報）を提供する。
# なぜ: GUI 生成と値検証に必要な型・レンジ情報を一元管理するため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class ParamMeta:
    """パラメータの UI/検証用メタ情報。

    ui_min/ui_max はスライダー初期レンジを示すだけで、実値をクランプしない。
    """

    kind: str  # "float" | "int" | "bool" | "str" | "font" | "choice" | "vec3" | "rgb"
    ui_min: Any | None = None
    ui_max: Any | None = None
    choices: Sequence[str] | None = None

    def __post_init__(self) -> None:
        """選択肢を tuple 化し、frozen spec の可変参照を残さない。"""

        if self.choices is not None:
            object.__setattr__(
                self,
                "choices",
                tuple(str(choice) for choice in self.choices),
            )
