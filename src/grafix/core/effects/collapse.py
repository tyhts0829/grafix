"""線分を細分化し、局所的なランダム変位で「崩し」を作る effect。"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.realized_geometry import RealizedGeometry
from grafix.core.parameters.meta import ParamMeta

EPS = 1e-12

collapse_meta = {
    "intensity": ParamMeta(kind="float", ui_min=0.0, ui_max=10.0),
    "subdivisions": ParamMeta(kind="int", ui_min=0, ui_max=10),
    "intensity_mask_base": ParamMeta(kind="vec3", ui_min=0.0, ui_max=1.0),
    "intensity_mask_slope": ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0),
    "auto_center": ParamMeta(kind="bool"),
    "pivot": ParamMeta(kind="vec3", ui_min=-100.0, ui_max=100.0),
}


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@effect(meta=collapse_meta)
def collapse(
    inputs: Sequence[RealizedGeometry],
    *,
    intensity: float = 5.0,
    subdivisions: int = 6,
    intensity_mask_base: tuple[float, float, float] = (1.0, 1.0, 1.0),
    intensity_mask_slope: tuple[float, float, float] = (0.0, 0.0, 0.0),
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> RealizedGeometry:
    """線分を細分化してノイズで崩す（非接続）。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        入力の実体ジオメトリ列。通常は 1 要素。
    intensity : float, default 5.0
        変位量（長さ単位は座標系に従う）。0.0 で no-op。
    subdivisions : int, default 6
        細分回数。0 以下で no-op。
    intensity_mask_base : tuple[float, float, float], default (1.0, 1.0, 1.0)
        ジオメトリ bbox の中心（正規化座標 t=0）における intensity 乗算係数（軸別）。
        各成分は 0.0〜1.0。
    intensity_mask_slope : tuple[float, float, float], default (0.0, 0.0, 0.0)
        正規化座標 t∈[-1,+1] に対する係数勾配（軸別）。
    auto_center : bool, default True
        True のとき `pivot` を無視し、入力 bbox の中心を pivot として扱う。
    pivot : tuple[float, float, float], default (0.0, 0.0, 0.0)
        auto_center=False のときの pivot（ワールド座標）。

    Returns
    -------
    RealizedGeometry
        変形後の実体ジオメトリ。

    Notes
    -----
    出力は「各サブセグメントが 2 点からなる独立ポリライン（非接続）」。

    崩し量は、各サブセグメントの midpoint を基準に係数 `p_eff` を計算し、
    `intensity_eff = intensity * p_eff` として適用する。
    係数は `p_eff = 1 - (1-px)(1-py)(1-pz)`（OR 合成）で作る。
    """
    if not inputs:
        return _empty_geometry()

    base = inputs[0]
    if base.coords.shape[0] == 0:
        return base

    intensity = float(intensity)
    divisions = int(subdivisions)
    if intensity == 0.0 or divisions <= 0:
        return base

    new_coords, new_offsets = _collapse_numba(
        base.coords,
        base.offsets,
        intensity,
        divisions,
        intensity_mask_base=intensity_mask_base,
        intensity_mask_slope=intensity_mask_slope,
        auto_center=bool(auto_center),
        pivot=pivot,
    )
    return RealizedGeometry(coords=new_coords, offsets=new_offsets)


def _collapse_numpy_v2(
    coords: np.ndarray,
    offsets: np.ndarray,
    intensity: float,
    divisions: int,
) -> tuple[np.ndarray, np.ndarray]:
    """collapse を分布互換のまま効率化（2 パス + 前方確保）。"""
    if coords.shape[0] == 0 or intensity == 0.0 or divisions <= 0:
        return coords.copy(), offsets.copy()

    rng = np.random.default_rng(0)
    n_lines = len(offsets) - 1

    total_lines = 0
    total_vertices = 0
    for li in range(n_lines):
        v = coords[offsets[li] : offsets[li + 1]]
        n = v.shape[0]
        if n < 2:
            total_lines += 1
            total_vertices += n
            continue
        seg = v[1:] - v[:-1]
        L = np.sqrt(np.sum(seg.astype(np.float64) ** 2, axis=1))
        nz = L > EPS
        total_lines += int(np.count_nonzero(nz)) * divisions + int(np.count_nonzero(~nz))
        total_vertices += (
            int(np.count_nonzero(nz)) * (2 * divisions) + int(np.count_nonzero(~nz)) * 2
        )

    if total_lines == 0:
        return coords.copy(), offsets.copy()

    out_coords = np.empty((total_vertices, 3), dtype=np.float32)
    out_offsets = np.empty((total_lines + 1,), dtype=np.int32)
    out_offsets[0] = 0
    vc = 0
    oc = 1

    t = np.linspace(0.0, 1.0, divisions + 1, dtype=np.float64)
    t0 = t[:-1]
    t1 = t[1:]

    for li in range(n_lines):
        v = coords[offsets[li] : offsets[li + 1]].astype(np.float64, copy=False)
        n = v.shape[0]
        if n < 2:
            if n > 0:
                out_coords[vc : vc + n] = v.astype(np.float32, copy=False)
                vc += n
            out_offsets[oc] = vc
            oc += 1
            continue

        for j in range(n - 1):
            a = v[j]
            b = v[j + 1]
            d = b - a
            L = float(np.sqrt(np.dot(d, d)))
            if not np.isfinite(L) or L <= EPS:
                out_coords[vc] = a.astype(np.float32)
                vc += 1
                out_coords[vc] = b.astype(np.float32)
                vc += 1
                out_offsets[oc] = vc
                oc += 1
                continue

            n_main = d / L
            ref = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            if abs(n_main[2]) >= 0.9:
                ref = np.array([1.0, 0.0, 0.0], dtype=np.float64)
            u = np.cross(n_main, ref)
            ul = float(np.sqrt(np.dot(u, u)))
            if ul <= EPS:
                u = np.array([1.0, 0.0, 0.0], dtype=np.float64)
                ul = 1.0
            u /= ul
            v_basis = np.cross(n_main, u)

            starts = a * (1.0 - t0[:, None]) + b * t0[:, None]
            ends = a * (1.0 - t1[:, None]) + b * t1[:, None]

            theta = rng.random(divisions) * (2.0 * math.pi)
            c = np.cos(theta)
            s = np.sin(theta)
            noise = (c[:, None] * u[None, :] + s[:, None] * v_basis[None, :]) * float(intensity)

            out_coords[vc : vc + 2 * divisions : 2] = (starts + noise).astype(
                np.float32, copy=False
            )
            out_coords[vc + 1 : vc + 2 * divisions : 2] = (ends + noise).astype(
                np.float32, copy=False
            )
            out_offsets[oc : oc + divisions] = vc + 2 * (np.arange(divisions, dtype=np.int32) + 1)
            vc += 2 * divisions
            oc += divisions

    if oc < out_offsets.shape[0]:
        out_offsets[oc:] = vc
    return out_coords, out_offsets


def _collapse_count(
    coords: np.ndarray,
    offsets: np.ndarray,
    divisions: int,
) -> tuple[int, int, int]:
    """出力配列サイズと有効セグメント数を事前に数える（NumPy）。"""
    n_lines = len(offsets) - 1
    total_lines = 0
    total_vertices = 0
    valid_seg_count = 0

    for li in range(n_lines):
        v = coords[offsets[li] : offsets[li + 1]]
        n = v.shape[0]
        if n < 2:
            total_lines += 1
            total_vertices += n
            continue
        seg = v[1:] - v[:-1]
        L2 = np.sum(seg.astype(np.float64) ** 2, axis=1)
        L = np.sqrt(L2)
        finite = np.isfinite(L)
        mask = finite & (L > EPS)
        n_valid = int(np.count_nonzero(mask))
        n_invalid = int(np.count_nonzero(~mask))

        valid_seg_count += n_valid
        total_lines += n_valid * divisions + n_invalid
        total_vertices += n_valid * (2 * divisions) + n_invalid * 2

    return total_lines, total_vertices, valid_seg_count


@njit(cache=True, fastmath=False)
def _collapse_njit_fill(
    coords64: np.ndarray,
    offsets32: np.ndarray,
    intensity64: float,
    divisions: int,
    t0: np.ndarray,
    t1: np.ndarray,
    cos_list: np.ndarray,
    sin_list: np.ndarray,
    pivot3: np.ndarray,
    inv_extent3: np.ndarray,
    mask_base_x: float,
    mask_base_y: float,
    mask_base_z: float,
    mask_slope_x: float,
    mask_slope_y: float,
    mask_slope_z: float,
    use_intensity_mask: bool,
    out_coords32: np.ndarray,
    out_offsets32: np.ndarray,
) -> None:
    vc = 0
    oc = 1
    out_offsets32[0] = 0
    idx = 0

    n_lines = offsets32.shape[0] - 1
    for li in range(n_lines):
        start = int(offsets32[li])
        end = int(offsets32[li + 1])
        n = end - start
        if n < 2:
            if n > 0:
                for m in range(n):
                    p = coords64[start + m]
                    out_coords32[vc, 0] = float(p[0])
                    out_coords32[vc, 1] = float(p[1])
                    out_coords32[vc, 2] = float(p[2])
                    vc += 1
            out_offsets32[oc] = vc
            oc += 1
            continue

        for j in range(n - 1):
            a = coords64[start + j]
            b = coords64[start + j + 1]
            d0 = b[0] - a[0]
            d1 = b[1] - a[1]
            d2 = b[2] - a[2]
            L = math.sqrt(d0 * d0 + d1 * d1 + d2 * d2)
            if (not math.isfinite(L)) or (L <= EPS):
                out_coords32[vc, 0] = float(a[0])
                out_coords32[vc, 1] = float(a[1])
                out_coords32[vc, 2] = float(a[2])
                vc += 1
                out_coords32[vc, 0] = float(b[0])
                out_coords32[vc, 1] = float(b[1])
                out_coords32[vc, 2] = float(b[2])
                vc += 1
                out_offsets32[oc] = vc
                oc += 1
                continue

            invL = 1.0 / L
            nmx = d0 * invL
            nmy = d1 * invL
            nmz = d2 * invL

            refx = 0.0
            refy = 0.0
            refz = 1.0
            if abs(nmz) >= 0.9:
                refx = 1.0
                refy = 0.0
                refz = 0.0

            ux = nmy * refz - nmz * refy
            uy = nmz * refx - nmx * refz
            uz = nmx * refy - nmy * refx
            ul = math.sqrt(ux * ux + uy * uy + uz * uz)
            if ul <= EPS:
                ux, uy, uz = 1.0, 0.0, 0.0
                ul = 1.0
            inv_ul = 1.0 / ul
            ux *= inv_ul
            uy *= inv_ul
            uz *= inv_ul

            vx = nmy * uz - nmz * uy
            vy = nmz * ux - nmx * uz
            vz = nmx * uy - nmy * ux

            for k in range(divisions):
                t0k = t0[k]
                t1k = t1[k]

                p0x = a[0] * (1.0 - t0k) + b[0] * t0k
                p0y = a[1] * (1.0 - t0k) + b[1] * t0k
                p0z = a[2] * (1.0 - t0k) + b[2] * t0k

                p1x = a[0] * (1.0 - t1k) + b[0] * t1k
                p1y = a[1] * (1.0 - t1k) + b[1] * t1k
                p1z = a[2] * (1.0 - t1k) + b[2] * t1k

                c = cos_list[idx]
                s = sin_list[idx]
                idx += 1

                intensity_eff = intensity64
                if use_intensity_mask:
                    mx = 0.5 * (p0x + p1x)
                    my = 0.5 * (p0y + p1y)
                    mz = 0.5 * (p0z + p1z)

                    tx = (mx - pivot3[0]) * inv_extent3[0]
                    ty = (my - pivot3[1]) * inv_extent3[1]
                    tz = (mz - pivot3[2]) * inv_extent3[2]

                    if tx < -1.0:
                        tx = -1.0
                    elif tx > 1.0:
                        tx = 1.0
                    if ty < -1.0:
                        ty = -1.0
                    elif ty > 1.0:
                        ty = 1.0
                    if tz < -1.0:
                        tz = -1.0
                    elif tz > 1.0:
                        tz = 1.0

                    px = mask_base_x + mask_slope_x * tx
                    py = mask_base_y + mask_slope_y * ty
                    pz = mask_base_z + mask_slope_z * tz

                    if px < 0.0:
                        px = 0.0
                    elif px > 1.0:
                        px = 1.0
                    if py < 0.0:
                        py = 0.0
                    elif py > 1.0:
                        py = 1.0
                    if pz < 0.0:
                        pz = 0.0
                    elif pz > 1.0:
                        pz = 1.0

                    p_eff = 1.0 - (1.0 - px) * (1.0 - py) * (1.0 - pz)
                    intensity_eff = intensity64 * p_eff

                nx = (c * ux + s * vx) * intensity_eff
                ny = (c * uy + s * vy) * intensity_eff
                nz = (c * uz + s * vz) * intensity_eff

                out_coords32[vc, 0] = float(p0x + nx)
                out_coords32[vc, 1] = float(p0y + ny)
                out_coords32[vc, 2] = float(p0z + nz)
                vc += 1
                out_coords32[vc, 0] = float(p1x + nx)
                out_coords32[vc, 1] = float(p1y + ny)
                out_coords32[vc, 2] = float(p1z + nz)
                vc += 1

                out_offsets32[oc] = vc
                oc += 1


def _collapse_numba(
    coords: np.ndarray,
    offsets: np.ndarray,
    intensity: float,
    divisions: int,
    *,
    intensity_mask_base: tuple[float, float, float],
    intensity_mask_slope: tuple[float, float, float],
    auto_center: bool,
    pivot: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Numba 経路で collapse を実行する。"""
    if coords.shape[0] == 0 or intensity == 0.0 or divisions <= 0:
        return coords.copy(), offsets.copy()

    try:
        base_x = float(intensity_mask_base[0])
        base_y = float(intensity_mask_base[1])
        base_z = float(intensity_mask_base[2])
    except Exception:
        base_x = 1.0
        base_y = 1.0
        base_z = 1.0

    if not np.isfinite(base_x):
        base_x = 1.0
    if not np.isfinite(base_y):
        base_y = 1.0
    if not np.isfinite(base_z):
        base_z = 1.0

    if base_x < 0.0:
        base_x = 0.0
    elif base_x > 1.0:
        base_x = 1.0
    if base_y < 0.0:
        base_y = 0.0
    elif base_y > 1.0:
        base_y = 1.0
    if base_z < 0.0:
        base_z = 0.0
    elif base_z > 1.0:
        base_z = 1.0

    try:
        slope_x = float(intensity_mask_slope[0])
        slope_y = float(intensity_mask_slope[1])
        slope_z = float(intensity_mask_slope[2])
    except Exception:
        slope_x = 0.0
        slope_y = 0.0
        slope_z = 0.0

    if not np.isfinite(slope_x):
        slope_x = 0.0
    if not np.isfinite(slope_y):
        slope_y = 0.0
    if not np.isfinite(slope_z):
        slope_z = 0.0

    use_intensity_mask = not (
        (base_x == 1.0)
        and (base_y == 1.0)
        and (base_z == 1.0)
        and (slope_x == 0.0)
        and (slope_y == 0.0)
        and (slope_z == 0.0)
    )

    pivot3 = np.zeros((3,), dtype=np.float64)
    inv_extent3 = np.zeros((3,), dtype=np.float64)
    if use_intensity_mask:
        mins3 = np.min(coords, axis=0).astype(np.float64, copy=False)
        maxs3 = np.max(coords, axis=0).astype(np.float64, copy=False)
        bbox_center = (mins3 + maxs3) * 0.5
        extent3 = (maxs3 - mins3) * 0.5

        for k in range(3):
            extent_k = float(extent3[k])
            inv_extent3[k] = 0.0 if extent_k < 1e-9 else 1.0 / extent_k

        if auto_center:
            pivot3 = bbox_center
        else:
            try:
                pivot3 = np.array(
                    [float(pivot[0]), float(pivot[1]), float(pivot[2])],
                    dtype=np.float64,
                )
            except Exception:
                pivot3 = np.zeros((3,), dtype=np.float64)
            if not np.all(np.isfinite(pivot3)):
                pivot3 = np.zeros((3,), dtype=np.float64)

    total_lines, total_vertices, valid_seg_count = _collapse_count(coords, offsets, divisions)
    if total_lines == 0:
        return coords.copy(), offsets.copy()

    out_coords = np.empty((total_vertices, 3), dtype=np.float32)
    out_offsets = np.empty((total_lines + 1,), dtype=np.int32)

    t = np.linspace(0.0, 1.0, divisions + 1, dtype=np.float64)
    t0 = t[:-1]
    t1 = t[1:]

    rng = np.random.default_rng(0)
    theta = rng.random(valid_seg_count * divisions) * (2.0 * math.pi)
    cos_list = np.cos(theta)
    sin_list = np.sin(theta)

    coords64 = coords.astype(np.float64, copy=False)
    offsets32 = offsets.astype(np.int32, copy=False)

    _collapse_njit_fill(
        coords64,
        offsets32,
        float(intensity),
        int(divisions),
        t0,
        t1,
        cos_list,
        sin_list,
        pivot3,
        inv_extent3,
        base_x,
        base_y,
        base_z,
        slope_x,
        slope_y,
        slope_z,
        bool(use_intensity_mask),
        out_coords,
        out_offsets,
    )
    return out_coords, out_offsets
