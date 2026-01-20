from grafix.interactive.parameter_gui.gui import ParameterGUI


def _new_gui_for_key_events() -> ParameterGUI:
    gui = ParameterGUI.__new__(ParameterGUI)
    gui._range_edit_key_r = 1
    gui._range_edit_key_e = 2
    gui._range_edit_key_t = 3
    gui._range_edit_r_down = False
    gui._range_edit_e_down = False
    gui._range_edit_t_down = False
    return gui


def test_parameter_gui_ignores_none_symbol_on_key_press():
    gui = _new_gui_for_key_events()
    gui._on_key_press(None, 0)
    assert gui._range_edit_r_down is False
    assert gui._range_edit_e_down is False
    assert gui._range_edit_t_down is False


def test_parameter_gui_ignores_none_symbol_on_key_release():
    gui = _new_gui_for_key_events()
    gui._range_edit_r_down = True
    gui._range_edit_e_down = True
    gui._range_edit_t_down = True
    gui._on_key_release(None, 0)
    assert gui._range_edit_r_down is True
    assert gui._range_edit_e_down is True
    assert gui._range_edit_t_down is True

