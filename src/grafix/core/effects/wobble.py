"""ポリラインの各頂点をサイン波でゆらし、手書き風のたわみを加える effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

wobble_meta = {
    "amplitude": ParamMeta(kind="vec3", ui_min=0.0, ui_max=20.0),
    "frequency": ParamMeta(kind="vec3", ui_min=0.0, ui_max=0.2),
    "phase": ParamMeta(kind="float", ui_min=0.0, ui_max=360.0),
}


@effect(meta=wobble_meta)
def wobble(
    g: GeomTuple,
    *,
    amplitude: tuple[float, float, float] = (2.0, 2.0, 2.0),
    frequency: tuple[float, float, float] = (0.1, 0.1, 0.1),
    phase: float = 0.0,
) -> GeomTuple:
    """各頂点へサイン波由来の変位を加える。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        変形対象の実体ジオメトリ（coords, offsets）。
    amplitude : tuple[float, float, float], default (2.0, 2.0, 2.0)
        変位量 [mm] 相当（各軸別）。
    frequency : tuple[float, float, float], default (0.1, 0.1, 0.1)
        空間周波数（各軸別）。
    phase : float, default 0.0
        位相 [deg]。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        変形後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    ax = float(amplitude[0])
    ay = float(amplitude[1])
    az = float(amplitude[2])
    if ax == 0.0 and ay == 0.0 and az == 0.0:
        return coords, offsets

    fx = float(frequency[0])
    fy = float(frequency[1])
    fz = float(frequency[2])
    phase_rad = float(np.deg2rad(float(phase)))

    v = coords.astype(np.float64, copy=False)
    out = v.copy()

    x = v[:, 0]
    y = v[:, 1]
    z = v[:, 2]
    out[:, 0] = x + ax * np.sin(2.0 * np.pi * fx * x + phase_rad)
    out[:, 1] = y + ay * np.sin(2.0 * np.pi * fy * y + phase_rad)
    out[:, 2] = z + az * np.sin(2.0 * np.pi * fz * z + phase_rad)

    coords_out = out.astype(np.float32, copy=False)
    return coords_out, offsets


__all__ = ["wobble", "wobble_meta"]
