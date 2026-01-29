"""
どこで: `src/grafix/devtools/generate_archimedean_polyhedra_resource.py`
何を: アルキメデス立体（+キラル）の `resource/regular_polyhedron/*.npz` を生成する。
なぜ: 面ポリライン列データを同梱し、primitive 側から再利用できるようにするため。
"""

from __future__ import annotations

from collections import Counter, deque
from itertools import permutations, product
from pathlib import Path

import numpy as np

_DATA_DIR = Path(__file__).resolve().parents[1] / "resource" / "regular_polyhedron"

_EPS = 1e-6


def _unique_rows(points: np.ndarray, *, decimals: int = 12) -> np.ndarray:
    rounded = np.round(points, decimals=decimals)
    uniq = np.unique(rounded, axis=0)
    return uniq.astype(np.float64, copy=False)


def _normalize_to_radius(vertices: np.ndarray, *, radius: float = 0.5) -> np.ndarray:
    r = np.linalg.norm(vertices, axis=1)
    s = float(radius) / float(r.mean())
    return vertices * s


def _load_face_polylines(kind: str) -> list[np.ndarray]:
    npz_path = _DATA_DIR / f"{kind}_vertices_list.npz"
    with np.load(npz_path, allow_pickle=False) as data:
        keys = sorted(data.files, key=lambda k: int(k.split("_")[1]))
        return [np.asarray(data[k], dtype=np.float64) for k in keys]


def _polylines_to_vertices_faces(polylines: list[np.ndarray]) -> tuple[np.ndarray, list[list[int]]]:
    raw = np.concatenate([p[:-1] for p in polylines], axis=0).astype(np.float64, copy=False)
    rounded = np.round(raw, decimals=12)
    uniq, inverse = np.unique(rounded, axis=0, return_inverse=True)

    faces: list[list[int]] = []
    offset = 0
    for p in polylines:
        m = int(p.shape[0]) - 1
        faces.append([int(i) for i in inverse[offset : offset + m]])
        offset += m
    return uniq.astype(np.float64, copy=False), faces


def _faces_to_edges(faces: list[list[int]]) -> list[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for face in faces:
        m = len(face)
        for i in range(m):
            a = int(face[i])
            b = int(face[(i + 1) % m])
            if a > b:
                a, b = b, a
            edges.add((a, b))
    return sorted(edges)


def _convex_hull_faces(vertices: np.ndarray) -> list[tuple[list[int], np.ndarray]]:
    v = np.asarray(vertices, dtype=np.float64)
    n = int(v.shape[0])
    faces: dict[tuple[int, ...], np.ndarray] = {}

    for i in range(n - 2):
        vi = v[i]
        for j in range(i + 1, n - 1):
            vj = v[j]
            for k in range(j + 1, n):
                vk = v[k]
                n_raw = np.cross(vj - vi, vk - vi)
                norm = float(np.linalg.norm(n_raw))
                if norm < 1e-12:
                    continue
                normal = n_raw / norm
                d = float(np.dot(normal, vi))

                proj = v @ normal
                if not np.all(proj <= d + _EPS):
                    normal = -normal
                    d = -d
                    proj = -proj
                    if not np.all(proj <= d + _EPS):
                        continue

                on = np.where(np.abs(proj - d) <= _EPS * 10.0)[0]
                if int(on.size) < 3:
                    continue

                key = tuple(sorted(int(idx) for idx in on.tolist()))
                if key not in faces:
                    faces[key] = normal

    return [(list(key), faces[key]) for key in faces]


def _order_face(vertices: np.ndarray, idxs: list[int], normal: np.ndarray) -> list[int]:
    v = np.asarray(vertices, dtype=np.float64)
    pts = v[np.asarray(idxs, dtype=np.int32)]
    center = pts.mean(axis=0)

    n = np.asarray(normal, dtype=np.float64)
    n = n / float(np.linalg.norm(n))

    ref = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    if abs(float(np.dot(n, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    u = np.cross(n, ref)
    u = u / float(np.linalg.norm(u))
    w = np.cross(n, u)

    rel = pts - center
    ang = np.arctan2(rel @ w, rel @ u)
    order = np.argsort(ang)
    ordered = [int(idxs[int(i)]) for i in order]

    # 安定化: 最小 index 始まりに回転
    min_pos = int(np.argmin(np.asarray(ordered, dtype=np.int32)))
    return ordered[min_pos:] + ordered[:min_pos]


def _faces_to_polylines(vertices: np.ndarray, faces: list[tuple[list[int], np.ndarray]]) -> list[np.ndarray]:
    v = np.asarray(vertices, dtype=np.float64)

    ordered_faces: list[tuple[list[int], np.ndarray]] = []
    for idxs, normal in faces:
        ordered = _order_face(v, idxs, normal)
        ordered_faces.append((ordered, normal))

    # 出力順序を固定（面サイズ→頂点 index 列）
    ordered_faces.sort(key=lambda it: (len(it[0]), tuple(it[0])))

    polylines: list[np.ndarray] = []
    for idxs, _normal in ordered_faces:
        pts = v[np.asarray(idxs, dtype=np.int32)]
        pts = np.concatenate([pts, pts[:1]], axis=0)
        polylines.append(pts.astype(np.float32, copy=False))
    return polylines


def _save_npz(kind: str, polylines: list[np.ndarray]) -> Path:
    out_path = _DATA_DIR / f"{kind}_vertices_list.npz"
    np.savez(out_path, *polylines)
    return out_path


def _validate(kind: str, vertices: np.ndarray, faces: list[tuple[list[int], np.ndarray]]) -> None:
    sizes = Counter(len(idxs) for idxs, _n in faces)
    ordered_faces = [_order_face(vertices, idxs, normal) for idxs, normal in faces]
    edges = _faces_to_edges(ordered_faces)
    radii = np.linalg.norm(vertices, axis=1)

    assert float(radii.min()) > 0.0
    assert float(radii.max() - radii.min()) < 1e-6
    assert float(abs(radii.mean() - 0.5)) < 1e-6

    lengths = np.array([np.linalg.norm(vertices[i] - vertices[j]) for i, j in edges], dtype=np.float64)
    assert float(lengths.max() - lengths.min()) < 1e-5, (kind, float(lengths.min()), float(lengths.max()))

    expected: dict[str, tuple[int, dict[int, int], int, int]] = {
        "cuboctahedron": (12, {3: 8, 4: 6}, 14, 24),
        "icosidodecahedron": (30, {3: 20, 5: 12}, 32, 60),
        "truncated_tetrahedron": (12, {3: 4, 6: 4}, 8, 18),
        "truncated_cube": (24, {3: 8, 8: 6}, 14, 36),
        "truncated_octahedron": (24, {4: 6, 6: 8}, 14, 36),
        "truncated_dodecahedron": (60, {3: 20, 10: 12}, 32, 90),
        "truncated_icosahedron": (60, {5: 12, 6: 20}, 32, 90),
        "rhombicuboctahedron": (24, {3: 8, 4: 18}, 26, 48),
        "snub_cube_left": (24, {3: 32, 4: 6}, 38, 60),
        "snub_cube_right": (24, {3: 32, 4: 6}, 38, 60),
        "snub_dodecahedron_left": (60, {3: 80, 5: 12}, 92, 150),
        "snub_dodecahedron_right": (60, {3: 80, 5: 12}, 92, 150),
    }
    exp = expected.get(kind)
    if exp is None:
        return
    n_verts, exp_sizes, n_faces, n_edges = exp
    assert int(vertices.shape[0]) == n_verts
    assert dict(sizes) == exp_sizes
    assert len(faces) == n_faces
    assert len(edges) == n_edges


def _rectify_from(kind: str) -> np.ndarray:
    polylines = _load_face_polylines(kind)
    vertices, faces = _polylines_to_vertices_faces(polylines)
    edges = _faces_to_edges(faces)
    mids = np.array([(vertices[i] + vertices[j]) * 0.5 for i, j in edges], dtype=np.float64)
    return _normalize_to_radius(_unique_rows(mids))


def _truncate_from(kind: str, *, t: float = 1.0 / 3.0) -> np.ndarray:
    polylines = _load_face_polylines(kind)
    vertices, faces = _polylines_to_vertices_faces(polylines)
    edges = _faces_to_edges(faces)

    points: list[np.ndarray] = []
    for i, j in edges:
        a = vertices[i]
        b = vertices[j]
        points.append(a * (1.0 - t) + b * t)
        points.append(b * (1.0 - t) + a * t)
    pts = np.asarray(points, dtype=np.float64)
    return _normalize_to_radius(_unique_rows(pts))


def _uniform_truncation_ratio(face_sides: int) -> float:
    """正 n 角形面の正多面体を一様切頭するための比率 t（辺上の切り位置）を返す。"""
    return 1.0 / (2.0 + 2.0 * float(np.cos(np.pi / float(face_sides))))


def _octahedral_rotations() -> list[np.ndarray]:
    mats: list[np.ndarray] = []
    for perm in permutations([0, 1, 2]):
        P = np.zeros((3, 3), dtype=np.float64)
        for r, c in enumerate(perm):
            P[r, c] = 1.0
        for signs in product([-1.0, 1.0], repeat=3):
            S = np.diag(np.asarray(signs, dtype=np.float64))
            M = S @ P
            if abs(float(np.linalg.det(M)) - 1.0) < 1e-9:
                mats.append(M)

    uniq: list[np.ndarray] = []
    for M in mats:
        if not any(np.allclose(M, U) for U in uniq):
            uniq.append(M)
    assert len(uniq) == 24
    return uniq


def _rotation_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    a = np.asarray(axis, dtype=np.float64)
    a = a / float(np.linalg.norm(a))
    x, y, z = float(a[0]), float(a[1]), float(a[2])

    c = float(np.cos(angle))
    s = float(np.sin(angle))
    C = 1.0 - c

    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ],
        dtype=np.float64,
    )


def _icosahedral_rotations() -> list[np.ndarray]:
    phi = (1.0 + 5.0**0.5) / 2.0

    axis5 = np.array([0.0, 1.0, phi], dtype=np.float64)
    g5 = _rotation_matrix(axis5, 2.0 * np.pi / 5.0)

    v1 = np.array([0.0, 1.0, phi], dtype=np.float64)
    v2 = np.array([1.0, phi, 0.0], dtype=np.float64)
    v3 = np.array([phi, 0.0, 1.0], dtype=np.float64)
    axis3 = v1 + v2 + v3
    g3 = _rotation_matrix(axis3, 2.0 * np.pi / 3.0)

    def key(M: np.ndarray) -> tuple[float, ...]:
        return tuple(np.round(M, 10).ravel())

    gens = [g5, g3, g5.T, g3.T]
    seen = {key(np.eye(3, dtype=np.float64))}
    mats = [np.eye(3, dtype=np.float64)]
    q: deque[np.ndarray] = deque([mats[0]])

    while q:
        A = q.popleft()
        for g in gens:
            B = A @ g
            k = key(B)
            if k in seen:
                continue
            seen.add(k)
            mats.append(B)
            q.append(B)

    assert len(mats) == 60
    return mats


def _snub_cube_vertices() -> np.ndarray:
    roots = np.roots([1.0, -1.0, -1.0, -1.0])
    t = float(sorted([r.real for r in roots if abs(float(r.imag)) < 1e-8])[-1])
    v0 = np.array([1.0, t, 1.0 / t], dtype=np.float64)
    r = float(np.linalg.norm(v0))

    mats = _octahedral_rotations()
    verts = np.array([M @ v0 for M in mats], dtype=np.float64) * (0.5 / r)
    return verts


def _snub_dodecahedron_vertices() -> np.ndarray:
    # 既知の snub dodecahedron の座標の 1 例（辺長が一様）として採用する。
    x = 1.4929136894519366
    y = 0.7682951506351664

    v0 = np.array([1.0, x, y], dtype=np.float64)
    r = float(np.linalg.norm(v0))

    mats = _icosahedral_rotations()
    verts = np.array([M @ v0 for M in mats], dtype=np.float64) * (0.5 / r)
    return verts


def _rhombicuboctahedron_vertices() -> np.ndarray:
    s = 1.0 + 2.0**0.5
    points: list[np.ndarray] = []
    for axis in range(3):
        base = np.array([1.0, 1.0, 1.0], dtype=np.float64)
        base[axis] = s
        for sx, sy, sz in product([-1.0, 1.0], repeat=3):
            points.append(base * np.array([sx, sy, sz], dtype=np.float64))
    verts = _unique_rows(np.asarray(points, dtype=np.float64))
    return _normalize_to_radius(verts)


def _build(kind: str, vertices: np.ndarray) -> list[np.ndarray]:
    faces = _convex_hull_faces(vertices)
    _validate(kind, vertices, faces)
    return _faces_to_polylines(vertices, faces)


def generate_all() -> list[Path]:
    generated: list[Path] = []

    tasks: list[tuple[str, np.ndarray]] = [
        ("cuboctahedron", _rectify_from("hexahedron")),
        ("icosidodecahedron", _rectify_from("icosahedron")),
        ("truncated_tetrahedron", _truncate_from("tetrahedron")),
        ("truncated_cube", _truncate_from("hexahedron", t=_uniform_truncation_ratio(4))),
        ("truncated_octahedron", _truncate_from("octahedron")),
        ("truncated_dodecahedron", _truncate_from("dodecahedron", t=_uniform_truncation_ratio(5))),
        ("truncated_icosahedron", _truncate_from("icosahedron")),
        ("rhombicuboctahedron", _rhombicuboctahedron_vertices()),
    ]

    snub_cube_left = _snub_cube_vertices()
    snub_cube_right = snub_cube_left.copy()
    snub_cube_right[:, 0] *= -1.0
    tasks.extend(
        [
            ("snub_cube_left", snub_cube_left),
            ("snub_cube_right", snub_cube_right),
        ]
    )

    snub_dode_left = _snub_dodecahedron_vertices()
    snub_dode_right = snub_dode_left.copy()
    snub_dode_right[:, 0] *= -1.0
    tasks.extend(
        [
            ("snub_dodecahedron_left", snub_dode_left),
            ("snub_dodecahedron_right", snub_dode_right),
        ]
    )

    for kind, vertices in tasks:
        polylines = _build(kind, vertices)
        out = _save_npz(kind, polylines)
        generated.append(out)

    return generated


def main() -> None:
    paths = generate_all()
    for p in paths:
        print(p.relative_to(Path.cwd()))


if __name__ == "__main__":
    main()
