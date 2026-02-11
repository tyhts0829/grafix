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

line_meta = {
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=300.0),
    "anchor": ParamMeta(kind="choice", choices=("center", "left", "right")),
    "length": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "angle": ParamMeta(kind="float", ui_min=0.0, ui_max=360.0),
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
        線分の長さ。
    angle : float, optional
        回転角 [deg]。0° で +X 方向。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        2 点の線分としての実体ジオメトリ（coords, offsets）。
    """
    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "line の center は長さ 3 のシーケンスである必要がある"
        ) from exc

    length_f = float(length)
    angle_deg = float(angle)
    cx_f, cy_f, cz_f = float(cx), float(cy), float(cz)

    anchor_s = str(anchor)
    if anchor_s not in {"center", "left", "right"}:
        anchor_s = "center"

    theta = math.radians(angle_deg)
    dx = length_f * math.cos(theta)
    dy = length_f * math.sin(theta)

    if anchor_s == "center":
        x0, y0 = cx_f - 0.5 * dx, cy_f - 0.5 * dy
        x1, y1 = cx_f + 0.5 * dx, cy_f + 0.5 * dy
    elif anchor_s == "left":
        x0, y0 = cx_f, cy_f
        x1, y1 = cx_f + dx, cy_f + dy
    else:  # anchor_s == "right"
        x0, y0 = cx_f - dx, cy_f - dy
        x1, y1 = cx_f, cy_f

    coords = np.array(
        [
            [x0, y0, cz_f],
            [x1, y1, cz_f],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets
