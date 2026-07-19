"""cubic Bezier curve の基本 primitive。"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

from ._shape_utils import point3, segment_count

bezier_meta = {
    "segments": ParamMeta(
        kind="int",
        ui_min=1,
        ui_max=512,
        description="4 制御点で定まる曲線を近似する直線セグメントの数を指定します。",
    ),
}


@primitive(meta=bezier_meta)
def bezier(
    *,
    p0: Sequence[float] = (-0.5, 0.0, 0.0),
    p1: Sequence[float] = (-0.2, 0.5, 0.0),
    p2: Sequence[float] = (0.2, -0.5, 0.0),
    p3: Sequence[float] = (0.5, 0.0, 0.0),
    segments: int = 64,
) -> GeomTuple:
    """4制御点からcubic Bezier curveを生成する。

    ``p0``〜``p3`` はcode-owned引数で、Parameter GUIには表示しない。

    Parameters
    ----------
    p0 : Sequence[float], optional
        曲線の始点となる 2 次元または 3 次元座標。
    p1 : Sequence[float], optional
        始点側の接線方向と曲がり方を定める第 1 制御点。
    p2 : Sequence[float], optional
        終点側の接線方向と曲がり方を定める第 2 制御点。
    p3 : Sequence[float], optional
        曲線の終点となる 2 次元または 3 次元座標。
    segments : int, optional
        4 制御点で定まる曲線を近似する直線セグメントの数。

    Returns
    -------
    GeomTuple
        1 本の曲線を表す座標配列とオフセット配列。
    """

    count = segment_count(segments, op="bezier", minimum=1)
    controls = np.asarray(
        [
            point3(p0, op="bezier", name="p0"),
            point3(p1, op="bezier", name="p1"),
            point3(p2, op="bezier", name="p2"),
            point3(p3, op="bezier", name="p3"),
        ],
        dtype=np.float64,
    )
    t = np.linspace(0.0, 1.0, count + 1, dtype=np.float64)[:, None]
    one_minus_t = 1.0 - t
    coords = (
        one_minus_t**3 * controls[0]
        + 3.0 * one_minus_t**2 * t * controls[1]
        + 3.0 * one_minus_t * t**2 * controls[2]
        + t**3 * controls[3]
    ).astype(np.float32)
    return coords, np.array([0, coords.shape[0]], dtype=np.int32)


__all__ = ["bezier", "bezier_meta"]
