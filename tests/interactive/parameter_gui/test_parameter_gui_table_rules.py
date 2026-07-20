import pytest

from grafix.interactive.parameter_gui.rules import ui_rules_for_row
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.view import ParameterRow


def _row(*, op: str, arg: str, kind: str) -> ParameterRow:
    return ParameterRow(
        label="",
        op=op,
        site_id="s",
        arg=arg,
        kind=kind,
        ui_value=None,
        ui_min=None,
        ui_max=None,
        choices=None,
        cc_key=None,
        override=True,
        ordinal=1,
    )


def test_ui_rules_for_row_defaults_by_kind():
    assert ui_rules_for_row(_row(op="circle", arg="r", kind="float")).minmax == "float_range"
    assert ui_rules_for_row(_row(op="circle", arg="n", kind="int")).minmax == "int_range"
    assert ui_rules_for_row(_row(op="circle", arg="p", kind="vec3")).minmax == "float_range"
    assert ui_rules_for_row(_row(op="circle", arg="c", kind="rgb")).minmax == "none"
    assert ui_rules_for_row(_row(op="circle", arg="f", kind="font")).minmax == "none"

    assert ui_rules_for_row(_row(op="circle", arg="r", kind="float")).cc_key == "int"
    assert ui_rules_for_row(_row(op="circle", arg="n", kind="int")).cc_key == "int"
    assert ui_rules_for_row(_row(op="circle", arg="p", kind="vec3")).cc_key == "int3"
    # RGB tuple CC は resolver が未対応なので、割り当て可能に見せない。
    assert ui_rules_for_row(_row(op="circle", arg="c", kind="rgb")).cc_key == "none"

    assert ui_rules_for_row(_row(op="circle", arg="b", kind="bool")).cc_key == "none"
    assert ui_rules_for_row(_row(op="circle", arg="b", kind="bool")).show_override is True
    assert ui_rules_for_row(_row(op="circle", arg="s", kind="str")).cc_key == "none"
    assert ui_rules_for_row(_row(op="circle", arg="s", kind="str")).show_override is True
    assert ui_rules_for_row(_row(op="circle", arg="f", kind="font")).cc_key == "none"
    assert ui_rules_for_row(_row(op="circle", arg="f", kind="font")).show_override is True
    assert ui_rules_for_row(_row(op="circle", arg="c", kind="choice")).cc_key == "int"
    assert ui_rules_for_row(_row(op="circle", arg="c", kind="choice")).show_override is True


def test_ui_rules_for_row_minmax_exceptions_by_key():
    style_thickness = _row(op=STYLE_OP, arg="global_thickness", kind="float")
    assert ui_rules_for_row(style_thickness).minmax == "none"
    # Style 専用 resolver は cc_snapshot を解決しない。
    assert ui_rules_for_row(style_thickness).cc_key == "none"
    assert ui_rules_for_row(style_thickness).show_override is True

    layer_thickness = _row(op=LAYER_STYLE_OP, arg="line_thickness", kind="float")
    assert ui_rules_for_row(layer_thickness).minmax == "none"
    # Layer Style も専用 resolver のため、同じく非機能 MIDI control を出さない。
    assert ui_rules_for_row(layer_thickness).cc_key == "none"
    assert ui_rules_for_row(layer_thickness).show_override is True


def test_style_rgb_rows_do_not_expose_tuple_midi_controls() -> None:
    background = _row(op=STYLE_OP, arg="background_color", kind="rgb")
    layer_color = _row(op=LAYER_STYLE_OP, arg="line_color", kind="rgb")

    assert ui_rules_for_row(background).cc_key == "none"
    assert ui_rules_for_row(layer_color).cc_key == "none"
    # CODE/UI の切替は残す。MIDI の非表示と source fallback は別の責務。
    assert ui_rules_for_row(background).show_override is True
    assert ui_rules_for_row(layer_color).show_override is True


def test_ui_rules_reject_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown parameter kind"):
        ui_rules_for_row(_row(op="circle", arg="x", kind="unknown"))
