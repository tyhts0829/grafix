"""warp effect の実体変換に関するテスト群。"""

from __future__ import annotations

import importlib

import numba
import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.effects.warp import (
    _build_ring_edge_invariants,
    _evaluate_sdf_points_numba,
    _evaluate_signed_distances_numba,
    warp,
)
from grafix.core.realize import realize

warp_module = importlib.import_module("grafix.core.effects.warp")


def _regular_ring(n_sides: int, radius: float) -> np.ndarray:
    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        num=n_sides,
        endpoint=False,
        dtype=np.float64,
    )
    coords = np.empty((n_sides + 1, 3), dtype=np.float32)
    coords[:-1, 0] = (radius * np.cos(angles)).astype(np.float32)
    coords[:-1, 1] = (radius * np.sin(angles)).astype(np.float32)
    coords[:-1, 2] = 0.0
    coords[-1] = coords[0]
    return coords


def _two_ring_mask(
    outer_sides: int = 96,
    inner_sides: int = 48,
) -> tuple[np.ndarray, np.ndarray]:
    outer = _regular_ring(outer_sides, 80.0)
    inner = _regular_ring(inner_sides, 25.0)
    coords = np.concatenate((outer, inner), axis=0)
    offsets = np.array([0, outer.shape[0], coords.shape[0]], dtype=np.int32)
    return coords, offsets


def test_warp_requires_two_inputs() -> None:
    a = G.line(length=100.0)
    with pytest.raises(TypeError):
        E.warp()(a)


def test_warp_lens_noop_when_mask_has_no_valid_rings() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    mask = G.line(length=100.0)

    out = realize(E.warp(mode="lens")(base, mask))
    expected = realize(base)

    np.testing.assert_allclose(out.coords, expected.coords, rtol=0.0, atol=1e-6)
    assert out.offsets.tolist() == expected.offsets.tolist()


def test_warp_lens_deforms_points_inside_and_keeps_outside() -> None:
    base = G.line(center=(40.0, 0.0, 0.0), anchor="left", length=60.0, angle=0.0)
    mask = G.polygon(n_sides=64, scale=100.0)

    out = realize(
        E.warp(
            mode="lens",
            kind="scale",
            scale=2.0,
            strength=1.0,
            profile="band",
            band=20.0,
            inside_only=True,
        )(base, mask)
    )
    expected = realize(base)

    assert out.offsets.tolist() == expected.offsets.tolist()

    moved = float(np.linalg.norm(out.coords[0, 0:2] - expected.coords[0, 0:2]))
    stayed = float(np.linalg.norm(out.coords[1, 0:2] - expected.coords[1, 0:2]))
    assert moved > 1e-3
    assert stayed < 1e-6


def test_warp_show_mask_appends_mask_geom_even_when_noop() -> None:
    base = G.line(length=10.0)
    mask = G.polygon(n_sides=6, scale=20.0)

    out = realize(E.warp(mode="lens", strength=0.0, show_mask=True)(base, mask))
    expected_base = realize(base)
    expected_mask = realize(mask)

    n0 = int(expected_base.coords.shape[0])
    n1 = int(expected_mask.coords.shape[0])

    assert out.offsets.tolist() == [0, n0, n0 + n1]
    np.testing.assert_allclose(out.coords[0:n0], expected_base.coords, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(out.coords[n0 : n0 + n1], expected_mask.coords, rtol=0.0, atol=1e-6)


def test_warp_keep_original_and_show_mask_appends_in_order() -> None:
    base = G.line(length=10.0)
    mask = G.polygon(n_sides=6, scale=20.0)

    out = realize(
        E.warp(
            mode="lens",
            kind="scale",
            scale=2.0,
            strength=1.0,
            band=0.0,
            keep_original=True,
            show_mask=True,
        )(base, mask)
    )
    expected_base = realize(base)
    expected_mask = realize(mask)

    n0 = int(expected_base.coords.shape[0])
    n1 = int(expected_mask.coords.shape[0])

    assert out.offsets.tolist() == [0, n0, n0 + n0, n0 + n0 + n1]
    np.testing.assert_allclose(out.coords[n0 : n0 + n0], expected_base.coords, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(
        out.coords[n0 + n0 : n0 + n0 + n1], expected_mask.coords, rtol=0.0, atol=1e-6
    )


def test_warp_attract_projects_line_endpoints_to_mask_boundary() -> None:
    base = G.line(center=(0.0, 0.0, 0.0), length=80.0, angle=0.0)
    mask = G.polygon(n_sides=64, scale=50.0)

    out = realize(
        E.warp(
            mode="attract",
            direction="attract",
            strength=1.0,
            bias=0.0,
            snap_band=0.0,
            falloff=0.0,
        )(base, mask)
    )

    assert out.coords.shape == (2, 3)
    assert out.offsets.tolist() == [0, 2]
    np.testing.assert_allclose(out.coords[:, 2], 0.0, rtol=0.0, atol=1e-6)

    # polygon(scale=50) は半径 25（=0.5*scale）。
    np.testing.assert_allclose(out.coords[0], (-25.0, 0.0, 0.0), rtol=0.0, atol=1e-4)
    np.testing.assert_allclose(out.coords[1], (25.0, 0.0, 0.0), rtol=0.0, atol=1e-4)


def test_warp_pruned_distance_kernel_matches_full_sdf_bits() -> None:
    outer = _regular_ring(40, 80.0)[:, :2].astype(np.float64)
    outer = np.insert(outer, 7, outer[7], axis=0)
    hole = _regular_ring(20, 25.0)[:, :2].astype(np.float64)
    far = _regular_ring(24, 12.0)[:, :2].astype(np.float64)
    far[:, 0] += 240.0
    ring_vertices = np.concatenate((outer, hole, far), axis=0)
    ring_offsets = np.array(
        [0, outer.shape[0], outer.shape[0] + hole.shape[0], ring_vertices.shape[0]],
        dtype=np.int32,
    )

    ring_mins = np.empty((3, 2), dtype=np.float64)
    ring_maxs = np.empty((3, 2), dtype=np.float64)
    for ring_index in range(3):
        start = int(ring_offsets[ring_index])
        stop = int(ring_offsets[ring_index + 1])
        ring_mins[ring_index] = np.min(ring_vertices[start:stop], axis=0)
        ring_maxs[ring_index] = np.max(ring_vertices[start:stop], axis=0)

    xs = np.linspace(-100.0, 270.0, num=257, dtype=np.float64)
    points_xy = np.stack((xs, 33.0 * np.sin(xs * 0.07)), axis=1)
    points_xy = np.concatenate(
        (
            points_xy,
            ring_vertices,
            np.array([[0.0, 0.0], [25.0, 0.0], [80.0, 0.0]], dtype=np.float64),
        ),
        axis=0,
    )

    expected, _, _ = _evaluate_sdf_points_numba(
        points_xy,
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
    )
    edge_dx, edge_dy, edge_denom, edge_bounds = _build_ring_edge_invariants(
        ring_vertices
    )
    actual = _evaluate_signed_distances_numba(
        points_xy,
        ring_vertices,
        edge_dx,
        edge_dy,
        edge_denom,
        edge_bounds,
        ring_offsets,
        ring_mins,
        ring_maxs,
    )

    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


def test_warp_distance_only_thread_counts_are_exact() -> None:
    ring_vertices = _regular_ring(96, 80.0)[:, :2].astype(np.float64)
    ring_offsets = np.array([0, ring_vertices.shape[0]], dtype=np.int32)
    ring_mins = np.min(ring_vertices, axis=0)[None, :]
    ring_maxs = np.max(ring_vertices, axis=0)[None, :]
    xs = np.linspace(-110.0, 110.0, num=513, dtype=np.float64)
    points_xy = np.stack((xs, 37.0 * np.sin(xs * 0.043)), axis=1)
    edge_invariants = _build_ring_edge_invariants(ring_vertices)
    expected, _, _ = _evaluate_sdf_points_numba(
        points_xy,
        ring_vertices,
        ring_offsets,
        ring_mins,
        ring_maxs,
    )

    previous_threads = numba.get_num_threads()
    maximum_threads = int(numba.config.NUMBA_NUM_THREADS)
    try:
        for thread_count in (1, 2, 4):
            if thread_count > maximum_threads:
                continue
            numba.set_num_threads(thread_count)
            actual = _evaluate_signed_distances_numba(
                points_xy,
                ring_vertices,
                *edge_invariants,
                ring_offsets,
                ring_mins,
                ring_maxs,
            )
            np.testing.assert_array_equal(
                actual.view(np.uint64),
                expected.view(np.uint64),
            )
    finally:
        numba.set_num_threads(previous_threads)


def test_warp_lens_resource_gate_threshold_sides() -> None:
    min_points = warp_module._LENS_OPTIMIZED_MIN_BASE_POINTS
    min_work = warp_module._LENS_OPTIMIZED_MIN_POINT_SEGMENTS
    assert not warp_module._use_optimized_lens_path(
        base_point_count=min_points - 1,
        segment_count=min_work,
        edge_count=1,
    )
    assert warp_module._use_optimized_lens_path(
        base_point_count=min_points,
        segment_count=(min_work + min_points - 1) // min_points,
        edge_count=1,
    )

    assert not warp_module._use_optimized_lens_path(
        base_point_count=min_work - 1,
        segment_count=1,
        edge_count=1,
    )
    assert warp_module._use_optimized_lens_path(
        base_point_count=min_work,
        segment_count=1,
        edge_count=1,
    )

    edge_bytes = warp_module._LENS_EDGE_SCRATCH_BYTES_PER_SEGMENT
    max_edges = warp_module._LENS_MAX_EDGE_SCRATCH_BYTES // edge_bytes
    assert warp_module._use_optimized_lens_path(
        base_point_count=min_work,
        segment_count=1,
        edge_count=max_edges,
    )
    assert not warp_module._use_optimized_lens_path(
        base_point_count=min_work,
        segment_count=1,
        edge_count=max_edges + 1,
    )
    assert not warp_module._use_optimized_lens_path(
        base_point_count=1,
        segment_count=max_edges + 1,
        edge_count=max_edges + 1,
    )


@pytest.mark.parametrize("gate", ("base_points", "edge_scratch"))
def test_warp_lens_gate_boundary_paths_match_bits(
    monkeypatch: pytest.MonkeyPatch,
    gate: str,
) -> None:
    point_count = 320
    x = np.linspace(-90.0, 90.0, num=point_count, dtype=np.float32)
    base_coords = np.stack(
        (x, (29.0 * np.sin(x * 0.061)).astype(np.float32), np.zeros_like(x)),
        axis=1,
    )
    base_offsets = np.array([0, point_count], dtype=np.int32)
    mask = _two_ring_mask()
    kwargs = {
        "mode": "lens",
        "kind": "rotate",
        "angle": 31.25,
        "profile": "band",
        "band": 21.0,
        "strength": 0.91,
    }
    monkeypatch.setattr(
        warp_module,
        "_LENS_OPTIMIZED_MIN_POINT_SEGMENTS",
        0,
    )

    if gate == "base_points":
        monkeypatch.setattr(
            warp_module,
            "_LENS_MAX_EDGE_SCRATCH_BYTES",
            np.iinfo(np.int64).max,
        )
        monkeypatch.setattr(
            warp_module,
            "_LENS_OPTIMIZED_MIN_BASE_POINTS",
            point_count,
        )
        optimized, optimized_offsets = warp(
            (base_coords, base_offsets),
            mask,
            **kwargs,
        )
        monkeypatch.setattr(
            warp_module,
            "_LENS_OPTIMIZED_MIN_BASE_POINTS",
            point_count + 1,
        )
    else:
        monkeypatch.setattr(
            warp_module,
            "_LENS_OPTIMIZED_MIN_BASE_POINTS",
            0,
        )
        edge_count = mask[0].shape[0] - 1
        scratch_bytes = warp_module._lens_edge_scratch_bytes(edge_count)
        monkeypatch.setattr(
            warp_module,
            "_LENS_MAX_EDGE_SCRATCH_BYTES",
            scratch_bytes,
        )
        optimized, optimized_offsets = warp(
            (base_coords, base_offsets),
            mask,
            **kwargs,
        )
        monkeypatch.setattr(
            warp_module,
            "_LENS_MAX_EDGE_SCRATCH_BYTES",
            scratch_bytes - 1,
        )

    fallback, fallback_offsets = warp(
        (base_coords, base_offsets),
        mask,
        **kwargs,
    )
    np.testing.assert_array_equal(
        optimized.view(np.uint32),
        fallback.view(np.uint32),
    )
    assert optimized_offsets is base_offsets
    assert fallback_offsets is base_offsets


def test_warp_one_point_lens_does_not_build_edge_scratch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_coords = np.array([[35.0, 4.0, 0.0]], dtype=np.float32)
    base_offsets = np.array([0, 1], dtype=np.int32)
    mask_coords = _regular_ring(512, 80.0)
    mask_offsets = np.array([0, mask_coords.shape[0]], dtype=np.int32)

    def fail(_vertices: np.ndarray) -> tuple[np.ndarray, ...]:
        raise AssertionError("one-point lens must use the scratch-free fallback")

    monkeypatch.setattr(warp_module, "_build_ring_edge_invariants", fail)
    coords, offsets = warp(
        (base_coords, base_offsets),
        (mask_coords, mask_offsets),
        mode="lens",
        kind="scale",
        scale=1.25,
        band=20.0,
    )

    assert coords.shape == base_coords.shape
    assert offsets is base_offsets


@pytest.mark.parametrize("profile", ("band", "ramp"))
@pytest.mark.parametrize(
    ("kind", "kind_kwargs"),
    (
        ("scale", {"scale": 1.37}),
        ("rotate", {"angle": 33.25}),
        ("shear", {"shear": (0.21, -0.17, 0.9)}),
        ("swirl", {"angle": 27.5}),
    ),
)
def test_warp_optimized_lens_matches_full_sdf_path_bits(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    kind_kwargs: dict[str, object],
    profile: str,
) -> None:
    x = np.linspace(-90.0, 90.0, num=800, dtype=np.float32)
    base_coords = np.stack(
        (x, (35.0 * np.sin(x * 0.05)).astype(np.float32), np.zeros_like(x)),
        axis=1,
    )
    base_offsets = np.array([0, base_coords.shape[0]], dtype=np.int32)
    mask = _two_ring_mask()
    kwargs = {
        "mode": "lens",
        "kind": kind,
        "profile": profile,
        "band": 23.5,
        "strength": 0.83,
        **kind_kwargs,
    }

    optimized_coords, optimized_offsets = warp(
        (base_coords, base_offsets),
        mask,
        **kwargs,
    )
    monkeypatch.setattr(
        warp_module,
        "_LENS_OPTIMIZED_MIN_POINT_SEGMENTS",
        np.iinfo(np.int64).max,
    )
    reference_coords, reference_offsets = warp(
        (base_coords, base_offsets),
        mask,
        **kwargs,
    )

    np.testing.assert_array_equal(
        optimized_coords.view(np.uint32),
        reference_coords.view(np.uint32),
    )
    assert optimized_offsets is base_offsets
    assert reference_offsets is base_offsets


def test_warp_lens_zeros_local_z_while_attract_preserves_it() -> None:
    mask_coords = np.array(
        [
            [-10.0, -10.0, 0.0],
            [10.0, -10.0, 0.0],
            [10.0, 10.0, 0.0],
            [-10.0, 10.0, 0.0],
            [-10.0, -10.0, 0.0],
        ],
        dtype=np.float32,
    )
    mask_offsets = np.array([0, 5], dtype=np.int32)
    base_coords = np.array(
        [[-2.0, 1.0, 1e-4], [3.0, -1.0, 1e-4]],
        dtype=np.float32,
    )
    base_offsets = np.array([0, 2], dtype=np.int32)

    lens_coords, lens_offsets = warp(
        (base_coords, base_offsets),
        (mask_coords, mask_offsets),
        mode="lens",
        kind="scale",
        scale=1.2,
        band=0.0,
        inside_only=False,
    )
    attract_coords, attract_offsets = warp(
        (base_coords, base_offsets),
        (mask_coords, mask_offsets),
        mode="attract",
        direction="attract",
        strength=0.5,
        snap_band=0.0,
        falloff=0.0,
    )

    np.testing.assert_array_equal(lens_coords[:, 2], np.zeros((2,), dtype=np.float32))
    np.testing.assert_array_equal(
        attract_coords[:, 2].view(np.uint32),
        base_coords[:, 2].view(np.uint32),
    )
    assert lens_offsets is base_offsets
    assert attract_offsets is base_offsets
