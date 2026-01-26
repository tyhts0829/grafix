from __future__ import annotations

from pathlib import Path

import numpy as np
from numba import njit

from grafix import E, G, P, run
from grafix.api import primitive
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import RealizedGeometry

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


# --- Field cache (disabled) -------------------------------------------------
# To re-enable:
# - Uncomment `_FIELD_CACHE` and `_gray_scott_field_cached()`
# - Replace `_gray_scott_field(...)` with `_gray_scott_field_cached(...)` in `gray_scott_lines`.
#
_FIELD_CACHE: dict[tuple[object, ...], np.ndarray] = {}


@njit
def _gray_scott_simulate(
    u: np.ndarray,
    v: np.ndarray,
    *,
    steps: int,
    du: float,
    dv: float,
    feed: float,
    kill: float,
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Gray-Scott を周期境界で時間発展させる（Numba 最適化）。"""
    ny, nx = u.shape
    u_next = np.empty_like(u)
    v_next = np.empty_like(v)

    w_edge = 0.2
    w_corner = 0.05
    one = 1.0
    fk = feed + kill

    for _ in range(int(steps)):
        for j in range(ny):
            jn = j - 1 if j > 0 else ny - 1
            js = j + 1 if j < ny - 1 else 0
            for i in range(nx):
                iw = i - 1 if i > 0 else nx - 1
                ie = i + 1 if i < nx - 1 else 0

                u_c = u[j, i]
                v_c = v[j, i]

                lap_u = -u_c
                lap_u += w_edge * (u[jn, i] + u[js, i] + u[j, ie] + u[j, iw])
                lap_u += w_corner * (u[jn, ie] + u[jn, iw] + u[js, ie] + u[js, iw])

                lap_v = -v_c
                lap_v += w_edge * (v[jn, i] + v[js, i] + v[j, ie] + v[j, iw])
                lap_v += w_corner * (v[jn, ie] + v[jn, iw] + v[js, ie] + v[js, iw])

                uvv = u_c * v_c * v_c
                u_val = u_c + (du * lap_u - uvv + feed * (one - u_c)) * dt
                v_val = v_c + (dv * lap_v + uvv - fk * v_c) * dt

                if u_val < 0.0:
                    u_val = 0.0
                elif u_val > 1.0:
                    u_val = 1.0

                if v_val < 0.0:
                    v_val = 0.0
                elif v_val > 1.0:
                    v_val = 1.0

                u_next[j, i] = u_val
                v_next[j, i] = v_val

        u, u_next = u_next, u
        v, v_next = v_next, v

    return u, v


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _gray_scott_field(
    *,
    nx: int,
    ny: int,
    steps: int,
    du: float,
    dv: float,
    feed: float,
    kill: float,
    dt: float,
    seed: int,
) -> np.ndarray:
    """Gray-Scott 反応拡散の V 場を返す（2D スカラー場）。

    Notes
    -----
    - 周期境界（wrap）で計算する。
    - 2D 配列は行=Y, 列=X（shape=(ny,nx)）。
    """
    rng = np.random.default_rng(int(seed))
    u = np.ones((int(ny), int(nx)), dtype=np.float32)
    v = np.zeros((int(ny), int(nx)), dtype=np.float32)

    rx = max(4, int(nx) // 10)
    ry = max(4, int(ny) // 10)
    cx = int(nx) // 2
    cy = int(ny) // 2
    x0 = max(0, cx - rx // 2)
    x1 = min(int(nx), cx + rx // 2)
    y0 = max(0, cy - ry // 2)
    y1 = min(int(ny), cy + ry // 2)

    u[y0:y1, x0:x1] = 0.50
    v[y0:y1, x0:x1] = 0.25
    v += (rng.random(v.shape).astype(np.float32) - 0.5) * 0.02
    u += (rng.random(u.shape).astype(np.float32) - 0.5) * 0.02
    np.clip(u, 0.0, 1.0, out=u)
    np.clip(v, 0.0, 1.0, out=v)

    du_f = float(du)
    dv_f = float(dv)
    f_f = float(feed)
    k_f = float(kill)
    dt_f = float(dt)

    u, v = _gray_scott_simulate(
        u,
        v,
        steps=int(steps),
        du=du_f,
        dv=dv_f,
        feed=f_f,
        kill=k_f,
        dt=dt_f,
    )
    return v


def _gray_scott_field_cached(
    *,
    nx: int,
    ny: int,
    steps: int,
    du: float,
    dv: float,
    feed: float,
    kill: float,
    dt: float,
    seed: int,
) -> np.ndarray:
    key = (
        int(nx),
        int(ny),
        int(steps),
        float(du),
        float(dv),
        float(feed),
        float(kill),
        float(dt),
        int(seed),
    )
    cached = _FIELD_CACHE.get(key)
    if cached is not None:
        return cached
    field = _gray_scott_field(
        nx=int(nx),
        ny=int(ny),
        steps=int(steps),
        du=float(du),
        dv=float(dv),
        feed=float(feed),
        kill=float(kill),
        dt=float(dt),
        seed=int(seed),
    )
    _FIELD_CACHE[key] = field
    return field


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


def _quant_key(x: float, y: float, snap: float) -> tuple[int, int]:
    s = float(snap)
    return (int(round(float(x) / s)), int(round(float(y) / s)))


def _edge_key(
    a: tuple[int, int], b: tuple[int, int]
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (a, b) if a <= b else (b, a)


def _stitch_segments_to_paths(
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in segments:
        if a == b:
            continue
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[list[tuple[int, int]]] = []

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

            if len(path) >= 2:
                paths.append(path)

    return paths


def _marching_squares_lines(
    field: np.ndarray,
    *,
    x0: float,
    y0: float,
    w: float,
    h: float,
    level: float,
    z: float,
    min_points: int,
) -> RealizedGeometry:
    ny, nx = int(field.shape[0]), int(field.shape[1])
    if nx < 2 or ny < 2:
        return _empty_geometry()

    dx = float(w) / float(nx - 1)
    dy = float(h) / float(ny - 1)
    xs = x0 + dx * np.arange(nx, dtype=np.float64)
    ys = y0 + dy * (np.arange(ny, dtype=np.float64)[::-1])

    def _interp(a: float, b: float, t_level: float) -> float:
        denom = b - a
        if denom == 0.0:
            return 0.5
        return (t_level - a) / denom

    snap = max(1e-9, min(dx, dy) * 1e-3)
    key_to_xy: dict[tuple[int, int], tuple[float, float]] = {}
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = []

    for j in range(ny - 1):
        y_top = float(ys[j])
        y_bot = float(ys[j + 1])
        for i in range(nx - 1):
            x_left = float(xs[i])
            x_right = float(xs[i + 1])

            v00 = float(field[j, i])
            v10 = float(field[j, i + 1])
            v11 = float(field[j + 1, i + 1])
            v01 = float(field[j + 1, i])

            b0 = v00 >= level
            b1 = v10 >= level
            b2 = v11 >= level
            b3 = v01 >= level
            idx = (
                (1 if b0 else 0)
                | (2 if b1 else 0)
                | (4 if b2 else 0)
                | (8 if b3 else 0)
            )
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
                x = x_left + float(np.clip(t, 0.0, 1.0)) * (x_right - x_left)
                y = y_top
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p0 = k
            if e1:
                t = _interp(v10, v11, level)
                x = x_right
                y = y_top + float(np.clip(t, 0.0, 1.0)) * (y_bot - y_top)
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p1 = k
            if e2:
                t = _interp(v01, v11, level)
                x = x_left + float(np.clip(t, 0.0, 1.0)) * (x_right - x_left)
                y = y_bot
                k = _quant_key(x, y, snap)
                key_to_xy.setdefault(k, (x, y))
                p2 = k
            if e3:
                t = _interp(v00, v01, level)
                x = x_left
                y = y_top + float(np.clip(t, 0.0, 1.0)) * (y_bot - y_top)
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

    paths = _stitch_segments_to_paths(segments)
    lines: list[np.ndarray] = []
    for path in paths:
        if len(path) < int(min_points):
            continue
        pts_xy = np.asarray([key_to_xy[k] for k in path], dtype=np.float32)
        ln = np.zeros((pts_xy.shape[0], 3), dtype=np.float32)
        ln[:, 0:2] = pts_xy
        ln[:, 2] = float(z)
        lines.append(ln)

    return _lines_to_realized(lines)


def _zhang_suen_thinning(binary: np.ndarray, *, max_iters: int) -> np.ndarray:
    """2 値画像を Zhang-Suen 法で細線化する。"""
    img = np.asarray(binary, dtype=bool).copy()
    for _ in range(int(max_iters)):
        changed = False
        for step in (0, 1):
            pad = np.pad(img, ((1, 1), (1, 1)), mode="constant", constant_values=False)
            p1 = pad[1:-1, 1:-1]
            p2 = pad[0:-2, 1:-1]
            p3 = pad[0:-2, 2:]
            p4 = pad[1:-1, 2:]
            p5 = pad[2:, 2:]
            p6 = pad[2:, 1:-1]
            p7 = pad[2:, 0:-2]
            p8 = pad[1:-1, 0:-2]
            p9 = pad[0:-2, 0:-2]

            n = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            s = (
                ((~p2) & p3)
                + ((~p3) & p4)
                + ((~p4) & p5)
                + ((~p5) & p6)
                + ((~p6) & p7)
                + ((~p7) & p8)
                + ((~p8) & p9)
                + ((~p9) & p2)
            )

            if step == 0:
                m = (~(p2 & p4 & p6)) & (~(p4 & p6 & p8))
            else:
                m = (~(p2 & p4 & p8)) & (~(p2 & p6 & p8))

            remove = p1 & (n >= 2) & (n <= 6) & (s == 1) & m
            if np.any(remove):
                img[remove] = False
                changed = True

        if not changed:
            break
    return img


def _compress_grid_path(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(path) < 3:
        return path
    out = [path[0]]
    prev = path[0]
    cur = path[1]
    prev_dx = cur[0] - prev[0]
    prev_dy = cur[1] - prev[1]
    out.append(cur)
    for nxt in path[2:]:
        dx = nxt[0] - cur[0]
        dy = nxt[1] - cur[1]
        if (dx, dy) != (prev_dx, prev_dy):
            out.append(cur)
        prev_dx, prev_dy = dx, dy
        prev, cur = cur, nxt
    out.append(path[-1])
    dedup: list[tuple[int, int]] = []
    for p in out:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    return dedup


def _skeleton_to_lines(
    skeleton: np.ndarray,
    *,
    x0: float,
    y0: float,
    w: float,
    h: float,
    z: float,
    min_points: int,
) -> RealizedGeometry:
    sk = np.asarray(skeleton, dtype=bool)
    ny, nx = int(sk.shape[0]), int(sk.shape[1])
    if nx < 2 or ny < 2:
        return _empty_geometry()

    points = np.argwhere(sk)
    if points.size == 0:
        return _empty_geometry()

    pts_set = {tuple(p) for p in points.tolist()}  # (j,i)
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for j, i in pts_set:
        neighs: list[tuple[int, int]] = []
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                if dj == 0 and di == 0:
                    continue
                q = (j + dj, i + di)
                if q in pts_set:
                    neighs.append(q)
        adj[(j, i)] = neighs

    def _edge(
        a: tuple[int, int], b: tuple[int, int]
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    endpoints = [p for p, ns in adj.items() if len(ns) == 1]

    paths: list[list[tuple[int, int]]] = []

    def _trace(start: tuple[int, int], nxt: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, nxt]
        visited_edges.add(_edge(start, nxt))
        prev = start
        cur = nxt
        while True:
            cand = [
                nn
                for nn in adj.get(cur, [])
                if nn != prev and _edge(cur, nn) not in visited_edges
            ]
            if not cand:
                break
            nn = cand[0]
            visited_edges.add(_edge(cur, nn))
            path.append(nn)
            prev, cur = cur, nn
        return path

    for p in endpoints:
        for n in adj[p]:
            if _edge(p, n) in visited_edges:
                continue
            paths.append(_trace(p, n))

    for p, ns in adj.items():
        for n in ns:
            if _edge(p, n) in visited_edges:
                continue
            paths.append(_trace(p, n))

    dx = float(w) / float(nx)
    dy = float(h) / float(ny)

    lines: list[np.ndarray] = []
    for path in paths:
        path = _compress_grid_path(path)
        if len(path) < int(min_points):
            continue
        pts = np.zeros((len(path), 3), dtype=np.float32)
        for k, (j, i) in enumerate(path):
            x = x0 + (float(i) + 0.5) * dx
            y = y0 + (float(ny - 1 - j) + 0.5) * dy
            pts[k, 0] = float(x)
            pts[k, 1] = float(y)
            pts[k, 2] = float(z)
        lines.append(pts)

    return _lines_to_realized(lines)


gray_scott_lines_meta = {
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=220.0),
    "size_w": ParamMeta(kind="float", ui_min=10.0, ui_max=140.0),
    "size_h": ParamMeta(kind="float", ui_min=10.0, ui_max=180.0),
    "nx": ParamMeta(kind="int", ui_min=40, ui_max=400),
    "ny": ParamMeta(kind="int", ui_min=40, ui_max=400),
    "steps": ParamMeta(kind="int", ui_min=0, ui_max=10000),
    "du": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "dv": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "feed": ParamMeta(kind="float", ui_min=0.0, ui_max=0.1),
    "kill": ParamMeta(kind="float", ui_min=0.0, ui_max=0.1),
    "dt": ParamMeta(kind="float", ui_min=0.1, ui_max=2.0),
    "seed": ParamMeta(kind="int", ui_min=0, ui_max=9999),
    "mode": ParamMeta(kind="choice", choices=("contour", "skeleton")),
    "level": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "thinning_iters": ParamMeta(kind="int", ui_min=1, ui_max=200),
    "min_points": ParamMeta(kind="int", ui_min=2, ui_max=200),
}

gray_scott_lines_ui_visible = {
    "thinning_iters": lambda v: str(v.get("mode", "")) == "skeleton",
}


@primitive(meta=gray_scott_lines_meta, ui_visible=gray_scott_lines_ui_visible)
def gray_scott_lines(
    *,
    center: tuple[float, float, float] = (74.0, 100.0, 0.0),
    size_w: float = 120.0,
    size_h: float = 80.0,
    nx: int = 220,
    ny: int = 160,
    steps: int = 4500,
    du: float = 0.16,
    dv: float = 0.08,
    feed: float = 0.035,
    kill: float = 0.062,
    dt: float = 1.0,
    seed: int = 0,
    mode: str = "contour",  # "contour" | "skeleton"
    level: float = 0.2,
    thinning_iters: int = 40,
    min_points: int = 16,
) -> RealizedGeometry:
    """Gray-Scott 反応拡散から「線（ポリライン列）」を生成する。

    - mode="contour": V の等値線（Marching Squares）
    - mode="skeleton": V を 2 値化→細線化（Zhang-Suen）→中心線トレース
    """
    cx, cy, cz = center
    w = float(size_w)
    h = float(size_h)
    x0 = float(cx) - 0.5 * float(w)
    y0 = float(cy) - 0.5 * float(h)

    field_v = _gray_scott_field_cached(
        nx=int(nx),
        ny=int(ny),
        steps=int(steps),
        du=float(du),
        dv=float(dv),
        feed=float(feed),
        kill=float(kill),
        dt=float(dt),
        seed=int(seed),
    )

    if str(mode) == "contour":
        geom = _marching_squares_lines(
            field_v,
            x0=float(x0),
            y0=float(y0),
            w=float(w),
            h=float(h),
            level=float(level),
            z=float(cz),
            min_points=int(min_points),
        )
    elif str(mode) == "skeleton":
        binary = field_v >= float(level)
        sk = _zhang_suen_thinning(binary, max_iters=int(thinning_iters))
        geom = _skeleton_to_lines(
            sk,
            x0=float(x0),
            y0=float(y0),
            w=float(w),
            h=float(h),
            z=float(cz),
            min_points=int(min_points),
        )
    else:
        geom = _empty_geometry()
    return geom


def draw(t):
    maze = G.gray_scott_lines(
        activate=True,
        center=(74.0, 121.0, 0.0),
        size_w=120.0,
        size_h=74.0,
        nx=220,
        ny=160,
        steps=4500,
        du=0.16,
        dv=0.08,
        feed=0.029,
        kill=0.057,
        dt=1.0,
        seed=42,
        mode="contour",
        level=0.20,
        thinning_iters=40,
        min_points=24,
    )

    e = E.fill()
    maze = e(maze)

    frame = P.grn_a5_frame(
        activate=True,
        show_layout=False,
        layout_color_rgb255=(191, 191, 191),
        number_text=str(Path(__file__).stem),
        explanation_text="Gray-Scott reaction diffusion\\ncontour + thinning",
        explanation_density=500.0,
        template_color_rgb255=(0, 0, 0),
    )

    return maze, frame


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
