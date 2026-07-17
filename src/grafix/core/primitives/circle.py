"""円の基本 primitive。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

from ._shape_utils import segment_count, xy_polyline

circle_meta = {
    "radius": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "segments": ParamMeta(kind="int", ui_min=3, ui_max=512),
    "center": ParamMeta(kind="vec3", ui_min=-300.0, ui_max=300.0),
}


@primitive(meta=circle_meta)
def circle(
    *,
    radius: float = 0.5,
    segments: int = 96,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """円を閉じたpolylineとして生成する。

    Parameters
    ----------
    radius : float, optional
        半径。0以上。
    segments : int, optional
        周上の線分数。3以上。
    center : tuple[float, float, float], optional
        円の中心。
    """

    radius_f = float(radius)
    if radius_f < 0.0:
        raise ValueError("circle の radius は0以上である必要がある")
    count = segment_count(segments, op="circle", minimum=3)
    angles = np.linspace(0.0, 2.0 * math.pi, count + 1, dtype=np.float64)
    return xy_polyline(
        radius_f * np.cos(angles),
        radius_f * np.sin(angles),
        center=center,
        op="circle",
    )


__all__ = ["circle", "circle_meta"]
