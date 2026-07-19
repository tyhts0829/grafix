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


@njit(cache=True, fastmath=True, inline="always")  # type: ignore[misc]
def _smooth_reflect_line_into_nb(
    points: np.ndarray,
    start: int,
    stop: int,
    kernel: np.ndarray,
    out: np.ndarray,
) -> None:
    source = points[start:stop]
    target = out[start:stop]
    n = int(source.shape[0])
    if n <= 1:
        if n == 1:
            target[0, 0] = source[0, 0]
            target[0, 1] = source[0, 1]
            target[0, 2] = source[0, 2]
        return

    r = int(kernel.shape[0] // 2)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-r, r + 1):
            j = _reflect_index(i + k, n)
            w = float(kernel[k + r])
            ax += w * float(source[j, 0])
            ay += w * float(source[j, 1])
            az += w * float(source[j, 2])
        target[i, 0] = np.float32(ax)
        target[i, 1] = np.float32(ay)
        target[i, 2] = np.float32(az)


@njit(cache=True, fastmath=True, inline="always")  # type: ignore[misc]
def _smooth_wrap_line_into_nb(
    points: np.ndarray,
    start: int,
    stop: int,
    kernel: np.ndarray,
    out: np.ndarray,
) -> None:
    source = points[start : stop - 1]
    target = out[start:stop]
    n = int(source.shape[0])
    if n <= 0:
        return

    r = int(kernel.shape[0] // 2)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-r, r + 1):
            j = (i + k) % n
            w = float(kernel[k + r])
            ax += w * float(source[j, 0])
            ay += w * float(source[j, 1])
            az += w * float(source[j, 2])
        target[i, 0] = np.float32(ax)
        target[i, 1] = np.float32(ay)
        target[i, 2] = np.float32(az)

    # 閉曲線は末尾を畳み込み対象から外し、平滑化後の先頭を複写する。
    target[n, 0] = target[0, 0]
    target[n, 1] = target[0, 1]
    target[n, 2] = target[0, 2]


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _smooth_packed_into_nb(
    points: np.ndarray,
    offsets: np.ndarray,
    closed_flags: np.ndarray,
    kernel: np.ndarray,
    out: np.ndarray,
) -> None:
    """packed line 全体を一度の JIT 呼び出しで平滑化して ``out`` へ書く。"""

    for line_index in range(int(offsets.shape[0]) - 1):
        start = int(offsets[line_index])
        stop = int(offsets[line_index + 1])
        if closed_flags[line_index]:
            _smooth_wrap_line_into_nb(points, start, stop, kernel, out)
        else:
            _smooth_reflect_line_into_nb(points, start, stop, kernel, out)


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
    closed_flags = np.fromiter(
        (line.closed for line in plan.lines),
        dtype=np.bool_,
        count=n_lines,
    )
    coords_out = np.empty_like(resampled)
    _smooth_packed_into_nb(resampled, offsets_out, closed_flags, kernel, coords_out)
    return coords_out, offsets_out


__all__ = [
    "CLOSED_DISTANCE_EPS",
    "lowpass",
    "lowpass_meta",
]
