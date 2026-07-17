from grafix.interactive.parameter_gui.gui import ParameterGUI


def _new_gui_for_key_events() -> ParameterGUI:
    gui = ParameterGUI.__new__(ParameterGUI)
    gui._range_edit_key_r = 1
    gui._range_edit_key_e = 2
    gui._range_edit_key_t = 3
    gui._range_edit_key_escape = 4
    gui._range_edit_mode = None
    gui._range_edit_session = None
    return gui


def test_parameter_gui_ignores_none_symbol_on_key_press():
    gui = _new_gui_for_key_events()
    gui._on_key_press(None, 0)
    assert gui._range_edit_mode is None
    assert gui._range_edit_session is None


def test_parameter_gui_ignores_none_symbol_on_key_release():
    gui = _new_gui_for_key_events()
    gui._range_edit_mode = "shift"
    gui._on_key_release(None, 0)
    assert gui._range_edit_mode == "shift"


def test_range_edit_shortcut_enters_explicit_mode_and_escape_cancels() -> None:
    gui = _new_gui_for_key_events()

    gui._on_key_press(2, 0)
    assert gui._range_edit_mode == "min"
    assert gui._range_edit_session is None

    gui._on_key_press(4, 0)
    assert gui._range_edit_mode is None
    assert gui._range_edit_session is None
