"""閉曲線群を距離場でブレンドし、等値線（輪郭）を生成する effect。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry
from .util import transform_back, transform_to_xy_plane

_AUTO_CLOSE_THRESHOLD_DEFAULT = 1e-3
_PLANAR_EPS_ABS = 1e-6
_PLANAR_EPS_REL = 1e-5

metaball_meta = {
    "radius": ParamMeta(kind="float", ui_min=0.0, ui_max=50.0),
    "threshold": ParamMeta(kind="float", ui_min=0.0, ui_max=5.0),
    "grid_pitch": ParamMeta(kind="float", ui_min=0.1, ui_max=10.0),
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


def _min_dist_sq_to_ring(px: np.ndarray, py: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """点群 (px,py) から閉曲線 ring への最短距離^2 を返す。"""
    dist_sq = np.full(px.shape, np.inf, dtype=np.float64)

    a = ring[:-1]
    b = ring[1:]
    for i in range(int(a.shape[0])):
        ax = float(a[i, 0])
        ay = float(a[i, 1])
        bx = float(b[i, 0])
        by = float(b[i, 1])

        dx = bx - ax
        dy = by - ay
        denom = dx * dx + dy * dy
        if denom == 0.0:
            ds = (px - ax) * (px - ax) + (py - ay) * (py - ay)
            dist_sq = np.minimum(dist_sq, ds)
            continue

        t = ((px - ax) * dx + (py - ay) * dy) / denom
        t = np.clip(t, 0.0, 1.0)
        cx = ax + t * dx
        cy = ay + t * dy
        ds = (px - cx) * (px - cx) + (py - cy) * (py - cy)
        dist_sq = np.minimum(dist_sq, ds)
    return dist_sq


def _point_in_polygon_evenodd(px: np.ndarray, py: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """偶奇規則による inside 判定（境界は False 扱い）。"""
    inside = np.zeros(px.shape, dtype=np.bool_)
    x = px
    y = py

    a = ring[:-1]
    b = ring[1:]
    for i in range(int(a.shape[0])):
        xi = float(a[i, 0])
        yi = float(a[i, 1])
        xj = float(b[i, 0])
        yj = float(b[i, 1])

        # `yi > y` と `yj > y` が異なるときだけ交差判定をする（水平エッジはここで落ちる）。
        y_between = np.logical_xor(yi > y, yj > y)
        denom = yj - yi

        # y_between 以外は参照されないので 0 埋めでよい。
        t = np.divide(y - yi, denom, out=np.zeros_like(y, dtype=np.float64), where=denom != 0.0)
        x_int = xi + t * (xj - xi)
        cross = np.logical_and(y_between, x < x_int)
        inside = np.logical_xor(inside, cross)

    return inside


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


@effect(meta=metaball_meta)
def metaball(
    inputs: Sequence[RealizedGeometry],
    *,
    radius: float = 3.0,
    threshold: float = 1.0,
    grid_pitch: float = 0.5,
    auto_close_threshold: float = _AUTO_CLOSE_THRESHOLD_DEFAULT,
    keep_original: bool = False,
) -> RealizedGeometry:
    """閉曲線群をメタボール的に接続し、輪郭（外周＋穴）を生成する。

    入力 `inputs[0]` の全ポリラインを走査し、閉曲線（端点が近ければ自動クローズ）を
    face として検知して対象にする。開曲線は無視する。

    Parameters
    ----------
    inputs : Sequence[RealizedGeometry]
        入力実体ジオメトリ列。通常は 1 要素。
    radius : float, default 3.0
        接続の届く距離（falloff 半径）[mm]。大きいほど繋がりやすい。
    threshold : float, default 1.0
        等値線レベル。`1.0` 付近が基準（内側項 + 距離場の合成）。
    grid_pitch : float, default 0.5
        距離場を評価する 2D グリッドのピッチ [mm]。
    auto_close_threshold : float, default 1e-3
        端点距離がこの値以下なら閉曲線扱いとして自動で閉じる [mm]。
    keep_original : bool, default False
        True のとき、生成結果に加えて元のポリラインも出力に含める。

    Returns
    -------
    RealizedGeometry
        生成した輪郭（外周＋穴）を含む実体ジオメトリ。
    """
    if not inputs:
        return _empty_geometry()

    base = inputs[0]
    if base.coords.shape[0] == 0:
        return base

    r = float(radius)
    if not np.isfinite(r) or r <= 0.0:
        return base

    level = float(threshold)
    if not np.isfinite(level):
        return base

    pitch = float(grid_pitch)
    if not np.isfinite(pitch) or pitch <= 0.0:
        return base

    auto_close = float(auto_close_threshold)
    if not np.isfinite(auto_close) or auto_close < 0.0:
        auto_close = 0.0

    rep = _pick_representative_ring(base)
    if rep is None:
        return base

    _rep_xy, rot, z_off = transform_to_xy_plane(rep)
    coords_xy_all = _apply_alignment(base.coords, rot, float(z_off))
    if float(np.max(np.abs(coords_xy_all[:, 2]))) > _planarity_threshold(base.coords):
        return base

    rings = _extract_rings_xy(coords_xy_all, base.offsets, auto_close_threshold=auto_close)
    if not rings:
        return base

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
        return base

    xs = x0 + pitch * np.arange(nx, dtype=np.float64)
    ys = y0 + pitch * np.arange(ny, dtype=np.float64)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    px = X.ravel()
    py = Y.ravel()

    inv_r2 = 1.0 / (r * r)
    field = np.zeros(px.shape, dtype=np.float64)
    inside_parity = np.zeros(px.shape, dtype=np.bool_)

    for ring in rings:
        dist_sq = _min_dist_sq_to_ring(px, py, ring.vertices)
        field += np.exp(-dist_sq * inv_r2)
        inside_parity = np.logical_xor(inside_parity, _point_in_polygon_evenodd(px, py, ring.vertices))

    # inside 項（偶奇規則）で「面（外周＋穴）」の基準を与える。
    field += inside_parity.astype(np.float64)
    field2 = field.reshape((ny, nx))

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
        for i in range(int(base.offsets.size) - 1):
            s = int(base.offsets[i])
            e = int(base.offsets[i + 1])
            original = base.coords[s:e]
            if original.shape[0] > 0:
                out_lines.append(original.astype(np.float32, copy=False))

    return _lines_to_realized(out_lines)

