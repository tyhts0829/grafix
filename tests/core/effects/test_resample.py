"""resample effect の弧長標本化と resource preflight を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.core.effects.resample import resample
from grafix.core.realized_geometry import GeomTuple
from grafix.core.resource_budget import (
    ResourceBudget,
    ResourceLimitError,
    resource_budget_context,
)


def _geom(lines: list[list[tuple[float, float, float]]]) -> GeomTuple:
    arrays = [np.asarray(line, dtype=np.float32).reshape((-1, 3)) for line in lines]
    coords = (
        np.concatenate(arrays, axis=0)
        if arrays
        else np.empty((0, 3), dtype=np.float32)
    )
    offsets = np.empty((len(arrays) + 1,), dtype=np.int32)
    offsets[0] = 0
    cursor = 0
    for index, line in enumerate(arrays):
        cursor += int(line.shape[0])
        offsets[index + 1] = cursor
    return coords, offsets


def test_resample_open_line_uses_target_step_and_preserves_endpoints() -> None:
    coords, offsets = _geom([[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]])

    out_coords, out_offsets = resample((coords, offsets), step=0.75, closed="open")

    np.testing.assert_allclose(
        out_coords,
        np.asarray(
            [
                [0.0, 0.0, 0.0],
                [0.75, 0.0, 0.0],
                [1.5, 0.0, 0.0],
                [2.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
        rtol=0.0,
        atol=1e-6,
    )
    assert out_offsets.tolist() == [0, 4]
    np.testing.assert_array_equal(out_coords[[0, -1]], coords[[0, -1]])


def test_resample_open_downsample_keeps_only_both_endpoints() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (0.5, 1.0, 0.0), (2.0, 0.0, 0.0)]]
    )

    out_coords, out_offsets = resample((coords, offsets), step=10.0, closed="open")

    np.testing.assert_array_equal(out_coords, coords[[0, 2]])
    assert out_offsets.tolist() == [0, 2]


def test_resample_uses_xyz_arc_length() -> None:
    coords, offsets = _geom([[(1.0, 2.0, 0.0), (1.0, 2.0, 2.0)]])

    out_coords, _ = resample((coords, offsets), step=0.5, closed="open")

    np.testing.assert_allclose(out_coords[:, 2], [0.0, 0.5, 1.0, 1.5, 2.0])
    np.testing.assert_array_equal(out_coords[:, :2], np.tile([1.0, 2.0], (5, 1)))


def test_resample_finite_float32_extremes_without_overflow() -> None:
    maximum = np.finfo(np.float32).max
    coords, offsets = _geom(
        [[(-maximum, 0.0, 0.0), (maximum, 0.0, 0.0)]]
    )

    out_coords, out_offsets = resample(
        (coords, offsets),
        step=2.0e38,
        closed="open",
    )

    assert out_offsets.tolist() == [0, 5]
    assert bool(np.all(np.isfinite(out_coords)))
    np.testing.assert_array_equal(out_coords[[0, -1]], coords)
    assert bool(np.all(np.diff(out_coords[:, 0].astype(np.float64)) > 0.0))


def test_resample_float32_extreme_exact_grid_is_identity() -> None:
    maximum = np.finfo(np.float32).max
    coords, offsets = _geom(
        [[(-maximum, 0.0, 0.0), (0.0, 0.0, 0.0), (maximum, 0.0, 0.0)]]
    )
    budget = ResourceBudget(
        max_output_vertices=0,
        max_output_lines=0,
        max_output_bytes=0,
    )

    with resource_budget_context(budget):
        out_coords, out_offsets = resample(
            (coords, offsets),
            step=float(maximum),
            closed="open",
        )

    assert out_coords is coords
    assert out_offsets is offsets


def test_resample_exact_closed_ring_is_strictly_closed() -> None:
    coords, offsets = _geom(
        [
            [
                (0.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
                (0.0, 0.0, 0.0),
            ]
        ]
    )

    out_coords, out_offsets = resample((coords, offsets), step=2.0)

    assert out_coords is coords
    assert out_offsets is offsets
    np.testing.assert_array_equal(out_coords, coords)
    assert out_offsets.tolist() == [0, 5]
    np.testing.assert_array_equal(out_coords[-1], out_coords[0])


def test_resample_near_closed_auto_replaces_last_point_with_exact_closure() -> None:
    coords, offsets = _geom(
        [
            [
                (0.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
                (0.005, 0.0, 0.0),
            ]
        ]
    )

    out_coords, _ = resample((coords, offsets), step=2.0, closed="auto")

    np.testing.assert_array_equal(out_coords[-1], out_coords[0])
    assert not np.array_equal(out_coords[-1], coords[-1])


def test_resample_forced_open_preserves_near_endpoint() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.005, 0.0, 0.0)]]
    )

    out_coords, _ = resample((coords, offsets), step=0.5, closed="open")

    np.testing.assert_array_equal(out_coords[0], coords[0])
    np.testing.assert_array_equal(out_coords[-1], coords[-1])


def test_resample_forced_closed_adds_closure_to_open_triangle() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)]]
    )

    out_coords, out_offsets = resample((coords, offsets), step=1.0, closed="closed")

    assert out_offsets.tolist() == [0, len(out_coords)]
    np.testing.assert_array_equal(out_coords[-1], out_coords[0])
    assert len(out_coords) >= 4


def test_resample_handles_mixed_empty_short_and_zero_length_lines() -> None:
    coords, offsets = _geom(
        [
            [],
            [(3.0, 4.0, 5.0)],
            [(7.0, 8.0, 9.0), (7.0, 8.0, 9.0), (7.0, 8.0, 9.0)],
        ]
    )

    out_coords, out_offsets = resample((coords, offsets), step=0.25, closed="open")

    assert out_coords is coords
    assert out_offsets is offsets


def test_resample_closed_ring_skips_consecutive_duplicate_vertices() -> None:
    coords, offsets = _geom(
        [
            [
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 2.0, 0.0),
                (0.0, 0.0, 0.0),
            ]
        ]
    )

    out_coords, _ = resample((coords, offsets), step=2.0, closed="auto")

    np.testing.assert_allclose(
        out_coords,
        np.asarray(
            [
                [0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [2.0, 2.0, 0.0],
                [0.0, 2.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        ),
        rtol=0.0,
        atol=1e-6,
    )


def test_resample_preserves_input_and_is_byte_deterministic() -> None:
    coords, offsets = _geom(
        [
            [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (4.0, 2.0, 1.0)],
            [(10.0, 0.0, 0.0), (12.0, 0.0, 0.0)],
        ]
    )
    coords_before = coords.copy()
    offsets_before = offsets.copy()

    first = resample((coords, offsets), step=0.6, closed="open")
    second = resample((coords, offsets), step=0.6, closed="open")

    np.testing.assert_array_equal(coords, coords_before)
    np.testing.assert_array_equal(offsets, offsets_before)
    assert first[0].dtype == np.float32
    assert first[1].dtype == np.int32
    assert first[0].tobytes() == second[0].tobytes()
    assert first[1].tobytes() == second[1].tobytes()


def test_resample_invalid_step_is_identity() -> None:
    coords, offsets = _geom([[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]])

    for step in (0.0, -1.0, np.nan, np.inf):
        out_coords, out_offsets = resample((coords, offsets), step=step)
        assert out_coords is coords
        assert out_offsets is offsets


def test_resample_nonfinite_geometry_is_identity() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]]
    )
    coords[1, 2] = np.nan

    out_coords, out_offsets = resample((coords, offsets), step=0.1)

    assert out_coords is coords
    assert out_offsets is offsets


def test_resample_resource_boundary_and_overflow() -> None:
    coords, offsets = _geom([[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]])
    boundary = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=1,
        max_output_bytes=1_000,
    )
    with resource_budget_context(boundary):
        out_coords, out_offsets = resample((coords, offsets), step=1.0, closed="open")
    assert out_coords.shape == (3, 3)
    assert out_offsets.tolist() == [0, 3]

    overflow = ResourceBudget(
        max_output_vertices=2,
        max_output_lines=1,
        max_output_bytes=1_000,
    )
    with resource_budget_context(overflow), pytest.raises(ResourceLimitError):
        resample((coords, offsets), step=1.0, closed="open")


def test_resample_true_copy_is_identity_even_under_tight_budget() -> None:
    coords, offsets = _geom(
        [
            [(1.0, 2.0, 3.0)],
            [(4.0, 5.0, 6.0), (4.0, 5.0, 6.0), (4.0, 5.0, 6.0)],
        ]
    )
    budget = ResourceBudget(
        max_output_vertices=0,
        max_output_lines=0,
        max_output_bytes=0,
    )

    with resource_budget_context(budget):
        out_coords, out_offsets = resample((coords, offsets), step=0.1, closed="open")

    assert out_coords is coords
    assert out_offsets is offsets


def test_resample_exact_open_grid_is_identity_even_under_tight_budget() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]]
    )
    budget = ResourceBudget(
        max_output_vertices=0,
        max_output_lines=0,
        max_output_bytes=0,
    )

    with resource_budget_context(budget):
        out_coords, out_offsets = resample(
            (coords, offsets),
            step=1.0,
            closed="open",
        )

    assert out_coords is coords
    assert out_offsets is offsets


def test_resample_identity_check_matches_fast_kernel_rounding() -> None:
    coords = np.asarray(
        [
            [29394.697, -49997.793, 11036.91],
            [-83480.875, -63583.77, 58150.164],
            [-46604.043, 648.8242, 26285.875],
        ],
        dtype=np.float32,
    )
    offsets = np.asarray([0, 3], dtype=np.int32)

    out_coords, out_offsets = resample(
        (coords, offsets),
        step=123065.5625,
        closed="open",
    )

    assert out_coords is not coords
    assert out_offsets is not offsets
    assert out_coords.tobytes() != coords.tobytes()
    np.testing.assert_array_equal(out_coords[[0, -1]], coords[[0, -1]])
