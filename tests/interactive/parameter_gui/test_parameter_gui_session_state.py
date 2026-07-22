from grafix.core.parameters.store import ParamStore
from grafix.interactive.parameter_gui.parameter_filter import ParameterFilterState
from grafix.interactive.parameter_gui.session_state import ParameterGuiSessionState


def test_parameter_gui_session_state_owns_mutable_frame_state() -> None:
    session = ParameterGuiSessionState.for_store(ParamStore())

    assert session.filter_state == ParameterFilterState()
    assert session.table_view is None
    assert session.help_row is None
    assert session.midi_clear_notice is None
    assert session.reconcile_model is not None

    session.show_inactive_parameters = True
    session.filter_state = ParameterFilterState(query="radius")
    session.parameter_edit_active = True
    session.invalidate_table()

    assert session.show_inactive_parameters is True
    assert session.filter_state.query == "radius"
    assert session.parameter_edit_active is True
    assert session.table_view is None
