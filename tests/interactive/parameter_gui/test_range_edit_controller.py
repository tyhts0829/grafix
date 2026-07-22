from __future__ import annotations

import ast
from pathlib import Path

import pytest

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.interactive.parameter_gui.range_edit_controller import RangeEditController


def test_range_edit_controller_has_no_imgui_or_window_dependency() -> None:
    source = Path(
        "src/grafix/interactive/parameter_gui/range_edit_controller.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("imgui" in module or "pyglet" in module for module in imported)


def _range_parameter(store: ParamStore, *, arg: str, cc: int) -> ParameterKey:
    key = ParameterKey(op="wave", site_id="site", arg=arg)
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=2.0)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.5,
                meta=meta,
                effective=0.5,
                source="code",
                explicit=False,
            )
        ],
    )
    updated, error = update_state_from_ui(
        store,
        key,
        0.5,
        meta=meta,
        cc_key=cc,
    )
    assert updated and error is None
    return key


def test_range_edit_controller_preview_and_cancel_leave_store_unchanged() -> None:
    store = ParamStore()
    key = _range_parameter(store, arg="amount", cc=7)
    controller = RangeEditController(store)

    controller.begin("shift")
    assert controller.preview_midi_change(sequence=1, cc=7, value=0.25) is False
    assert controller.preview_midi_change(sequence=2, cc=7, value=0.5) is True
    assert controller.session is not None
    assert controller.session.targets[0].pending_range == (0.5, 2.5)
    assert store.get_meta(key) == ParamMeta(kind="float", ui_min=0.0, ui_max=2.0)

    controller.cancel()
    assert controller.mode is None
    assert controller.session is None
    assert store.get_meta(key) == ParamMeta(kind="float", ui_min=0.0, ui_max=2.0)


def test_range_edit_controller_commit_is_one_undo_step() -> None:
    store = ParamStore()
    first = _range_parameter(store, arg="first", cc=11)
    second = _range_parameter(store, arg="second", cc=11)
    history = ParamStoreHistory(store)
    controller = RangeEditController(store, history=history)

    controller.begin("max")
    controller.preview_midi_change(sequence=1, cc=11, value=0.0)
    assert controller.preview_midi_change(sequence=2, cc=11, value=0.5) is True
    assert controller.commit() == (first, second)
    assert controller.mode is None
    assert history.undo_depth == 1
    assert store.get_meta(first).ui_max == 3.0  # type: ignore[union-attr]
    assert store.get_meta(second).ui_max == 3.0  # type: ignore[union-attr]

    assert history.undo() is True
    assert store.get_meta(first).ui_max == 2.0  # type: ignore[union-attr]
    assert store.get_meta(second).ui_max == 2.0  # type: ignore[union-attr]


def test_range_edit_controller_ignores_repeated_sequence_and_noop_commit() -> None:
    store = ParamStore()
    _range_parameter(store, arg="amount", cc=5)
    controller = RangeEditController(store)

    controller.begin("min")
    assert controller.preview_midi_change(sequence=1, cc=5, value=0.1) is False
    assert controller.preview_midi_change(sequence=1, cc=5, value=0.9) is False
    assert controller.session is None
    assert controller.commit() == ()
    assert controller.mode == "min"


def test_blocked_midi_change_advances_baseline_without_preview() -> None:
    store = ParamStore()
    _range_parameter(store, arg="amount", cc=9)
    controller = RangeEditController(store)
    controller.begin("shift")

    assert controller.preview_midi_change(
        sequence=1,
        cc=9,
        value=0.2,
        blocked=True,
    ) is False
    assert controller.preview_midi_change(
        sequence=2,
        cc=9,
        value=0.4,
        blocked=True,
    ) is False
    assert controller.preview_midi_change(sequence=3, cc=9, value=0.5) is True
    assert controller.session is not None
    assert controller.session.targets[0].pending_range == pytest.approx((0.2, 2.2))
