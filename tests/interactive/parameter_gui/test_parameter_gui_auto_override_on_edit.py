from __future__ import annotations

from grafix.core.parameters import ParameterRow
from grafix.interactive.parameter_gui.table import _should_auto_enable_override


def _row(
    *,
    kind: str,
    ui_value: object,
    choices: tuple[str, ...] | None = None,
) -> ParameterRow:
    return ParameterRow(
        label="0:arg",
        op="op",
        site_id="s1",
        arg="arg",
        kind=str(kind),
        ui_value=ui_value,
        ui_min=None,
        ui_max=None,
        choices=choices,
        cc_key=None,
        override=False,
        ordinal=0,
    )


def test_auto_enable_override_on_value_edit_enables_for_float() -> None:
    row = _row(kind="float", ui_value=0.0)
    assert (
        _should_auto_enable_override(row, before_ui_value=row.ui_value, after_ui_value=0.25)
        is True
    )


def test_auto_enable_override_on_value_edit_is_disabled_for_bool() -> None:
    row = _row(kind="bool", ui_value=False)
    assert (
        _should_auto_enable_override(row, before_ui_value=row.ui_value, after_ui_value=True)
        is False
    )


def test_auto_enable_override_choice_coerce_to_first_does_not_enable() -> None:
    row = _row(kind="choice", ui_value="old", choices=("a", "b"))
    assert (
        _should_auto_enable_override(row, before_ui_value=row.ui_value, after_ui_value="a")
        is False
    )


def test_auto_enable_override_choice_change_to_other_enables() -> None:
    row = _row(kind="choice", ui_value="old", choices=("a", "b"))
    assert (
        _should_auto_enable_override(row, before_ui_value=row.ui_value, after_ui_value="b")
        is True
    )


def test_auto_enable_override_choice_valid_value_change_enables() -> None:
    row = _row(kind="choice", ui_value="a", choices=("a", "b"))
    assert (
        _should_auto_enable_override(row, before_ui_value=row.ui_value, after_ui_value="b")
        is True
    )

