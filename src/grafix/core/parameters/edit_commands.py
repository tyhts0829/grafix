"""Parameter GUI などから渡された immutable edit command を適用する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .favorites import favorite_parameter_key_set, set_parameters_favorite
from .key import ParameterKey
from .meta import ParamMeta
from .meta_ops import set_meta
from .store import ParamStore
from .ui_ops import update_state_from_ui
from .validation import CcKey, validate_cc_key, validate_parameter_value


@dataclass(frozen=True, slots=True)
class ParameterEdit:
    """一つの parameter の最終 UI-owned state。"""

    key: ParameterKey
    meta: ParamMeta
    ui_value: Any
    override: bool
    cc_key: CcKey
    favorite: bool

    def __post_init__(self) -> None:
        if not isinstance(self.key, ParameterKey):
            raise TypeError("key must be a ParameterKey")
        if not isinstance(self.meta, ParamMeta):
            raise TypeError("meta must be a ParamMeta")
        if type(self.override) is not bool:
            raise TypeError("override must be an exact bool")
        if type(self.favorite) is not bool:
            raise TypeError("favorite must be an exact bool")
        object.__setattr__(
            self,
            "ui_value",
            validate_parameter_value(
                self.ui_value,
                kind=self.meta.kind,
                choices=self.meta.choices,
            ),
        )
        object.__setattr__(
            self,
            "cc_key",
            validate_cc_key(
                self.cc_key,
                kind=self.meta.kind,
                op=self.key.op,
            ),
        )


def apply_parameter_edits(
    store: ParamStore,
    edits: tuple[ParameterEdit, ...],
) -> tuple[ParameterKey, ...]:
    """複数 edit を一つの core command として適用する。

    実差分がない edit は無視する。複数 key を変更しても store revision は
    一度だけ進み、history observer は各 key の変更前値を取得できる。
    """

    if not isinstance(store, ParamStore):
        raise TypeError("store must be a ParamStore")
    if not isinstance(edits, tuple) or not all(
        isinstance(edit, ParameterEdit) for edit in edits
    ):
        raise TypeError("edits must be a tuple of ParameterEdit values")
    keys = tuple(edit.key for edit in edits)
    if len(set(keys)) != len(keys):
        raise ValueError("edits must contain at most one command per key")

    favorites_before = favorite_parameter_key_set(store)
    changed: list[ParameterEdit] = []
    for edit in edits:
        state = store.get_state(edit.key)
        if (
            store.get_meta(edit.key) != edit.meta
            or state is None
            or state.ui_value != edit.ui_value
            or state.override != edit.override
            or state.cc_key != edit.cc_key
            or (edit.key in favorites_before) != edit.favorite
        ):
            changed.append(edit)
    if not changed:
        return ()

    revision_before = store.revision
    owner = object()
    store._begin_mutation_batch(owner)
    try:
        favorite_on: list[ParameterKey] = []
        favorite_off: list[ParameterKey] = []
        for edit in changed:
            state = store.get_state(edit.key)
            if store.get_meta(edit.key) != edit.meta:
                set_meta(store, edit.key, edit.meta)
            if (
                state is None
                or state.ui_value != edit.ui_value
                or state.override != edit.override
                or state.cc_key != edit.cc_key
            ):
                ok, error = update_state_from_ui(
                    store,
                    edit.key,
                    edit.ui_value,
                    meta=edit.meta,
                    override=edit.override,
                    cc_key=edit.cc_key,
                )
                if not ok:
                    raise ValueError(error or f"invalid parameter edit: {edit.key!r}")
            favorite_before = edit.key in favorites_before
            if edit.favorite != favorite_before:
                (favorite_on if edit.favorite else favorite_off).append(edit.key)

        if favorite_on:
            set_parameters_favorite(store, favorite_on, favorite=True)
        if favorite_off:
            set_parameters_favorite(store, favorite_off, favorite=False)
    finally:
        store._end_mutation_batch(owner)

    if store.revision == revision_before:
        return ()
    return tuple(edit.key for edit in changed)


__all__ = ["ParameterEdit", "apply_parameter_edits"]
