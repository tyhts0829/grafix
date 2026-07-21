"""simplify effect の XYZ RDP、閉曲線契約、resource preflight を検証する。"""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from grafix.core.effects.simplify import simplify
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


def test_simplify_removes_collinear_vertices_and_preserves_endpoints() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]]
    )

    out_coords, out_offsets = simplify((coords, offsets), tolerance=0.01, closed="open")

    np.testing.assert_array_equal(out_coords, coords[[0, 2]])
    assert out_offsets.tolist() == [0, 2]


def test_simplify_tolerance_boundary_is_removed_but_smaller_value_keeps_corner() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]]
    )

    at_boundary, _ = simplify((coords, offsets), tolerance=1.0, closed="open")
    below_boundary, _ = simplify((coords, offsets), tolerance=0.999, closed="open")

    np.testing.assert_array_equal(at_boundary, coords[[0, 2]])
    np.testing.assert_array_equal(below_boundary, coords)


def test_simplify_measures_deviation_in_z() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (2.0, 0.0, 0.0)]]
    )

    kept, _ = simplify((coords, offsets), tolerance=0.9, closed="open")
    removed, _ = simplify((coords, offsets), tolerance=1.0, closed="open")

    np.testing.assert_array_equal(kept, coords)
    np.testing.assert_array_equal(removed, coords[[0, 2]])


def test_simplify_returns_identity_when_every_vertex_is_kept() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)]]
    )

    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=0.1,
        closed="open",
    )

    assert out_coords is coords
    assert out_offsets is offsets


def test_simplify_closed_ring_keeps_three_unique_vertices_and_exact_closure() -> None:
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

    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=100.0,
        closed="auto",
    )

    assert out_offsets.tolist() == [0, 4]
    assert len({_point_key(point) for point in out_coords[:-1]}) == 3
    np.testing.assert_array_equal(out_coords[-1], out_coords[0])
    # seam=0、最遠 anchor=2、第三頂点の同距離 tie は小さい index=1。
    np.testing.assert_array_equal(out_coords, coords[[0, 1, 2, 0]])


def _point_key(point: np.ndarray) -> tuple[float, float, float]:
    return float(point[0]), float(point[1]), float(point[2])


def test_simplify_near_closed_ring_replaces_endpoint_with_exact_seam() -> None:
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

    out_coords, _ = simplify((coords, offsets), tolerance=0.01, closed="auto")

    np.testing.assert_array_equal(out_coords[-1], out_coords[0])
    assert not np.array_equal(out_coords[-1], coords[-1])


def test_simplify_forced_closed_open_triangle_adds_closure() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)]]
    )

    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=100.0,
        closed="closed",
    )

    assert out_offsets.tolist() == [0, 4]
    np.testing.assert_array_equal(out_coords[-1], out_coords[0])
    assert len({_point_key(point) for point in out_coords[:-1]}) == 3


def test_simplify_degenerate_closed_ring_is_identity() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)]]
    )

    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=100.0,
        closed="auto",
    )

    assert out_coords is coords
    assert out_offsets is offsets


def test_simplify_mixed_lines_preserves_line_order_and_short_lines() -> None:
    coords, offsets = _geom(
        [
            [],
            [(9.0, 8.0, 7.0)],
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
            [(4.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
        ]
    )

    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=0.1,
        closed="open",
    )

    assert out_offsets.tolist() == [0, 0, 1, 3, 5]
    np.testing.assert_array_equal(
        out_coords,
        coords[[0, 1, 3, 4, 5]],
    )


def test_simplify_zero_tolerance_is_identity() -> None:
    coords, offsets = _geom(
        [[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]]
    )
    out_coords, out_offsets = simplify(
        (coords, offsets),
        tolerance=0.0,
        closed="open",
    )
    assert out_coords is coords
    assert out_offsets is offsets


def test_simplify_rejects_negative_tolerance_before_empty_input() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        simplify(_geom([]), tolerance=-1.0, closed="open")


def test_simplify_preserves_input_dtype_and_is_byte_deterministic() -> None:
    coords, offsets = _geom(
        [
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.1, 0.2),
                (2.0, -0.1, 0.1),
                (3.0, 0.0, 0.0),
            ]
        ]
    )
    coords_before = coords.copy()
    offsets_before = offsets.copy()

    first = simplify((coords, offsets), tolerance=0.15, closed="open")
    second = simplify((coords, offsets), tolerance=0.15, closed="open")

    np.testing.assert_array_equal(coords, coords_before)
    np.testing.assert_array_equal(offsets, offsets_before)
    assert first[0].dtype == np.float32
    assert first[1].dtype == np.int32
    assert first[0].tobytes() == second[0].tobytes()
    assert first[1].tobytes() == second[1].tobytes()


def test_simplify_resource_budget_includes_scratch_before_output_allocation() -> None:
    coords, offsets = _geom(
        [
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (3.0, 0.0, 0.0),
                (4.0, 0.0, 0.0),
            ]
        ]
    )
    # 最終 geometry は 2 頂点で 32 bytes だが、RDP scratch を含めると超過する。
    budget = ResourceBudget(
        max_output_vertices=2,
        max_output_lines=1,
        max_output_bytes=32,
    )

    with resource_budget_context(budget), pytest.raises(ResourceLimitError):
        simplify((coords, offsets), tolerance=0.1, closed="open")


def test_simplify_rejects_scratch_budget_before_rdp_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coords, offsets = _geom(
        [[(float(index), 0.0, 0.0) for index in range(100)]]
    )
    module = importlib.import_module("grafix.core.effects.simplify")

    def fail_rdp(*_args: object, **_kwargs: object) -> np.ndarray:
        raise AssertionError("scratch preflight より前に RDP を実行した")

    monkeypatch.setattr(module, "_rdp_keep_indices", fail_rdp)
    budget = ResourceBudget(
        max_output_vertices=1_000,
        max_output_lines=100,
        max_output_bytes=1_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="simplify",
    ):
        module.simplify((coords, offsets), tolerance=0.1, closed="open")
