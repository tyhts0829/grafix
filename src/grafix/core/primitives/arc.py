"""円弧の基本 primitive。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

from ._shape_utils import segment_count, xy_polyline

arc_meta = {
    "radius": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="円弧の中心から輪郭までの半径を指定します。",
    ),
    "start": ParamMeta(
        kind="float",
        ui_min=-360.0,
        ui_max=360.0,
        description="+X 軸を基準とする円弧の開始角を度単位で指定します。",
    ),
    "sweep": ParamMeta(
        kind="float",
        ui_min=-360.0,
        ui_max=360.0,
        description="開始角から終点までの符号付き回転量を度単位で指定します。",
    ),
    "segments": ParamMeta(
        kind="int",
        ui_min=1,
        ui_max=512,
        description="円弧を近似する直線セグメントの数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=-300.0,
        ui_max=300.0,
        description="円弧の中心となる XYZ 座標を指定します。",
    ),
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

    radius_f = radius
    if radius_f < 0.0:
        raise ValueError("arc の radius は0以上である必要がある")
    count = segment_count(segments, op="arc", minimum=1)
    angles = np.linspace(
        math.radians(start),
        math.radians(start + sweep),
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
