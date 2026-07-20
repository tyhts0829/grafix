# どこで: `src/grafix/core/parameters/ui_ops.py`。
# 何を: UI 入力（文字列/数値/タプル等）を ParamState へ反映する更新手続きを提供する。
# なぜ: ParamState の参照リークを避け、更新経路を ops に固定するため。

from __future__ import annotations

from typing import Any

from .key import ParameterKey
from .meta import ParamMeta
from .store import ParamStore
from .validation import validate_cc_key, validate_parameter_value


class _KeepCcKey:
    pass


_KEEP = _KeepCcKey()


def update_state_from_ui(
    store: ParamStore,
    key: ParameterKey,
    ui_input_value: Any,
    *,
    meta: ParamMeta,
    override: bool | None = None,
    cc_key: int | tuple[int | None, int | None, int | None] | None | _KeepCcKey = _KEEP,
) -> tuple[bool, str | None]:
    """UI から渡された入力を正規化し、対応する ParamState に反映する。"""

    try:
        canonical = validate_parameter_value(
            ui_input_value,
            kind=meta.kind,
            choices=meta.choices,
        )
        if override is not None and type(override) is not bool:
            raise TypeError("override must be an exact bool or None")
        canonical_cc = (
            cc_key
            if isinstance(cc_key, _KeepCcKey)
            else validate_cc_key(cc_key, kind=meta.kind, op=key.op)
        )
    except (TypeError, ValueError) as exc:
        return False, str(exc)

    # History の patch transaction は変更対象が判明した時点で、この 1 key
    # だけの変更前値を退避する。既存 key の slider 操作で store 全体を
    # deepcopy しないため、代入より前に通知する必要がある。
    store._observe_history_key_before(key)
    state = store._ensure_state(key, base_value=canonical, explicit=False)
    before = (state.ui_value, state.override, state.cc_key)
    state.ui_value = canonical
    if override is not None:
        state.override = override

    if not isinstance(canonical_cc, _KeepCcKey):
        state.cc_key = canonical_cc

    if (state.ui_value, state.override, state.cc_key) != before:
        store._touch(structure=False, value_keys=(key,))

    return True, None


__all__ = ["update_state_from_ui"]
