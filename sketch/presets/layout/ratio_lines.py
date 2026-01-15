"""
どこで: `sketch/presets/layout/ratio_lines.py`。
何を: 任意 ratio の分割線（levels 段）を描く preset。
なぜ: 比率ガイドを独立モジュールとして合成可能にするため。
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
    _ratio_lines,
    _rect_from_canvas,
    _rect_outline,
)

meta = {
    **META_COMMON,
    "ratio": {"kind": "float", "ui_min": 1.01, "ui_max": 10.0},
    "levels": {"kind": "int", "ui_min": 1, "ui_max": 8},
    "min_spacing": {"kind": "float", "ui_min": 0.0, "ui_max": 20.0},
    "max_lines": {"kind": "int", "ui_min": 0, "ui_max": 20000},
}


@preset(meta=meta)
def layout_ratio_lines(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    ratio: float = 1.61803398875,
    levels: int = 2,
    min_spacing: float = 2.0,
    max_lines: int = 3000,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """比率分割線を描く。"""
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
        _ratio_lines(
            rect=target_rect,
            ratio=ratio,
            levels=int(levels),
            axes=axes,
            z=z,
            min_spacing=min_spacing,
            max_lines=int(max_lines),
        )
    )
    if bool(show_center):
        out.extend(_center_lines(target_rect, axes=axes, z=z))

    return _finish(geoms=out, offset=offset)
