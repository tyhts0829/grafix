"""任意の点列を受け取る高水準 primitive。"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

from ._shape_utils import point3

polyline_meta = {
    "closed": ParamMeta(
        kind="bool",
        description="終点が始点と異なる場合に始点を末尾へ追加して線を閉じます。",
    ),
}


@primitive(meta=polyline_meta)
def polyline(
    *,
    points: Sequence[Sequence[float]] = ((-0.5, 0.0), (0.5, 0.0)),
    closed: bool = False,
) -> GeomTuple:
    """2D/3D point列から単一polylineを生成する。

    ``points`` はcode-owned引数で、Parameter GUIには表示しない。
    ``closed=True`` では必要な場合だけ先頭点を末尾へ追加する。
    """

    normalized = [point3(point, op="polyline", name="points") for point in points]
    if not normalized:
        ensure_geometry_output("polyline", vertices=0, lines=0)
        return np.empty((0, 3), dtype=np.float32), np.zeros(1, dtype=np.int32)
    if bool(closed) and normalized[-1] != normalized[0]:
        normalized.append(normalized[0])
    ensure_geometry_output("polyline", vertices=len(normalized), lines=1)
    coords = np.asarray(normalized, dtype=np.float32)
    return coords, np.array([0, coords.shape[0]], dtype=np.int32)


__all__ = ["polyline", "polyline_meta"]
