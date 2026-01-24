"""
どこで: `sketch/presets/layout/metallic_rectangles.py`。
何を: 貴金属比の矩形分割（正方形タイル境界）を描く preset。
なぜ: 比率矩形分割を独立モジュールとして合成可能にするため。
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
    _metallic_rectangles,
    _rect_from_canvas,
    _rect_outline,
)

meta: dict[str, Mapping[str, object]] = {
    **META_COMMON,
    "metallic_n": {"kind": "int", "ui_min": 1, "ui_max": 12},
    "levels": {"kind": "int", "ui_min": 1, "ui_max": 8},
    "corner": {"kind": "choice", "choices": ["tl", "tr", "br", "bl"]},
    "clockwise": {"kind": "bool"},
}


@preset(meta=meta)
def layout_metallic_rectangles(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    metallic_n: int = 1,
    levels: int = 2,
    corner: str = "tl",
    clockwise: bool = True,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """貴金属比の矩形分割を描く。"""
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
    out.extend(
        _metallic_rectangles(
            rect=target_rect,
            metallic_n=int(metallic_n),
            levels=int(levels),
            axes=axes,
            corner=str(corner),
            clockwise=bool(clockwise),
            z=z,
        )
    )
    if bool(show_center):
        out.extend(_center_lines(target_rect, axes=axes, z=z))

    return _finish(geoms=out, offset=offset)
