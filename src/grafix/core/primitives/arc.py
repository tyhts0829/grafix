"""円弧の基本 primitive。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

from ._shape_utils import segment_count, xy_polyline

arc_meta = {
    "radius": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "start": ParamMeta(kind="float", ui_min=-360.0, ui_max=360.0),
    "sweep": ParamMeta(kind="float", ui_min=-360.0, ui_max=360.0),
    "segments": ParamMeta(kind="int", ui_min=1, ui_max=512),
    "center": ParamMeta(kind="vec3", ui_min=-300.0, ui_max=300.0),
}


@primitive(meta=arc_meta)
def arc(
    *,
    radius: float = 0.5,
    start: float = 0.0,
    sweep: float = 180.0,
    segments: int = 48,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """開始角とsigned sweepから開いた円弧を生成する。"""

    radius_f = float(radius)
    if radius_f < 0.0:
        raise ValueError("arc の radius は0以上である必要がある")
    count = segment_count(segments, op="arc", minimum=1)
    angles = np.linspace(
        math.radians(float(start)),
        math.radians(float(start) + float(sweep)),
        count + 1,
        dtype=np.float64,
    )
    return xy_polyline(
        radius_f * np.cos(angles),
        radius_f * np.sin(angles),
        center=center,
        op="arc",
    )


__all__ = ["arc", "arc_meta"]
