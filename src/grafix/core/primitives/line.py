"""
どこで: `src/grafix/core/primitives/line.py`。線分プリミティブの実体生成。
何を: center/anchor/length/angle から XY 平面上の線分を構築する。
なぜ: 最小の一次元形状として、他の effect/合成の基礎にするため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

_ANCHOR_CHOICES = ("center", "left", "right")

line_meta = {
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="選択した基準点を配置する XYZ 座標を指定します。",
    ),
    "anchor": ParamMeta(
        kind="choice",
        choices=_ANCHOR_CHOICES,
        description="指定座標を線分の中心・始点・終点のどこに合わせるか選択します。",
    ),
    "length": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="線分の始点から終点までの長さを指定します。",
    ),
    "angle": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=360.0,
        description="+X 軸を基準とする線分の向きを度単位で指定します。",
    ),
}


@primitive(meta=line_meta)
def line(
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    anchor: str = "center",
    length: float = 1.0,
    angle: float = 0.0,
) -> GeomTuple:
    """正規化済み引数から線分を生成する。

    Parameters
    ----------
    center : tuple[float, float, float], optional
        `anchor` で指定した基準点の座標 (cx, cy, cz)。
    anchor : {"center","left","right"}, default "center"
        `center` の基準点。
        `"center"` は中心、`"left"` は左端（angle 方向の逆側）、`"right"` は右端（angle 方向）。
    length : float, optional
        0 以上の線分の長さ。
    angle : float, optional
        回転角 [deg]。0° で +X 方向。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        2 点の線分としての実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `length` が負の場合。
    """
    if length < 0.0:
        raise ValueError("line の length は 0 以上である必要がある")

    anchor_s = anchor
    cx, cy, cz = center

    length_f = length
    angle_deg = angle

    theta = math.radians(angle_deg)
    dx = length_f * math.cos(theta)
    dy = length_f * math.sin(theta)

    if anchor_s == "center":
        x0, y0 = cx - 0.5 * dx, cy - 0.5 * dy
        x1, y1 = cx + 0.5 * dx, cy + 0.5 * dy
    elif anchor_s == "left":
        x0, y0 = cx, cy
        x1, y1 = cx + dx, cy + dy
    else:  # anchor_s == "right"
        x0, y0 = cx - dx, cy - dy
        x1, y1 = cx, cy

    coords = np.array(
        [
            [x0, y0, cz],
            [x1, y1, cz],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets
