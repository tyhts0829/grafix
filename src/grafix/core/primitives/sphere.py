"""
どこで: `src/grafix/primitives/sphere.py`。球プリミティブの実体生成。
何を: 4 つのスタイル（latlon/zigzag/icosphere/rings）で球のポリライン列を生成して返す。
なぜ: 3D 座標を持つ基本形状として、回転などの effect と組み合わせて使うため。
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from grafix.core.operation_diagnostics import emit_operation_diagnostic
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import primitive
from grafix.core.realized_geometry import GeomTuple

_RADIUS = 0.5
_MIN_SUBDIVISIONS = 0
_MAX_SUBDIVISIONS = 5

_STYLE_ORDER = ("latlon", "zigzag", "icosphere", "rings")
_LINE_MODE_ORDER = ("horizontal", "vertical", "both")

sphere_meta = {
    "subdivisions": ParamMeta(
        kind="int",
        ui_min=_MIN_SUBDIVISIONS,
        ui_max=_MAX_SUBDIVISIONS,
        description="球面を構成する線や面の細分化レベルを指定します。",
    ),
    "style": ParamMeta(
        kind="choice",
        choices=_STYLE_ORDER,
        description="緯経線・螺旋・三角面・リングからワイヤーフレームの生成方式を選択します。",
    ),
    "line_mode": ParamMeta(
        kind="choice",
        choices=_LINE_MODE_ORDER,
        description="緯経線またはリング方式で横線・縦線のどちらを描くか選択します。",
    ),
    "center": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=300.0,
        description="球全体を平行移動する XYZ 座標を指定します。",
    ),
    "scale": ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=200.0,
        description="直径 1 の球全体に適用する等方スケールを指定します。",
    ),
}

SPHERE_UI_VISIBLE = {
    "line_mode": lambda v: v.get("style", "latlon") in {"latlon", "rings"},
}


def _polylines_to_realized(
    polylines: list[np.ndarray],
) -> GeomTuple:
    """ポリライン列を (coords, offsets) に変換する。"""
    filtered: list[np.ndarray] = []
    lengths: list[int] = []
    for i, line in enumerate(polylines):
        arr = np.asarray(line, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError(
                "sphere の各ポリラインは shape (N,3) の配列である必要がある"
                f": index={i}, shape={arr.shape}"
            )
        if arr.shape[0] == 0:
            continue
        filtered.append(arr)
        lengths.append(int(arr.shape[0]))

    if not filtered:
        coords = np.zeros((0, 3), dtype=np.float32)
        offsets = np.zeros((1,), dtype=np.int32)
        return coords, offsets

    coords = np.concatenate(filtered, axis=0).astype(np.float32, copy=False)
    offsets = np.zeros(len(filtered) + 1, dtype=np.int32)
    offsets[1:] = np.cumsum(np.asarray(lengths, dtype=np.int32), dtype=np.int32)

    return coords, offsets


def _sphere_latlon(subdivisions: int, mode: int) -> list[np.ndarray]:
    """緯度/経度線のポリライン列を生成する。"""
    pi = math.pi
    two_pi = 2.0 * math.pi

    s = subdivisions
    m = mode

    eq_segments = max(16, 64 * (s + 1))
    if s <= 0:
        eq_segments = max(eq_segments, 160)
    meridian_samples = max(12, eq_segments // 2)
    if s <= 0:
        lat_rings = max(4, meridian_samples // 4)
        min_segments_lat = 24
    else:
        lat_rings = meridian_samples
        min_segments_lat = 8
    target_step_equator = two_pi * _RADIUS / float(eq_segments)

    polylines: list[np.ndarray] = []

    # 経度線（極→極）
    if m in (1, 2):
        lat_vals = np.linspace(0.0, pi, meridian_samples + 1, dtype=np.float32)
        sin_lat = np.sin(lat_vals)
        cos_lat = np.cos(lat_vals)

        meridian_lines = max(8, lat_rings)
        stride = max(1, eq_segments // max(1, meridian_lines))
        for j in range(0, eq_segments, stride):
            lon = two_pi * j / eq_segments
            cos_lon = np.float32(np.cos(lon))
            sin_lon = np.float32(np.sin(lon))
            x = (sin_lat * cos_lon * _RADIUS).astype(np.float32)
            y = (sin_lat * sin_lon * _RADIUS).astype(np.float32)
            z = (cos_lat * _RADIUS).astype(np.float32)
            line = np.stack((x, y, z), axis=1).astype(np.float32)
            polylines.append(line)

    # 緯度リング（周方向）
    if m in (0, 2):
        for i in range(1, lat_rings):  # 極は除外
            lat = pi * i / lat_rings
            r = abs(math.sin(lat)) * _RADIUS
            if r <= 1e-9:
                continue
            segments_at_lat = int(
                np.ceil((two_pi * r) / max(1e-9, target_step_equator))
            )
            segments_at_lat = max(min_segments_lat, segments_at_lat)

            angles = np.linspace(0.0, two_pi, segments_at_lat + 1, dtype=np.float32)
            x = (np.cos(angles) * r).astype(np.float32)
            y = (np.sin(angles) * r).astype(np.float32)
            z = np.full_like(x, fill_value=np.cos(lat) * _RADIUS, dtype=np.float32)
            ring = np.stack((x, y, z), axis=1).astype(np.float32)
            polylines.append(ring)

    return polylines


def _sphere_zigzag(subdivisions: int) -> list[np.ndarray]:
    """螺旋（ジグザグ）スタイルのポリライン列を生成する。"""
    s = subdivisions
    total_rotations = 8 + 4 * s

    if s <= 0:
        strand_count = 2
    elif s == 1:
        strand_count = 3
    else:
        strand_count = 4

    base_ppr = 64 + 16 * min(s, 2)  # 64, 80, 96, ...
    points_per_rotation = base_ppr if strand_count <= 2 else max(48, base_ppr - 24)

    polylines: list[np.ndarray] = []
    for k in range(strand_count):
        phase = 2.0 * math.pi * (k / float(strand_count))
        points = int(total_rotations * points_per_rotation)
        t = np.linspace(0.0, 1.0, points, dtype=np.float32)

        y = 1.0 - 2.0 * t
        radius = np.sqrt(np.maximum(0.0, 1.0 - y * y))
        theta = 2.0 * math.pi * total_rotations * t + phase

        x = np.cos(theta) * radius * _RADIUS
        z = np.sin(theta) * radius * _RADIUS
        y = y * _RADIUS

        polyline = np.stack(
            (x.astype(np.float32), y.astype(np.float32), z.astype(np.float32)),
            axis=1,
        )
        polylines.append(polyline)

    return polylines


def _sphere_icosphere(subdivisions: int) -> GeomTuple:
    """固定した DFS と辺順でアイコスフィアを packed geometry へ直接生成する。"""

    phi = (1.0 + math.sqrt(5.0)) / 2.0
    base_vertices = np.array(
        [
            [-1.0, phi, 0.0],
            [1.0, phi, 0.0],
            [-1.0, -phi, 0.0],
            [1.0, -phi, 0.0],
            [0.0, -1.0, phi],
            [0.0, 1.0, phi],
            [0.0, -1.0, -phi],
            [0.0, 1.0, -phi],
            [phi, 0.0, -1.0],
            [phi, 0.0, 1.0],
            [-phi, 0.0, -1.0],
            [-phi, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    norms = np.linalg.norm(base_vertices, axis=1, keepdims=True)
    base_vertices = base_vertices / norms * np.float32(_RADIUS)

    base_faces = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (9, 5, 4),
        (4, 11, 2),
        (2, 10, 6),
        (6, 7, 8),
        (8, 1, 9),
    ]

    EdgeKey = tuple[int, int]

    def edge_key(v1: int, v2: int) -> EdgeKey:
        return (v1, v2) if v1 <= v2 else (v2, v1)

    # 共有辺は同じ頂点 id の組で表す。座標演算は最初の生成時だけ行い、
    # 以後は同じ float32 midpoint を再利用して決定的な順序を保つ。
    vertices = [base_vertices[i] for i in range(int(base_vertices.shape[0]))]
    midpoint_cache: dict[EdgeKey, int] = {}

    def midpoint_on_sphere(v1: int, v2: int) -> int:
        key = edge_key(v1, v2)
        cached = midpoint_cache.get(key)
        if cached is not None:
            return cached

        p1 = vertices[v1]
        p2 = vertices[v2]
        mid = (p1 + p2) * np.float32(0.5)
        norm = float(np.linalg.norm(mid))
        if norm <= 0.0:
            result = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        else:
            result = mid / np.float32(norm) * np.float32(_RADIUS)
        result_id = len(vertices)
        vertices.append(result)
        midpoint_cache[key] = result_id
        return result_id

    level = subdivisions
    expected_edges = 30 * (4**level)
    coords = np.empty((expected_edges * 2, 3), dtype=np.float32)
    seen: set[EdgeKey] = set()
    edge_at = 0

    def emit_edge(v0: int, v1: int) -> None:
        nonlocal edge_at
        key = edge_key(v0, v1)
        if key in seen:
            return
        seen.add(key)
        coords[edge_at * 2] = vertices[v0]
        coords[edge_at * 2 + 1] = vertices[v1]
        edge_at += 1

    def subdivide_triangle(
        v1: int,
        v2: int,
        v3: int,
        remaining: int,
    ) -> None:
        if remaining <= 0:
            emit_edge(v1, v2)
            emit_edge(v2, v3)
            emit_edge(v3, v1)
            return

        m1 = midpoint_on_sphere(v1, v2)
        m2 = midpoint_on_sphere(v2, v3)
        m3 = midpoint_on_sphere(v3, v1)

        subdivide_triangle(v1, m1, m3, remaining - 1)
        subdivide_triangle(m1, v2, m2, remaining - 1)
        subdivide_triangle(m3, m2, v3, remaining - 1)
        subdivide_triangle(m1, m2, m3, remaining - 1)

    for v1, v2, v3 in base_faces:
        subdivide_triangle(v1, v2, v3, level)

    if edge_at != expected_edges:
        coords = coords[: edge_at * 2].copy()
    offsets = np.arange(0, coords.shape[0] + 1, 2, dtype=np.int32)
    return coords, offsets


def _sphere_rings(subdivisions: int, mode: int) -> list[np.ndarray]:
    """3 軸リング（水平+縦リング）スタイルのポリライン列を生成する。"""
    s = subdivisions
    m = mode

    ring_count = 5 + 12 * s

    equator_segments = max(16, 64 * (s + 1))
    if s <= 0:
        equator_segments = max(equator_segments, 160)
    target_step_equator = 2.0 * math.pi * _RADIUS / float(equator_segments)
    min_segments = 24 if s <= 0 else 8

    polylines: list[np.ndarray] = []

    # 高さごとに水平リング（Y 一定の XZ 面の円）
    if m in (0, 2):
        for i in range(ring_count):
            y_pos = -_RADIUS + (i / (ring_count - 1)) * (2.0 * _RADIUS)
            radius = float(math.sqrt(max(0.0, _RADIUS * _RADIUS - y_pos * y_pos)))
            if radius <= 1e-9:
                continue
            segments = int(
                np.ceil((2.0 * math.pi * radius) / max(1e-9, target_step_equator))
            )
            segments = max(min_segments, segments)
            angles = np.linspace(0.0, 2.0 * math.pi, segments + 1, dtype=np.float32)
            xs = (radius * np.cos(angles)).astype(np.float32)
            zs = (radius * np.sin(angles)).astype(np.float32)
            ys = np.full_like(xs, fill_value=np.float32(y_pos))
            polylines.append(np.stack((xs, ys, zs), axis=1).astype(np.float32))

    # 縦リング（X 固定の YZ 円 / Z 固定の XY 円）
    if m in (1, 2):
        for i in range(ring_count):
            x_pos = -_RADIUS + (i / (ring_count - 1)) * (2.0 * _RADIUS)
            radius = float(math.sqrt(max(0.0, _RADIUS * _RADIUS - x_pos * x_pos)))
            if radius <= 1e-9:
                continue
            segments = int(
                np.ceil((2.0 * math.pi * radius) / max(1e-9, target_step_equator))
            )
            segments = max(min_segments, segments)
            angles = np.linspace(0.0, 2.0 * math.pi, segments + 1, dtype=np.float32)
            ys = (radius * np.cos(angles)).astype(np.float32)
            zs = (radius * np.sin(angles)).astype(np.float32)
            xs = np.full_like(ys, fill_value=np.float32(x_pos))
            polylines.append(np.stack((xs, ys, zs), axis=1).astype(np.float32))

        for i in range(ring_count):
            z_pos = -_RADIUS + (i / (ring_count - 1)) * (2.0 * _RADIUS)
            radius = float(math.sqrt(max(0.0, _RADIUS * _RADIUS - z_pos * z_pos)))
            if radius <= 1e-9:
                continue
            segments = int(
                np.ceil((2.0 * math.pi * radius) / max(1e-9, target_step_equator))
            )
            segments = max(min_segments, segments)
            angles = np.linspace(0.0, 2.0 * math.pi, segments + 1, dtype=np.float32)
            xs = (radius * np.cos(angles)).astype(np.float32)
            ys = (radius * np.sin(angles)).astype(np.float32)
            zs = np.full_like(xs, fill_value=np.float32(z_pos))
            polylines.append(np.stack((xs, ys, zs), axis=1).astype(np.float32))

    return polylines


@lru_cache(maxsize=16)
def _sphere_base_geometry(style: str, subdivisions: int, mode: int) -> GeomTuple:
    """配置前の単位球を immutable な packed geometry として再利用する。"""

    if style == "icosphere":
        coords, offsets = _sphere_icosphere(subdivisions)
    else:
        if style == "latlon":
            polylines = _sphere_latlon(subdivisions, mode)
        elif style == "zigzag":
            polylines = _sphere_zigzag(subdivisions)
        else:
            polylines = _sphere_rings(subdivisions, mode)
        coords, offsets = _polylines_to_realized(polylines)

    coords.setflags(write=False)
    offsets.setflags(write=False)
    return coords, offsets


def _place_cached_sphere(
    packed: GeomTuple,
    *,
    center: tuple[float, float, float],
    scale: float,
) -> GeomTuple:
    """cache を共有せず、scale、center の順に float32 演算を適用する。"""

    base_coords, base_offsets = packed
    coords = base_coords.copy()
    offsets = base_offsets.copy()

    s_f = scale
    if s_f != 1.0:
        coords *= np.float32(s_f)
    cx, cy, cz = center
    if (cx, cy, cz) != (0.0, 0.0, 0.0):
        coords += np.array([cx, cy, cz], dtype=np.float32)
    return coords, offsets


@primitive(meta=sphere_meta, ui_visible=SPHERE_UI_VISIBLE)
def sphere(
    *,
    subdivisions: int = 1,
    style: str = "latlon",
    line_mode: str = "both",
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: float = 1.0,
) -> GeomTuple:
    """球のワイヤーフレームをポリライン列として生成する。

    Parameters
    ----------
    subdivisions : int, optional
        細分化レベル。5 を超える値はクランプする。
    style : str, optional
        生成方式。``latlon``, ``zigzag``, ``icosphere``, ``rings`` から選ぶ。
    line_mode : str, optional
        ``latlon`` / ``rings`` の線種。``horizontal``, ``vertical``, ``both``
        から選ぶ。他の style では使用しない。
    center : tuple[float, float, float], optional
        平行移動ベクトル (cx, cy, cz)。
    scale : float, optional
        等方スケール倍率 s。縦横比変更は effect を使用する。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        球ワイヤーフレームの実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `subdivisions` が負、または ``style`` / ``line_mode`` が未登録の場合。
    """
    if subdivisions < 0:
        raise ValueError("sphere の subdivisions は 0 以上である必要がある")

    requested_subdivisions = subdivisions
    s = min(requested_subdivisions, _MAX_SUBDIVISIONS)
    if s != requested_subdivisions:
        emit_operation_diagnostic(
            op="sphere.subdivisions",
            original_value=requested_subdivisions,
            effective_value=s,
            reason="subdivisions was clamped to the supported range",
        )
    if style not in _STYLE_ORDER:
        raise ValueError(f"sphere.style must be one of {_STYLE_ORDER}; got {style!r}")
    if line_mode not in _LINE_MODE_ORDER:
        raise ValueError(
            "sphere.line_mode must be one of "
            f"{_LINE_MODE_ORDER}; got {line_mode!r}"
        )
    m = _LINE_MODE_ORDER.index(line_mode)

    cx, cy, cz = center
    s_f = scale

    base_mode = m if style in {"latlon", "rings"} else 0
    packed = _sphere_base_geometry(style, s, base_mode)
    return _place_cached_sphere(packed, center=(cx, cy, cz), scale=s_f)


__all__ = ["sphere", "sphere_meta"]
