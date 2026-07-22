"""楕円の基本 primitive。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.operation_authoring import primitive
from grafix.core.realized_geometry import GeomTuple

from ._shape_utils import segment_count, xy_polyline

ellipse_meta = {
    "radius_x": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="回転前の X 軸方向における楕円の半径を指定します。",
    ),
    "radius_y": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="回転前の Y 軸方向における楕円の半径を指定します。",
    ),
    "angle": ParamMeta(
        kind="float",
        ui_min=-180.0,
        ui_max=180.0,
        description="楕円を中心まわりに回転させる角度を度単位で指定します。",
    ),
    "segments": ParamMeta(
        kind="int",
        ui_min=3,
        ui_max=512,
        description="楕円周を近似する直線セグメントの数を指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=-300.0,
        ui_max=300.0,
        description="楕円の中心となる XYZ 座標を指定します。",
    ),
}


@primitive(meta=ellipse_meta)
def ellipse(
    *,
    radius_x: float = 0.5,
    radius_y: float = 0.25,
    angle: float = 0.0,
    segments: int = 96,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """楕円を閉じたpolylineとして生成する。"""

    rx = radius_x
    ry = radius_y
    if rx < 0.0 or ry < 0.0:
        raise ValueError("ellipse の radius_x/radius_y は0以上である必要がある")
    count = segment_count(segments, op="ellipse", minimum=3)
    angles = np.linspace(0.0, 2.0 * math.pi, count + 1, dtype=np.float64)
    return xy_polyline(
        rx * np.cos(angles),
        ry * np.sin(angles),
        center=center,
        angle=angle,
        op="ellipse",
    )


__all__ = ["ellipse", "ellipse_meta"]
