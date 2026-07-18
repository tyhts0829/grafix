"""ポリラインを弧長で再サンプルし、ガウス畳み込みで高周波成分を落とす effect。"""

from __future__ import annotations

import numpy as np
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple
from .util import (
    RESAMPLE_CLOSED_DISTANCE_EPS,
    ResamplePlan,
    build_gaussian_kernel,
    resample_polylines,
)

# `closed=auto` の近接判定しきい値（距離）。単位は入力座標系に従う（通常は mm）。
CLOSED_DISTANCE_EPS = RESAMPLE_CLOSED_DISTANCE_EPS
MAX_TOTAL_VERTICES = 10_000_000
MAX_KERNEL_RADIUS = 2048

lowpass_meta = {
    "step": ParamMeta(
        kind="float",
        ui_min=0.1,
        ui_max=20.0,
        description="平滑化の前に線を再サンプルする弧長間隔。",
    ),
    "sigma": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=20.0,
        description="線の細かな変化をならすガウス平滑の半径。",
    ),
    "closed": ParamMeta(
        kind="choice",
        choices=("auto", "open", "closed"),
        description="端点の平滑境界条件を開曲線、閉曲線、端点距離による自動判定から選ぶ。",
    ),
}


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _reflect_index(i: int, n: int) -> int:
    j = int(i)
    nn = int(n)
    if nn <= 1:
        return 0
    while j < 0 or j >= nn:
        if j < 0:
            j = -j
        elif j >= nn:
            j = 2 * nn - 2 - j
    return int(j)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _smooth_reflect_nb(points: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 1:
        return points

    r = int(kernel.shape[0] // 2)
    out = np.empty_like(points)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-r, r + 1):
            j = _reflect_index(i + k, n)
            w = float(kernel[k + r])
            ax += w * float(points[j, 0])
            ay += w * float(points[j, 1])
            az += w * float(points[j, 2])
        out[i, 0] = np.float32(ax)
        out[i, 1] = np.float32(ay)
        out[i, 2] = np.float32(az)
    return out


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _smooth_wrap_nb(points: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 0:
        return points

    r = int(kernel.shape[0] // 2)
    out = np.empty_like(points)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-r, r + 1):
            j = (i + k) % n
            w = float(kernel[k + r])
            ax += w * float(points[j, 0])
            ay += w * float(points[j, 1])
            az += w * float(points[j, 2])
        out[i, 0] = np.float32(ax)
        out[i, 1] = np.float32(ay)
        out[i, 2] = np.float32(az)
    return out


@effect(meta=lowpass_meta)
def lowpass(
    g: GeomTuple,
    *,
    step: float = 0.5,
    sigma: float = 1.0,
    closed: str = "auto",
) -> GeomTuple:
    """ポリライン列を低域通過（ローパス）して滑らかにする。

    各ポリラインを弧長で等間隔に再サンプルし、ガウス畳み込みで x/y/z を平滑化する。
    コーナーは丸まり、細かいギザギザ（高周波成分）が抑えられる。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        変形対象の実体ジオメトリ（coords, offsets）。
    step : float, default 0.5
        再サンプル間隔（弧長）。小さいほど頂点が増え、効果が細かく出る。
    sigma : float, default 1.0
        ガウス平滑半径。大きいほど強く丸まる（`sigma/step` が実効的な強さ）。
    closed : str, default "auto"
        境界条件。`"open"` は反射、`"closed"` は周期。
        `"auto"` は端点距離が `CLOSED_DISTANCE_EPS` 以下なら `"closed"` 扱い。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        平滑化後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    step_size = float(step)
    sigma_size = float(sigma)
    if not np.isfinite(step_size) or not np.isfinite(sigma_size):
        return coords, offsets
    if step_size <= 0.0 or sigma_size <= 0.0:
        return coords, offsets

    closed_mode = str(closed)
    if closed_mode not in {"auto", "open", "closed"}:
        closed_mode = "auto"

    sigma_in_samples = sigma_size / step_size
    if not np.isfinite(sigma_in_samples) or sigma_in_samples <= 0.0:
        return coords, offsets

    n_lines = int(offsets.size) - 1
    if n_lines <= 0:
        return coords, offsets

    plan = ResamplePlan.from_geometry(
        coords,
        offsets,
        step=step_size,
        closed=closed_mode,
        max_vertices=MAX_TOTAL_VERTICES,
        closed_distance=CLOSED_DISTANCE_EPS,
    )
    if not plan.fits:
        return coords, offsets

    kernel = build_gaussian_kernel(
        sigma_in_samples=float(sigma_in_samples), max_radius=MAX_KERNEL_RADIUS
    )
    resampled, offsets_out = resample_polylines(coords, plan)
    coords_out = np.empty_like(resampled)
    for line in plan.lines:
        source = resampled[line.output_start : line.output_stop]
        target = coords_out[line.output_start : line.output_stop]
        if line.closed:
            smoothed = _smooth_wrap_nb(source[:-1], kernel)
            target[:-1] = smoothed
            target[-1] = smoothed[0]
        else:
            target[:] = _smooth_reflect_nb(source, kernel)
    return coords_out, offsets_out


__all__ = [
    "CLOSED_DISTANCE_EPS",
    "lowpass",
    "lowpass_meta",
]
