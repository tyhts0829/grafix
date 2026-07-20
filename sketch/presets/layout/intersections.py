"""
どこで: `sketch/presets/layout/intersections.py`。
何を: 中心・三分割・黄金分割ガイドの交点を十字マーカーで描く preset。
なぜ: 構図上の配置候補点を、ガイド線とは独立して合成可能にするため。
"""

from __future__ import annotations

from collections.abc import Mapping

from grafix import preset

from .common import (
    CANVAS_SIZE,
    META_COMMON,
    _GOLDEN_F,
    _GOLDEN_T,
    _axes_flags,
    _cross_mark,
    _finish,
    _inset_rect,
    _rect_from_canvas,
)

meta: dict[str, Mapping[str, object]] = {
    **META_COMMON,
    "show_thirds": {
        "kind": "bool",
        "description": "三分割線の交点をマーカー対象に含める。",
    },
    "show_golden": {
        "kind": "bool",
        "description": "黄金比分割線の交点をマーカー対象に含める。",
    },
    "mark_size": {
        "kind": "float",
        "ui_min": 0.0,
        "ui_max": 20.0,
        "description": "各交点に描く十字マーカーの幅と高さを指定する。",
    },
}


@preset(meta=meta)
def layout_intersections(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    show_thirds: bool = False,
    show_golden: bool = False,
    mark_size: float = 2.0,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """指定した構図ガイドの交点へ十字マーカーを描く。"""
    show_v, show_h = _axes_flags(str(axes))
    _ox, _oy, oz = offset
    z = float(oz)

    canvas_rect = _rect_from_canvas(canvas_w=canvas_w, canvas_h=canvas_h, offset=offset)
    x0, y0, x1, y1 = _inset_rect(
        canvas_rect,
        left=margin_l,
        right=margin_r,
        top=margin_t,
        bottom=margin_b,
    )
    w = float(x1 - x0)
    h = float(y1 - y0)

    xs: list[float] = []
    ys: list[float] = []
    if bool(show_center):
        if show_v:
            xs.append(float(x0) + 0.5 * w)
        if show_h:
            ys.append(float(y0) + 0.5 * h)
    if bool(show_thirds):
        if show_v:
            xs.extend((float(x0) + w / 3.0, float(x0) + 2.0 * w / 3.0))
        if show_h:
            ys.extend((float(y0) + h / 3.0, float(y0) + 2.0 * h / 3.0))
    if bool(show_golden):
        if show_v:
            xs.extend(
                (
                    float(x0) + _GOLDEN_T * w,
                    float(x0) + _GOLDEN_F * w,
                )
            )
        if show_h:
            ys.extend(
                (
                    float(y0) + _GOLDEN_T * h,
                    float(y0) + _GOLDEN_F * h,
                )
            )

    out: list[object] = []
    for x in sorted(set(xs)):
        for y in sorted(set(ys)):
            out.extend(_cross_mark(x=x, y=y, size=mark_size, z=z))
    return _finish(geoms=out, offset=offset)
