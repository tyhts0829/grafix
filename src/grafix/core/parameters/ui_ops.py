# どこで: `src/grafix/core/parameters/ui_ops.py`。
# 何を: UI 入力（文字列/数値/タプル等）を ParamState へ反映する更新手続きを提供する。
# なぜ: ParamState の参照リークを避け、更新経路を ops に固定するため。

from __future__ import annotations

from typing import Any

from .key import ParameterKey
from .meta import ParamMeta
from .store import ParamStore
from .view import canonicalize_ui_value, normalize_input


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

    normalized, err = normalize_input(ui_input_value, meta)
    if err and normalized is None:
        return False, err

    canonical = canonicalize_ui_value(
        ui_input_value if normalized is None else normalized,
        meta,
    )

    # History の patch transaction は変更対象が判明した時点で、この 1 key
    # だけの変更前値を退避する。既存 key の slider 操作で store 全体を
    # deepcopy しないため、代入より前に通知する必要がある。
    store._observe_history_key_before(key)
    state = store._ensure_state(key, base_value=canonical)
    before = (state.ui_value, state.override, state.cc_key)
    state.ui_value = canonical
    if override is not None:
        state.override = bool(override)

    if not isinstance(cc_key, _KeepCcKey):
        if cc_key is None:
            state.cc_key = None
        elif isinstance(cc_key, int):
            state.cc_key = int(cc_key)
        else:
            a, b, c = cc_key
            cc_tuple = (
                None if a is None else int(a),
                None if b is None else int(b),
                None if c is None else int(c),
            )
            state.cc_key = None if cc_tuple == (None, None, None) else cc_tuple

    if (state.ui_value, state.override, state.cc_key) != before:
        store._touch(structure=False, value_keys=(key,))

    return True, err


__all__ = ["update_state_from_ui"]
