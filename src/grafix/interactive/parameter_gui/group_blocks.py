# どこで: `src/grafix/interactive/parameter_gui/group_blocks.py`。
# 何を: `ParameterRow` 列を “連続する group” ごとのブロックへ分割する純粋関数を提供する。
# なぜ: `collapsing_header` をテーブル外に出して全幅表示するために、描画単位（ブロック）を先に組み立てたいから。

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from grafix.core.parameters.view import ParameterRow

from .grouping import group_info_for_row


@dataclass(frozen=True, slots=True)
class GroupBlockLayoutItem:
    """静的 layout 内の 1 行を model row index で参照する。"""

    row_index: int
    visible_label: str


@dataclass(frozen=True, slots=True)
class GroupBlockLayout:
    """row の動的値を持たない、不変な group 描画構造。"""

    group_id: tuple[str, object]
    header_id: str
    header: str | None
    items: tuple[GroupBlockLayoutItem, ...]


@dataclass(frozen=True, slots=True)
class GroupBlockItem:
    """グループ内の 1 行ぶんの描画情報。"""

    row: ParameterRow
    visible_label: str


@dataclass(frozen=True, slots=True)
class GroupBlock:
    """連続する group（Style/Primitive/Effect chain）を 1 ブロックとして表す。"""

    group_id: tuple[str, object]
    header_id: str
    header: str | None
    items: list[GroupBlockItem]


def group_layout_from_rows(
    rows: Sequence[ParameterRow],
    *,
    primitive_header_by_group: Mapping[tuple[str, int], str] | None = None,
    layer_style_name_by_site_id: Mapping[str, str] | None = None,
    effect_chain_header_by_id: Mapping[str, str] | None = None,
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]] | None = None,
    effect_step_ordinal_by_site: Mapping[tuple[str, str], int] | None = None,
) -> tuple[GroupBlockLayout, ...]:
    """rows から revision 内で不変な group layout を構築する。"""

    out: list[GroupBlockLayout] = []

    current_group_id: tuple[str, object] | None = None
    current_header_id: str | None = None
    current_header: str | None = None
    current_items: list[GroupBlockLayoutItem] = []

    def _flush() -> None:
        nonlocal current_group_id, current_header_id, current_header, current_items
        if current_group_id is None or current_header_id is None:
            return
        out.append(
            GroupBlockLayout(
                group_id=current_group_id,
                header_id=current_header_id,
                header=current_header,
                items=tuple(current_items),
            )
        )
        current_group_id = None
        current_header_id = None
        current_header = None
        current_items = []

    for row_index, row in enumerate(rows):
        info = group_info_for_row(
            row,
            primitive_header_by_group=primitive_header_by_group,
            layer_style_name_by_site_id=layer_style_name_by_site_id,
            effect_chain_header_by_id=effect_chain_header_by_id,
            step_info_by_site=step_info_by_site,
            effect_step_ordinal_by_site=effect_step_ordinal_by_site,
        )

        if info.group_id != current_group_id:
            _flush()
            current_group_id = info.group_id
            current_header_id = info.header_id
            current_header = info.header
            current_items = []

        current_items.append(
            GroupBlockLayoutItem(
                row_index=int(row_index),
                visible_label=str(info.visible_label),
            )
        )

    _flush()
    return tuple(out)


def group_blocks_from_layout(
    rows: Sequence[ParameterRow],
    layout: Sequence[GroupBlockLayout],
) -> list[GroupBlock]:
    """静的 layout と現在値の rows を従来の block 表現へ合成する。"""

    return [
        GroupBlock(
            group_id=block.group_id,
            header_id=block.header_id,
            header=block.header,
            items=[
                GroupBlockItem(
                    row=rows[item.row_index],
                    visible_label=item.visible_label,
                )
                for item in block.items
            ],
        )
        for block in layout
    ]


def visible_group_layout(
    layout: Sequence[GroupBlockLayout],
    visible_mask: Sequence[bool],
) -> tuple[GroupBlockLayout, ...]:
    """visible rows だけを参照する model-index layout を返す。"""

    if all(visible_mask):
        return tuple(layout)

    out: list[GroupBlockLayout] = []
    for block in layout:
        items = tuple(
            item
            for item in block.items
            if visible_mask[item.row_index]
        )
        if not items:
            continue
        visible_block = (
            block
            if len(items) == len(block.items)
            else GroupBlockLayout(
                group_id=block.group_id,
                header_id=block.header_id,
                header=block.header,
                items=items,
            )
        )

        # filter で中間 block が消えた場合は、filtered rows を改めて grouping
        # した従来挙動と同様に、隣接した同一 group を 1 つへ戻す。
        if out and out[-1].group_id == visible_block.group_id:
            previous = out[-1]
            out[-1] = GroupBlockLayout(
                group_id=previous.group_id,
                header_id=previous.header_id,
                header=previous.header,
                items=previous.items + visible_block.items,
            )
            continue
        out.append(visible_block)

    return tuple(out)


def group_blocks_from_rows(
    rows: list[ParameterRow],
    *,
    primitive_header_by_group: Mapping[tuple[str, int], str] | None = None,
    layer_style_name_by_site_id: Mapping[str, str] | None = None,
    effect_chain_header_by_id: Mapping[str, str] | None = None,
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]] | None = None,
    effect_step_ordinal_by_site: Mapping[tuple[str, str], int] | None = None,
) -> list[GroupBlock]:
    """rows を “連続する group_id” ごとのブロックへ分割して返す。"""

    layout = group_layout_from_rows(
        rows,
        primitive_header_by_group=primitive_header_by_group,
        layer_style_name_by_site_id=layer_style_name_by_site_id,
        effect_chain_header_by_id=effect_chain_header_by_id,
        step_info_by_site=step_info_by_site,
        effect_step_ordinal_by_site=effect_step_ordinal_by_site,
    )
    out = group_blocks_from_layout(rows, layout)
    return out


__all__ = [
    "GroupBlock",
    "GroupBlockItem",
    "GroupBlockLayout",
    "GroupBlockLayoutItem",
    "group_blocks_from_layout",
    "group_blocks_from_rows",
    "group_layout_from_rows",
    "visible_group_layout",
]
