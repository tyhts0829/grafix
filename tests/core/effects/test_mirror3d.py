"""mirror3d effect（3D 放射状ミラー）の実体変換に関するテスト群。"""

from __future__ import annotations

import pytest
import numpy as np

from grafix.api import E, G
from grafix.core.effects.mirror3d import (
    _dedup_lines,
    _dedup_uniform_finite_lines,
    _packed_polyhedral_transforms,
    _polyhedral_rotation_mats,
)
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


@primitive
def mirror3d_test_line_in_wedge_posz() -> GeomTuple:
    """くさび内（azimuth）にある 2 点ポリライン（z>0）。"""
    coords = np.array([[-2.0, 1.5, 5.0], [-1.5, 1.6, 6.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def mirror3d_test_line_in_wedge_negz() -> GeomTuple:
    """くさび内（azimuth）にある 2 点ポリライン（z<0）。"""
    coords = np.array([[-2.0, 1.5, -5.0], [-1.5, 1.6, -6.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def mirror3d_test_line_pos_octant() -> GeomTuple:
    """正の八分体（polyhedral のソース領域）内にある 2 点ポリライン。"""
    coords = np.array([[1.1, 2.2, 3.3], [4.4, 5.5, 6.6]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


def _iter_polylines(realized: RealizedGeometry):
    offsets = realized.offsets
    for i in range(len(offsets) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        yield realized.coords[s:e]


def test_mirror3d_azimuth_produces_2n_polylines_and_preserves_z() -> None:
    g = G.mirror3d_test_line_in_wedge_posz()
    out = realize(
        E.mirror3d(
            mode="azimuth",
            n_azimuth=3,
            center=(0.0, 0.0, 0.0),
            axis=(0.0, 0.0, 1.0),
            phi0=0.0,
            mirror_equator=False,
            show_planes=False,
        )(g)
    )

    polylines = list(_iter_polylines(out))
    assert len(polylines) == 6
    assert all(p.shape == (2, 3) for p in polylines)
    for p in polylines:
        np.testing.assert_allclose(p[:, 2], [5.0, 6.0], rtol=0.0, atol=1e-6)


def test_mirror3d_azimuth_n1_produces_two_polylines() -> None:
    g = G.mirror3d_test_line_in_wedge_posz()
    out = realize(E.mirror3d(mode="azimuth", n_azimuth=1, show_planes=False)(g))
    polylines = list(_iter_polylines(out))
    assert len(polylines) == 2


def test_mirror3d_equator_source_side_selects_halfspace() -> None:
    g = G.mirror3d_test_line_in_wedge_negz()

    # z<0 のみを持つ入力に対して「正側をソース」にすると、何も残らない。
    out_pos = realize(
        E.mirror3d(
            mode="azimuth",
            n_azimuth=3,
            center=(0.0, 0.0, 0.0),
            axis=(0.0, 0.0, 1.0),
            phi0=0.0,
            mirror_equator=True,
            source_side=True,
            show_planes=False,
        )(g)
    )
    assert out_pos.coords.shape == (0, 3)
    assert out_pos.offsets.shape == (1,)

    # 「負側をソース」にすると、2n から赤道ミラーで倍になり 4n になる。
    out_neg = realize(
        E.mirror3d(
            mode="azimuth",
            n_azimuth=3,
            center=(0.0, 0.0, 0.0),
            axis=(0.0, 0.0, 1.0),
            phi0=0.0,
            mirror_equator=True,
            source_side=False,
            show_planes=False,
        )(g)
    )

    polylines = list(_iter_polylines(out_neg))
    assert len(polylines) == 12
    z0 = np.array([float(p[0, 2]) for p in polylines], dtype=np.float64)
    assert np.any(z0 < 0.0)
    assert np.any(z0 > 0.0)


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("T", 12),
        ("O", 24),
        ("I", 60),
    ],
)
def test_mirror3d_polyhedral_rotation_group_sizes(group: str, expected: int) -> None:
    g = G.mirror3d_test_line_pos_octant()
    out = realize(
        E.mirror3d(
            mode="polyhedral",
            group=group,
            center=(0.0, 0.0, 0.0),
            use_reflection=False,
            show_planes=False,
        )(g)
    )
    polylines = list(_iter_polylines(out))
    assert len(polylines) == expected


def test_mirror3d_polyhedral_use_reflection_doubles() -> None:
    g = G.mirror3d_test_line_pos_octant()
    out = realize(
        E.mirror3d(
            mode="polyhedral",
            group="T",
            center=(0.0, 0.0, 0.0),
            use_reflection=True,
            show_planes=False,
        )(g)
    )
    polylines = list(_iter_polylines(out))
    assert len(polylines) == 24


def test_mirror3d_show_planes_adds_lines() -> None:
    g = G.mirror3d_test_line_in_wedge_posz()
    out0 = realize(E.mirror3d(mode="azimuth", n_azimuth=3, show_planes=False)(g))
    out1 = realize(E.mirror3d(mode="azimuth", n_azimuth=3, show_planes=True)(g))

    n0 = len(list(_iter_polylines(out0)))
    n1 = len(list(_iter_polylines(out1)))
    assert n1 > n0


def test_mirror3d_polyhedral_rotation_mats_are_bounded_readonly_cache() -> None:
    _polyhedral_rotation_mats.cache_clear()

    first_results = {
        group: _polyhedral_rotation_mats(group) for group in ("T", "O", "I")
    }
    assert [len(first_results[group]) for group in ("T", "O", "I")] == [12, 24, 60]
    assert _polyhedral_rotation_mats.cache_info().currsize == 3
    assert _polyhedral_rotation_mats.cache_info().maxsize == 3
    assert all(
        not matrix.flags.writeable
        for matrices in first_results.values()
        for matrix in matrices
    )

    for group, matrices in first_results.items():
        assert _polyhedral_rotation_mats(group) is matrices
    assert _polyhedral_rotation_mats.cache_info().hits == 3


def test_mirror3d_dedup_keeps_first_line_with_same_quantized_bytes() -> None:
    first = np.array(
        [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]],
        dtype=np.float32,
    )
    same_bucket = np.asfortranarray(first + np.float32(1e-8))
    distinct = first + np.float32(2e-6)

    result = _dedup_lines([first, same_bucket, distinct])

    assert len(result) == 2
    assert result[0] is first
    assert result[1] is distinct


def test_mirror3d_packed_polyhedral_transform_matches_generic_bits() -> None:
    center = np.array([0.25, -0.5, 1.25], dtype=np.float32)
    mats = _polyhedral_rotation_mats("I")
    lines = [
        np.array(
            [[index + 0.1, index + 1.2, index + 2.3], [3.4, 4.5, 5.6]],
            dtype=np.float32,
        )
        for index in range(40)
    ]

    actual = _packed_polyhedral_transforms(lines, mats=mats, center=center)
    assert actual is not None

    expected = []
    for line in lines:
        local = line - center
        for matrix in mats:
            expected.append(
                (local @ matrix.T + center).astype(np.float32, copy=False)
            )

    assert len(actual) == len(expected)
    for actual_line, expected_line in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(
            actual_line.view(np.uint32),
            expected_line.view(np.uint32),
        )


def test_mirror3d_packed_polyhedral_transform_falls_back_safely() -> None:
    center = np.zeros((3,), dtype=np.float32)
    mats = _polyhedral_rotation_mats("T")
    line = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)

    assert (
        _packed_polyhedral_transforms([line] * 31, mats=mats, center=center)
        is None
    )

    nonfinite = [line.copy() for _ in range(40)]
    nonfinite[7][0, 0] = np.nan
    assert (
        _packed_polyhedral_transforms(nonfinite, mats=mats, center=center) is None
    )

    nonstandard = [np.asfortranarray(line) for _ in range(40)]
    assert (
        _packed_polyhedral_transforms(nonstandard, mats=mats, center=center) is None
    )


def test_mirror3d_packed_dedup_matches_generic_and_keeps_first_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unique = [
        np.array(
            [[index * 0.1, 1.0, 2.0], [3.0, 4.0, 5.0]],
            dtype=np.float32,
        )
        for index in range(20)
    ]
    lines = [unique[index % len(unique)] for index in range(80)]

    actual = _dedup_lines(lines)
    monkeypatch.setattr(
        "grafix.core.effects.mirror3d._PACKED_DEDUP_MIN_LINES",
        np.iinfo(np.int64).max,
    )
    expected = _dedup_lines(lines)

    assert len(actual) == len(expected)
    assert all(
        actual_line is expected_line
        for actual_line, expected_line in zip(actual, expected, strict=True)
    )
    assert actual[0] is lines[0]


def test_mirror3d_packed_dedup_falls_back_for_nonfinite_and_nonstandard() -> None:
    line = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
    assert _dedup_uniform_finite_lines([line] * 63) is None

    nonfinite = [line.copy() for _ in range(64)]
    nonfinite[5][0, 1] = np.inf
    assert _dedup_uniform_finite_lines(nonfinite) is None

    nonstandard = [np.asfortranarray(line) for _ in range(64)]
    assert _dedup_uniform_finite_lines(nonstandard) is None
