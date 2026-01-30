"""
どこで: `sketch/presets/layout/grid_system.py`。
何を: columns / modular / baseline をまとめた “grid system” preset。
なぜ: タイポグラフィ向けの基本グリッドを 1 モジュールとして合成可能にするため。
"""

from __future__ import annotations

from collections.abc import Mapping

from grafix import preset

from .common import (
    CANVAS_SIZE,
    META_COMMON,
    _baseline,
    _center_lines,
    _finish,
    _inset_rect,
    _modular,
    _rect_from_canvas,
)

meta: dict[str, Mapping[str, object]] = {
    **META_COMMON,
    "cols": {"kind": "int", "ui_min": 1, "ui_max": 24},
    "rows": {"kind": "int", "ui_min": 1, "ui_max": 24},
    "gutter_x": {"kind": "float", "ui_min": 0.0, "ui_max": 50.0},
    "gutter_y": {"kind": "float", "ui_min": 0.0, "ui_max": 50.0},
    "show_column_centers": {"kind": "bool"},
    "show_baseline": {"kind": "bool"},
    "baseline_step": {"kind": "float", "ui_min": 0.1, "ui_max": 50.0},
    "baseline_offset": {"kind": "float", "ui_min": -50.0, "ui_max": 50.0},
}

LAYOUT_GRID_SYSTEM_UI_VISIBLE = {
    "baseline_step": lambda v: bool(v.get("show_baseline")),
    "baseline_offset": lambda v: bool(v.get("show_baseline")),
}

@preset(meta=meta, ui_visible=LAYOUT_GRID_SYSTEM_UI_VISIBLE)
def layout_grid_system(
    *,
    canvas_w: float = float(CANVAS_SIZE[0]),
    canvas_h: float = float(CANVAS_SIZE[1]),
    axes: str = "both",
    margin_l: float = 0.0,
    margin_r: float = 0.0,
    margin_t: float = 0.0,
    margin_b: float = 0.0,
    show_center: bool = False,
    cols: int = 12,
    rows: int = 12,
    gutter_x: float = 4.0,
    gutter_y: float = 4.0,
    show_column_centers: bool = False,
    show_baseline: bool = False,
    baseline_step: float = 6.0,
    baseline_offset: float = 0.0,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """grid system（columns / modular / baseline）を描く。"""
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
    out.extend(
        _modular(
            target_rect,
            cols=int(cols),
            rows=int(rows),
            gutter_x=gutter_x,
            gutter_y=gutter_y,
            axes=axes,
            show_column_centers=bool(show_column_centers),
            z=z,
        )
    )
    if bool(show_baseline):
        out.extend(
            _baseline(
                target_rect,
                baseline_step=baseline_step,
                baseline_offset=baseline_offset,
                axes=axes,
                z=z,
            )
        )
    if bool(show_center):
        out.extend(_center_lines(target_rect, axes=axes, z=z))

    return _finish(geoms=out, offset=offset)
