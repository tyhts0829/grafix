"""
どこで: `sketch/presets/layout/bounds.py`。
何を: canvas / margin(safe) / trim の外周線を描く preset。
なぜ: グリッド類と “外枠” を分離して合成しやすくするため。
"""

from __future__ import annotations

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
)

meta = {
    **META_COMMON,
    "border": {"kind": "bool"},
    "show_margin": {"kind": "bool"},
    "trim": {"kind": "float", "ui_min": 0.0, "ui_max": 100.0},
    "show_trim": {"kind": "bool"},
}


@preset(meta=meta)
def layout_bounds(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    border: bool = True,
    show_margin: bool = False,
    trim: float = 0.0,
    show_trim: bool = False,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """外枠（canvas / safe / trim）を描く。"""
    axes = str(axes)
    _ox, _oy, oz = offset
    z = float(oz)

    canvas_rect = _rect_from_canvas(canvas_w=canvas_w, canvas_h=canvas_h, offset=offset)
    safe_rect = _inset_rect(
        canvas_rect,
        left=margin_l,
        right=margin_r,
        top=margin_t,
        bottom=margin_b,
    )
    trim_rect = _inset_rect(canvas_rect, left=trim, right=trim, top=trim, bottom=trim)

    out: list[object] = []
    if bool(border):
        out.extend(_rect_outline(canvas_rect, axes=axes, z=z))
    if bool(show_margin) or _has_margin(margin_l=margin_l, margin_r=margin_r, margin_t=margin_t, margin_b=margin_b):
        out.extend(_rect_outline(safe_rect, axes=axes, z=z))
    if bool(show_trim):
        out.extend(_rect_outline(trim_rect, axes=axes, z=z))
    if bool(show_center):
        out.extend(_center_lines(safe_rect, axes=axes, z=z))

    return _finish(geoms=out, offset=offset)
