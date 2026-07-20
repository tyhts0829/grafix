# どこで: `src/grafix/core/parameters/state.py`。
# 何を: ParamState を定義する。
# なぜ: GUI 側からの設定と既定値を保持し、snapshot の単位にするため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParamState:
    """単一 ParameterKey に紐づく GUI 状態（レンジ情報は保持しない）。"""

    override: bool = True
    ui_value: Any = None
    cc_key: int | tuple[int | None, int | None, int | None] | None = None


@dataclass(frozen=True, slots=True)
class ParamStateSnapshot:
    """revision cache から安全に共有できる読み取り専用の ParamState。"""

    override: bool
    ui_value: Any
    cc_key: int | tuple[int | None, int | None, int | None] | None

    @classmethod
    def from_state(cls, state: ParamState) -> ParamStateSnapshot:
        """mutable な store state を読み取り専用値へコピーする。"""

        if type(state.override) is not bool:
            raise TypeError("state.override must be an exact bool")
        return cls(
            override=state.override,
            ui_value=state.ui_value,
            cc_key=state.cc_key,
        )
