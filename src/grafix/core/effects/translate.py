"""座標に XYZ オフセットを加算して平行移動する effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

translate_meta = {
    "delta": ParamMeta(kind="vec3", ui_min=-100.0, ui_max=100.0),
}


@effect(meta=translate_meta)
def translate(
    g: GeomTuple,
    *,
    delta: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """平行移動（XYZ のオフセット加算）。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        平行移動対象の実体ジオメトリ（coords, offsets）。
    delta : tuple[float, float, float], default (0.0,0.0,0.0)
        平行移動量（dx, dy, dz）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        平行移動後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    dx, dy, dz = float(delta[0]), float(delta[1]), float(delta[2])
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        return coords, offsets

    delta_vec = np.array([dx, dy, dz], dtype=np.float32)
    coords_out = coords + delta_vec
    return coords_out, offsets
