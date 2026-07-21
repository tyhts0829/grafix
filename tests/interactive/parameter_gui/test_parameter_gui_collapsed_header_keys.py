from dataclasses import replace

from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.collapsed_header import (
    STYLE_COLLAPSED_HEADER_KEY,
    effect_chain_collapsed_header_key,
    preset_collapsed_header_key,
    primitive_collapsed_header_key,
)
from grafix.core.parameters.view import ParameterRow
from grafix.interactive.parameter_gui.group_blocks import group_layout_from_rows
from grafix.interactive.parameter_gui.grouping import GroupType
from grafix.interactive.parameter_gui.table import parameter_group_collapse_keys


def _row(*, op: str, site_id: str, ordinal: int, arg: str) -> ParameterRow:
    return ParameterRow(
        label="",
        op=op,
        site_id=site_id,
        arg=arg,
        kind="float",
        ui_value=0.0,
        ui_min=None,
        ui_max=None,
        choices=None,
        cc_key=None,
        override=True,
        ordinal=int(ordinal),
    )


def test_collapse_key_for_block_style():
    rows = [
        _row(
            op=STYLE_OP,
            site_id="__global__",
            ordinal=1,
            arg="background_color",
        )
    ]
    layout = group_layout_from_rows(rows)
    assert parameter_group_collapse_keys(
        rows,
        group_layout=layout,
    ) == (STYLE_COLLAPSED_HEADER_KEY,)


def test_collapse_key_for_block_primitive_uses_site_id():
    rows = [_row(op="circle", site_id="c:1", ordinal=1, arg="r")]
    layout = group_layout_from_rows(
        rows,
        primitive_header_by_group={("circle", 1): "Circle"},
    )
    assert parameter_group_collapse_keys(
        rows,
        group_layout=layout,
    ) == (primitive_collapsed_header_key(("circle", "c:1")),)


def test_collapse_key_for_block_preset_uses_site_id():
    rows = [_row(op="preset.logo", site_id="p:1", ordinal=1, arg="size")]
    layout = group_layout_from_rows(
        rows,
        primitive_header_by_group={("preset.logo", 1): "Logo"},
    )
    preset_layout = tuple(
        replace(
            block,
            group_id=(GroupType.PRESET, block.group_id[1]),
        )
        for block in layout
    )
    assert parameter_group_collapse_keys(
        rows,
        group_layout=preset_layout,
    ) == (preset_collapsed_header_key(("preset.logo", "p:1")),)


def test_collapse_key_for_block_effect_chain_uses_chain_id():
    rows = [
        _row(op="scale", site_id="e:1", ordinal=99, arg="auto_center")
    ]
    layout = group_layout_from_rows(
        rows,
        step_info_by_site={("scale", "e:1"): ("chain:1", 0)},
        effect_chain_header_by_id={"chain:1": "Effect"},
    )
    assert parameter_group_collapse_keys(
        rows,
        group_layout=layout,
    ) == (effect_chain_collapsed_header_key("chain:1"),)
