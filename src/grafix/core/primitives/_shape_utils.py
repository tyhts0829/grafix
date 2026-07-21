"""基本2D primitive が共有する小さな座標生成ヘルパ。"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output


def point3(
    value: tuple[float, ...],
    *,
    op: str,
    name: str,
) -> tuple[float, float, float]:
    """2D/3D point を3成分floatへ正規化する。"""

    if type(value) is not tuple or len(value) not in {2, 3}:
        raise TypeError(f"{op} の {name} は2または3成分の tuple である必要がある")
    for component in value:
        component_type = type(component)
        if component_type is not int and component_type is not float:
            raise TypeError(
                f"{op} の {name} の各成分は exact int または float である必要がある"
            )
    values = tuple(float(component) for component in value)
    if any(not math.isfinite(component) for component in values):
        raise ValueError(f"{op} の {name} は有限な実数座標である必要がある")
    if len(values) == 2:
        return values[0], values[1], 0.0
    return values[0], values[1], values[2]


def segment_count(value: int, *, op: str, minimum: int) -> int:
    """sample segment数を明示検証し、resource budgetへ接続する。"""

    if value < minimum:
        raise ValueError(f"{op} の segments は {minimum} 以上である必要がある")
    ensure_geometry_output(op, vertices=value + 1, lines=1)
    return value


def xy_polyline(
    x: np.ndarray,
    y: np.ndarray,
    *,
    center: tuple[float, float, float],
    angle: float = 0.0,
    op: str,
) -> GeomTuple:
    """local XY samples を回転・平行移動して単一polylineへする。"""

    cx, cy, cz = center
    x64 = np.asarray(x, dtype=np.float64)
    y64 = np.asarray(y, dtype=np.float64)
    if x64.shape != y64.shape or x64.ndim != 1:
        raise ValueError(f"{op} の内部 sample shape が不正です")

    theta = math.radians(angle)
    if theta:
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)
        x64, y64 = (
            x64 * cos_theta - y64 * sin_theta,
            x64 * sin_theta + y64 * cos_theta,
        )
    coords64 = np.empty((x64.shape[0], 3), dtype=np.float64)
    coords64[:, 0] = x64 + cx
    coords64[:, 1] = y64 + cy
    coords64[:, 2] = cz
    coords = coords64.astype(np.float32)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


__all__ = ["point3", "segment_count", "xy_polyline"]
