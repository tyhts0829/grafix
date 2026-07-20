"""buffer/partition が共有する canonical planar frame 契約を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.core.effects.buffer import buffer
from grafix.core.effects.partition import partition
from grafix.core.effects.util import (
    canonical_planar_frame,
    planarity_threshold,
)

pytest.importorskip("shapely")


def _geometry(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    coords = np.asarray(points, dtype=np.float32)
    return coords, np.asarray([0, coords.shape[0]], dtype=np.int32)


def _square() -> np.ndarray:
    return np.asarray(
        [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
            (-1.0, -1.0, 0.0),
        ],
        dtype=np.float64,
    )


def _plane_transforms() -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    identity = np.eye(3, dtype=np.float64)
    xz = np.asarray(
        (
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, -1.0, 0.0),
        ),
        dtype=np.float64,
    )
    u = np.asarray((1.0, 1.0, 0.0), dtype=np.float64)
    u /= np.linalg.norm(u)
    normal = np.asarray((1.0, -1.0, 1.0), dtype=np.float64)
    normal /= np.linalg.norm(normal)
    v = np.cross(normal, u)
    oblique = np.stack((u, v, normal), axis=0)
    return (
        (identity, np.zeros((3,), dtype=np.float64)),
        (xz, np.asarray((2.0, -3.0, 4.0), dtype=np.float64)),
        (oblique, np.asarray((-4.0, 2.0, 3.0), dtype=np.float64)),
    )


def _to_world(
    local_points: np.ndarray,
    transform: np.ndarray,
    translation: np.ndarray,
) -> np.ndarray:
    return np.asarray(local_points, dtype=np.float64) @ transform + translation


def _to_local(
    world_points: np.ndarray,
    transform: np.ndarray,
    translation: np.ndarray,
) -> np.ndarray:
    return (
        np.asarray(world_points, dtype=np.float64) - translation
    ) @ transform.T


def _point_signature(points: np.ndarray) -> np.ndarray:
    rounded = np.round(np.asarray(points, dtype=np.float64), decimals=5)
    return np.unique(rounded, axis=0)


@pytest.mark.parametrize(("transform", "translation"), _plane_transforms())
def test_buffer_projects_xy_xz_and_oblique_inputs_to_their_source_plane(
    transform: np.ndarray,
    translation: np.ndarray,
) -> None:
    source = _to_world(_square(), transform, translation)

    coords, offsets = buffer(
        _geometry(source),
        distance=0.2,
        quad_segs=2,
        join="mitre",
    )

    assert offsets.tolist() == [0, coords.shape[0]]
    local = _to_local(coords, transform, translation)
    np.testing.assert_allclose(local[:, 2], 0.0, rtol=0.0, atol=2e-6)
    assert float(np.min(local[:, 0])) == pytest.approx(-1.2, abs=2e-6)
    assert float(np.max(local[:, 0])) == pytest.approx(1.2, abs=2e-6)
    assert float(np.min(local[:, 1])) == pytest.approx(-1.2, abs=2e-6)
    assert float(np.max(local[:, 1])) == pytest.approx(1.2, abs=2e-6)


def test_buffer_is_independent_of_closed_ring_winding_and_seam() -> None:
    core = _square()[:-1]
    variants = (
        np.concatenate((core, core[:1]), axis=0),
        np.concatenate((core[::-1], core[-1:]), axis=0),
        np.concatenate((np.roll(core, -2, axis=0), core[2:3]), axis=0),
    )

    signatures = [
        _point_signature(
            buffer(
                _geometry(points),
                distance=0.2,
                quad_segs=3,
                join="round",
            )[0]
        )
        for points in variants
    ]

    np.testing.assert_array_equal(signatures[1], signatures[0])
    np.testing.assert_array_equal(signatures[2], signatures[0])


def test_buffer_linear_policy_is_direction_independent() -> None:
    points = np.asarray(
        ((-1.0, -2.0, -3.0), (2.0, 1.0, 3.0)),
        dtype=np.float64,
    )

    forward = buffer(_geometry(points), distance=0.25, quad_segs=3)[0]
    backward = buffer(_geometry(points[::-1]), distance=0.25, quad_segs=3)[0]

    assert forward.shape[0] > 2
    np.testing.assert_array_equal(
        _point_signature(backward),
        _point_signature(forward),
    )
    frame = canonical_planar_frame(points, allow_linear=True)
    assert frame.is_planar(1e-12)
    np.testing.assert_allclose(
        (forward.astype(np.float64) - frame.origin) @ frame.normal,
        0.0,
        rtol=0.0,
        atol=2e-6,
    )


@pytest.mark.parametrize("height", [1e-6, 0.4])
def test_buffer_explicitly_projects_near_planar_and_spatial_inputs(
    height: float,
) -> None:
    points = _square()
    points[2, 2] = height
    source = _geometry(points)
    frame = canonical_planar_frame(source[0], source[1])
    assert frame.valid

    coords, offsets = buffer(source, distance=0.15, quad_segs=2)

    assert offsets.tolist() == [0, coords.shape[0]]
    assert coords.shape[0] > points.shape[0]
    np.testing.assert_allclose(
        (coords.astype(np.float64) - frame.origin) @ frame.normal,
        0.0,
        rtol=0.0,
        atol=2e-6,
    )


@pytest.mark.parametrize(("transform", "translation"), _plane_transforms())
def test_partition_accepts_xy_xz_and_oblique_planar_inputs(
    transform: np.ndarray,
    translation: np.ndarray,
) -> None:
    source = _to_world(_square(), transform, translation)

    coords, offsets = partition(
        _geometry(source),
        site_count=8,
        seed=7,
    )

    assert offsets.size > 2
    local = _to_local(coords, transform, translation)
    np.testing.assert_allclose(local[:, 2], 0.0, rtol=0.0, atol=3e-6)
    assert bool(np.all(local[:, :2] >= -1.0 - 3e-6))
    assert bool(np.all(local[:, :2] <= 1.0 + 3e-6))


def test_partition_is_independent_of_closed_ring_winding_and_seam() -> None:
    core = _square()[:-1]
    variants = (
        np.concatenate((core, core[:1]), axis=0),
        np.concatenate((core[::-1], core[-1:]), axis=0),
        np.concatenate((np.roll(core, -2, axis=0), core[2:3]), axis=0),
    )

    results = [
        partition(_geometry(points), site_count=8, seed=7)
        for points in variants
    ]

    for coords, offsets in results[1:]:
        np.testing.assert_allclose(coords, results[0][0], rtol=0.0, atol=1e-6)
        np.testing.assert_array_equal(offsets, results[0][1])


def test_partition_accepts_near_planar_input_at_shared_tolerance() -> None:
    points = _square()
    points[2, 2] = 1e-6
    source = _geometry(points)
    frame = canonical_planar_frame(source[0], source[1])
    assert frame.is_planar(planarity_threshold(source[0]))

    coords, offsets = partition(source, site_count=8, seed=7)

    assert offsets.size > 2
    assert coords.shape != source[0].shape


def test_partition_rejects_nonplanar_and_linear_inputs_without_projection() -> None:
    nonplanar = _square()
    nonplanar[2, 2] = 0.4
    linear = np.asarray(
        (
            (-2.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
        ),
        dtype=np.float64,
    )

    for points in (nonplanar, linear):
        source = _geometry(points)
        coords, offsets = partition(source, site_count=8, seed=7)
        assert coords is source[0]
        assert offsets is source[1]
