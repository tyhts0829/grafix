"""
どこで: `src/grafix/core/primitives/asemic.py`。擬似文字（asemic）プリミティブの実体生成。
何を:
- ノード配置 → Relative Neighborhood Graph → ランダムウォークで、文字ごとの複数ストロークを生成する
- `text.py` 風の改行/折り返し/揃え/スペーシングでレイアウトし、文章として出力する
なぜ: 手描きっぽい「字形の骨格」を、決定的かつ軽量に生成し、文章として使える primitive にするため。
"""

from __future__ import annotations

import hashlib

import numpy as np

from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import RealizedGeometry

asemic_meta = {
    "text": ParamMeta(kind="str"),
    "seed": ParamMeta(kind="int", ui_min=0, ui_max=999999),
    # --- glyph params（全文共通）---
    "n_nodes": ParamMeta(kind="int", ui_min=3, ui_max=200),
    "candidates": ParamMeta(kind="int", ui_min=1, ui_max=50),
    "stroke_min": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "stroke_max": ParamMeta(kind="int", ui_min=0, ui_max=20),
    "walk_min_steps": ParamMeta(kind="int", ui_min=1, ui_max=20),
    "walk_max_steps": ParamMeta(kind="int", ui_min=1, ui_max=20),
    "stroke_style": ParamMeta(kind="choice", choices=("line", "bezier")),
    "bezier_samples": ParamMeta(kind="int", ui_min=2, ui_max=64),
    "bezier_tension": ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    # --- layout params ---
    "text_align": ParamMeta(kind="choice", choices=("left", "center", "right")),
    "glyph_advance_em": ParamMeta(kind="float", ui_min=0.0, ui_max=3.0),
    "space_advance_em": ParamMeta(kind="float", ui_min=0.0, ui_max=3.0),
    "letter_spacing_em": ParamMeta(kind="float", ui_min=0.0, ui_max=2.0),
    "line_height": ParamMeta(kind="float", ui_min=0.8, ui_max=3.0),
    "use_bounding_box": ParamMeta(kind="bool"),
    "box_width": ParamMeta(kind="float", ui_min=0.0, ui_max=300.0),
    "box_height": ParamMeta(kind="float", ui_min=0.0, ui_max=300.0),
    "show_bounding_box": ParamMeta(kind="bool"),
    # --- placement ---
    "center": ParamMeta(kind="vec3", ui_min=0.0, ui_max=300.0),
    "scale": ParamMeta(kind="float", ui_min=0.0, ui_max=200.0),
}

ASEMIC_UI_VISIBLE = {
    "bezier_samples": lambda v: str(v.get("stroke_style", "bezier")) == "bezier",
    "bezier_tension": lambda v: str(v.get("stroke_style", "bezier")) == "bezier",
    "box_width": lambda v: bool(v.get("use_bounding_box")),
    "box_height": lambda v: bool(v.get("use_bounding_box")),
    "show_bounding_box": lambda v: bool(v.get("use_bounding_box")),
}


def _empty_geometry() -> RealizedGeometry:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _stable_hash64(text: str) -> int:
    """Python の `hash()` に依存しない安定ハッシュ（64-bit）を返す。"""
    h = hashlib.blake2b(text.encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), byteorder="big", signed=False)


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


def _polylines_to_realized(
    polylines: list[np.ndarray],
    *,
    center: tuple[float, float, float],
    scale: float,
) -> RealizedGeometry:
    filtered = [
        p.astype(np.float32, copy=False) for p in polylines if int(p.shape[0]) >= 2
    ]
    if not filtered:
        return _empty_geometry()

    coords = np.concatenate(filtered, axis=0).astype(np.float32, copy=False)

    offsets = np.zeros(len(filtered) + 1, dtype=np.int32)
    acc = 0
    for i, line in enumerate(filtered):
        acc += int(line.shape[0])
        offsets[i + 1] = acc

    cx, cy, cz = center
    s_f = float(scale)
    cx_f, cy_f, cz_f = float(cx), float(cy), float(cz)
    if (cx_f, cy_f, cz_f) != (0.0, 0.0, 0.0) or s_f != 1.0:
        center_vec = np.array([cx_f, cy_f, cz_f], dtype=np.float32)
        coords = coords * np.float32(s_f) + center_vec

    return RealizedGeometry(coords=coords, offsets=offsets)


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


def _char_advance_em(
    char: str,
    *,
    glyph_advance_em: float,
    space_advance_em: float,
) -> float:
    if char == " ":
        return float(space_advance_em)
    return float(glyph_advance_em)


def _wrap_line_by_width_em(
    line_str: str,
    *,
    max_width_em: float,
    glyph_advance_em: float,
    space_advance_em: float,
    letter_spacing_em: float,
) -> list[str]:
    """1 行分の文字列を指定幅（em）で折り返して返す（text.py と同等の方針）。"""
    if max_width_em <= 0.0:
        return [line_str]
    if not line_str:
        return [""]

    s_em = float(letter_spacing_em)
    n = int(len(line_str))

    out: list[str] = []
    i = 0
    segment_start = 0
    segment_width_em = 0.0
    segment_len = 0
    last_space: int | None = None

    while i < n:
        ch = line_str[i]
        adv = _char_advance_em(
            ch,
            glyph_advance_em=glyph_advance_em,
            space_advance_em=space_advance_em,
        )
        inc = adv + (s_em if segment_len > 0 else 0.0)

        if segment_len > 0 and (segment_width_em + inc) > float(max_width_em):
            if last_space is not None and last_space > segment_start:
                out.append(line_str[segment_start:last_space])
                segment_start = last_space + 1
                while segment_start < n and line_str[segment_start] == " ":
                    segment_start += 1
                i = segment_start
            else:
                out.append(line_str[segment_start:i])
                segment_start = i
                while segment_start < n and line_str[segment_start] == " ":
                    segment_start += 1
                i = segment_start

            segment_width_em = 0.0
            segment_len = 0
            last_space = None
            continue

        if ch == " ":
            last_space = i
        segment_width_em += inc
        segment_len += 1
        i += 1

    if segment_start < n:
        out.append(line_str[segment_start:])
    return out


def _measure_line_width_em(
    line_str: str,
    *,
    glyph_advance_em: float,
    space_advance_em: float,
    letter_spacing_em: float,
) -> float:
    width_em = 0.0
    for ch in line_str:
        width_em += _char_advance_em(
            ch,
            glyph_advance_em=glyph_advance_em,
            space_advance_em=space_advance_em,
        ) + float(letter_spacing_em)
    if line_str:
        width_em -= float(letter_spacing_em)
    return float(width_em)


def _generate_asemic_glyph(
    *,
    seed: int,
    n_nodes: int,
    candidates: int,
    stroke_min: int,
    stroke_max: int,
    walk_min_steps: int,
    walk_max_steps: int,
    stroke_style: str,
    bezier_samples: int,
    bezier_tension: float,
) -> list[np.ndarray]:
    """1 文字分のストローク（ポリライン列）を生成して返す（1em=1.0, 左上起点）。"""
    nodes = int(n_nodes)
    if nodes < 2:
        return []

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
        return []

    style = str(stroke_style)
    if style not in {"line", "bezier"}:
        style = "bezier"

    polylines: list[np.ndarray] = []
    for path in strokes:
        poly = pts[np.asarray(path, dtype=np.int64)]
        if style == "bezier":
            poly = _sample_bezier(
                poly,
                samples_per_segment=int(bezier_samples),
                tension=float(bezier_tension),
            )

        # glyph 座標系は左上起点にしたいので [-0.5,0.5]^2 → [0,1]^2 へシフト。
        poly = poly + np.float64(0.5)
        poly32 = poly.astype(np.float32, copy=False)
        if int(poly32.shape[0]) < 2:
            continue
        arr3 = np.zeros((poly32.shape[0], 3), dtype=np.float32)
        arr3[:, :2] = poly32
        polylines.append(arr3)

    return polylines


def _dot_polylines() -> list[np.ndarray]:
    """ピリオド `.` 用のドット（小円）を返す（1em=1.0, 左上起点）。"""
    cx = 0.5
    cy = 0.85
    r = 0.06
    segments = 12

    angles = np.linspace(0.0, 2.0 * np.pi, num=segments, endpoint=False, dtype=np.float64)
    x = cx + r * np.cos(angles)
    y = cy + r * np.sin(angles)
    xy = np.stack([x, y], axis=1).astype(np.float32, copy=False)
    xy = np.concatenate([xy, xy[:1]], axis=0)

    arr3 = np.zeros((xy.shape[0], 3), dtype=np.float32)
    arr3[:, :2] = xy
    return [arr3]


@primitive(meta=asemic_meta, ui_visible=ASEMIC_UI_VISIBLE)
def asemic(
    *,
    text: str = "A",
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
    text_align: str = "left",
    glyph_advance_em: float = 1.0,
    space_advance_em: float = 0.35,
    letter_spacing_em: float = 0.0,
    line_height: float = 1.2,
    use_bounding_box: bool = False,
    box_width: float = -1.0,
    box_height: float = -1.0,
    show_bounding_box: bool = False,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> RealizedGeometry:
    """擬似文字（asemic）の文章をポリライン列として生成する。

    同じ文字は同じ字形になる（seed を文字で派生させる）ため、フォントのように使える。
    レイアウトは `text.py` と同様に「1em=1.0 の座標系 → 最後に scale/center 適用」。

    Parameters
    ----------
    text : str, default "A"
        描画する文字列。`\\n` 区切りで複数行を表す。
    seed : int, default 0
        全体 seed。同じ文字は `seed` と文字から派生した seed で生成され、決定的に同じ字形になる。
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
    text_align : {"left","center","right"}, default "left"
        行揃え。
    glyph_advance_em : float, default 1.0
        空白以外の文字送り（em）。
    space_advance_em : float, default 0.35
        空白の文字送り（em）。
    letter_spacing_em : float, default 0.0
        追加の文字間スペーシング（em）。
    line_height : float, default 1.2
        行送り（em）。
    use_bounding_box : bool, default False
        True のとき `box_width` による自動改行と、`show_bounding_box` による枠描画を有効にする。
    box_width : float, default -1.0
        幅による自動改行を行う際のボックス幅（出力座標系）。0 以下なら無効。
    box_height : float, default -1.0
        デバッグ用ボックス表示の高さ（出力座標系）。0 以下なら無効。
    show_bounding_box : bool, default False
        True のとき、`box_width/box_height` で指定されたボックス枠（4本の線分）を追加で描画する。
    center : tuple[float, float, float], default (0,0,0)
        平行移動ベクトル (cx, cy, cz)。
    scale : float, default 1.0
        等方スケール倍率。1em の出力スケール（例: 1em=40mm → scale=40）。

    Returns
    -------
    RealizedGeometry
        文章のポリライン列。
    """
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

    base_seed = int(seed)
    glyph_adv = float(glyph_advance_em)
    space_adv = float(space_advance_em)

    text_align_s = str(text_align)
    if text_align_s not in {"left", "center", "right"}:
        text_align_s = "left"

    lines = str(text).split("\n")
    use_bb = bool(use_bounding_box)
    s_abs = abs(float(s_f))
    bw = float(box_width)
    bh = float(box_height)

    if use_bb and bw > 0.0 and s_abs > 0.0:
        bw_em = bw / s_abs
        wrapped: list[str] = []
        for line_str in lines:
            wrapped.extend(
                _wrap_line_by_width_em(
                    line_str,
                    max_width_em=bw_em,
                    glyph_advance_em=glyph_adv,
                    space_advance_em=space_adv,
                    letter_spacing_em=float(letter_spacing_em),
                )
            )
        lines = wrapped

    polylines: list[np.ndarray] = []
    glyph_cache: dict[str, list[np.ndarray]] = {}

    y_em = 0.0
    for li, line_str in enumerate(lines):
        width_em = _measure_line_width_em(
            line_str,
            glyph_advance_em=glyph_adv,
            space_advance_em=space_adv,
            letter_spacing_em=float(letter_spacing_em),
        )
        if text_align_s == "center":
            x_em = -width_em / 2.0
        elif text_align_s == "right":
            x_em = -width_em
        else:
            x_em = 0.0

        cur_x_em = float(x_em)
        for ch in str(line_str):
            if ch != " ":
                cached = glyph_cache.get(ch)
                if cached is None:
                    if ch == ".":
                        cached = _dot_polylines()
                    else:
                        seed_char = _stable_hash64(f"{base_seed}|{ch}")
                        cached = _generate_asemic_glyph(
                            seed=int(seed_char),
                            n_nodes=int(n_nodes),
                            candidates=int(candidates),
                            stroke_min=int(stroke_min),
                            stroke_max=int(stroke_max),
                            walk_min_steps=int(walk_min_steps),
                            walk_max_steps=int(walk_max_steps),
                            stroke_style=str(stroke_style),
                            bezier_samples=int(bezier_samples),
                            bezier_tension=float(bezier_tension),
                        )
                    glyph_cache[ch] = cached

                if cached:
                    if cur_x_em == 0.0 and y_em == 0.0:
                        polylines.extend(cached)
                    else:
                        shift = np.array([cur_x_em, y_em, 0.0], dtype=np.float32)
                        for p in cached:
                            polylines.append(p + shift)

            cur_x_em += _char_advance_em(
                ch, glyph_advance_em=glyph_adv, space_advance_em=space_adv
            ) + float(letter_spacing_em)

        if li < len(lines) - 1:
            y_em += float(line_height)

    if use_bb and bool(show_bounding_box) and bw > 0.0 and bh > 0.0 and s_abs > 0.0:
        bw_em = bw / s_abs
        bh_em = bh / s_abs

        if text_align_s == "center":
            x0 = -bw_em / 2.0
            x1 = bw_em / 2.0
        elif text_align_s == "right":
            x0 = -bw_em
            x1 = 0.0
        else:
            x0 = 0.0
            x1 = bw_em

        y0 = 0.0
        y1 = bh_em
        z0 = 0.0
        polylines.extend(
            [
                np.asarray([[x0, y0, z0], [x1, y0, z0]], dtype=np.float32),
                np.asarray([[x1, y0, z0], [x1, y1, z0]], dtype=np.float32),
                np.asarray([[x1, y1, z0], [x0, y1, z0]], dtype=np.float32),
                np.asarray([[x0, y1, z0], [x0, y0, z0]], dtype=np.float32),
            ]
        )

    return _polylines_to_realized(
        polylines,
        center=(float(cx), float(cy), float(cz)),
        scale=float(s_f),
    )


__all__ = ["asemic", "asemic_meta"]
