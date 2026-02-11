"""閉曲線群を距離場でブレンドし、等値線（輪郭）を生成する effect。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numba import njit  # type: ignore[import-untyped]

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple
from .util import transform_back, transform_to_xy_plane

_AUTO_CLOSE_THRESHOLD_DEFAULT = 1e-3
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

metaball_meta = {
    "radius": ParamMeta(kind="float", ui_min=0.0, ui_max=50.0),
    "threshold": ParamMeta(kind="float", ui_min=0.0, ui_max=5.0),
    "grid_pitch": ParamMeta(kind="float", ui_min=0.1, ui_max=10.0),
    "auto_close_threshold": ParamMeta(kind="float", ui_min=0.0, ui_max=5.0),
    "output": ParamMeta(kind="choice", choices=("exterior", "both")),
    "keep_original": ParamMeta(kind="bool"),
}


@dataclass(frozen=True, slots=True)
class _Ring2D:
    vertices: np.ndarray  # (N, 2) float64, closed (first == last)
    mins: np.ndarray  # (2,) float64
    maxs: np.ndarray  # (2,) float64


def _empty_geometry() -> GeomTuple:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


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


def _pick_representative_ring(
    coords: np.ndarray, offsets: np.ndarray
) -> np.ndarray | None:
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
            # 3 点（閉じ含む）以下は面を作れない。
            continue

        # 閉曲線のみを face として扱う（開曲線は無視）。
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
    """リング列を Numba 入力用の連結バッファへパックする。"""
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
def _evaluate_field_grid_numba(
    xs: np.ndarray,
    ys: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    ring_mins: np.ndarray,
    ring_maxs: np.ndarray,
    inv_r2: float,
) -> np.ndarray:
    ny = int(ys.shape[0])
    nx = int(xs.shape[0])
    n_rings = int(ring_offsets.shape[0]) - 1

    out = np.zeros((ny, nx), dtype=np.float64)
    for j in range(ny):
        y = float(ys[j])
        for i in range(nx):
            x = float(xs[i])
            val = 0.0
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

                min_ds = 1e300
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

                val += math.exp(-min_ds * inv_r2)
                inside_parity ^= inside

            val += float(inside_parity)
            out[j, i] = val

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


def _marching_squares_segments(
    field: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    level: float,
    snap: float,
    key_to_xy: dict[tuple[int, int], tuple[float, float]],
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """等値線を線分集合として抽出する（Marching Squares）。"""
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

            # 5/10 の曖昧ケースは、中心値で接続を決める（midpoint decider）。
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

            # その他の 4 交点は、隣接順で 2 本にする（トポロジが壊れにくい最小処理）。
            segments.append((p0, p1))  # type: ignore[arg-type]
            segments.append((p2, p3))  # type: ignore[arg-type]

    return segments


def _lines_to_realized(lines: list[np.ndarray]) -> GeomTuple:
    if not lines:
        return _empty_geometry()
    coords = np.concatenate(lines, axis=0).astype(np.float32, copy=False)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    acc = 0
    for i, ln in enumerate(lines):
        acc += int(ln.shape[0])
        offsets[i + 1] = acc
    return coords, offsets


def _pack_loops_xy(loops_xy: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """可変長ループ列を Numba 入力用の連結バッファへパックする。"""
    n = len(loops_xy)
    total = 0
    for pts in loops_xy:
        total += int(pts.shape[0])

    vertices = np.empty((total, 2), dtype=np.float64)
    offsets = np.empty((n + 1,), dtype=np.int32)
    offsets[0] = 0
    cursor = 0
    for i, pts in enumerate(loops_xy):
        v = pts.astype(np.float64, copy=False)
        m = int(v.shape[0])
        vertices[cursor : cursor + m] = v
        cursor += m
        offsets[i + 1] = np.int32(cursor)
    return vertices, offsets


@njit(cache=True)
def _round_ties_to_even(x: float) -> int:
    # `np.rint`（banker's rounding: ties to even）相当。
    f = math.floor(x)
    frac = x - f
    if frac < 0.5:
        return int(f)
    if frac > 0.5:
        return int(f + 1.0)
    # frac == 0.5
    if int(f) % 2 == 0:
        return int(f)
    return int(f + 1.0)


@njit(cache=True)
def _exterior_loop_mask_numba(
    field: np.ndarray,
    x0: float,
    y0: float,
    pitch: float,
    level: float,
    loop_vertices: np.ndarray,
    loop_offsets: np.ndarray,
) -> np.ndarray:
    ny = int(field.shape[0])
    nx = int(field.shape[1])
    n_loops = int(loop_offsets.shape[0]) - 1
    out = np.zeros((n_loops,), dtype=np.uint8)

    if ny <= 0 or nx <= 0:
        return out
    if pitch <= 0.0 or not math.isfinite(pitch):
        return out

    eps = 0.5 * float(pitch)
    for li in range(n_loops):
        s = int(loop_offsets[li])
        e = int(loop_offsets[li + 1])
        if e - s < 4:
            continue

        area2 = 0.0
        for k in range(s, e - 1):
            x1 = float(loop_vertices[k, 0])
            y1 = float(loop_vertices[k, 1])
            x2 = float(loop_vertices[k + 1, 0])
            y2 = float(loop_vertices[k + 1, 1])
            area2 += x1 * y2 - y1 * x2

        if area2 == 0.0 or not math.isfinite(area2):
            continue
        ccw = area2 > 0.0

        k0 = -1
        for k in range(s, e - 1):
            dx = float(loop_vertices[k + 1, 0] - loop_vertices[k, 0])
            dy = float(loop_vertices[k + 1, 1] - loop_vertices[k, 1])
            if dx * dx + dy * dy > 1e-12:
                k0 = k
                break
        if k0 < 0:
            continue

        dx = float(loop_vertices[k0 + 1, 0] - loop_vertices[k0, 0])
        dy = float(loop_vertices[k0 + 1, 1] - loop_vertices[k0, 1])
        if ccw:
            nx_in, ny_in = -dy, dx
        else:
            nx_in, ny_in = dy, -dx
        n_norm = math.sqrt(nx_in * nx_in + ny_in * ny_in)
        if n_norm <= 0.0 or not math.isfinite(n_norm):
            continue
        nx_in /= n_norm
        ny_in /= n_norm

        xin = float(loop_vertices[k0, 0]) + float(nx_in) * eps
        yin = float(loop_vertices[k0, 1]) + float(ny_in) * eps
        ii = _round_ties_to_even((xin - float(x0)) / float(pitch))
        jj = _round_ties_to_even((yin - float(y0)) / float(pitch))

        if ii < 0:
            ii = 0
        elif ii >= nx:
            ii = nx - 1
        if jj < 0:
            jj = 0
        elif jj >= ny:
            jj = ny - 1

        if float(field[jj, ii]) >= float(level):
            out[li] = 1

    return out


def _filter_exterior_loops(
    loops_xy: list[np.ndarray],
    *,
    field: np.ndarray,
    x0: float,
    y0: float,
    pitch: float,
    level: float,
) -> list[np.ndarray]:
    """等値線ループ列から外周（exterior）のみ抽出する。"""
    if not loops_xy:
        return []

    loop_vertices, loop_offsets = _pack_loops_xy(loops_xy)
    mask_u8 = _exterior_loop_mask_numba(
        field.astype(np.float64, copy=False),
        float(x0),
        float(y0),
        float(pitch),
        float(level),
        loop_vertices,
        loop_offsets,
    )
    return [pts for i, pts in enumerate(loops_xy) if bool(mask_u8[int(i)])]


@effect(meta=metaball_meta)
def metaball(
    g: GeomTuple,
    *,
    radius: float = 3.0,
    threshold: float = 1.0,
    grid_pitch: float = 0.5,
    auto_close_threshold: float = _AUTO_CLOSE_THRESHOLD_DEFAULT,
    output: str = "both",  # "exterior" | "both"
    keep_original: bool = False,
) -> GeomTuple:
    """閉曲線群をメタボール的に接続し、輪郭（外周＋穴）を生成する。

    入力 `inputs[0]` の全ポリラインを走査し、閉曲線（端点が近ければ自動クローズ）を
    face として検知して対象にする。開曲線は無視する。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    radius : float, default 3.0
        接続の届く距離（falloff 半径）[mm]。大きいほど繋がりやすい。
    threshold : float, default 1.0
        等値線レベル。`1.0` 付近が基準（内側項 + 距離場の合成）。
    grid_pitch : float, default 0.5
        距離場を評価する 2D グリッドのピッチ [mm]。
    auto_close_threshold : float, default 1e-3
        端点距離がこの値以下なら閉曲線扱いとして自動で閉じる [mm]。
    output : str, default "both"
        出力輪郭の選択。

        - `"both"`: 外周＋穴（holes）を出力
        - `"exterior"`: 外周のみ出力
    keep_original : bool, default False
        True のとき、生成結果に加えて元のポリラインも出力に含める。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        生成した輪郭（外周＋穴）を含む実体ジオメトリ（coords, offsets）。
    """
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    r = float(radius)
    if not np.isfinite(r) or r <= 0.0:
        return coords, offsets

    level = float(threshold)
    if not np.isfinite(level):
        return coords, offsets

    pitch = float(grid_pitch)
    if not np.isfinite(pitch) or pitch <= 0.0:
        return coords, offsets

    output_s = str(output)
    if output_s not in {"exterior", "both"}:
        return coords, offsets

    auto_close = float(auto_close_threshold)
    if not np.isfinite(auto_close) or auto_close < 0.0:
        auto_close = 0.0

    rep = _pick_representative_ring(coords, offsets)
    if rep is None:
        return coords, offsets

    _rep_xy, rot, z_off = transform_to_xy_plane(rep)
    coords_xy_all = _apply_alignment(coords, rot, float(z_off))
    if float(np.max(np.abs(coords_xy_all[:, 2]))) > _planarity_threshold(coords):
        return coords, offsets

    rings = _extract_rings_xy(coords_xy_all, offsets, auto_close_threshold=auto_close)
    if not rings:
        return coords, offsets

    mins = np.min(np.stack([r0.mins for r0 in rings], axis=0), axis=0)
    maxs = np.max(np.stack([r0.maxs for r0 in rings], axis=0), axis=0)

    margin = 2.0 * r + 2.0 * pitch
    x0 = float(mins[0] - margin)
    x1 = float(maxs[0] + margin)
    y0 = float(mins[1] - margin)
    y1 = float(maxs[1] + margin)

    span_x = max(0.0, x1 - x0)
    span_y = max(0.0, y1 - y0)
    nx = int(np.ceil(span_x / pitch)) + 1
    ny = int(np.ceil(span_y / pitch)) + 1
    if nx < 2 or ny < 2:
        return coords, offsets

    xs = x0 + pitch * np.arange(nx, dtype=np.float64)
    ys = y0 + pitch * np.arange(ny, dtype=np.float64)

    ring_vertices, ring_offsets, ring_mins, ring_maxs = _pack_rings(rings)
    inv_r2 = 1.0 / (r * r)
    field2 = _evaluate_field_grid_numba(
        xs.astype(np.float64, copy=False),
        ys.astype(np.float64, copy=False),
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
        float(inv_r2),
    )

    snap = max(1e-9, pitch * 1e-6)
    key_to_xy: dict[tuple[int, int], tuple[float, float]] = {}
    segments = _marching_squares_segments(
        field2,
        xs,
        ys,
        level=level,
        snap=snap,
        key_to_xy=key_to_xy,
    )
    loops = _stitch_segments_to_loops(segments)

    loops_xy: list[np.ndarray] = []
    for loop in loops:
        pts_xy = np.asarray([key_to_xy[k] for k in loop], dtype=np.float64)
        if pts_xy.shape[0] >= 4:
            loops_xy.append(pts_xy)

    if output_s == "exterior":
        loops_xy = _filter_exterior_loops(
            loops_xy,
            field=field2,
            x0=float(xs[0]),
            y0=float(ys[0]),
            pitch=float(pitch),
            level=float(level),
        )

    out_lines: list[np.ndarray] = []
    for pts_xy in loops_xy:
        v3 = np.zeros((pts_xy.shape[0], 3), dtype=np.float64)
        v3[:, 0:2] = pts_xy
        out = transform_back(v3, rot, float(z_off)).astype(np.float32, copy=False)
        out_lines.append(out)

    if bool(keep_original):
        for i in range(int(offsets.size) - 1):
            s = int(offsets[i])
            e = int(offsets[i + 1])
            original = coords[s:e]
            if original.shape[0] > 0:
                out_lines.append(original.astype(np.float32, copy=False))

    return _lines_to_realized(out_lines)
