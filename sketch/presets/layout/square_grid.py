"""
どこで: `sketch/presets/layout/square_grid.py`。
何を: 正方形グリッドを描く preset。
なぜ: もっとも基本的なグリッドを独立モジュールとして合成可能にするため。
"""

from __future__ import annotations

from collections.abc import Mapping

from grafix import preset

from .common import (
    CANVAS_SIZE,
    META_COMMON,
    _center_lines,
    _finish,
    _has_margin,
    _inset_rect,
    _rect_from_canvas,
    _rect_outline,
    _square_grid,
)

meta: dict[str, Mapping[str, object]] = {
    **META_COMMON,
    "cell_size": {"kind": "float", "ui_min": 1.0, "ui_max": 50.0},
}


@preset(meta=meta)
def layout_square_grid(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    cell_size: float = 10.0,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """正方形グリッドを描く。"""
    axes = str(axes)
    _ox, _oy, oz = offset
    z = float(oz)

    canvas_rect = _rect_from_canvas(canvas_w=canvas_w, canvas_h=canvas_h, offset=offset)
    target_rect = _inset_rect(
        canvas_rect,
        left=margin_l,
        right=margin_r,
        top=margin_t,
        bottom=margin_b,
    )

    out: list[object] = []
    if _has_margin(margin_l=margin_l, margin_r=margin_r, margin_t=margin_t, margin_b=margin_b):
        out.extend(_rect_outline(target_rect, axes=axes, z=z))
    out.extend(_square_grid(target_rect, cell_size=cell_size, axes=axes, z=z))
    if bool(show_center):
        out.extend(_center_lines(target_rect, axes=axes, z=z))

    return _finish(geoms=out, offset=offset)
