"""閉曲線群から符号付き距離場を作り、複数レベルの等高線（等値線）をポリライン化する effect。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry
from .util import transform_back, transform_to_xy_plane

MAX_GRID_POINTS = 4_000_000

_AUTO_CLOSE_THRESHOLD_DEFAULT = 1e-3
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

isocontour_meta = {
    "spacing": ParamMeta(kind="float", ui_min=0.2, ui_max=10.0),
    "phase": ParamMeta(kind="float", ui_min=-10.0, ui_max=10.0),
    "max_dist": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "mode": ParamMeta(kind="choice", choices=("inside", "outside", "both")),
    "grid_pitch": ParamMeta(kind="float", ui_min=0.1, ui_max=5.0),
    "gamma": ParamMeta(kind="float", ui_min=0.3, ui_max=3.0),
    "level_step": ParamMeta(kind="int", ui_min=1, ui_max=20),
    "auto_close_threshold": ParamMeta(kind="float", ui_min=0.0, ui_max=5.0),
    "keep_original": ParamMeta(kind="bool"),
}


@dataclass(frozen=True, slots=True)
class _Ring2D:
    vertices: np.ndarray  # (N, 2) float64, closed (first == last)
    mins: np.ndarray  # (2,) float64
    maxs: np.ndarray  # (2,) float64


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _lines_to_realized(lines: list[np.ndarray]) -> RealizedGeometry:
    if not lines:
        return _empty_geometry()
    coords = np.concatenate(lines, axis=0).astype(np.float32, copy=False)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    acc = 0
    for i, ln in enumerate(lines):
        acc += int(ln.shape[0])
        offsets[i + 1] = acc
    return RealizedGeometry(coords=coords, offsets=offsets)


def _planarity_threshold(points: np.ndarray) -> float:
    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def _apply_alignment(coords: np.ndarray, rotation_matrix: np.ndarray, z_offset: float) -> np.ndarray:
    aligned = coords.astype(np.float64, copy=False) @ rotation_matrix.T
    aligned[:, 2] -= float(z_offset)
    return aligned


def _close_curve(points: np.ndarray, threshold: float) -> np.ndarray:
    if points.shape[0] < 2:
        return points
    dist = float(np.linalg.norm(points[0] - points[-1]))
    if dist <= float(threshold):
        return np.concatenate([points[:-1], points[0:1]], axis=0)
    return points


def _pick_representative_ring(base: RealizedGeometry) -> np.ndarray | None:
    coords = base.coords
    offsets = base.offsets
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        if e - s >= 3:
            return coords[s:e]
    return None


def _extract_rings_xy(
    coords_xy: np.ndarray,
    offsets: np.ndarray,
    *,
    auto_close_threshold: float,
) -> list[_Ring2D]:
    rings: list[_Ring2D] = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        poly3 = coords_xy[s:e]
        if poly3.shape[0] < 3:
            continue

        closed3 = _close_curve(poly3, float(auto_close_threshold))
        if closed3.shape[0] < 4:
            continue

        if not np.allclose(closed3[0], closed3[-1], rtol=0.0, atol=1e-12):
            continue

        v2 = closed3[:, :2].astype(np.float64, copy=False)
        mins = np.min(v2, axis=0)
        maxs = np.max(v2, axis=0)
        rings.append(_Ring2D(vertices=v2, mins=mins, maxs=maxs))

    return rings


def _pack_rings(
    rings: list[_Ring2D],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(rings)
    total = 0
    for ring in rings:
        total += int(ring.vertices.shape[0])

    ring_vertices = np.empty((total, 2), dtype=np.float64)
    ring_offsets = np.empty((n + 1,), dtype=np.int32)
    ring_mins = np.empty((n, 2), dtype=np.float64)
    ring_maxs = np.empty((n, 2), dtype=np.float64)

    ring_offsets[0] = 0
    cursor = 0
    for i, ring in enumerate(rings):
        v = ring.vertices.astype(np.float64, copy=False)
        m = int(v.shape[0])
        ring_vertices[cursor : cursor + m] = v
        cursor += m
        ring_offsets[i + 1] = np.int32(cursor)
        ring_mins[i] = ring.mins
        ring_maxs[i] = ring.maxs

    return ring_vertices, ring_offsets, ring_mins, ring_maxs


@njit(cache=True)
def _evaluate_sdf_grid_numba(
    xs: np.ndarray,
    ys: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
    max_dist: float,
    gamma: float,
) -> np.ndarray:
    ny = int(ys.shape[0])
    nx = int(xs.shape[0])
    n_rings = int(ring_offsets.shape[0]) - 1

    out = np.empty((ny, nx), dtype=np.float64)
    for j in range(ny):
        y = float(ys[j])
        for i in range(nx):
            x = float(xs[i])
            min_ds = 1e300
            inside_parity = 0

            for ri in range(n_rings):
                s = int(ring_offsets[ri])
                e = int(ring_offsets[ri + 1])

                inside_possible = (
                    x >= float(ring_mins[ri, 0])
                    and x <= float(ring_maxs[ri, 0])
                    and y >= float(ring_mins[ri, 1])
                    and y <= float(ring_maxs[ri, 1])
                )

                inside = 0
                for k in range(s, e - 1):
                    ax = float(ring_vertices[k, 0])
                    ay = float(ring_vertices[k, 1])
                    bx = float(ring_vertices[k + 1, 0])
                    by = float(ring_vertices[k + 1, 1])

                    # distance^2 to segment
                    dx = bx - ax
                    dy = by - ay
                    denom = dx * dx + dy * dy
                    if denom <= 0.0:
                        ds = (x - ax) * (x - ax) + (y - ay) * (y - ay)
                    else:
                        t = ((x - ax) * dx + (y - ay) * dy) / denom
                        if t < 0.0:
                            t = 0.0
                        elif t > 1.0:
                            t = 1.0
                        cx = ax + t * dx
                        cy = ay + t * dy
                        ds = (x - cx) * (x - cx) + (y - cy) * (y - cy)
                    if ds < min_ds:
                        min_ds = ds

                    # even-odd (boundary is treated as outside)
                    if inside_possible and ((ay > y) != (by > y)):
                        x_int = ax + (y - ay) * (bx - ax) / (by - ay)
                        if x < x_int:
                            inside ^= 1

                inside_parity ^= inside

            dist = math.sqrt(min_ds)
            if max_dist > 0.0 and gamma != 1.0:
                t = dist / max_dist
                if t < 0.0:
                    t = 0.0
                dist = max_dist * math.pow(t, gamma)

            if inside_parity != 0:
                dist = -dist
            out[j, i] = dist

    return out


def _quant_key(x: float, y: float, snap: float) -> tuple[int, int]:
    return (int(np.rint(x / snap)), int(np.rint(y / snap)))


def _stitch_segments_to_loops(
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in segments:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    def _edge_key(u: tuple[int, int], v: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (u, v) if u <= v else (v, u)

    loops: list[list[tuple[int, int]]] = []
    for start, neighs in adj.items():
        for nxt in neighs:
            ek = _edge_key(start, nxt)
            if ek in visited_edges:
                continue

            path = [start, nxt]
            visited_edges.add(ek)
            prev = start
            cur = nxt
            while True:
                cand = adj.get(cur, [])
                next_node: tuple[int, int] | None = None
                for nn in cand:
                    if nn == prev:
                        continue
                    ek2 = _edge_key(cur, nn)
                    if ek2 in visited_edges:
                        continue
                    next_node = nn
                    visited_edges.add(ek2)
                    break

                if next_node is None:
                    break

                path.append(next_node)
                prev, cur = cur, next_node
                if cur == start:
                    break

            if len(path) >= 4 and path[-1] == start:
                loops.append(path)

    return loops


@njit(cache=True)
def _interp_zero(a: float, b: float) -> float:
    denom = b - a
    if denom == 0.0:
        return 0.5
    t = -a / denom
    if t < 0.0:
        return 0.0
    if t > 1.0:
        return 1.0
    return float(t)


@njit(cache=True)
def _count_marching_squares_zero_segments_numba(
    field: np.ndarray,
    sdf: np.ndarray,
    lo: float,
    hi: float,
) -> int:
    ny, nx = int(field.shape[0]), int(field.shape[1])
    n = 0
    for j in range(ny - 1):
        for i in range(nx - 1):
            v00 = float(field[j, i])
            v10 = float(field[j, i + 1])
            v11 = float(field[j + 1, i + 1])
            v01 = float(field[j + 1, i])

            b0 = v00 >= 0.0
            b1 = v10 >= 0.0
            b2 = v11 >= 0.0
            b3 = v01 >= 0.0
            idx = (1 if b0 else 0) | (2 if b1 else 0) | (4 if b2 else 0) | (8 if b3 else 0)
            if idx == 0 or idx == 15:
                continue

            e0 = b0 != b1
            e1 = b1 != b2
            e2 = b3 != b2
            e3 = b0 != b3

            valid = 0
            if e0:
                t = _interp_zero(v00, v10)
                s = float(sdf[j, i]) + t * float(sdf[j, i + 1] - sdf[j, i])
                if s >= lo and s <= hi:
                    valid += 1
            if e1:
                t = _interp_zero(v10, v11)
                s = float(sdf[j, i + 1]) + t * float(sdf[j + 1, i + 1] - sdf[j, i + 1])
                if s >= lo and s <= hi:
                    valid += 1
            if e2:
                t = _interp_zero(v01, v11)
                s = float(sdf[j + 1, i]) + t * float(sdf[j + 1, i + 1] - sdf[j + 1, i])
                if s >= lo and s <= hi:
                    valid += 1
            if e3:
                t = _interp_zero(v00, v01)
                s = float(sdf[j, i]) + t * float(sdf[j + 1, i] - sdf[j, i])
                if s >= lo and s <= hi:
                    valid += 1

            if valid == 2:
                n += 1
            elif valid == 4:
                n += 2

    return int(n)


@njit(cache=True)
def _fill_marching_squares_zero_segments_xy_numba(
    field: np.ndarray,
    sdf: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    lo: float,
    hi: float,
    out_segments: np.ndarray,
) -> int:
    ny, nx = int(field.shape[0]), int(field.shape[1])
    cursor = 0

    for j in range(ny - 1):
        y0 = float(ys[j])
        y1 = float(ys[j + 1])
        for i in range(nx - 1):
            x0 = float(xs[i])
            x1 = float(xs[i + 1])

            v00 = float(field[j, i])
            v10 = float(field[j, i + 1])
            v11 = float(field[j + 1, i + 1])
            v01 = float(field[j + 1, i])

            b0 = v00 >= 0.0
            b1 = v10 >= 0.0
            b2 = v11 >= 0.0
            b3 = v01 >= 0.0
            idx = (1 if b0 else 0) | (2 if b1 else 0) | (4 if b2 else 0) | (8 if b3 else 0)
            if idx == 0 or idx == 15:
                continue

            e0 = b0 != b1
            e1 = b1 != b2
            e2 = b3 != b2
            e3 = b0 != b3

            has0 = False
            has1 = False
            has2 = False
            has3 = False
            p0x = 0.0
            p0y = 0.0
            p1x = 0.0
            p1y = 0.0
            p2x = 0.0
            p2y = 0.0
            p3x = 0.0
            p3y = 0.0

            if e0:
                t = _interp_zero(v00, v10)
                s = float(sdf[j, i]) + t * float(sdf[j, i + 1] - sdf[j, i])
                if s >= lo and s <= hi:
                    has0 = True
                    p0x = x0 + t * (x1 - x0)
                    p0y = y0
            if e1:
                t = _interp_zero(v10, v11)
                s = float(sdf[j, i + 1]) + t * float(sdf[j + 1, i + 1] - sdf[j, i + 1])
                if s >= lo and s <= hi:
                    has1 = True
                    p1x = x1
                    p1y = y0 + t * (y1 - y0)
            if e2:
                t = _interp_zero(v01, v11)
                s = float(sdf[j + 1, i]) + t * float(sdf[j + 1, i + 1] - sdf[j + 1, i])
                if s >= lo and s <= hi:
                    has2 = True
                    p2x = x0 + t * (x1 - x0)
                    p2y = y1
            if e3:
                t = _interp_zero(v00, v01)
                s = float(sdf[j, i]) + t * float(sdf[j + 1, i] - sdf[j, i])
                if s >= lo and s <= hi:
                    has3 = True
                    p3x = x0
                    p3y = y0 + t * (y1 - y0)

            npts = 0
            if has0:
                npts += 1
            if has1:
                npts += 1
            if has2:
                npts += 1
            if has3:
                npts += 1

            if npts == 2:
                ax = 0.0
                ay = 0.0
                bx = 0.0
                by = 0.0
                found_first = False
                if has0:
                    ax, ay = p0x, p0y
                    found_first = True
                if has1:
                    if not found_first:
                        ax, ay = p1x, p1y
                        found_first = True
                    else:
                        bx, by = p1x, p1y
                if has2:
                    if not found_first:
                        ax, ay = p2x, p2y
                        found_first = True
                    else:
                        bx, by = p2x, p2y
                if has3:
                    if not found_first:
                        ax, ay = p3x, p3y
                        found_first = True
                    else:
                        bx, by = p3x, p3y

                out_segments[cursor, 0] = ax
                out_segments[cursor, 1] = ay
                out_segments[cursor, 2] = bx
                out_segments[cursor, 3] = by
                cursor += 1
                continue

            if npts != 4:
                continue

            vc = 0.25 * (v00 + v10 + v11 + v01)
            center_inside = vc >= 0.0
            if idx == 5:
                if center_inside:
                    out_segments[cursor, 0] = p0x
                    out_segments[cursor, 1] = p0y
                    out_segments[cursor, 2] = p1x
                    out_segments[cursor, 3] = p1y
                    cursor += 1
                    out_segments[cursor, 0] = p2x
                    out_segments[cursor, 1] = p2y
                    out_segments[cursor, 2] = p3x
                    out_segments[cursor, 3] = p3y
                    cursor += 1
                else:
                    out_segments[cursor, 0] = p0x
                    out_segments[cursor, 1] = p0y
                    out_segments[cursor, 2] = p3x
                    out_segments[cursor, 3] = p3y
                    cursor += 1
                    out_segments[cursor, 0] = p1x
                    out_segments[cursor, 1] = p1y
                    out_segments[cursor, 2] = p2x
                    out_segments[cursor, 3] = p2y
                    cursor += 1
                continue
            if idx == 10:
                if center_inside:
                    out_segments[cursor, 0] = p0x
                    out_segments[cursor, 1] = p0y
                    out_segments[cursor, 2] = p3x
                    out_segments[cursor, 3] = p3y
                    cursor += 1
                    out_segments[cursor, 0] = p1x
                    out_segments[cursor, 1] = p1y
                    out_segments[cursor, 2] = p2x
                    out_segments[cursor, 3] = p2y
                    cursor += 1
                else:
                    out_segments[cursor, 0] = p0x
                    out_segments[cursor, 1] = p0y
                    out_segments[cursor, 2] = p1x
                    out_segments[cursor, 3] = p1y
                    cursor += 1
                    out_segments[cursor, 0] = p2x
                    out_segments[cursor, 1] = p2y
                    out_segments[cursor, 2] = p3x
                    out_segments[cursor, 3] = p3y
                    cursor += 1
                continue

            out_segments[cursor, 0] = p0x
            out_segments[cursor, 1] = p0y
            out_segments[cursor, 2] = p1x
            out_segments[cursor, 3] = p1y
            cursor += 1
            out_segments[cursor, 0] = p2x
            out_segments[cursor, 1] = p2y
            out_segments[cursor, 2] = p3x
            out_segments[cursor, 3] = p3y
            cursor += 1

    return int(cursor)


@effect(meta=isocontour_meta, n_inputs=1)
def isocontour(
    inputs: Sequence[RealizedGeometry],
    *,
    spacing: float = 2.0,
    phase: float = 0.0,
    max_dist: float = 30.0,
    mode: str = "inside",  # "inside" | "outside" | "both"
    grid_pitch: float = 0.5,
    gamma: float = 1.0,
    level_step: int = 1,
    auto_close_threshold: float = _AUTO_CLOSE_THRESHOLD_DEFAULT,
    keep_original: bool = False,
) -> RealizedGeometry:
    """閉曲線群から等高線（等値線）を複数レベル抽出して出力する。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        `inputs[0]` が閉曲線群（外周＋穴）。開曲線は無視する。
    spacing : float, default 2.0
        レベル間隔。
    phase : float, default 0.0
        レベルの位相（`0` だと境界 `SDF=0` が含まれる）。
    max_dist : float, default 30.0
        抽出範囲（`|SDF| <= max_dist`）。
    mode : str, default "inside"
        `"inside"` は内側のみ、`"outside"` は外側のみ、`"both"` は両側を抽出する。
    grid_pitch : float, default 0.5
        SDF 評価グリッドのピッチ。
    gamma : float, default 1.0
        距離の非線形（`1.0` は線形）。`max_dist` を基準に 0..max_dist を保ったままカーブを歪める。
    level_step : int, default 1
        レベルの間引き。`n` のとき「n 本に 1 本」だけ残す（`1` は全て）。
    auto_close_threshold : float, default 1e-3
        閉曲線とみなす端点距離閾値。
    keep_original : bool, default False
        True のとき、生成結果に加えて元の入力も出力に含める。

    Returns
    -------
    RealizedGeometry
        抽出した等値線のポリライン列。
    """
    if not inputs:
        return _empty_geometry()
    mask = inputs[0]
    if mask.coords.shape[0] == 0:
        return _empty_geometry()

    pitch = float(grid_pitch)
    if pitch <= 0.0 or not math.isfinite(pitch):
        return _empty_geometry()

    spacing_f = float(spacing)
    if spacing_f <= 0.0 or not math.isfinite(spacing_f):
        return _empty_geometry()

    phase_f = float(phase)
    if not math.isfinite(phase_f):
        return _empty_geometry()

    max_d = float(max_dist)
    if not math.isfinite(max_d):
        return _empty_geometry()
    if max_d < 0.0:
        return _empty_geometry()

    mode_s = str(mode)
    if mode_s not in {"inside", "outside", "both"}:
        return _empty_geometry()

    auto_close = float(auto_close_threshold)
    if not math.isfinite(auto_close) or auto_close < 0.0:
        auto_close = float(_AUTO_CLOSE_THRESHOLD_DEFAULT)

    gamma_f = float(gamma)
    if not math.isfinite(gamma_f) or gamma_f <= 0.0:
        gamma_f = 1.0

    rep = _pick_representative_ring(mask)
    if rep is None:
        return _empty_geometry()

    _rep_xy, rot, z_off = transform_to_xy_plane(rep)
    coords_xy_all = _apply_alignment(mask.coords, rot, float(z_off))

    if float(np.max(np.abs(coords_xy_all[:, 2]))) > _planarity_threshold(mask.coords):
        return _empty_geometry()

    rings = _extract_rings_xy(coords_xy_all, mask.offsets, auto_close_threshold=auto_close)
    if not rings:
        return _empty_geometry()

    mins = np.min(np.stack([r0.mins for r0 in rings], axis=0), axis=0)
    maxs = np.max(np.stack([r0.maxs for r0 in rings], axis=0), axis=0)

    margin = max(0.0, max_d) + 2.0 * pitch
    x0 = float(mins[0] - margin)
    x1 = float(maxs[0] + margin)
    y0 = float(mins[1] - margin)
    y1 = float(maxs[1] + margin)

    span_x = max(0.0, x1 - x0)
    span_y = max(0.0, y1 - y0)
    nx = int(np.ceil(span_x / pitch)) + 1
    ny = int(np.ceil(span_y / pitch)) + 1
    if nx < 2 or ny < 2:
        return _empty_geometry()
    if int(nx) * int(ny) > int(MAX_GRID_POINTS):
        return _empty_geometry()

    xs = x0 + pitch * np.arange(nx, dtype=np.float64)
    ys = y0 + pitch * np.arange(ny, dtype=np.float64)

    ring_vertices, ring_offsets, ring_mins, ring_maxs = _pack_rings(rings)
    sdf = _evaluate_sdf_grid_numba(
        xs.astype(np.float64, copy=False),
        ys.astype(np.float64, copy=False),
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
        float(max_d),
        float(gamma_f),
    )

    level_step_i = max(1, int(level_step))
    spacing_eff = float(spacing_f) * float(level_step_i)
    field = np.sin(np.pi * (sdf - float(phase_f)) / spacing_eff).astype(np.float64, copy=False)

    if mode_s == "inside":
        lo, hi = -max_d, 0.0
    elif mode_s == "outside":
        lo, hi = 0.0, max_d
    else:
        lo, hi = -max_d, max_d

    n_segments = _count_marching_squares_zero_segments_numba(field, sdf, float(lo), float(hi))
    if n_segments <= 0:
        return _empty_geometry()

    segments_xy = np.empty((int(n_segments), 4), dtype=np.float64)
    filled = _fill_marching_squares_zero_segments_xy_numba(
        field,
        sdf,
        xs,
        ys,
        lo=float(lo),
        hi=float(hi),
        out_segments=segments_xy,
    )
    segments_xy = segments_xy[: int(filled)]

    snap = max(1e-9, pitch * 1e-6)
    key_to_xy: dict[tuple[int, int], tuple[float, float]] = {}
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for seg in segments_xy:
        ax = float(seg[0])
        ay = float(seg[1])
        bx = float(seg[2])
        by = float(seg[3])
        k0 = _quant_key(ax, ay, snap)
        k1 = _quant_key(bx, by, snap)
        if k0 == k1:
            continue
        key_to_xy.setdefault(k0, (ax, ay))
        key_to_xy.setdefault(k1, (bx, by))
        segments.append((k0, k1))

    loops = _stitch_segments_to_loops(segments)

    out_lines: list[np.ndarray] = []
    for loop in loops:
        pts_xy = np.asarray([key_to_xy[k] for k in loop], dtype=np.float64)
        if pts_xy.shape[0] < 4:
            continue
        v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
        v3[:, 0:2] = pts_xy
        out = transform_back(v3, rot, float(z_off)).astype(np.float32, copy=False)
        out_lines.append(out)

    if bool(keep_original):
        for i in range(int(mask.offsets.size) - 1):
            s = int(mask.offsets[i])
            e = int(mask.offsets[i + 1])
            original = mask.coords[s:e]
            if original.shape[0] > 0:
                out_lines.append(original.astype(np.float32, copy=False))

    return _lines_to_realized(out_lines)
