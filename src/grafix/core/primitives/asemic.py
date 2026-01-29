"""
どこで: `src/grafix/core/primitives/asemic.py`。擬似文字（asemic）プリミティブの実体生成。
何を: ノード配置 → Relative Neighborhood Graph → ランダムウォークで、複数ストロークのポリライン列を生成する。
なぜ: 手描きっぽい「字形の骨格」を、決定的かつ軽量に生成できる primitive として提供するため。
"""

from __future__ import annotations

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import RealizedGeometry

asemic_meta = {
    "seed": ParamMeta(kind="int", ui_min=0, ui_max=999999),
    "n_nodes": ParamMeta(kind="int", ui_min=3, ui_max=200),
    "candidates": ParamMeta(kind="int", ui_min=1, ui_max=50),
    "stroke_min": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "stroke_max": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "walk_min_steps": ParamMeta(kind="int", ui_min=1, ui_max=20),
    "walk_max_steps": ParamMeta(kind="int", ui_min=1, ui_max=20),
    "stroke_style": ParamMeta(kind="choice", choices=("line", "bezier")),
    "bezier_samples": ParamMeta(kind="int", ui_min=2, ui_max=64),
    "bezier_tension": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=300.0),
    "scale": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
}


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _best_candidate_points(
    rng: np.random.Generator,
    *,
    n: int,
    candidates: int,
) -> np.ndarray:
    """Mitchell 風 best-candidate で点をそこそこ均一にばら撒く。"""
    if n <= 0:
        return np.zeros((0, 2), dtype=np.float64)

    k = int(candidates)
    if k <= 0:
        k = 1

    pts = np.empty((n, 2), dtype=np.float64)
    pts[0] = rng.uniform(-0.5, 0.5, size=(2,))

    for i in range(1, n):
        cand = rng.uniform(-0.5, 0.5, size=(k, 2))
        diff = cand[:, None, :] - pts[None, :i, :]
        dist2 = (diff * diff).sum(axis=2)
        min_dist2 = dist2.min(axis=1)
        best = int(np.argmax(min_dist2))
        pts[i] = cand[best]

    return pts


def _build_rng_adjacency(points: np.ndarray) -> list[set[int]]:
    """Relative Neighborhood Graph (RNG) を構築し、隣接集合を返す。"""
    n = int(points.shape[0])
    if n <= 0:
        return []

    diff = points[:, None, :] - points[None, :, :]
    dist2 = (diff * diff).sum(axis=2)

    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            dij = float(dist2[i, j])
            if not np.isfinite(dij) or dij <= 0.0:
                continue
            mask = (dist2[i] < dij) & (dist2[j] < dij)
            mask[i] = False
            mask[j] = False
            if mask.any():
                continue
            adj[i].add(j)
            adj[j].add(i)

    return adj


def _random_walk_strokes(
    rng: np.random.Generator,
    *,
    adjacency: list[set[int]],
    stroke_min: int,
    stroke_max: int,
    walk_min_steps: int,
    walk_max_steps: int,
) -> list[list[int]]:
    n = len(adjacency)
    if n <= 0:
        return []

    s_min = int(stroke_min)
    s_max = int(stroke_max)
    if s_min < 0:
        s_min = 0
    if s_max < 0:
        s_max = 0
    if s_min > s_max:
        s_min, s_max = s_max, s_min

    w_min = int(walk_min_steps)
    w_max = int(walk_max_steps)
    if w_min < 1:
        w_min = 1
    if w_max < 1:
        w_max = 1
    if w_min > w_max:
        w_min, w_max = w_max, w_min

    n_strokes = int(rng.integers(s_min, s_max + 1)) if s_max > 0 else int(s_min)
    if n_strokes <= 0:
        return []

    strokes: list[list[int]] = []

    for _ in range(n_strokes):
        starts = [i for i, nb in enumerate(adjacency) if nb]
        if not starts:
            break
        current = int(rng.choice(starts))
        steps = int(rng.integers(w_min, w_max + 1))

        path: list[int] = [current]
        for _step in range(steps):
            neighbors = list(adjacency[current])
            if not neighbors:
                break
            nxt = int(rng.choice(neighbors))
            adjacency[current].remove(nxt)
            adjacency[nxt].remove(current)
            current = nxt
            path.append(current)

        if len(path) >= 2:
            strokes.append(path)

    return strokes


def _sample_bezier(points: np.ndarray, *, samples_per_segment: int, tension: float) -> np.ndarray:
    """折れ線を Catmull-Rom 風の合成 Bézier としてサンプル点列化する。"""
    n = int(points.shape[0])
    if n < 2:
        return points

    samples = int(samples_per_segment)
    if samples < 2:
        samples = 2

    t = float(tension)
    if t < 0.0:
        t = 0.0
    if t > 1.0:
        t = 1.0

    m = np.zeros((n, 2), dtype=np.float64)
    if n == 2:
        m[0] = points[1] - points[0]
        m[1] = points[1] - points[0]
    else:
        m[0] = points[1] - points[0]
        m[-1] = points[-1] - points[-2]
        m[1:-1] = 0.5 * (points[2:] - points[:-2])

    # tension=1 で直線化、tension=0 で通常の Catmull-Rom。
    m *= 1.0 - t

    segs: list[np.ndarray] = []
    for i in range(n - 1):
        p0 = points[i]
        p1 = points[i + 1]
        c1 = p0 + m[i] / 3.0
        c2 = p1 - m[i + 1] / 3.0

        ts = np.linspace(0.0, 1.0, num=samples, dtype=np.float64)
        if i > 0:
            ts = ts[1:]
        u = 1.0 - ts
        curve = (
            (u**3)[:, None] * p0
            + (3.0 * (u**2) * ts)[:, None] * c1
            + (3.0 * u * (ts**2))[:, None] * c2
            + (ts**3)[:, None] * p1
        )
        segs.append(curve)

    return np.concatenate(segs, axis=0) if segs else points


@primitive(meta=asemic_meta)
def asemic(
    *,
    seed: int = 0,
    n_nodes: int = 28,
    candidates: int = 12,
    stroke_min: int = 2,
    stroke_max: int = 5,
    walk_min_steps: int = 2,
    walk_max_steps: int = 4,
    stroke_style: str = "bezier",
    bezier_samples: int = 12,
    bezier_tension: float = 0.5,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> RealizedGeometry:
    """擬似文字（asemic）のストローク群を生成する。

    正方領域にノードを均一寄りに配置し、Relative Neighborhood Graph (RNG) 上で
    短いランダムウォークを行って 2〜5 本程度のストローク（ポリライン列）を作る。
    ストロークは合成 Bézier としてサンプル点列化できる（primitive 内で完結）。

    Parameters
    ----------
    seed : int, default 0
        乱数 seed（同一 seed/params で決定的に同じ出力）。
    n_nodes : int, default 28
        ノード数（少なすぎるとストロークが生成できないことがある）。
    candidates : int, default 12
        best-candidate の候補数（大きいほど均一になりやすい）。
    stroke_min : int, default 2
        ストローク本数の最小値。
    stroke_max : int, default 5
        ストローク本数の最大値。
    walk_min_steps : int, default 2
        ランダムウォークの最小ステップ数。
    walk_max_steps : int, default 4
        ランダムウォークの最大ステップ数。
    stroke_style : {"line", "bezier"}, default "bezier"
        ストロークの描画スタイル。
        `"bezier"` は折れ線を合成 Bézier としてサンプル点列化して滑らかにする。
    bezier_samples : int, default 12
        `"bezier"` 時の 1 セグメントあたりのサンプル点数（2 以上）。
    bezier_tension : float, default 0.5
        `"bezier"` 時の張り（0=曲がりやすい, 1=直線寄り）。
    center : tuple[float, float, float], default (0,0,0)
        平行移動ベクトル (cx, cy, cz)。
    scale : float, default 1.0
        等方スケール倍率。内部の正規化領域 `[-0.5,0.5]^2` を拡大する。

    Returns
    -------
    RealizedGeometry
        ストロークごとのポリライン列。
    """
    nodes = int(n_nodes)
    if nodes < 2:
        return _empty_geometry()

    try:
        cx, cy, cz = center
    except Exception as exc:
        raise ValueError(
            "asemic の center は長さ 3 のシーケンスである必要がある"
        ) from exc
    try:
        s_f = float(scale)
    except Exception as exc:
        raise ValueError("asemic の scale は float である必要がある") from exc

    rng = np.random.default_rng(int(seed))

    pts = _best_candidate_points(rng, n=nodes, candidates=int(candidates))
    adjacency = _build_rng_adjacency(pts)
    strokes = _random_walk_strokes(
        rng,
        adjacency=adjacency,
        stroke_min=int(stroke_min),
        stroke_max=int(stroke_max),
        walk_min_steps=int(walk_min_steps),
        walk_max_steps=int(walk_max_steps),
    )
    if not strokes:
        return _empty_geometry()

    style = str(stroke_style)
    sampled: list[np.ndarray] = []
    for path in strokes:
        poly = pts[np.asarray(path, dtype=np.int64)]
        if style == "bezier":
            poly = _sample_bezier(
                poly,
                samples_per_segment=int(bezier_samples),
                tension=float(bezier_tension),
            )
        sampled.append(poly.astype(np.float32, copy=False))

    total = int(sum(int(p.shape[0]) for p in sampled))
    if total <= 0:
        return _empty_geometry()

    coords = np.zeros((total, 3), dtype=np.float32)
    offsets = np.zeros((len(sampled) + 1,), dtype=np.int32)

    acc = 0
    for i, poly in enumerate(sampled):
        n = int(poly.shape[0])
        coords[acc : acc + n, 0:2] = poly
        acc += n
        offsets[i + 1] = acc

    center_vec = np.array([float(cx), float(cy), float(cz)], dtype=np.float32)
    coords = coords * np.float32(s_f) + center_vec

    return RealizedGeometry(coords=coords, offsets=offsets)


__all__ = ["asemic", "asemic_meta"]

