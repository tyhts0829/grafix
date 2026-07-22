from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from grafix.core.parameters import FrameParamRecord, ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.parameters.variations import create_variation
from grafix.interactive.parameter_gui.gui import ParameterGUI
from grafix.interactive.parameter_gui.variation_controller import VariationController


META = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)


class _Popup:
    opened = False

    def __enter__(self) -> _Popup:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeImGui:
    def __init__(self, clicked: str) -> None:
        self.clicked = clicked
        self.labels: list[str] = []

    @staticmethod
    def get_io() -> object:
        return SimpleNamespace(
            want_text_input=False,
            want_capture_keyboard=False,
        )

    def button(self, label: str, width: float = 0.0, height: float = 0.0) -> bool:
        self.labels.append(str(label))
        return label.rpartition("##")[2] == self.clicked

    def same_line(self, position: float = 0.0, spacing: float = -1.0) -> None:
        pass

    def text_disabled(self, _text: str) -> None:
        pass

    def begin_popup(self, _label: str) -> _Popup:
        return _Popup()

    def open_popup(self, _label: str) -> None:
        pass


def _setup(
    gui: ParameterGUI,
) -> tuple[Any, ParamStore, ParameterKey, ParamStoreHistory]:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site", arg="radius")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.25,
                meta=META,
                effective=0.25,
                source="code",
                explicit=False,
            )
        ],
    )
    history = ParamStoreHistory(store)
    gui_state = cast(Any, gui)
    gui_state._store = store
    gui_state._history = history
    gui_state._variation_controller = VariationController(store, history=history)
    gui_state._session.table_view = None
    return gui_state, store, key, history


def _set(store: ParamStore, key: ParameterKey, value: float) -> None:
    ok, error = update_state_from_ui(store, key, value, meta=META)
    assert ok and error is None


def _value(store: ParamStore, key: ParameterKey) -> float:
    state = store.get_state(key)
    assert state is not None
    return float(state.ui_value)


def test_history_toolbar_undo_restores_the_previous_value(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui, store, key, history = _setup(initialized_parameter_gui)
    _set(store, key, 0.75)
    history.record_change(source="test")
    gui._imgui = _FakeImGui("param_undo")

    assert gui._render_history_toolbar() is True
    assert _value(store, key) == 0.25


def test_named_variation_restore_is_itself_undoable(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui, store, key, history = _setup(initialized_parameter_gui)
    create_variation(store, "saved", created_at=100.0)

    _set(store, key, 0.9)
    history.synchronize()
    assert gui._variation_controller.load("saved") is True
    assert _value(store, key) == 0.25

    assert history.undo() is True
    assert _value(store, key) == 0.9


def test_history_toolbar_exposes_named_variations_without_ab_slots(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui, _store, _key, _history = _setup(initialized_parameter_gui)
    imgui = _FakeImGui("")
    gui._imgui = imgui

    assert gui._render_history_toolbar() is False

    assert any("Variations" in label for label in imgui.labels)
    assert not any("snapshot_" in label for label in imgui.labels)


def test_command_z_and_shift_command_z_drive_parameter_history(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui, store, key, history = _setup(initialized_parameter_gui)
    _set(store, key, 0.75)
    history.record_change(source="test")
    gui._imgui = _FakeImGui("")
    gui._history_key_z = 90
    gui._history_key_y = 89
    gui._shortcut_modifier_mask = 0b0010 | 0b0100
    gui._shortcut_shift_mask = 0b1000
    gui._range_edit_key_r = -1
    gui._range_edit_key_e = -1
    gui._range_edit_key_t = -1
    gui._transport = None

    gui._on_key_press(90, 0b0010)
    assert _value(store, key) == 0.25

    gui._on_key_press(90, 0b0010 | 0b1000)
    assert _value(store, key) == 0.75
