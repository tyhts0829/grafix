from grafix.interactive.parameter_gui.group_blocks import (
    group_blocks_from_layout,
    group_blocks_from_rows,
    group_layout_from_rows,
    visible_group_layout,
)
from grafix.interactive.parameter_gui.table import _effect_step_heading_by_step
from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.view import ParameterRow


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


def test_group_blocks_from_rows_merges_contiguous_same_group():
    rows = [
        _row(op="polygon", site_id="p:1", ordinal=1, arg="n_sides"),
        _row(op="polygon", site_id="p:1", ordinal=1, arg="r"),
    ]
    blocks = group_blocks_from_rows(
        rows,
        primitive_header_by_group={("polygon", 1): "P"},
    )
    assert len(blocks) == 1

    block = blocks[0]
    assert block.group_id == ("primitive", ("polygon", 1))
    assert block.header_id == "primitive:polygon#1"
    assert block.header == "P"
    assert [it.visible_label for it in block.items] == [
        "N sides",
        "R",
    ]


def test_group_blocks_from_rows_splits_when_group_changes():
    rows = [
        _row(op="polygon", site_id="p:1", ordinal=1, arg="n_sides"),
        _row(op="circle", site_id="c:1", ordinal=1, arg="r"),
    ]
    blocks = group_blocks_from_rows(
        rows,
        primitive_header_by_group={("polygon", 1): "P", ("circle", 1): "C"},
    )
    assert [b.header for b in blocks] == ["P", "C"]
    assert [b.header_id for b in blocks] == ["primitive:polygon#1", "primitive:circle#1"]


def test_group_blocks_from_rows_preserves_effect_visible_label():
    rows = [
        _row(op="scale", site_id="e:1", ordinal=99, arg="auto_center"),
        _row(op="rotate", site_id="e:2", ordinal=99, arg="deg"),
    ]
    blocks = group_blocks_from_rows(
        rows,
        step_info_by_site={("scale", "e:1"): ("chain:1", 0), ("rotate", "e:2"): ("chain:1", 1)},
        effect_chain_header_by_id={"chain:1": "xf"},
        effect_step_ordinal_by_site={("scale", "e:1"): 1, ("rotate", "e:2"): 1},
    )
    assert len(blocks) == 1
    assert blocks[0].group_id == ("effect_chain", "chain:1")
    assert blocks[0].header == "xf"
    assert [it.visible_label for it in blocks[0].items] == [
        "Auto center",
        "Deg",
    ]


def test_effect_step_headings_number_only_duplicate_operations():
    rows = [
        _row(op="scale", site_id="e:1", ordinal=99, arg="x"),
        _row(op="rotate", site_id="e:2", ordinal=99, arg="deg"),
        _row(op="scale", site_id="e:3", ordinal=99, arg="y"),
    ]
    blocks = group_blocks_from_rows(
        rows,
        step_info_by_site={
            ("scale", "e:1"): ("chain:1", 0),
            ("rotate", "e:2"): ("chain:1", 1),
            ("scale", "e:3"): ("chain:1", 2),
        },
        effect_chain_header_by_id={"chain:1": "xf"},
    )

    assert _effect_step_heading_by_step(blocks[0]) == {
        ("scale", "e:1"): "Scale 1",
        ("rotate", "e:2"): "Rotate",
        ("scale", "e:3"): "Scale 2",
    }


def test_effect_step_headings_keep_different_ops_with_same_site_id() -> None:
    rows = [
        _row(op="scale", site_id="shared", ordinal=99, arg="x"),
        _row(op="rotate", site_id="shared", ordinal=99, arg="deg"),
    ]
    blocks = group_blocks_from_rows(
        rows,
        step_info_by_site={
            ("scale", "shared"): ("chain:1", 0),
            ("rotate", "shared"): ("chain:1", 1),
        },
        effect_chain_header_by_id={"chain:1": "xf"},
    )

    assert _effect_step_heading_by_step(blocks[0]) == {
        ("scale", "shared"): "Scale",
        ("rotate", "shared"): "Rotate",
    }


def test_group_blocks_from_rows_style_is_single_block():
    rows = [
        _row(op=STYLE_OP, site_id="__global__", ordinal=1, arg="background_color"),
        _row(op=STYLE_OP, site_id="__global__", ordinal=1, arg="global_thickness"),
    ]
    blocks = group_blocks_from_rows(rows)
    assert len(blocks) == 1
    assert blocks[0].header == "Style"


def test_visible_group_layout_matches_regrouping_filtered_rows():
    rows = [
        _row(op="polygon", site_id="p:1", ordinal=1, arg="n_sides"),
        _row(op="polygon", site_id="p:1", ordinal=1, arg="r"),
        _row(op="circle", site_id="c:1", ordinal=1, arg="r"),
    ]
    headers = {("polygon", 1): "P", ("circle", 1): "C"}
    layout = group_layout_from_rows(
        rows,
        primitive_header_by_group=headers,
    )
    mask = (False, True, True)
    view_rows = [row for row, visible in zip(rows, mask, strict=True) if visible]

    from_layout = group_blocks_from_layout(
        rows,
        visible_group_layout(layout, mask),
    )
    regrouped = group_blocks_from_rows(
        view_rows,
        primitive_header_by_group=headers,
    )

    assert [
        (
            block.group_id,
            block.header_id,
            block.header,
            [(item.row, item.visible_label) for item in block.items],
        )
        for block in from_layout
    ] == [
        (
            block.group_id,
            block.header_id,
            block.header,
            [(item.row, item.visible_label) for item in block.items],
        )
        for block in regrouped
    ]


def test_visible_group_layout_reuses_full_layout_when_all_rows_are_visible():
    rows = [
        _row(op="polygon", site_id="p:1", ordinal=1, arg="n_sides"),
        _row(op="polygon", site_id="p:1", ordinal=1, arg="r"),
    ]
    layout = group_layout_from_rows(rows)

    assert visible_group_layout(layout, (True, True)) is layout


def test_visible_group_layout_reuses_unchanged_blocks_with_model_indices():
    rows = [
        _row(op="polygon", site_id="p:1", ordinal=1, arg="r"),
        _row(op="circle", site_id="c:1", ordinal=1, arg="r"),
        _row(op="line", site_id="l:1", ordinal=1, arg="length"),
    ]
    layout = group_layout_from_rows(rows)

    filtered = visible_group_layout(layout, (True, False, True))

    assert filtered == (layout[0], layout[2])
    assert filtered[0] is layout[0]
    assert filtered[1] is layout[2]
    assert filtered[1].items[0].row_index == 2
