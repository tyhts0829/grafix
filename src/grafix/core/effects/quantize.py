"""座標をグリッドへ量子化（スナップ）する effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

quantize_meta = {
    "step": ParamMeta(kind="vec3", ui_min=0.0, ui_max=10.0),
}


def _round_half_away_from_zero(values: np.ndarray) -> np.ndarray:
    """0.5 境界を絶対値方向へ丸める（half away from zero）。"""
    return np.sign(values) * np.floor(np.abs(values) + 0.5)


@effect(meta=quantize_meta)
def quantize(
    g: GeomTuple,
    *,
    step: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> GeomTuple:
    """頂点座標を各軸のステップ幅で量子化する（XYZ）。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    step : tuple[float, float, float], default (1.0, 1.0, 1.0)
        各軸の格子間隔 (sx, sy, sz)。いずれかが 0 以下なら no-op。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        量子化後の実体ジオメトリ（coords, offsets）。頂点数と offsets は維持。

    Notes
    -----
    丸め規則は half away from zero:
    - +0.5 は +1 側
    - -0.5 は -1 側
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    sx, sy, sz = float(step[0]), float(step[1]), float(step[2])
    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
        return coords, offsets

    step_vec = np.array([sx, sy, sz], dtype=np.float64)
    coords64 = coords.astype(np.float64, copy=False)
    q = coords64 / step_vec
    q_rounded = _round_half_away_from_zero(q)
    snapped64 = q_rounded * step_vec
    coords_out = snapped64.astype(np.float32, copy=False)
    return coords_out, offsets
