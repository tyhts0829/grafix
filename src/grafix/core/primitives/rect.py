"""長方形の基本 primitive。"""

from __future__ import annotations

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

from ._shape_utils import xy_polyline

rect_meta = {
    "width": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="回転前の X 軸方向における長方形の幅を指定します。",
    ),
    "height": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="回転前の Y 軸方向における長方形の高さを指定します。",
    ),
    "angle": ParamMeta(
        kind="float",
        ui_min=-180.0,
        ui_max=180.0,
        description="長方形を中心まわりに回転させる角度を度単位で指定します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=-300.0,
        ui_max=300.0,
        description="長方形の中心となる XYZ 座標を指定します。",
    ),
}


@primitive(meta=rect_meta)
def rect(
    *,
    width: float = 1.0,
    height: float = 1.0,
    angle: float = 0.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """中心・幅・高さから閉じた長方形を生成する。"""

    width_f = float(width)
    height_f = float(height)
    if width_f < 0.0 or height_f < 0.0:
        raise ValueError("rect の width/height は0以上である必要がある")
    ensure_geometry_output("rect", vertices=5, lines=1)
    half_w = 0.5 * width_f
    half_h = 0.5 * height_f
    x = np.array([-half_w, half_w, half_w, -half_w, -half_w], dtype=np.float64)
    y = np.array([-half_h, -half_h, half_h, half_h, -half_h], dtype=np.float64)
    return xy_polyline(x, y, center=center, angle=angle, op="rect")


__all__ = ["rect", "rect_meta"]
