# どこで: `src/grafix/core/parameters/state.py`。
# 何を: ParamState を定義する。
# なぜ: GUI 側からの設定と既定値を保持し、snapshot の単位にするため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grafix.core.value_validation import canonical_immutable_value, exact_bool

from .validation import CcKey, validate_cc_key_shape


@dataclass
class ParamState:
    """単一 ParameterKey に紐づく GUI 状態（レンジ情報は保持しない）。"""

    override: bool = True
    ui_value: Any = None
    cc_key: CcKey = None

    def __post_init__(self) -> None:
        self.override = exact_bool(self.override, name="override")
        self.ui_value = canonical_immutable_value(
            self.ui_value,
            name="ui_value",
        )
        self.cc_key = validate_cc_key_shape(self.cc_key)


@dataclass(frozen=True, slots=True)
class ParamStateSnapshot:
    """revision cache から安全に共有できる読み取り専用の ParamState。"""

    override: bool
    ui_value: Any
    cc_key: CcKey

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "override",
            exact_bool(self.override, name="state.override"),
        )
        object.__setattr__(
            self,
            "ui_value",
            canonical_immutable_value(
                self.ui_value,
                name="state.ui_value",
            ),
        )
        object.__setattr__(
            self,
            "cc_key",
            validate_cc_key_shape(self.cc_key),
        )

    @classmethod
    def from_state(cls, state: ParamState) -> ParamStateSnapshot:
        """mutable な store state を読み取り専用値へコピーする。"""

        return cls(
            override=state.override,
            ui_value=state.ui_value,
            cc_key=state.cc_key,
        )
