"""polyhedron プリミティブの面ポリライン形状に関するテスト群。"""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest

from grafix.api import G
from grafix.core.primitives.polyhedron import _POLYHEDRON_CACHE, polyhedron
from grafix.core.realize import realize

polyhedron_module = importlib.import_module("grafix.core.primitives.polyhedron")


@pytest.mark.parametrize(
    "kind,expected_faces",
    [
        ("tetrahedron", 4),
        ("hexahedron", 6),
        ("octahedron", 8),
        ("dodecahedron", 12),
        ("icosahedron", 20),
    ],
)
def test_polyhedron_face_count_and_closed_polylines(
    kind: str,
    expected_faces: int,
) -> None:
    """面数が一致し、各面が閉ポリライン（先頭==末尾）になっている。"""
    g = G.polyhedron(kind=kind)
    realized = realize(g)

    assert realized.offsets.shape[0] == expected_faces + 1

    for i in range(expected_faces):
        start = int(realized.offsets[i])
        end = int(realized.offsets[i + 1])
        assert end - start >= 2
        np.testing.assert_array_equal(realized.coords[start], realized.coords[end - 1])


def test_polyhedron_kind_rejects_unknown_name() -> None:
    """未知の形状名を別の形へ黙って置換しない。"""
    with pytest.raises(ValueError, match="polyhedron.*kind"):
        G.polyhedron(kind="unknown")


def test_polyhedron_center_and_scale_affect_coords() -> None:
    """center/scale が座標に反映される。"""
    base = realize(G.polyhedron(kind="tetrahedron"))

    center = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    scale = 2.0
    moved = realize(
        G.polyhedron(
            kind="tetrahedron",
            center=(float(center[0]), float(center[1]), float(center[2])),
            scale=float(scale),
        )
    )

    expected = base.coords * np.float32(scale) + center
    np.testing.assert_allclose(moved.coords, expected, rtol=0.0, atol=1e-6)


def test_polyhedron_raw_arrays_are_fresh_writable_and_do_not_share_cache() -> None:
    """packed resource cacheを使っても、呼び出し側へは独立した配列を返す。"""

    kind = "truncated_icosidodecahedron"
    coords_a, offsets_a = polyhedron(kind=kind)
    coords_b, offsets_b = polyhedron(kind=kind)

    assert coords_a.flags.writeable
    assert offsets_a.flags.writeable
    assert coords_b.flags.writeable
    assert offsets_b.flags.writeable
    assert not np.shares_memory(coords_a, coords_b)
    assert not np.shares_memory(offsets_a, offsets_b)

    cached_coords, cached_offsets = _POLYHEDRON_CACHE[kind]
    assert not cached_coords.flags.writeable
    assert not cached_offsets.flags.writeable
    assert not np.shares_memory(coords_a, cached_coords)
    assert not np.shares_memory(offsets_a, cached_offsets)

    expected_coords = coords_b.copy()
    expected_offsets = offsets_b.copy()
    coords_a[0, 0] = np.float32(123.0)
    offsets_a[0] = np.int32(1)
    np.testing.assert_array_equal(coords_b, expected_coords)
    np.testing.assert_array_equal(offsets_b, expected_offsets)


def test_polyhedron_loader_rejects_legacy_arrays_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = "legacy_fixture"
    np.savez(
        tmp_path / f"{kind}_vertices_list.npz",
        arrays=np.zeros((1, 2, 3), dtype=np.float32),
    )
    monkeypatch.setattr(polyhedron_module, "_DATA_DIR", tmp_path)
    _POLYHEDRON_CACHE.pop(kind, None)

    with pytest.raises(ValueError, match="arr_0"):
        polyhedron_module._load_packed_polyhedron(kind)


def test_polyhedron_loader_rejects_two_dimensional_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = "two_dimensional_fixture"
    np.savez(
        tmp_path / f"{kind}_vertices_list.npz",
        arr_0=np.zeros((2, 2), dtype=np.float32),
    )
    monkeypatch.setattr(polyhedron_module, "_DATA_DIR", tmp_path)
    _POLYHEDRON_CACHE.pop(kind, None)

    with pytest.raises(ValueError, match=r"shape \(N,3\)"):
        polyhedron_module._load_packed_polyhedron(kind)
