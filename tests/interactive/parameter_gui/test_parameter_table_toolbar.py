from __future__ import annotations

from types import SimpleNamespace

from grafix.core.parameters import FrameParamRecord, ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.interactive.parameter_gui.gui import ParameterGUI


class _Popup:
    def __init__(self, *, opened: bool) -> None:
        self.opened = bool(opened)

    def __enter__(self) -> _Popup:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Imgui:
    def __init__(
        self,
        *,
        click_clear: bool,
        click_undo: bool = False,
        query: str = "",
        click_filter: bool = False,
        clicked_filter_ids: set[str] | None = None,
    ) -> None:
        self.click_clear = bool(click_clear)
        self.click_undo = bool(click_undo)
        self.query = str(query)
        self.click_filter = bool(click_filter)
        self.clicked_filter_ids = set(clicked_filter_ids or set())
        self.checkbox_labels: list[str] = []
        self.menu_enabled: list[bool] = []
        self.opened_popups: list[str] = []
        self.disabled_text: list[str] = []

    def text_disabled(self, text: str) -> None:
        self.disabled_text.append(str(text))

    def text(self, _text: str) -> None:
        pass

    def same_line(self) -> None:
        pass

    def input_text_with_hint(
        self,
        _label: str,
        _hint: str,
        value: str,
    ) -> tuple[bool, str]:
        return self.query != str(value), self.query

    def set_next_item_width(self, _width: float) -> None:
        pass

    def checkbox(self, label: str, _value: bool) -> tuple[bool, bool]:
        self.checkbox_labels.append(label)
        return True, True

    def button(self, label: str) -> bool:
        widget_id = label.rpartition("##")[2]
        if widget_id == "midi_menu":
            return True
        if widget_id == "parameter_filter_menu":
            return self.click_filter
        if widget_id == "midi_clear_notice_undo":
            return self.click_undo
        return False

    def open_popup(self, label: str) -> None:
        self.opened_popups.append(label)

    def begin_popup(self, label: str) -> _Popup:
        return _Popup(opened=label in self.opened_popups)

    def menu_item(
        self,
        label: str,
        _shortcut: str | None = None,
        selected: bool = False,
        enabled: bool = True,
    ) -> tuple[bool, bool]:
        widget_id = label.rpartition("##")[2]
        if widget_id == "clear_midi_assigns":
            self.menu_enabled.append(bool(enabled))
            return self.click_clear and bool(enabled), bool(selected)
        return widget_id in self.clicked_filter_ids and bool(enabled), bool(selected)

    def separator(self) -> None:
        pass


def _setup_with_mapping() -> tuple[ParameterGUI, ParamStore, ParameterKey]:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=0.25, meta=meta, explicit=False)],
    )
    ok, error = update_state_from_ui(
        store,
        key,
        0.5,
        meta=meta,
        override=True,
        cc_key=12,
    )
    assert ok and error is None

    gui = ParameterGUI.__new__(ParameterGUI)
    gui._store = store
    gui._show_inactive_params = False
    gui._midi_clear_notice = None
    gui._midi_clear_notice_token = None
    gui._history = None
    gui._midi_learn_state = SimpleNamespace(active_target="target", active_component=0)
    return gui, store, key


def test_table_toolbar_names_filter_and_moves_clear_into_midi_menu() -> None:
    gui, store, key = _setup_with_mapping()
    imgui = _Imgui(click_clear=True)
    gui._imgui = imgui

    assert gui._render_parameter_table_toolbar() is True

    assert imgui.checkbox_labels == ["Show inactive##show_inactive_params"]
    assert imgui.opened_popups == ["MIDI mappings##midi_menu_popup"]
    assert imgui.menu_enabled == [True]
    assert gui._show_inactive_params is True
    assert gui._midi_learn_state.active_target is None
    assert gui._midi_learn_state.active_component is None
    assert gui._midi_clear_notice == "MIDI mappings cleared"
    state = store.get_state(key)
    assert state is not None and state.cc_key is None


def test_table_toolbar_updates_search_filter_and_displays_filtered_count() -> None:
    gui, _store, _key = _setup_with_mapping()
    imgui = _Imgui(
        click_clear=False,
        query="CIRCLE MIDI 12",
        click_filter=True,
        clicked_filter_ids={"filter_activity_active", "filter_midi_mapped"},
    )
    gui._imgui = imgui

    assert gui._render_parameter_table_toolbar() is False

    assert gui._parameter_filter_state.query == "CIRCLE MIDI 12"
    assert gui._parameter_filter_state.activity == "active"
    assert gui._parameter_filter_state.midi_mapped_only is True
    assert "1 / 1 parameters" in imgui.disabled_text


def test_clear_all_menu_item_is_disabled_without_mappings() -> None:
    gui, store, key = _setup_with_mapping()
    state = store.get_state(key)
    meta = store.get_meta(key)
    assert state is not None and meta is not None
    ok, error = update_state_from_ui(
        store,
        key,
        state.ui_value,
        meta=meta,
        override=state.override,
        cc_key=None,
    )
    assert ok and error is None
    imgui = _Imgui(click_clear=True)
    gui._imgui = imgui

    assert gui._render_parameter_table_toolbar() is False
    assert imgui.menu_enabled == [False]
    assert gui._midi_clear_notice is None


def test_clear_notice_exposes_one_click_undo() -> None:
    gui, store, key = _setup_with_mapping()
    history = ParamStoreHistory(store)
    gui._history = history
    gui._imgui = _Imgui(click_clear=True)
    assert gui._render_parameter_table_toolbar() is True
    assert history.undo_depth == 1

    gui._imgui = _Imgui(click_clear=False, click_undo=True)
    assert gui._render_midi_clear_notice() is True

    state = store.get_state(key)
    assert state is not None and state.cc_key == 12
    assert gui._midi_clear_notice is None


def test_clear_notice_disappears_instead_of_undoing_a_later_edit() -> None:
    gui, store, key = _setup_with_mapping()
    history = ParamStoreHistory(store)
    gui._history = history
    gui._imgui = _Imgui(click_clear=True)
    assert gui._render_parameter_table_toolbar() is True

    meta = store.get_meta(key)
    assert meta is not None
    with history.transaction(source="later_parameter_edit"):
        ok, error = update_state_from_ui(store, key, 0.9, meta=meta, override=True)
        assert ok and error is None
    assert history.undo_depth == 2

    gui._imgui = _Imgui(click_clear=False, click_undo=True)
    assert gui._render_midi_clear_notice() is False
    state = store.get_state(key)
    assert state is not None and state.ui_value == 0.9
    assert gui._midi_clear_notice is None


def test_vec3_menu_counts_each_assigned_component() -> None:
    store = ParamStore()
    key = ParameterKey(op="scale", site_id="site", arg="xyz")
    meta = ParamMeta(kind="vec3", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=(0.0, 0.0, 0.0), meta=meta, explicit=False)],
    )
    ok, error = update_state_from_ui(
        store,
        key,
        (0.1, 0.2, 0.3),
        meta=meta,
        cc_key=(10, 11, 12),
    )
    assert ok and error is None
    gui = ParameterGUI.__new__(ParameterGUI)
    gui._store = store
    gui._history = None
    gui._show_inactive_params = False
    gui._midi_clear_notice = None
    gui._midi_clear_notice_token = None
    gui._midi_learn_state = SimpleNamespace(active_target=None, active_component=None)
    imgui = _Imgui(click_clear=False)
    gui._imgui = imgui

    assert gui._render_parameter_table_toolbar() is False
    assert any("3 mappings" in text for text in imgui.disabled_text)
