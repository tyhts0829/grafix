"""ポリラインを弧長で再サンプルし、unsharp mask で高周波成分を強調する effect。"""

from __future__ import annotations

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

# `closed=auto` の近接判定しきい値（距離）。単位は入力座標系に従う（通常は mm）。
CLOSED_DISTANCE_EPS = 0.01
CLOSED_DISTANCE_EPS_SQ = float(CLOSED_DISTANCE_EPS * CLOSED_DISTANCE_EPS)

MAX_TOTAL_VERTICES = 10_000_000
MAX_KERNEL_RADIUS = 2048

highpass_meta = {
    "step": ParamMeta(kind="float", ui_min=0.0, ui_max=20.0),
    "sigma": ParamMeta(kind="float", ui_min=0.0, ui_max=20.0),
    "gain": ParamMeta(kind="float", ui_min=0.0, ui_max=5.0),
    "closed": ParamMeta(kind="choice", choices=("auto", "open", "closed")),
}


def _empty_geometry() -> GeomTuple:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


def _build_gaussian_kernel(sigma_in_samples: float) -> np.ndarray:
    r = int(np.ceil(3.0 * float(sigma_in_samples)))
    if r < 1:
        r = 1
    if r > MAX_KERNEL_RADIUS:
        r = MAX_KERNEL_RADIUS

    x = np.arange(-r, r + 1, dtype=np.float64)
    w = np.exp(-0.5 * (x / float(sigma_in_samples)) ** 2)
    wsum = float(np.sum(w))
    if wsum > 0.0:
        w = w / wsum
    return w.astype(np.float64, copy=False)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _total_length_open_nb(vertices: np.ndarray) -> float:
    total = 0.0
    for i in range(vertices.shape[0] - 1):
        dx = float(vertices[i + 1, 0] - vertices[i, 0])
        dy = float(vertices[i + 1, 1] - vertices[i, 1])
        dz = float(vertices[i + 1, 2] - vertices[i, 2])
        total += float(np.sqrt(dx * dx + dy * dy + dz * dz))
    return float(total)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _total_length_closed_nb(vertices: np.ndarray) -> float:
    n = int(vertices.shape[0])
    if n < 2:
        return 0.0

    total = 0.0
    for i in range(n - 1):
        dx = float(vertices[i + 1, 0] - vertices[i, 0])
        dy = float(vertices[i + 1, 1] - vertices[i, 1])
        dz = float(vertices[i + 1, 2] - vertices[i, 2])
        total += float(np.sqrt(dx * dx + dy * dy + dz * dz))

    dx = float(vertices[0, 0] - vertices[n - 1, 0])
    dy = float(vertices[0, 1] - vertices[n - 1, 1])
    dz = float(vertices[0, 2] - vertices[n - 1, 2])
    total += float(np.sqrt(dx * dx + dy * dy + dz * dz))
    return float(total)


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_open_nb(vertices: np.ndarray, step: float) -> np.ndarray:
    n = int(vertices.shape[0])
    if n < 2:
        return vertices

    total = _total_length_open_nb(vertices)
    if total <= 0.0:
        return vertices

    step_size = float(step)
    if step_size <= 0.0:
        return vertices

    count = int(np.floor(total / step_size)) + 1
    if float((count - 1) * step_size) < float(total):
        count += 1
    if count < 2:
        count = 2

    out = np.empty((count, 3), dtype=np.float32)
    out[0, 0] = vertices[0, 0]
    out[0, 1] = vertices[0, 1]
    out[0, 2] = vertices[0, 2]
    out[count - 1, 0] = vertices[n - 1, 0]
    out[count - 1, 1] = vertices[n - 1, 1]
    out[count - 1, 2] = vertices[n - 1, 2]

    seg_i = 0
    dist_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    seg_len = float(np.sqrt(dx * dx + dy * dy + dz * dz))

    target = step_size
    out_i = 1
    while out_i < count - 1:
        if seg_len <= 0.0:
            seg_i += 1
            if seg_i >= n - 1:
                break
            sx = float(vertices[seg_i, 0])
            sy = float(vertices[seg_i, 1])
            sz = float(vertices[seg_i, 2])
            ex = float(vertices[seg_i + 1, 0])
            ey = float(vertices[seg_i + 1, 1])
            ez = float(vertices[seg_i + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            seg_len = float(np.sqrt(dx * dx + dy * dy + dz * dz))
            continue

        if dist_acc + seg_len >= target:
            t = (target - dist_acc) / seg_len
            out[out_i, 0] = np.float32(sx + t * dx)
            out[out_i, 1] = np.float32(sy + t * dy)
            out[out_i, 2] = np.float32(sz + t * dz)
            out_i += 1
            target += step_size
        else:
            dist_acc += seg_len
            seg_i += 1
            if seg_i >= n - 1:
                break
            sx = ex
            sy = ey
            sz = ez
            ex = float(vertices[seg_i + 1, 0])
            ey = float(vertices[seg_i + 1, 1])
            ez = float(vertices[seg_i + 1, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            seg_len = float(np.sqrt(dx * dx + dy * dy + dz * dz))

    return out


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _resample_closed_nb(vertices: np.ndarray, step: float) -> np.ndarray:
    n = int(vertices.shape[0])
    if n < 3:
        return vertices

    total = _total_length_closed_nb(vertices)
    if total <= 0.0:
        return vertices

    step_size = float(step)
    if step_size <= 0.0:
        return vertices

    count = int(np.ceil(total / step_size))
    if count < 3:
        count = 3

    out = np.empty((count, 3), dtype=np.float32)
    out[0, 0] = vertices[0, 0]
    out[0, 1] = vertices[0, 1]
    out[0, 2] = vertices[0, 2]

    seg_i = 0
    dist_acc = 0.0
    sx = float(vertices[0, 0])
    sy = float(vertices[0, 1])
    sz = float(vertices[0, 2])
    ex = float(vertices[1, 0])
    ey = float(vertices[1, 1])
    ez = float(vertices[1, 2])
    dx = ex - sx
    dy = ey - sy
    dz = ez - sz
    seg_len = float(np.sqrt(dx * dx + dy * dy + dz * dz))

    for out_i in range(1, count):
        target = float(out_i) * step_size
        while dist_acc + seg_len < target and seg_len > 0.0:
            dist_acc += seg_len
            seg_i += 1
            if seg_i >= n:
                seg_i = 0
            sx = ex
            sy = ey
            sz = ez
            nxt = seg_i + 1
            if nxt >= n:
                nxt = 0
            ex = float(vertices[nxt, 0])
            ey = float(vertices[nxt, 1])
            ez = float(vertices[nxt, 2])
            dx = ex - sx
            dy = ey - sy
            dz = ez - sz
            seg_len = float(np.sqrt(dx * dx + dy * dy + dz * dz))

        if seg_len <= 0.0:
            out[out_i, 0] = np.float32(sx)
            out[out_i, 1] = np.float32(sy)
            out[out_i, 2] = np.float32(sz)
            continue

        t = (target - dist_acc) / seg_len
        out[out_i, 0] = np.float32(sx + t * dx)
        out[out_i, 1] = np.float32(sy + t * dy)
        out[out_i, 2] = np.float32(sz + t * dz)

    return out


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
def _highpass_reflect_nb(points: np.ndarray, kernel: np.ndarray, gain: float) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 1:
        return points

    g = float(gain)
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
        bx = float(points[i, 0])
        by = float(points[i, 1])
        bz = float(points[i, 2])
        out[i, 0] = np.float32(bx + g * (bx - ax))
        out[i, 1] = np.float32(by + g * (by - ay))
        out[i, 2] = np.float32(bz + g * (bz - az))
    return out


@njit(cache=True, fastmath=True)  # type: ignore[misc]
def _highpass_wrap_nb(points: np.ndarray, kernel: np.ndarray, gain: float) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 0:
        return points

    g = float(gain)
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
        bx = float(points[i, 0])
        by = float(points[i, 1])
        bz = float(points[i, 2])
        out[i, 0] = np.float32(bx + g * (bx - ax))
        out[i, 1] = np.float32(by + g * (by - ay))
        out[i, 2] = np.float32(bz + g * (bz - az))
    return out


def _is_closed_auto(vertices: np.ndarray) -> bool:
    if vertices.shape[0] < 3:
        return False
    dx = float(vertices[-1, 0] - vertices[0, 0])
    dy = float(vertices[-1, 1] - vertices[0, 1])
    dz = float(vertices[-1, 2] - vertices[0, 2])
    return float(dx * dx + dy * dy + dz * dz) <= CLOSED_DISTANCE_EPS_SQ


@effect(meta=highpass_meta)
def highpass(
    g: GeomTuple,
    *,
    step: float = 0.5,
    sigma: float = 1.0,
    gain: float = 1.0,
    closed: str = "auto",
) -> GeomTuple:
    """ポリライン列を highpass（高周波強調）する。

    `lowpass` と同様に弧長で等間隔に再サンプルし、ガウス平滑を低域成分として
    unsharp mask（`x + gain * (x - lowpass(x))`）でディテールを強調する。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        変形対象の実体ジオメトリ（coords, offsets）。
    step : float, default 0.5
        再サンプル間隔（弧長）。
    sigma : float, default 1.0
        低域成分を作るガウス平滑半径（`sigma/step` が実効的なスケール）。
    gain : float, default 1.0
        高周波強調係数。0 は no-op。
    closed : str, default "auto"
        境界条件。`"open"` は反射、`"closed"` は周期。
        `"auto"` は端点距離が `CLOSED_DISTANCE_EPS` 以下なら `"closed"` 扱い。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        highpass 適用後の実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    step_size = float(step)
    sigma_size = float(sigma)
    gain_size = float(gain)
    if not np.isfinite(step_size) or not np.isfinite(sigma_size) or not np.isfinite(gain_size):
        return coords, offsets
    if step_size <= 0.0 or sigma_size <= 0.0:
        return coords, offsets
    if gain_size == 0.0:
        return coords, offsets

    closed_mode = str(closed)
    if closed_mode not in {"auto", "open", "closed"}:
        closed_mode = "auto"

    sigma_in_samples = sigma_size / step_size
    if not np.isfinite(sigma_in_samples) or sigma_in_samples <= 0.0:
        return coords, offsets

    kernel = _build_gaussian_kernel(float(sigma_in_samples))

    n_lines = int(offsets.size) - 1
    if n_lines <= 0:
        return coords, offsets

    out_lines: list[np.ndarray] = []
    total_vertices = 0
    for li in range(n_lines):
        s = int(offsets[li])
        e = int(offsets[li + 1])
        v = coords[s:e]
        if v.shape[0] < 2:
            out = v.astype(np.float32, copy=False)
            out_lines.append(out)
            total_vertices += int(out.shape[0])
            continue

        is_closed = False
        if closed_mode == "closed":
            is_closed = True
        elif closed_mode == "auto":
            is_closed = _is_closed_auto(v)

        if is_closed and v.shape[0] >= 3:
            if _is_closed_auto(v):
                v0 = v[:-1]
            else:
                v0 = v
            if v0.shape[0] < 3:
                resampled = _resample_open_nb(v.astype(np.float32, copy=False), float(step_size))
                out = _highpass_reflect_nb(resampled, kernel, float(gain_size))
            else:
                resampled = _resample_closed_nb(v0.astype(np.float32, copy=False), float(step_size))
                hp = _highpass_wrap_nb(resampled, kernel, float(gain_size))
                out = np.empty((hp.shape[0] + 1, 3), dtype=np.float32)
                out[:-1] = hp
                out[-1] = hp[0]
        else:
            resampled = _resample_open_nb(v.astype(np.float32, copy=False), float(step_size))
            out = _highpass_reflect_nb(resampled, kernel, float(gain_size))

        total_vertices += int(out.shape[0])
        if total_vertices > MAX_TOTAL_VERTICES:
            return coords, offsets
        out_lines.append(out)

    if not out_lines:
        return _empty_geometry()

    offsets_out = np.zeros((len(out_lines) + 1,), dtype=np.int32)
    cursor = 0
    coords_list: list[np.ndarray] = []
    for i, line in enumerate(out_lines):
        v = np.asarray(line, dtype=np.float32)
        coords_list.append(v)
        cursor += int(v.shape[0])
        offsets_out[i + 1] = cursor

    coords_out = np.concatenate(coords_list, axis=0) if coords_list else np.zeros((0, 3), np.float32)
    return coords_out, offsets_out


__all__ = [
    "CLOSED_DISTANCE_EPS",
    "highpass",
    "highpass_meta",
]
