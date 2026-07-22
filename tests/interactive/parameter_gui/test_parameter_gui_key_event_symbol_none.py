from grafix.interactive.parameter_gui.gui import ParameterGUI


def _new_gui_for_key_events(gui: ParameterGUI) -> ParameterGUI:
    gui._range_edit_key_r = 1
    gui._range_edit_key_e = 2
    gui._range_edit_key_t = 3
    gui._range_edit_key_escape = 4
    gui._range_edit_controller.cancel()
    return gui


def test_parameter_gui_ignores_none_symbol_on_key_press(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui = _new_gui_for_key_events(initialized_parameter_gui)
    gui._on_key_press(None, 0)
    assert gui._range_edit_controller.mode is None
    assert gui._range_edit_controller.session is None


def test_range_edit_shortcut_enters_explicit_mode_and_escape_cancels(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui = _new_gui_for_key_events(initialized_parameter_gui)

    gui._on_key_press(2, 0)
    assert gui._range_edit_controller.mode == "min"
    assert gui._range_edit_controller.session is None

    gui._on_key_press(4, 0)
    assert gui._range_edit_controller.mode is None
    assert gui._range_edit_controller.session is None
