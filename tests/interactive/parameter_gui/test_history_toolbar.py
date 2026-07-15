from grafix.core.parameters import FrameParamRecord, ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.history import ParamSnapshotSlots, ParamStoreHistory
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.interactive.parameter_gui.gui import ParameterGUI


META = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)


class _FakeImGui:
    def __init__(self, clicked: str) -> None:
        self.clicked = clicked

    def button(self, label: str) -> bool:
        return label.rpartition("##")[2] == self.clicked

    def same_line(self) -> None:
        pass

    def text_disabled(self, _text: str) -> None:
        pass


def _setup() -> tuple[ParameterGUI, ParamStore, ParameterKey, ParamStoreHistory]:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site", arg="radius")
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=0.25, meta=META, explicit=False)],
    )
    history = ParamStoreHistory(store)
    gui = ParameterGUI.__new__(ParameterGUI)
    gui._history = history
    gui._snapshot_slots = ParamSnapshotSlots(store)
    return gui, store, key, history


def _set(store: ParamStore, key: ParameterKey, value: float) -> None:
    ok, error = update_state_from_ui(store, key, value, meta=META)
    assert ok and error is None


def _value(store: ParamStore, key: ParameterKey) -> float:
    state = store.get_state(key)
    assert state is not None
    return float(state.ui_value)


def test_history_toolbar_undo_restores_the_previous_value() -> None:
    gui, store, key, history = _setup()
    _set(store, key, 0.75)
    history.record_change(source="test")
    gui._imgui = _FakeImGui("param_undo")

    assert gui._render_history_toolbar() is True
    assert _value(store, key) == 0.25


def test_snapshot_restore_is_itself_undoable() -> None:
    gui, store, key, history = _setup()
    gui._imgui = _FakeImGui("snapshot_set_A")
    assert gui._render_history_toolbar() is False

    _set(store, key, 0.9)
    history.record_change(source="test")
    gui._imgui = _FakeImGui("snapshot_load_A")
    assert gui._render_history_toolbar() is True
    assert _value(store, key) == 0.25

    assert history.undo() is True
    assert _value(store, key) == 0.9


def test_command_z_and_shift_command_z_drive_parameter_history() -> None:
    gui, store, key, history = _setup()
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
