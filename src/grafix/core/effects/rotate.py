"""座標に XYZ 回転を適用する effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

rotate_meta = {
    "auto_center": ParamMeta(
        kind="bool",
        description="入力頂点の平均座標を回転中心として使用する。",
    ),
    "pivot": ParamMeta(
        kind="vec3",
        ui_min=-100.0,
        ui_max=100.0,
        description="自動中心が無効な場合に使用する回転中心。",
    ),
    "rotation": ParamMeta(
        kind="vec3",
        ui_min=-180.0,
        ui_max=180.0,
        description="各軸まわりに適用する回転角を度単位で指定する。",
    ),
}

rotate_ui_visible = {
    "pivot": lambda v: not bool(v.get("auto_center", True)),
}

_F_ORDER_MIN_VERTICES = 1024


@effect(meta=rotate_meta, ui_visible=rotate_ui_visible)
def rotate(
    g: GeomTuple,
    *,
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """回転（auto_center / pivot 対応、degree 入力）。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        回転対象の実体ジオメトリ（coords, offsets）。
    auto_center : bool, default True
        True なら頂点の平均座標を中心に使用。False なら `pivot` を使用。
    pivot : tuple[float, float, float], default (0.0,0.0,0.0)
        回転の中心（`auto_center=False` のとき有効）。
    rotation : tuple[float, float, float], default (0.0, 0.0, 0.0)
        各軸の回転角 [deg]（rx, ry, rz）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        回転後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    rx_deg, ry_deg, rz_deg = float(rotation[0]), float(rotation[1]), float(rotation[2])
    if rx_deg == 0.0 and ry_deg == 0.0 and rz_deg == 0.0:
        return coords, offsets

    rx, ry, rz = np.deg2rad([rx_deg, ry_deg, rz_deg]).astype(np.float64)

    large_canonical_coords = bool(
        type(coords) is np.ndarray
        and coords.dtype == np.float32
        and coords.ndim == 2
        and coords.shape[1] == 3
        and coords.flags.c_contiguous
        and coords.shape[0] >= _F_ORDER_MIN_VERTICES
    )
    coords_abs_max = (
        float(np.max(np.abs(coords))) if large_canonical_coords else float("nan")
    )
    optimize_buffers = bool(large_canonical_coords and np.isfinite(coords_abs_max))
    if auto_center:
        # ndarray subclass は従来の ufunc/matmul dispatch を維持する。
        center = coords.astype(np.float64, copy=False).mean(axis=0)
    else:
        center = np.array(
            [float(pivot[0]), float(pivot[1]), float(pivot[2])],
            dtype=np.float64,
        )

    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)

    rx_mat = np.array(
        [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]],
        dtype=np.float64,
    )
    ry_mat = np.array(
        [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]],
        dtype=np.float64,
    )
    rz_mat = np.array(
        [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    # 適用順序: x → y → z（row-vector のため転置で適用）
    rot = rz_mat @ ry_mat @ rx_mat

    if optimize_buffers:
        float32_limit = float(np.finfo(np.float32).max)
        center_abs_max = float(np.max(np.abs(center)))
        rot_abs_max = float(np.max(np.abs(rot)))
        if (
            np.isfinite(rot_abs_max)
            and np.isfinite(center_abs_max)
            and coords_abs_max <= float32_limit / 16.0
            and center_abs_max <= float32_limit / 16.0
            and rot_abs_max <= 2.0
            and np.geterr()["under"] == "ignore"
        ):
            # K=3 の積順は従来の ``shifted @ rot.T`` のまま、BLAS が効率良く
            # 列を読める Fortran-order の working buffer だけを使う。
            shifted = coords.astype(np.float64, order="F", copy=True)
            shifted -= center
            rotated = shifted @ rot.T
            # 安全に float32 へ丸められる通常範囲では、加算と cast も 1 pass にする。
            coords_out = np.empty(coords.shape, dtype=np.float32)
            np.add(rotated, center, out=coords_out)
            return coords_out, offsets

    shifted = coords.astype(np.float64, copy=False) - center
    rotated = shifted @ rot.T + center
    coords_out = rotated.astype(np.float32, copy=False)
    return coords_out, offsets
