"""閉ループ群を Voronoi 図で分割し、部分領域の閉ループ群を返す effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.effect_registry import effect
from grafix.core.realized_geometry import GeomTuple
from grafix.core.parameters.meta import ParamMeta
from .argument_validation import finite_vec3, integer_scalar
from .util import (
    canonical_planar_frame,
    pack_polylines,
    planarity_threshold,
)

partition_meta = {
    "mode": ParamMeta(
        kind="choice",
        choices=("merge", "group", "ring"),
        description="入力リングを統合、穴を含む領域単位、または個別リングとして分割する。",
    ),
    "site_count": ParamMeta(
        kind="int",
        ui_min=1,
        ui_max=500,
        description="領域をボロノイ分割するために配置するサイトの数。",
    ),
    # imgui.slider_int は内部で「min/max が int32 の半分レンジ以内」を要求するため、
    # GUI 用レンジは控えめにし、必要ならコード側で任意の seed を指定する。
    "seed": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=1_073_741_823,
        description="ボロノイサイトの配置を再現可能にする乱数シード。",
    ),
    "site_density_base": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=1.0,
        description=(
            "基準点におけるサイト採用確率を軸ごとに指定する。"
            "勾配も含めた全成分が 0 なら密度制御を無効にする。"
        ),
    ),
    "site_density_slope": ParamMeta(
        kind="vec3",
        ui_min=-1.0,
        ui_max=1.0,
        description=(
            "正規化した各軸位置に対するサイト採用確率の勾配。"
            "基準確率も含めた全成分が 0 なら密度制御を無効にする。"
        ),
    ),
    "auto_center": ParamMeta(
        kind="bool",
        description="入力のバウンディングボックス中心を密度勾配の基準点にする。",
    ),
    "pivot": ParamMeta(
        kind="vec3",
        ui_min=-100.0,
        ui_max=100.0,
        description="自動中心が無効な場合に密度勾配の基準とする点。",
    ),
}

partition_ui_visible = {
    "pivot": lambda v: not bool(v.get("auto_center", True)),
}

def _ensure_closed_2d(loop: np.ndarray) -> np.ndarray:
    if loop.shape[0] == 0:
        return loop
    if loop.shape[0] >= 2 and np.allclose(loop[0], loop[-1], rtol=0.0, atol=1e-6):
        return loop
    return np.concatenate([loop, loop[:1]], axis=0)


def _collect_polygon_exteriors(geom) -> list[np.ndarray]:  # type: ignore[no-untyped-def]
    """Shapely geometry から Polygon 外周を ndarray で抽出する（holes は無視）。"""
    try:
        if geom.is_empty:
            return []
    except Exception:
        return []

    gtype = getattr(geom, "geom_type", "")
    if gtype == "Polygon":
        coords = np.asarray(geom.exterior.coords, dtype=np.float32)
        return [coords]

    out: list[np.ndarray] = []
    for g in getattr(geom, "geoms", []):  # type: ignore[attr-defined]
        out.extend(_collect_polygon_exteriors(g))
    return out


def _combine_evenodd(polys, Polygon):  # type: ignore[no-untyped-def]
    if not polys:
        return None

    if len(polys) == 1:
        return polys[0]

    if len(polys) == 2:
        a, b = polys
        if a.geom_type == "Polygon" and b.geom_type == "Polygon" and a.contains(b):
            try:
                return Polygon(a.exterior.coords, holes=[b.exterior.coords])
            except Exception:
                return a.symmetric_difference(b)
        if a.geom_type == "Polygon" and b.geom_type == "Polygon" and b.contains(a):
            try:
                return Polygon(b.exterior.coords, holes=[a.exterior.coords])
            except Exception:
                return a.symmetric_difference(b)
        if a.disjoint(b):
            return a.union(b)
        return a.symmetric_difference(b)

    region = None
    for poly in polys:
        region = poly if region is None else region.symmetric_difference(poly)
    return region


def _build_evenodd_groups(polys, rings_2d, Point):  # type: ignore[no-untyped-def]
    """外周＋穴を even-odd でグルーピングし、[outer, hole...] のインデックス列を返す。"""
    n = int(len(polys))
    if n == 0:
        return []
    if n != int(len(rings_2d)):
        raise ValueError("polys と rings_2d のサイズが一致しない")

    rep_pts = [(float(ring[0, 0]), float(ring[0, 1])) for ring in rings_2d]
    areas = [float(getattr(poly, "area", 0.0)) for poly in polys]

    contains_count = [0] * n
    for i in range(n):
        x, y = rep_pts[i]
        pt = Point(x, y)
        count = 0
        for j in range(n):
            if j == i:
                continue
            try:
                if polys[j].contains(pt):
                    count += 1
            except Exception:
                continue
        contains_count[i] = count

    is_outer = [(c % 2) == 0 for c in contains_count]
    outer_ids = [i for i in range(n) if is_outer[i]]

    parent_outer = [-1] * n
    for i in range(n):
        if is_outer[i]:
            continue
        x, y = rep_pts[i]
        pt = Point(x, y)
        best = -1
        best_area = float("inf")
        for j in outer_ids:
            if j == i:
                continue
            try:
                if polys[j].contains(pt):
                    a = float(areas[j])
                    if a < best_area:
                        best_area = a
                        best = j
            except Exception:
                continue
        parent_outer[i] = best

    groups = {oi: [oi] for oi in outer_ids}
    orphan_keys: list[int] = []
    for i in range(n):
        if is_outer[i]:
            continue
        p = int(parent_outer[i])
        if p >= 0 and p != i:
            groups.setdefault(p, [p]).append(i)
        else:
            groups[i] = [i]
            orphan_keys.append(i)

    ordered: list[list[int]] = []
    for oi in outer_ids:
        members = sorted(groups.get(oi, [oi]))
        ordered.append(members)
    for key in orphan_keys:
        members = sorted(groups.get(key, [key]))
        ordered.append(members)
    return ordered


@effect(meta=partition_meta, ui_visible=partition_ui_visible)
def partition(
    g: GeomTuple,
    *,
    mode: str = "merge",
    site_count: int = 12,
    seed: int = 0,
    site_density_base: tuple[float, float, float] = (0.0, 0.0, 0.0),
    site_density_slope: tuple[float, float, float] = (0.0, 0.0, 0.0),
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
    """偶奇規則の平面領域を Voronoi 分割し、閉ループ群を返す。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力の実体ジオメトリ（coords, offsets）。各ポリラインが閉ループ（リング）を表す想定。
    site_count : int, default 12
        Voronoi の正のサイト数。
    seed : int, default 0
        乱数シード（再現性）。
    site_density_base : tuple[float, float, float], default (0.0, 0.0, 0.0)
        サイト密度（採用確率）の中心値（軸別）。各成分は 0.0〜1.0。
        全成分が 0.0 かつ `site_density_slope` が全て 0.0 の場合、密度制御は無効。
    site_density_slope : tuple[float, float, float], default (0.0, 0.0, 0.0)
        正規化座標 t∈[-1,+1] に対する密度勾配（軸別）。
    auto_center : bool, default True
        True のとき `pivot` を無視し、入力 bbox の中心を pivot として扱う。
    pivot : tuple[float, float, float], default (0.0, 0.0, 0.0)
        auto_center=False のときの pivot（ワールド座標）。
    mode : str, default "merge"
        入力リングの扱い。
        `"merge"` は全リングを 1 つの領域へ畳み込んでから分割する。
        `"group"` は even-odd で外周+穴をグループ化し、グループごとに分割する。
        `"ring"` は各リングを独立領域として扱い、リングごとに分割する（穴構造は無視）。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        分割セルの外周を並べた実体ジオメトリ（coords, offsets）。

    Notes
    -----
    rank 2 以上かつ最大平面残差が
    ``max(1e-6, 1e-5 * bbox_diagonal)`` 以下の有限入力だけを処理する。
    非共平面または linear な入力は射影せず no-op として返す。
    """
    if not isinstance(mode, str):
        raise TypeError("partition: mode は str である必要がある")
    if mode not in {"merge", "group", "ring"}:
        raise ValueError(f"partition: 未知の mode です: {mode!r}")
    mode_s = mode

    site_count_i = integer_scalar(site_count, name="partition: site_count")
    if site_count_i <= 0:
        raise ValueError("partition: site_count は正の整数である必要がある")

    base_x, base_y, base_z = finite_vec3(
        site_density_base,
        name="partition: site_density_base",
    )
    if not all(0.0 <= value <= 1.0 for value in (base_x, base_y, base_z)):
        raise ValueError(
            "partition: site_density_base の各要素は 0.0 以上 1.0 以下である必要がある"
        )
    slope_x, slope_y, slope_z = finite_vec3(
        site_density_slope,
        name="partition: site_density_slope",
    )
    pivot_value = finite_vec3(pivot, name="partition: pivot")
    seed_i = integer_scalar(seed, name="partition: seed")
    if seed_i < 0:
        raise ValueError("partition: seed は 0 以上である必要がある")

    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets
    frame = canonical_planar_frame(coords, offsets)
    if not frame.is_planar(planarity_threshold(coords)):
        return coords, offsets

    try:
        import shapely  # type: ignore
        from shapely.geometry import MultiPoint, Point, Polygon  # type: ignore
        from shapely.ops import voronoi_diagram  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("partition effect は shapely が必要です") from exc

    coords_2d_all = frame.project(coords)
    rings_2d: list[np.ndarray] = []
    polys = []
    for i in range(int(offsets.size) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        ring = coords_2d_all[s:e]
        if ring.shape[0] < 3:
            continue
        ring_2d = _ensure_closed_2d(ring)
        try:
            poly = Polygon(ring_2d)
            if not poly.is_valid:
                poly = poly.buffer(0)
        except Exception:
            continue
        if poly.is_empty:
            continue
        rings_2d.append(ring_2d)
        polys.append(poly)

    if not polys:
        return coords, offsets

    rng = np.random.default_rng(seed_i)

    regions = []
    if mode_s == "ring":
        regions = list(polys)
    elif mode_s == "group":
        groups = _build_evenodd_groups(polys, rings_2d, Point)
        for g in groups:
            region = _combine_evenodd([polys[i] for i in g], Polygon)
            if region is not None and not region.is_empty:
                regions.append(region)
    else:
        region = _combine_evenodd(polys, Polygon)
        if region is None or region.is_empty:
            return coords, offsets
        regions = [region]

    density_enabled = (
        (base_x != 0.0)
        or (base_y != 0.0)
        or (base_z != 0.0)
        or (slope_x != 0.0)
        or (slope_y != 0.0)
        or (slope_z != 0.0)
    )

    if density_enabled:
        mins3 = np.min(coords, axis=0).astype(np.float64, copy=False)
        maxs3 = np.max(coords, axis=0).astype(np.float64, copy=False)
        bbox_center = (mins3 + maxs3) * 0.5
        extent3 = (maxs3 - mins3) * 0.5

        inv_extent3 = np.zeros((3,), dtype=np.float64)
        for k in range(3):
            extent_k = float(extent3[k])
            inv_extent3[k] = 0.0 if extent_k < 1e-9 else 1.0 / extent_k

        if auto_center:
            pivot3 = bbox_center
        else:
            pivot3 = np.asarray(pivot_value, dtype=np.float64)

        def _p_eff_for_xy(xy: np.ndarray) -> np.ndarray:
            p3 = frame.lift(xy)
            t = (p3 - pivot3[None, :]) * inv_extent3[None, :]
            t = np.clip(t, -1.0, 1.0)
            tx = t[:, 0]
            ty = t[:, 1]
            tz = t[:, 2]

            p_x = np.clip(base_x + slope_x * tx, 0.0, 1.0)
            p_y = np.clip(base_y + slope_y * ty, 0.0, 1.0)
            p_z = np.clip(base_z + slope_z * tz, 0.0, 1.0)
            return 1.0 - (1.0 - p_x) * (1.0 - p_y) * (1.0 - p_z)

    all_loops_2d: list[np.ndarray] = []
    for region in regions:
        minx, miny, maxx, maxy = region.bounds
        width = float(maxx) - float(minx)
        height = float(maxy) - float(miny)

        pts: list[tuple[float, float]] = []
        if width > 0.0 and height > 0.0:
            trials_per_phase = max(1000, site_count_i * 50)
            batch = max(256, site_count_i * 20)

            def _append_points(xs: np.ndarray, ys: np.ndarray) -> None:
                need = site_count_i - len(pts)
                if need <= 0:
                    return
                for x, y in zip(xs[:need], ys[:need], strict=False):
                    pts.append((float(x), float(y)))

            trials_left = int(trials_per_phase)
            while len(pts) < site_count_i and trials_left > 0:
                n = min(int(batch), int(trials_left))
                xs = float(minx) + rng.random(n) * width
                ys = float(miny) + rng.random(n) * height
                inside = shapely.contains_xy(region, xs, ys)
                if not np.any(inside):
                    trials_left -= n
                    continue

                xs_in = xs[inside]
                ys_in = ys[inside]
                if density_enabled:
                    xy = np.stack([xs_in, ys_in], axis=1).astype(np.float64, copy=False)
                    p_eff = _p_eff_for_xy(xy)
                    take = rng.random(int(p_eff.shape[0])) < p_eff
                    _append_points(xs_in[take], ys_in[take])
                else:
                    _append_points(xs_in, ys_in)

                trials_left -= n

            # top-up: density で足りない場合は、一様サンプリングで埋めて site_count を満たす。
            if density_enabled and len(pts) < site_count_i:
                trials_left = int(trials_per_phase)
                while len(pts) < site_count_i and trials_left > 0:
                    n = min(int(batch), int(trials_left))
                    xs = float(minx) + rng.random(n) * width
                    ys = float(miny) + rng.random(n) * height
                    inside = shapely.contains_xy(region, xs, ys)
                    if np.any(inside):
                        _append_points(xs[inside], ys[inside])
                    trials_left -= n

        if not pts:
            try:
                c = region.representative_point()
                pts = [(float(c.x), float(c.y))]
            except Exception:
                continue

        if len(pts) <= 1:
            all_loops_2d.extend(_collect_polygon_exteriors(region))
            continue

        mp = MultiPoint(pts)
        try:
            vd = voronoi_diagram(mp, envelope=region.envelope, edges=False)  # type: ignore[arg-type]
        except Exception:
            continue

        for cell in getattr(vd, "geoms", []):  # type: ignore[attr-defined]
            try:
                inter = cell.intersection(region)
            except Exception:
                continue
            if inter.is_empty:
                continue
            all_loops_2d.extend(_collect_polygon_exteriors(inter))

    loops_2d = [loop for loop in all_loops_2d if loop.shape[0] >= 4]
    if not loops_2d:
        return coords, offsets

    def _sort_key(loop: np.ndarray) -> tuple[float, float]:
        c = loop[:-1].astype(np.float64, copy=False).mean(axis=0)
        return (float(c[0]), float(c[1]))

    loops_2d.sort(key=_sort_key)

    lines_3d = [frame.lift(loop[:, :2]) for loop in loops_2d]
    return pack_polylines([line for line in lines_3d if line.shape[0] > 0])
