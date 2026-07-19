"""mirror effect（対称ミラー）の実体変換に関するテスト群。"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


@primitive
def mirror_test_cross_x0() -> GeomTuple:
    """x=0 を跨ぐ 2 点ポリラインを返す（z は非整数）。"""
    coords = np.array([[-1.0, 0.0, 1.0], [1.0, 0.0, 2.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def mirror_test_quadrant_pp() -> GeomTuple:
    """(+x,+y) 象限の 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 2.0, 3.0], [4.0, 6.0, 7.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def mirror_test_wedge_n3() -> GeomTuple:
    """n=3 の楔内にある短い 2 点ポリラインを返す。"""
    coords = np.array([[2.0, 0.2, 5.0], [2.0, 0.4, 6.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


def _iter_polylines(realized: RealizedGeometry):
    offsets = realized.offsets
    for i in range(len(offsets) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        yield realized.coords[s:e]


def _mirror_contract_geometry() -> GeomTuple:
    coords = np.asarray(
        [
            [-2.0, -1.0, 1.0],
            [0.0, 0.0, 2.0],
            [2.0, 1.0, 3.0],
            [1.0, 0.0, 4.0],
            [2.0, 0.0, 5.0],
            [0.0, 0.0, 6.0],
            [1.0, 1.0, 7.0],
            [1.0, 1.0, 8.0],
        ],
        dtype=np.float32,
    )
    offsets = np.asarray([0, 3, 5, 6, 6, 8], dtype=np.int32)
    return coords, offsets


@pytest.mark.parametrize(
    ("kwargs", "expected_shape", "expected_sha256"),
    [
        (
            {"n_mirror": 1, "cx": 0.25, "source_positive_x": True},
            (12, 3),
            "5de9a5e38297e06720de5082cfc304b279989edb5d703239bff0efc73d07f595",
        ),
        (
            {
                "n_mirror": 2,
                "cx": 0.25,
                "cy": -0.25,
                "source_positive_x": False,
                "source_positive_y": True,
            },
            (16, 3),
            "c39b2917738e194dc09dff2afe297ee1360e78a4e127bfbafc534b15f3f6fcb0",
        ),
        (
            {"n_mirror": 3, "cx": 0.0, "cy": 0.0},
            (37, 3),
            "6e96505a92053744377ad08225b837cf6370ac177558e35d8e88574dca49c1e2",
        ),
        (
            {"n_mirror": 8, "cx": 0.0, "cy": 0.0, "show_planes": True},
            (51, 3),
            "5701d587f303d3a5c33b37364cadafbeeba6b04fe8c9fe65fc850dab724abf02",
        ),
    ],
)
def test_mirror_matches_frozen_piece_copy_dedup_and_plane_order(
    kwargs: dict[str, object],
    expected_shape: tuple[int, int],
    expected_sha256: str,
) -> None:
    import grafix.core.effects.mirror as module

    coords, offsets = _mirror_contract_geometry()
    before = (coords.tobytes(), offsets.tobytes())
    with operation_diagnostic_context() as diagnostics:
        actual = module.mirror((coords, offsets), **kwargs)

    digest = hashlib.sha256(actual[0].tobytes() + actual[1].tobytes())
    assert actual[0].shape == expected_shape
    assert digest.hexdigest() == expected_sha256
    assert diagnostics.snapshot() == ()
    assert (coords.tobytes(), offsets.tobytes()) == before


def test_mirror_packed_halfplane_matches_frozen_boundary_cases() -> None:
    import grafix.core.effects.mirror as module

    outside = np.nextafter(
        np.float32(-module.EPS),
        np.float32(-np.inf),
    )
    coords = np.asarray(
        [
            [-2.0, -1.0, 1.0],
            [0.0, np.float32(-module.EPS), 2.0],
            [2.0, 1.0, 3.0],
            [1.0, outside, 4.0],
            [1.0, np.float32(-module.EPS), 5.0],
            [np.nan, 2.0, 6.0],
            [1.0, 2.0, 7.0],
            [1.0, 2.0, 7.0],
        ],
        dtype=np.float32,
    )
    offsets = np.asarray([0, 3, 3, 4, 5, 7, 8], dtype=np.int32)

    actual_coords, actual_offsets = module._clip_polylines_halfplane_nb(
        coords,
        offsets,
        0.0,
        0.0,
        0.0,
        1.0,
    )

    digest = hashlib.sha256(actual_coords.tobytes() + actual_offsets.tobytes())
    assert actual_coords.shape == (7, 3)
    np.testing.assert_array_equal(
        actual_offsets,
        np.asarray([0, 3, 4, 6, 7], dtype=np.int32),
    )
    assert (
        digest.hexdigest()
        == "39168b3684108b0fe8cb85f718190b0bfc3ee1e24a71d2a66dd7593bf1913a34"
    )


def test_mirror_include_boundary_uses_exact_eps_threshold() -> None:
    import grafix.core.effects.mirror as module

    inside = np.float32(-module.EPS)
    outside = np.nextafter(inside, np.float32(-np.inf))
    coords = np.asarray(
        [[0.0, inside, 1.0], [0.0, outside, 2.0]],
        dtype=np.float32,
    )
    offsets = np.asarray([0, 1, 2], dtype=np.int32)

    clipped, clipped_offsets = module._clip_polylines_halfplane_nb(
        coords,
        offsets,
        0.0,
        0.0,
        0.0,
        1.0,
    )

    assert clipped.tobytes() == coords[:1].tobytes()
    np.testing.assert_array_equal(clipped_offsets, np.asarray([0, 1], np.int32))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_mirror": 0},
        {"n_mirror": 8, "cx": np.nan},
        {"n_mirror": 8, "cy": np.inf},
    ],
)
def test_mirror_invalid_parameters_preserve_input_identity(
    kwargs: dict[str, object],
) -> None:
    import grafix.core.effects.mirror as module

    coords, offsets = _mirror_contract_geometry()
    before = (coords.tobytes(), offsets.tobytes())
    with operation_diagnostic_context() as diagnostics:
        actual = module.mirror((coords, offsets), **kwargs)

    assert actual[0] is coords
    assert actual[1] is offsets
    assert diagnostics.snapshot() == ()
    assert (coords.tobytes(), offsets.tobytes()) == before


def test_mirror_n1_clips_and_reflects_across_x_plane() -> None:
    g = G.mirror_test_cross_x0()
    mirrored = realize(E.mirror(n_mirror=1, cx=0.0, source_positive_x=True, show_planes=False)(g))

    polylines = list(_iter_polylines(mirrored))
    assert len(polylines) == 2
    assert [p.shape[0] for p in polylines] == [2, 2]

    p0, p1 = polylines
    np.testing.assert_allclose(p0[0], [0.0, 0.0, 1.5], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(p0[1], [1.0, 0.0, 2.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(p1[0], [0.0, 0.0, 1.5], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(p1[1], [-1.0, 0.0, 2.0], rtol=0.0, atol=1e-6)


def test_mirror_n2_generates_four_quadrants_and_preserves_z() -> None:
    g = G.mirror_test_quadrant_pp()
    mirrored = realize(
        E.mirror(
            n_mirror=2,
            cx=0.0,
            cy=0.0,
            source_positive_x=True,
            source_positive_y=True,
            show_planes=False,
        )(g)
    )

    polylines = list(_iter_polylines(mirrored))
    assert len(polylines) == 4

    endpoints = {(float(p[0, 0]), float(p[0, 1]), float(p[1, 0]), float(p[1, 1])) for p in polylines}
    assert endpoints == {
        (1.0, 2.0, 4.0, 6.0),
        (-1.0, 2.0, -4.0, 6.0),
        (1.0, -2.0, 4.0, -6.0),
        (-1.0, -2.0, -4.0, -6.0),
    }
    for p in polylines:
        np.testing.assert_allclose(p[:, 2], [3.0, 7.0], rtol=0.0, atol=1e-6)


def test_mirror_n3_produces_2n_polylines() -> None:
    g = G.mirror_test_wedge_n3()
    mirrored = realize(E.mirror(n_mirror=3, cx=0.0, cy=0.0, show_planes=False)(g))

    polylines = list(_iter_polylines(mirrored))
    assert len(polylines) == 6
    assert all(p.shape == (2, 3) for p in polylines)
