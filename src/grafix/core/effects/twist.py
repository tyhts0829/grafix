"""位置に応じて指定軸回りにねじる effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

twist_meta = {
    "auto_center": ParamMeta(kind="bool"),
    "pivot": ParamMeta(kind="vec3", ui_min=-100.0, ui_max=100.0),
    "angle": ParamMeta(kind="float", ui_min=0.0, ui_max=360.0),
    "axis_dir": ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0),
}

twist_ui_visible = {
    "pivot": lambda v: not bool(v.get("auto_center", True)),
}

@effect(meta=twist_meta, ui_visible=twist_ui_visible)
def twist(
    g: GeomTuple,
    *,
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    angle: float = 60.0,
    axis_dir: tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> GeomTuple:
    """位置に応じて軸回りにねじる（中心付近は 0）。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    auto_center : bool, default True
        True なら平均座標を回転中心に使用。False なら `pivot` を使用。
    pivot : tuple[float, float, float], default (0.0,0.0,0.0)
        ねじり軸（`axis_dir` に平行な直線）の通過点（`auto_center=False` のとき有効）。
    angle : float, default 60.0
        最大ねじれ角 [deg]。
    axis_dir : tuple[float, float, float], default (0.0, 1.0, 0.0)
        ねじり軸方向（ベクトル）。長さは正規化される。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ねじり適用後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    max_rad = float(np.deg2rad(float(angle)))
    if max_rad == 0.0:
        return coords, offsets

    axis_dir64 = np.array(
        [float(axis_dir[0]), float(axis_dir[1]), float(axis_dir[2])],
        dtype=np.float64,
    )
    axis_norm = float(np.linalg.norm(axis_dir64))
    if axis_norm <= 1e-9:
        raise ValueError(f"axis_dir は非ゼロのベクトルである必要がある: {axis_dir!r}")
    k = axis_dir64 / axis_norm

    if auto_center:
        center = coords.astype(np.float64, copy=False).mean(axis=0)
    else:
        center = np.array(
            [float(pivot[0]), float(pivot[1]), float(pivot[2])],
            dtype=np.float64,
        )

    coords64 = coords.astype(np.float64, copy=False)
    s = coords64 @ k
    lo = float(s.min())
    hi = float(s.max())
    rng = hi - lo
    if rng <= 1e-9:
        return coords, offsets

    # 各頂点の正規化位置 t = 0..1
    t = (s - lo) / rng
    # -max..+max に分布させる（中心 0）
    twist_rad = (t - 0.5) * 2.0 * max_rad

    c = np.cos(twist_rad)
    sin_rad = np.sin(twist_rad)

    v = coords64 - center
    cross = np.cross(v, k)
    dot = v @ k
    v_rot = (
        v * c[:, None]
        + cross * sin_rad[:, None]
        + (dot * (1.0 - c))[:, None] * k[None, :]
    )
    out = v_rot + center

    coords_out = out.astype(np.float32, copy=False)
    return coords_out, offsets


__all__ = ["twist"]
