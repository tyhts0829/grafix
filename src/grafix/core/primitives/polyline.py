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

    Parameters
    ----------
    points : Sequence[Sequence[float]], optional
        入力順に単一ポリラインを構成する 2 次元または 3 次元点列。
        2 次元点の Z 座標は 0 とし、空列からは空の Geometry を生成する。
    closed : bool, optional
        終点が始点と異なる場合に始点を末尾へ追加して線を閉じる。

    Returns
    -------
    GeomTuple
        単一ポリラインを表す座標配列とオフセット配列。
    """

    if (
        type(points) is np.ndarray
        and points.ndim == 2
        and points.shape[1] in (2, 3)
        and points.dtype.kind in "biuf"
        and not (points.dtype.kind == "f" and points.dtype.itemsize > 8)
    ):
        n_points = int(points.shape[0])
        if n_points == 0:
            ensure_geometry_output("polyline", vertices=0, lines=0)
            return np.empty((0, 3), dtype=np.float32), np.zeros(1, dtype=np.int32)

        # point3() は全scalarをPython float（binary64）へ変換してから
        # float32配列化する。この二段変換はwide integerの丸めだけでなく、
        # signaling NaNのquiet化にも影響するため省略しない。
        with np.errstate(under="ignore", invalid="ignore"):
            points64 = points.astype(np.float64, copy=True)

        # Python float列からfloat32へ変換する従来経路は、有限overflowを
        # 要素ごとに通知する。一括astypeはwarningを集約するため、稀な
        # float32範囲外入力だけsnapshotをscalar列へ戻して通知数を保つ。
        with np.errstate(invalid="ignore"):
            has_finite_overflow = bool(
                np.any(
                    np.isfinite(points64)
                    & (np.abs(points64) > np.finfo(np.float32).max)
                )
            )
        if has_finite_overflow:
            if points.shape[1] == 2:
                normalized = [
                    (float(point[0]), float(point[1]), 0.0)
                    for point in points64
                ]
            else:
                normalized = [
                    tuple(float(component) for component in point)
                    for point in points64
                ]
            if bool(closed) and normalized[-1] != normalized[0]:
                normalized.append(normalized[0])
            ensure_geometry_output(
                "polyline",
                vertices=len(normalized),
                lines=1,
            )
            coords = np.asarray(normalized, dtype=np.float32)
            return coords, np.array([0, coords.shape[0]], dtype=np.int32)

        # 従来は全点の正規化を終えてからclosedを評価する。closed.__bool__が
        # 入力配列を変更しても、このsnapshotから作る出力へ混入させない。
        # closure判定自体もfloat32化前のPython tuple比較を維持する。
        first = tuple(float(component) for component in points64[0])
        last = tuple(float(component) for component in points64[-1])
        append_first = bool(closed) and last != first
        n_output = n_points + int(append_first)
        ensure_geometry_output("polyline", vertices=n_output, lines=1)

        coords64 = np.empty((n_output, 3), dtype=np.float64)
        coords64[:n_points, :2] = points64[:, :2]
        if points.shape[1] == 2:
            coords64[:n_points, 2] = 0.0
        else:
            coords64[:n_points, 2] = points64[:, 2]
        if append_first:
            coords64[-1] = coords64[0]
        # Python scalar列からの従来castはunderflow/invalidを通知せず、
        # overflowだけはNumPyのseterr設定に従う。
        with np.errstate(under="ignore", invalid="ignore"):
            coords = coords64.astype(np.float32)
        return coords, np.array([0, n_output], dtype=np.int32)

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
