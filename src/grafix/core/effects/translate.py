"""座標に XYZ オフセットを加算して平行移動する effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

translate_meta = {
    "delta": ParamMeta(
        kind="vec3",
        ui_min=-100.0,
        ui_max=100.0,
        description="入力全体へ加える各軸の平行移動量。",
    ),
}

_SCALAR_ADD_MIN_VERTICES = 512
_SCALAR_ADD_SAFE_ABS_MAX = np.float32(np.finfo(np.float32).max / 4.0)


def _can_use_scalar_add(coords: np.ndarray, delta_vec: np.ndarray) -> bool:
    """軸別 ufunc でも浮動小数点通知が増えない通常範囲かを返す。"""

    if (
        type(coords) is not np.ndarray
        or coords.dtype != np.float32
        or coords.ndim != 2
        or coords.shape[1] != 3
        or not coords.flags.c_contiguous
        or np.geterr()["under"] != "ignore"
    ):
        return False

    coords_abs_max = np.max(np.abs(coords))
    delta_abs_max = np.max(np.abs(delta_vec))
    return bool(
        np.isfinite(coords_abs_max)
        and np.isfinite(delta_abs_max)
        and coords_abs_max <= _SCALAR_ADD_SAFE_ABS_MAX
        and delta_abs_max <= _SCALAR_ADD_SAFE_ABS_MAX
    )


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
    # 小規模配列では 1 回の broadcast 加算の固定費の方が低い。
    if coords.shape[0] < _SCALAR_ADD_MIN_VERTICES:
        return coords + delta_vec, offsets

    if not _can_use_scalar_add(coords, delta_vec):
        # direct call で渡される非 canonical 入力は、従来の dtype promotion と
        # ndarray subclass、出力 layout、浮動小数点通知の規則を維持する。
        return coords + delta_vec, offsets

    coords_out = coords.copy()
    dx32, dy32, dz32 = delta_vec
    # 0 の軸も加算する。省略すると入力の -0.0 がそのまま残り、従来の
    # broadcast 加算が生成する +0.0 と bitwise に異なる。
    coords_out[:, 0] += dx32
    coords_out[:, 1] += dy32
    coords_out[:, 2] += dz32
    return coords_out, offsets
