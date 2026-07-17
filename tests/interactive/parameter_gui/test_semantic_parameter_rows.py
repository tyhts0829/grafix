from __future__ import annotations

from grafix.core.parameters.view import ParameterRow
from grafix.interactive.parameter_gui.grouping import group_info_for_row
from grafix.interactive.parameter_gui.parameter_filter import (
    ParameterFilterRecord,
    matches_parameter_search,
)


def _semantic_row() -> ParameterRow:
    return ParameterRow(
        label="1:width",
        op="line",
        site_id="site-1",
        arg="width",
        kind="float",
        ui_value=1.0,
        ui_min=0.1,
        ui_max=10.0,
        choices=None,
        cc_key=None,
        override=False,
        ordinal=1,
        display_name="Stroke width",
        description="Controls the rendered stroke weight",
        unit="mm",
        category="Appearance",
    )


def test_display_name_is_used_as_visible_parameter_label() -> None:
    info = group_info_for_row(_semantic_row())

    assert info.visible_label == "Stroke width"


def test_semantic_text_is_searchable() -> None:
    row = _semantic_row()
    record = ParameterFilterRecord(
        row=row,
        label="Stroke width",
        source="code",
        active=True,
    )

    assert matches_parameter_search(record, "rendered weight") is True
    assert matches_parameter_search(record, "appearance mm") is True
