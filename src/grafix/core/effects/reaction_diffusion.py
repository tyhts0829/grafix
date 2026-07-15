"""閉曲線マスク内で Gray-Scott 反応拡散を回し、等値線（閉ループ）をポリライン化する effect。"""

from __future__ import annotations

import math

import numpy as np
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple

from .util import (
    DEFAULT_MAX_GRID_CELLS,
    GridSpec,
    PlanarFrame,
    empty_geom,
    marching_squares_loops,
    pack_polylines,
    scanline_evenodd_mask,
)

MAX_GRID_POINTS = DEFAULT_MAX_GRID_CELLS

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
    "level": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "min_points": ParamMeta(kind="int", ui_min=4, ui_max=200),
    "boundary": ParamMeta(kind="choice", choices=("noflux", "dirichlet")),
}


def _planarity_threshold(points: np.ndarray) -> float:
    if points.size == 0:
        return float(_PLANAR_EPS_ABS)
    p = points.astype(np.float64, copy=False)
    mins = np.min(p, axis=0)
    maxs = np.max(p, axis=0)
    diag = float(np.linalg.norm(maxs - mins))
    return max(float(_PLANAR_EPS_ABS), float(_PLANAR_EPS_REL) * diag)


def _pack_mask_rings_xy(
    aligned_mask: np.ndarray, offsets: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    rings: list[np.ndarray] = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        if e - s < 3:
            continue
        pts = aligned_mask[s:e, 0:2]
        if pts.shape[0] >= 3:
            values = pts.astype(np.float64, copy=False)
            if not np.all(values[0] == values[-1]):
                values = np.concatenate([values, values[:1]], axis=0)
            rings.append(values)

    if not rings:
        return None

    total = 0
    for pts in rings:
        total += int(pts.shape[0])

    vertices = np.empty((total, 2), dtype=np.float64)
    ring_offsets = np.empty((len(rings) + 1,), dtype=np.int32)
    ring_mins = np.empty((len(rings), 2), dtype=np.float64)
    ring_maxs = np.empty((len(rings), 2), dtype=np.float64)
    ring_offsets[0] = 0
    cursor = 0
    for i, pts in enumerate(rings):
        n = int(pts.shape[0])
        vertices[cursor : cursor + n] = pts
        cursor += n
        ring_offsets[i + 1] = np.int32(cursor)
        ring_mins[i] = np.min(pts, axis=0)
        ring_maxs[i] = np.max(pts, axis=0)

    return vertices, ring_offsets, ring_mins, ring_maxs



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



@effect(meta=reaction_diffusion_meta, n_inputs=1)
def reaction_diffusion(
    mask: GeomTuple,
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
    level: float = 0.2,
    min_points: int = 16,
    boundary: str = "noflux",  # "noflux" | "dirichlet"
) -> GeomTuple:
    """閉曲線マスク内で反応拡散を走らせ、線として出力する。

    Parameters
    ----------
    mask : tuple[np.ndarray, np.ndarray]
        閉曲線（複数可）からなるマスク（coords, offsets）。
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
    level : float, default 0.2
        等値線の閾値。
    min_points : int, default 16
        出力するポリラインの最小点数。
    boundary : str, default "noflux"
        マスク境界の扱い。`"noflux"` は法線方向の勾配 0、`"dirichlet"` は外側を (u=1,v=0) 固定。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        生成されたポリライン列（coords, offsets）。
    """
    mask_coords, mask_offsets = mask
    if mask_coords.shape[0] == 0:
        return empty_geom()

    pitch = float(grid_pitch)
    if pitch <= 0.0 or not math.isfinite(pitch):
        return empty_geom()

    frame = PlanarFrame.from_points(mask_coords, mask_offsets)
    if not frame.is_planar(_planarity_threshold(mask_coords)):
        return empty_geom()

    aligned_mask = frame.to_local(mask_coords)

    packed = _pack_mask_rings_xy(aligned_mask, mask_offsets)
    if packed is None:
        return empty_geom()
    ring_vertices, ring_offsets, ring_mins, ring_maxs = packed

    mins = np.min(ring_vertices, axis=0)
    maxs = np.max(ring_vertices, axis=0)

    margin = 2.0 * pitch
    grid = GridSpec.from_bbox(
        mins,
        maxs,
        pitch=pitch,
        padding=margin,
        max_cells=MAX_GRID_POINTS,
        overflow="reject",
    )
    if grid is None:
        return empty_geom()
    xs, ys = grid.coordinates()
    nx = grid.nx
    ny = grid.ny
    pitch = grid.pitch

    domain_mask = scanline_evenodd_mask(
        ys.astype(np.float64, copy=False),
        origin_x=grid.origin_x,
        pitch=pitch,
        nx=nx,
        ring_vertices=ring_vertices,
        ring_offsets=ring_offsets,
        ring_mins=ring_mins,
        ring_maxs=ring_maxs,
    )
    if int(np.sum(domain_mask)) == 0:
        return empty_geom()

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

    out_lines: list[np.ndarray] = []

    field = v_final.astype(np.float64, copy=False)
    loops = marching_squares_loops(
        field,
        origin_x=grid.origin_x,
        origin_y=grid.origin_y,
        pitch=pitch,
        level=float(level),
        mask=domain_mask,
    )

    for pts_xy in loops:
        if pts_xy.shape[0] < int(min_points):
            continue
        if pts_xy.shape[0] >= 2 and not np.all(pts_xy[0] == pts_xy[-1]):
            pts_xy = np.concatenate([pts_xy, pts_xy[:1]], axis=0)
        v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
        v3[:, 0:2] = pts_xy
        out = frame.to_world(v3).astype(np.float32, copy=False)
        out_lines.append(out)

    return pack_polylines(out_lines)


__all__ = ["reaction_diffusion"]
