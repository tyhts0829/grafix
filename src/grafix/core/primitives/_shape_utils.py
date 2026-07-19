"""基本2D primitive が共有する小さな座標生成ヘルパ。"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output


def point3(value: Sequence[float], *, op: str, name: str) -> tuple[float, float, float]:
    """2D/3D point を3成分floatへ正規化する。"""

    try:
        values = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{op} の {name} は2または3成分の座標である必要がある") from exc
    if len(values) == 2:
        return values[0], values[1], 0.0
    if len(values) == 3:
        return values
    raise ValueError(f"{op} の {name} は2または3成分の座標である必要がある")


def segment_count(value: int | float, *, op: str, minimum: int) -> int:
    """sample segment数を明示検証し、resource budgetへ接続する。"""

    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{op} の segments は整数である必要がある") from exc
    if count < minimum:
        raise ValueError(f"{op} の segments は {minimum} 以上である必要がある")
    ensure_geometry_output(op, vertices=count + 1, lines=1)
    return count


def xy_polyline(
    x: np.ndarray,
    y: np.ndarray,
    *,
    center: Sequence[float],
    angle: float = 0.0,
    op: str,
) -> GeomTuple:
    """local XY samples を回転・平行移動して単一polylineへする。"""

    cx, cy, cz = point3(center, op=op, name="center")
    x64 = np.asarray(x, dtype=np.float64)
    y64 = np.asarray(y, dtype=np.float64)
    if x64.shape != y64.shape or x64.ndim != 1:
        raise ValueError(f"{op} の内部 sample shape が不正です")

    theta = math.radians(float(angle))
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
