"""閉曲線マスク内で Gray-Scott 反応拡散を回し、等値線/スケルトンをポリライン化する effect。"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry

from .util import transform_back, transform_to_xy_plane

MAX_GRID_POINTS = 4_000_000

_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

reaction_diffusion_meta = {
    "grid_pitch": ParamMeta(kind="float", ui_min=0.2, ui_max=2.0),
    "steps": ParamMeta(kind="int", ui_min=0, ui_max=10_000),
    "du": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "dv": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "feed": ParamMeta(kind="float", ui_min=0.0, ui_max=0.1),
    "kill": ParamMeta(kind="float", ui_min=0.0, ui_max=0.1),
    "dt": ParamMeta(kind="float", ui_min=0.1, ui_max=2.0),
    "seed": ParamMeta(kind="int", ui_min=0, ui_max=9999),
    "seed_radius": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
    "noise": ParamMeta(kind="float", ui_min=0.0, ui_max=0.1),
    "mode": ParamMeta(kind="choice", choices=("contour", "skeleton")),
    "level": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "thinning_iters": ParamMeta(kind="int", ui_min=1, ui_max=200),
    "min_points": ParamMeta(kind="int", ui_min=2, ui_max=200),
    "boundary": ParamMeta(kind="choice", choices=("noflux", "dirichlet")),
}


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


def _apply_alignment(
    coords: np.ndarray, rotation_matrix: np.ndarray, z_offset: float
) -> np.ndarray:
    aligned = coords.astype(np.float64, copy=False) @ rotation_matrix.T
    aligned[:, 2] -= float(z_offset)
    return aligned


def _pick_representative_ring(mask: RealizedGeometry) -> np.ndarray | None:
    coords = mask.coords
    offsets = mask.offsets
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        if e - s >= 3:
            return coords[s:e]
    return None


def _pack_mask_rings_xy(
    aligned_mask: np.ndarray, offsets: np.ndarray
) -> tuple[np.ndarray, np.ndarray] | None:
    rings: list[np.ndarray] = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        if e - s < 3:
            continue
        pts = aligned_mask[s:e, 0:2]
        if pts.shape[0] >= 3 and np.all(pts[0] == pts[-1]):
            pts = pts[:-1]
        if pts.shape[0] >= 3:
            rings.append(pts.astype(np.float64, copy=False))

    if not rings:
        return None

    total = 0
    for pts in rings:
        total += int(pts.shape[0])

    vertices = np.empty((total, 2), dtype=np.float64)
    ring_offsets = np.empty((len(rings) + 1,), dtype=np.int32)
    ring_offsets[0] = 0
    cursor = 0
    for i, pts in enumerate(rings):
        n = int(pts.shape[0])
        vertices[cursor : cursor + n] = pts
        cursor += n
        ring_offsets[i + 1] = np.int32(cursor)

    return vertices, ring_offsets


@njit(cache=True)
def _domain_mask_even_odd(
    xs: np.ndarray,
    ys: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
) -> np.ndarray:
    ny = int(ys.shape[0])
    nx = int(xs.shape[0])
    n_rings = int(ring_offsets.shape[0]) - 1

    out = np.zeros((ny, nx), dtype=np.uint8)
    for j in range(ny):
        y = float(ys[j])
        for i in range(nx):
            x = float(xs[i])
            inside = 0
            for ri in range(n_rings):
                s = int(ring_offsets[ri])
                e = int(ring_offsets[ri + 1])
                if e - s < 3:
                    continue
                parity = 0
                for k in range(s, e):
                    k2 = k + 1
                    if k2 >= e:
                        k2 = s
                    ax = float(ring_vertices[k, 0])
                    ay = float(ring_vertices[k, 1])
                    bx = float(ring_vertices[k2, 0])
                    by = float(ring_vertices[k2, 1])
                    if (ay > y) != (by > y):
                        x_int = ax + (y - ay) * (bx - ax) / (by - ay)
                        if x < x_int:
                            parity ^= 1
                inside ^= parity
            if inside == 1:
                out[j, i] = 1
    return out


@njit(cache=True)
def _gray_scott_simulate_masked(
    u0: np.ndarray,
    v0: np.ndarray,
    mask: np.ndarray,
    *,
    steps: int,
    du: float,
    dv: float,
    feed: float,
    kill: float,
    dt: float,
    boundary: int,  # 0: noflux, 1: dirichlet
) -> np.ndarray:
    ny = int(u0.shape[0])
    nx = int(u0.shape[1])
    u = u0.copy()
    v = v0.copy()
    u2 = np.empty_like(u)
    v2 = np.empty_like(v)

    u_out = 1.0
    v_out = 0.0

    for _ in range(int(steps)):
        for j in range(ny):
            for i in range(nx):
                if mask[j, i] == 0:
                    u2[j, i] = u_out
                    v2[j, i] = v_out
                    continue

                uc = float(u[j, i])
                vc = float(v[j, i])

                # up
                if j - 1 < 0 or mask[j - 1, i] == 0:
                    uu = uc if boundary == 0 else u_out
                    vu = vc if boundary == 0 else v_out
                else:
                    uu = float(u[j - 1, i])
                    vu = float(v[j - 1, i])

                # down
                if j + 1 >= ny or mask[j + 1, i] == 0:
                    ud = uc if boundary == 0 else u_out
                    vd = vc if boundary == 0 else v_out
                else:
                    ud = float(u[j + 1, i])
                    vd = float(v[j + 1, i])

                # left
                if i - 1 < 0 or mask[j, i - 1] == 0:
                    ul = uc if boundary == 0 else u_out
                    vl = vc if boundary == 0 else v_out
                else:
                    ul = float(u[j, i - 1])
                    vl = float(v[j, i - 1])

                # right
                if i + 1 >= nx or mask[j, i + 1] == 0:
                    ur = uc if boundary == 0 else u_out
                    vr = vc if boundary == 0 else v_out
                else:
                    ur = float(u[j, i + 1])
                    vr = float(v[j, i + 1])

                lap_u = (uu + ud + ul + ur) - 4.0 * uc
                lap_v = (vu + vd + vl + vr) - 4.0 * vc

                uvv = uc * vc * vc
                du_term = float(du) * lap_u - uvv + float(feed) * (1.0 - uc)
                dv_term = float(dv) * lap_v + uvv - (float(feed) + float(kill)) * vc

                un = uc + du_term * float(dt)
                vn = vc + dv_term * float(dt)

                if un < 0.0:
                    un = 0.0
                elif un > 1.0:
                    un = 1.0
                if vn < 0.0:
                    vn = 0.0
                elif vn > 1.0:
                    vn = 1.0

                u2[j, i] = un
                v2[j, i] = vn

        u, u2 = u2, u
        v, v2 = v2, v

    return v


def _quant_key(x: float, y: float, snap: float) -> tuple[int, int]:
    return (int(np.rint(x / snap)), int(np.rint(y / snap)))


def _stitch_segments_to_paths(
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in segments:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    def _edge_key(u: tuple[int, int], v: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (u, v) if u <= v else (v, u)

    paths: list[list[tuple[int, int]]] = []

    endpoints = [k for k, neighs in adj.items() if len(neighs) == 1]
    for start in endpoints:
        for nxt in adj.get(start, []):
            ek = _edge_key(start, nxt)
            if ek in visited_edges:
                continue
            visited_edges.add(ek)
            path = [start, nxt]
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
            paths.append(path)

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
            paths.append(path)

    return paths


def _marching_squares_segments_masked(
    field: np.ndarray,
    mask: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    level: float,
    snap: float,
    key_to_xy: dict[tuple[int, int], tuple[float, float]],
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    ny, nx = int(field.shape[0]), int(field.shape[1])
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def _interp(a: float, b: float, t_level: float) -> float:
        denom = b - a
        if denom == 0.0:
            return 0.5
        return (t_level - a) / denom

    for j in range(ny - 1):
        y0 = float(ys[j])
        y1 = float(ys[j + 1])
        for i in range(nx - 1):
            if (
                mask[j, i] == 0
                or mask[j, i + 1] == 0
                or mask[j + 1, i + 1] == 0
                or mask[j + 1, i] == 0
            ):
                continue

            x0 = float(xs[i])
            x1 = float(xs[i + 1])

            v00 = float(field[j, i])
            v10 = float(field[j, i + 1])
            v11 = float(field[j + 1, i + 1])
            v01 = float(field[j + 1, i])

            b0 = v00 >= level
            b1 = v10 >= level
            b2 = v11 >= level
            b3 = v01 >= level
            idx = (1 if b0 else 0) | (2 if b1 else 0) | (4 if b2 else 0) | (8 if b3 else 0)
            if idx == 0 or idx == 15:
                continue

            e0 = b0 != b1
            e1 = b1 != b2
            e2 = b3 != b2
            e3 = b0 != b3

            p0 = None
            p1 = None
            p2 = None
            p3 = None

            if e0:
                t = _interp(v00, v10, level)
                x = x0 + float(np.clip(t, 0.0, 1.0)) * (x1 - x0)
                y = y0
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p0 = k
            if e1:
                t = _interp(v10, v11, level)
                x = x1
                y = y0 + float(np.clip(t, 0.0, 1.0)) * (y1 - y0)
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p1 = k
            if e2:
                t = _interp(v01, v11, level)
                x = x0 + float(np.clip(t, 0.0, 1.0)) * (x1 - x0)
                y = y1
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p2 = k
            if e3:
                t = _interp(v00, v01, level)
                x = x0
                y = y0 + float(np.clip(t, 0.0, 1.0)) * (y1 - y0)
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p3 = k

            pts = [p for p in (p0, p1, p2, p3) if p is not None]
            if len(pts) == 2:
                segments.append((pts[0], pts[1]))
                continue
            if len(pts) != 4:
                continue

            vc = 0.25 * (v00 + v10 + v11 + v01)
            center_inside = vc >= level
            if idx == 5:
                if center_inside:
                    segments.append((p0, p1))  # type: ignore[arg-type]
                    segments.append((p2, p3))  # type: ignore[arg-type]
                else:
                    segments.append((p0, p3))  # type: ignore[arg-type]
                    segments.append((p1, p2))  # type: ignore[arg-type]
                continue
            if idx == 10:
                if center_inside:
                    segments.append((p0, p3))  # type: ignore[arg-type]
                    segments.append((p1, p2))  # type: ignore[arg-type]
                else:
                    segments.append((p0, p1))  # type: ignore[arg-type]
                    segments.append((p2, p3))  # type: ignore[arg-type]
                continue

            segments.append((p0, p1))  # type: ignore[arg-type]
            segments.append((p2, p3))  # type: ignore[arg-type]

    return segments


@njit(cache=True)
def _zhang_suen_thinning(binary: np.ndarray, max_iters: int) -> np.ndarray:
    img = binary.copy()
    h = int(img.shape[0])
    w = int(img.shape[1])
    if h < 3 or w < 3:
        return img

    changed = True
    it = 0
    while changed and it < int(max_iters):
        changed = False

        to_del = np.zeros((h, w), dtype=np.uint8)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if img[y, x] == 0:
                    continue
                p2 = int(img[y - 1, x])
                p3 = int(img[y - 1, x + 1])
                p4 = int(img[y, x + 1])
                p5 = int(img[y + 1, x + 1])
                p6 = int(img[y + 1, x])
                p7 = int(img[y + 1, x - 1])
                p8 = int(img[y, x - 1])
                p9 = int(img[y - 1, x - 1])
                n = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                if n < 2 or n > 6:
                    continue
                s = 0
                if p2 == 0 and p3 == 1:
                    s += 1
                if p3 == 0 and p4 == 1:
                    s += 1
                if p4 == 0 and p5 == 1:
                    s += 1
                if p5 == 0 and p6 == 1:
                    s += 1
                if p6 == 0 and p7 == 1:
                    s += 1
                if p7 == 0 and p8 == 1:
                    s += 1
                if p8 == 0 and p9 == 1:
                    s += 1
                if p9 == 0 and p2 == 1:
                    s += 1
                if s != 1:
                    continue
                if p2 * p4 * p6 != 0:
                    continue
                if p4 * p6 * p8 != 0:
                    continue
                to_del[y, x] = 1

        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if to_del[y, x] == 1:
                    img[y, x] = 0
                    changed = True

        to_del2 = np.zeros((h, w), dtype=np.uint8)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if img[y, x] == 0:
                    continue
                p2 = int(img[y - 1, x])
                p3 = int(img[y - 1, x + 1])
                p4 = int(img[y, x + 1])
                p5 = int(img[y + 1, x + 1])
                p6 = int(img[y + 1, x])
                p7 = int(img[y + 1, x - 1])
                p8 = int(img[y, x - 1])
                p9 = int(img[y - 1, x - 1])
                n = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                if n < 2 or n > 6:
                    continue
                s = 0
                if p2 == 0 and p3 == 1:
                    s += 1
                if p3 == 0 and p4 == 1:
                    s += 1
                if p4 == 0 and p5 == 1:
                    s += 1
                if p5 == 0 and p6 == 1:
                    s += 1
                if p6 == 0 and p7 == 1:
                    s += 1
                if p7 == 0 and p8 == 1:
                    s += 1
                if p8 == 0 and p9 == 1:
                    s += 1
                if p9 == 0 and p2 == 1:
                    s += 1
                if s != 1:
                    continue
                if p2 * p4 * p8 != 0:
                    continue
                if p2 * p6 * p8 != 0:
                    continue
                to_del2[y, x] = 1

        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if to_del2[y, x] == 1:
                    img[y, x] = 0
                    changed = True

        it += 1

    return img


def _trace_skeleton_paths(skel: np.ndarray) -> list[list[tuple[int, int]]]:
    h, w = int(skel.shape[0]), int(skel.shape[1])
    if h <= 0 or w <= 0:
        return []

    offsets_8 = [
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    ]

    deg = np.zeros_like(skel, dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            if skel[y, x] == 0:
                continue
            d = 0
            for dy, dx in offsets_8:
                yy = y + dy
                xx = x + dx
                if 0 <= yy < h and 0 <= xx < w and skel[yy, xx] != 0:
                    d += 1
            deg[y, x] = np.uint8(d)

    def edge_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    def neighbors(node: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = node
        out: list[tuple[int, int]] = []
        for dy, dx in offsets_8:
            yy = y + dy
            xx = x + dx
            if 0 <= yy < h and 0 <= xx < w and skel[yy, xx] != 0:
                out.append((yy, xx))
        return out

    paths: list[list[tuple[int, int]]] = []

    # endpoints / junctions から伸ばす（junction で止める）
    for y in range(h):
        for x in range(w):
            if skel[y, x] == 0:
                continue
            d = int(deg[y, x])
            if d != 1 and d < 3:
                continue
            start = (y, x)
            for nxt in neighbors(start):
                ek = edge_key(start, nxt)
                if ek in visited:
                    continue
                visited.add(ek)
                path = [start, nxt]
                prev = start
                cur = nxt
                while True:
                    dcur = int(deg[cur[0], cur[1]])
                    if dcur != 2:
                        break
                    cand = neighbors(cur)
                    next_node: tuple[int, int] | None = None
                    for nn in cand:
                        if nn == prev:
                            continue
                        ek2 = edge_key(cur, nn)
                        if ek2 in visited:
                            continue
                        next_node = nn
                        visited.add(ek2)
                        break
                    if next_node is None:
                        break
                    path.append(next_node)
                    prev, cur = cur, next_node
                paths.append(path)

    # ループ（degree==2 のみの残り）を拾う
    for y in range(h):
        for x in range(w):
            if skel[y, x] == 0 or int(deg[y, x]) != 2:
                continue
            start = (y, x)
            for nxt in neighbors(start):
                ek = edge_key(start, nxt)
                if ek in visited:
                    continue
                visited.add(ek)
                path = [start, nxt]
                prev = start
                cur = nxt
                while True:
                    cand = neighbors(cur)
                    next_node: tuple[int, int] | None = None
                    for nn in cand:
                        if nn == prev:
                            continue
                        ek2 = edge_key(cur, nn)
                        if ek2 in visited:
                            continue
                        next_node = nn
                        visited.add(ek2)
                        break
                    if next_node is None:
                        break
                    path.append(next_node)
                    prev, cur = cur, next_node
                    if cur == start:
                        break
                paths.append(path)

    return paths


@effect(
    meta=reaction_diffusion_meta,
    n_inputs=1,
    ui_visible={"thinning_iters": lambda p: str(p.get("mode", "contour")) == "skeleton"},
)
def reaction_diffusion(
    inputs: Sequence[RealizedGeometry],
    *,
    grid_pitch: float = 0.6,
    steps: int = 4500,
    du: float = 0.16,
    dv: float = 0.08,
    feed: float = 0.035,
    kill: float = 0.062,
    dt: float = 1.0,
    seed: int = 0,
    seed_radius: float = 10.0,
    noise: float = 0.02,
    mode: str = "contour",  # "contour" | "skeleton"
    level: float = 0.2,
    thinning_iters: int = 60,
    min_points: int = 16,
    boundary: str = "noflux",  # "noflux" | "dirichlet"
) -> RealizedGeometry:
    """閉曲線マスク内で反応拡散を走らせ、線として出力する。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        `inputs[0]` が閉曲線（複数可）からなるマスク。
    grid_pitch : float, default 0.6
        計算グリッドのピッチ（出力座標系の長さ単位）。
    steps : int, default 4500
        Gray-Scott の反復回数。
    du, dv : float, default 0.16, 0.08
        拡散係数。
    feed, kill : float, default 0.035, 0.062
        反応パラメータ。
    dt : float, default 1.0
        時間刻み。
    seed : int, default 0
        乱数シード（初期条件用）。
    seed_radius : float, default 10.0
        中心ブロブの半径（0 ならブロブ無し）。
    noise : float, default 0.02
        初期ノイズ量（V に一様ノイズを加える）。
    mode : str, default "contour"
        `"contour"` は等値線、`"skeleton"` は細線化中心線。
    level : float, default 0.2
        等値線/二値化の閾値。
    thinning_iters : int, default 60
        `mode="skeleton"` のときの細線化反復上限。
    min_points : int, default 16
        出力するポリラインの最小点数。
    boundary : str, default "noflux"
        マスク境界の扱い。`"noflux"` は法線方向の勾配 0、`"dirichlet"` は外側を (u=1,v=0) 固定。

    Returns
    -------
    RealizedGeometry
        生成されたポリライン列。
    """
    if not inputs:
        return _empty_geometry()
    mask = inputs[0]
    if mask.coords.shape[0] == 0:
        return _empty_geometry()

    pitch = float(grid_pitch)
    if pitch <= 0.0 or not math.isfinite(pitch):
        return _empty_geometry()

    rep = _pick_representative_ring(mask)
    if rep is None:
        return _empty_geometry()

    _rep_aligned, rotation_matrix, z_offset = transform_to_xy_plane(rep)
    aligned_mask = _apply_alignment(mask.coords, rotation_matrix, z_offset)

    threshold = _planarity_threshold(rep)
    if float(np.max(np.abs(aligned_mask[:, 2]))) > threshold:
        return _empty_geometry()

    packed = _pack_mask_rings_xy(aligned_mask, mask.offsets)
    if packed is None:
        return _empty_geometry()
    ring_vertices, ring_offsets = packed

    mins = np.min(ring_vertices, axis=0)
    maxs = np.max(ring_vertices, axis=0)

    margin = 2.0 * pitch
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
    if nx * ny > MAX_GRID_POINTS:
        return _empty_geometry()

    xs = x0 + pitch * np.arange(nx, dtype=np.float64)
    ys = y0 + pitch * np.arange(ny, dtype=np.float64)

    domain_mask = _domain_mask_even_odd(
        xs.astype(np.float64, copy=False),
        ys.astype(np.float64, copy=False),
        ring_vertices,
        ring_offsets,
    )
    if int(np.sum(domain_mask)) == 0:
        return _empty_geometry()

    rng = np.random.default_rng(int(seed))
    u0 = np.ones((ny, nx), dtype=np.float32)
    v0 = np.zeros((ny, nx), dtype=np.float32)

    mask_bool = domain_mask.astype(bool, copy=False)
    if float(noise) > 0.0:
        v0[mask_bool] = (rng.random(int(np.sum(mask_bool))) - 0.5).astype(np.float32) * (
            2.0 * float(noise)
        )

    r = float(seed_radius)
    if r > 0.0 and math.isfinite(r):
        jj, ii = np.nonzero(domain_mask)
        cy = int(np.rint(np.mean(jj)))
        cx = int(np.rint(np.mean(ii)))
        rr = int(np.ceil(r / pitch))
        y_min = max(0, cy - rr)
        y_max = min(ny - 1, cy + rr)
        x_min = max(0, cx - rr)
        x_max = min(nx - 1, cx + rr)
        r2 = (r / pitch) * (r / pitch)
        for y in range(y_min, y_max + 1):
            dy = float(y - cy)
            for x in range(x_min, x_max + 1):
                if domain_mask[y, x] == 0:
                    continue
                dx = float(x - cx)
                if dx * dx + dy * dy <= r2:
                    u0[y, x] = 0.0
                    v0[y, x] = 1.0

    boundary_s = str(boundary)
    boundary_i = 0 if boundary_s == "noflux" else 1 if boundary_s == "dirichlet" else 0
    v_final = _gray_scott_simulate_masked(
        u0,
        v0,
        domain_mask,
        steps=int(steps),
        du=float(du),
        dv=float(dv),
        feed=float(feed),
        kill=float(kill),
        dt=float(dt),
        boundary=int(boundary_i),
    )

    mode_s = str(mode)
    out_lines: list[np.ndarray] = []

    if mode_s == "skeleton":
        binary = ((v_final >= float(level)) & mask_bool).astype(np.uint8)
        iters = int(thinning_iters)
        if iters > 0:
            binary = _zhang_suen_thinning(binary, iters)
        paths = _trace_skeleton_paths(binary)

        for path in paths:
            if len(path) < int(min_points):
                continue
            pts_xy = np.empty((len(path), 2), dtype=np.float64)
            for pi, (yy, xx) in enumerate(path):
                pts_xy[pi, 0] = float(xs[int(xx)])
                pts_xy[pi, 1] = float(ys[int(yy)])
            v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
            v3[:, 0:2] = pts_xy
            out = transform_back(v3, rotation_matrix, float(z_offset)).astype(
                np.float32, copy=False
            )
            out_lines.append(out)

        return _lines_to_realized(out_lines)

    # contour
    field = v_final.astype(np.float64, copy=False)
    snap = max(1e-9, pitch * 1e-6)
    key_to_xy: dict[tuple[int, int], tuple[float, float]] = {}
    segments = _marching_squares_segments_masked(
        field,
        domain_mask,
        xs,
        ys,
        level=float(level),
        snap=float(snap),
        key_to_xy=key_to_xy,
    )
    paths = _stitch_segments_to_paths(segments)

    for path in paths:
        if len(path) < int(min_points):
            continue
        pts_xy = np.asarray([key_to_xy[k] for k in path], dtype=np.float64)
        v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
        v3[:, 0:2] = pts_xy
        out = transform_back(v3, rotation_matrix, float(z_offset)).astype(
            np.float32, copy=False
        )
        out_lines.append(out)

    return _lines_to_realized(out_lines)


__all__ = ["reaction_diffusion"]
