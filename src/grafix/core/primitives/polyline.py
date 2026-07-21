"""任意の点列を受け取る高水準 primitive。"""

from __future__ import annotations

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import ensure_geometry_output

polyline_meta = {
    "closed": ParamMeta(
        kind="bool",
        description="終点が始点と異なる場合に始点を末尾へ追加して線を閉じます。",
    ),
}

_FLOAT32_MAX = float(np.finfo(np.float32).max)


def _endpoint3(point: tuple[float, ...]) -> tuple[float, float, float]:
    """検証済みの端点を比較用 3D float tuple にする。"""

    try:
        return (
            float(point[0]),
            float(point[1]),
            0.0 if len(point) == 2 else float(point[2]),
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("polyline の座標は float64 に変換可能である必要があります") from exc


@primitive(meta=polyline_meta)
def polyline(
    *,
    points: tuple[tuple[float, ...], ...] = ((-0.5, 0.0), (0.5, 0.0)),
    closed: bool = False,
) -> GeomTuple:
    """2D/3D point列から単一polylineを生成する。

    ``points`` はcode-owned引数で、Parameter GUIには表示しない。
    ``closed=True`` では必要な場合だけ先頭点を末尾へ追加する。

    Parameters
    ----------
    points : tuple[tuple[float, ...], ...], optional
        入力順に単一ポリラインを構成する 2 次元または 3 次元点列。
        2 次元点の Z 座標は 0 とし、空列からは空の Geometry を生成する。
    closed : bool, optional
        終点が始点と異なる場合に始点を末尾へ追加して線を閉じる。

    Returns
    -------
    GeomTuple
        単一ポリラインを表す座標配列とオフセット配列。
    """

    if type(points) is not tuple:
        raise TypeError("polyline の points は exact tuple である必要があります")

    count = len(points)
    if count == 0:
        ensure_geometry_output("polyline", vertices=0, lines=0)
        return np.empty((0, 3), dtype=np.float32), np.zeros(1, dtype=np.int32)

    dimension: int | None = None
    mixed_dimensions = False
    for point_index, point in enumerate(points):
        if type(point) is not tuple or len(point) not in {2, 3}:
            raise TypeError(
                f"polyline の points[{point_index}] は長さ 2 または 3 の"
                " exact tuple である必要があります"
            )
        point_dimension = len(point)
        if dimension is None:
            dimension = point_dimension
        elif point_dimension != dimension:
            mixed_dimensions = True
        for component_index, component in enumerate(point):
            component_type = type(component)
            if component_type is float or component_type is int:
                continue
            raise TypeError(
                f"polyline の points[{point_index}][{component_index}] は"
                " exact int または float である必要があります"
            )

    append_start = closed and _endpoint3(points[-1]) != _endpoint3(points[0])
    vertex_count = count + int(append_start)
    ensure_geometry_output("polyline", vertices=vertex_count, lines=1)

    values: tuple[tuple[float, ...], ...]
    if mixed_dimensions:
        values = tuple(
            point if len(point) == 3 else (point[0], point[1], 0.0)
            for point in points
        )
    else:
        values = points
    try:
        coords64 = np.asarray(values, dtype=np.float64)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("polyline の座標は float64 に変換可能である必要があります") from exc
    if not np.isfinite(coords64).all():
        raise ValueError("polyline の座標は有限値である必要があります")
    if np.max(np.abs(coords64)) > _FLOAT32_MAX:
        raise ValueError("polyline の座標は float32 の範囲内である必要があります")

    source_dimension = 3 if mixed_dimensions else dimension
    assert source_dimension is not None
    coords = np.empty((vertex_count, 3), dtype=np.float32)
    coords[:count, :source_dimension] = coords64
    if source_dimension == 2:
        coords[:count, 2] = 0.0
    if append_start:
        coords[-1] = coords[0]
    return coords, np.array([0, coords.shape[0]], dtype=np.int32)


__all__ = ["polyline", "polyline_meta"]
