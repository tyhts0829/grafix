"""
どこで: `src/grafix/primitives/polygon.py`。正多角形プリミティブの実体生成。
何を: 辺数・位相・center/scale から正多角形ポリラインを構築する。
なぜ: プレビューとエクスポートで再利用できる基本図形を提供するため。
"""

from __future__ import annotations

import math

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.operation_authoring import primitive
from grafix.core.realized_geometry import GeomTuple

polygon_meta = {
    "n_sides": ParamMeta(
        kind="int",
        ui_min=3,
        ui_max=128,
        description="正多角形の頂点と辺の数を指定します。",
    ),
    "phase": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=360.0,
        description="+X 軸を基準とする最初の頂点の角度を度単位で指定します。",
    ),
    "sweep": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=360.0,
        description="外周のうち描画する角度を指定し、欠けた区間は弦で閉じます。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="正多角形全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="直径 1 の正多角形全体に適用する等方スケールを指定します。",
    ),
}


@primitive(meta=polygon_meta)
def polygon(
    *,
    n_sides: int = 6,
    phase: float = 0.0,
    sweep: float = 360.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> GeomTuple:
    """正多角形の閉ポリラインを生成する。

    Parameters
    ----------
    n_sides : int, optional
        辺の数。3 以上。
    phase : float, optional
        頂点開始角 [deg]。0° で +X 軸上に頂点を置く。
    sweep : float, optional
        描画する周回角 [deg]。0° 以上 360° 以下。
        360° で全周、0°〜360° で部分周回になる。
        部分周回の場合、終点から始点へ直線で戻して閉じる（欠け部分が弦になる）。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        開始点を終端に重ねた閉じたポリラインとしての正多角形（coords, offsets）。

    Raises
    ------
    ValueError
        ``n_sides`` が 3 未満、または ``sweep`` が 0° から 360° の範囲外の場合。
    """
    if n_sides < 3:
        raise ValueError("polygon の n_sides は 3 以上である必要がある")
    if sweep < 0.0 or sweep > 360.0:
        raise ValueError("polygon の sweep は 0 以上 360 以下である必要がある")
    sides = n_sides

    phase_deg = phase
    sweep_deg = sweep
    cx, cy, cz = center
    s_f = scale

    if sweep_deg >= 360.0:
        angles = np.linspace(
            0.0,
            2.0 * math.pi,
            num=sides,
            endpoint=False,
            dtype=np.float32,
        )
    else:
        step = (2.0 * math.pi) / float(sides)
        sweep_rad = math.radians(sweep_deg)

        n_full = int(math.floor(sweep_rad / step))
        angles64 = step * np.arange(n_full + 1, dtype=np.float64)
        if sweep_rad - angles64[-1] > 1e-9:
            angles64 = np.concatenate(
                [angles64, np.array([sweep_rad], dtype=np.float64)]
            )
        angles = angles64.astype(np.float32, copy=False)

    if phase_deg != 0.0:
        angles = angles + np.deg2rad(np.float32(phase_deg))

    radius = np.float32(0.5)
    x = radius * np.cos(angles, dtype=np.float32)
    y = radius * np.sin(angles, dtype=np.float32)
    z = np.zeros_like(x)

    s32 = np.float32(s_f)
    x = x * s32 + np.float32(cx)
    y = y * s32 + np.float32(cy)
    z = z * s32 + np.float32(cz)

    # 先頭頂点を終端に複製する領域まで一度に確保し、中間concatenateを避ける。
    coords = np.empty((x.shape[0] + 1, 3), dtype=np.float32)
    coords[:-1, 0] = x
    coords[:-1, 1] = y
    coords[:-1, 2] = z
    coords[-1] = coords[0]
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets
