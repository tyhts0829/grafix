"""deduplicate effect の重複線分除去と chain 再構成を検証する。"""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from grafix import E, G
from grafix.core.effects.deduplicate import deduplicate
from grafix.core.realize import RealizeError, realize
from grafix.core.resource_budget import (
    ResourceBudget,
    ResourceLimitError,
    resource_budget_context,
)


def _geometry(*lines: list[tuple[float, float, float]]) -> tuple[np.ndarray, np.ndarray]:
    coords = np.asarray(
        [point for line in lines for point in line],
        dtype=np.float32,
    ).reshape((-1, 3))
    counts = np.asarray([len(line) for line in lines], dtype=np.int64)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    np.cumsum(counts, out=offsets[1:])
    return coords, offsets


def _lines(
    geometry: tuple[np.ndarray, np.ndarray],
) -> list[np.ndarray]:
    coords, offsets = geometry
    return [
        coords[int(offsets[index]) : int(offsets[index + 1])]
        for index in range(int(offsets.size) - 1)
    ]


def test_deduplicate_removes_same_and_reverse_segments_first_wins() -> None:
    a = (0.0, 0.0, 0.0)
    b = (1.0, 2.0, 3.0)
    geometry = _geometry([a, b, a, b], [b, a])

    output = deduplicate(geometry, tolerance=0.0, merge_chains=False)

    assert output[1].tolist() == [0, 2]
    np.testing.assert_array_equal(output[0], np.asarray([a, b], dtype=np.float32))


def test_deduplicate_exact_mode_keeps_nearby_segments_distinct() -> None:
    geometry = _geometry(
        [(0.49, 0.0, 0.0), (1.49, 0.0, 0.0)],
        [(0.40, 0.0, 0.0), (1.40, 0.0, 0.0)],
    )

    output = deduplicate(geometry, tolerance=0.0, merge_chains=False)

    assert output[1].tolist() == [0, 2, 4]


def test_deduplicate_positive_tolerance_uses_half_away_grid_and_first_point() -> None:
    first_a = (0.49, 0.0, 0.0)
    first_b = (1.49, 0.0, 0.0)
    geometry = _geometry(
        [first_a, first_b],
        [(1.40, 0.0, 0.0), (0.40, 0.0, 0.0)],
        [(-0.50, 0.0, 0.0), (0.50, 0.0, 0.0)],
    )

    output = deduplicate(geometry, tolerance=1.0, merge_chains=False)
    lines = _lines(output)

    assert len(lines) == 2
    np.testing.assert_array_equal(
        lines[0],
        np.asarray([first_a, first_b], dtype=np.float32),
    )
    np.testing.assert_array_equal(
        lines[1],
        np.asarray([(-0.50, 0.0, 0.0), first_b], dtype=np.float32),
    )


def test_deduplicate_compares_z_as_well_as_xy() -> None:
    geometry = _geometry(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0)],
    )

    output = deduplicate(geometry, tolerance=0.0, merge_chains=False)

    assert output[1].tolist() == [0, 2, 4]
    np.testing.assert_array_equal(output[0], geometry[0])


def test_deduplicate_merge_false_preserves_unique_edge_first_seen_order() -> None:
    geometry = _geometry(
        [(2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(3.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
    )

    output = deduplicate(geometry, tolerance=0.0, merge_chains=False)
    lines = _lines(output)

    assert len(lines) == 2
    np.testing.assert_array_equal(lines[0], geometry[0][0:2])
    np.testing.assert_array_equal(lines[1], geometry[0][2:4])


def test_deduplicate_merges_scrambled_open_chain() -> None:
    a = (0.0, 0.0, 0.0)
    b = (1.0, 0.0, 0.0)
    c = (2.0, 0.0, 0.0)
    d = (3.0, 0.0, 0.0)
    geometry = _geometry([b, c], [a, b], [c, d])

    output = deduplicate(geometry, tolerance=0.0, merge_chains=True)

    assert output[1].tolist() == [0, 4]
    np.testing.assert_array_equal(
        output[0],
        np.asarray([a, b, c, d], dtype=np.float32),
    )


def test_deduplicate_splits_at_branch_nodes() -> None:
    center = (0.0, 0.0, 0.0)
    a = (1.0, 0.0, 0.0)
    b = (0.0, 1.0, 0.0)
    c = (-1.0, 0.0, 0.0)
    geometry = _geometry([center, a], [center, b], [center, c])

    output = deduplicate(geometry, tolerance=0.0, merge_chains=True)

    assert output[1].tolist() == [0, 2, 4, 6]
    np.testing.assert_array_equal(output[0], geometry[0])


def test_deduplicate_cycle_uses_min_edge_original_start_and_direction() -> None:
    a = (0.0, 0.0, 0.0)
    b = (1.0, 0.0, 0.0)
    c = (0.0, 1.0, 0.0)
    geometry = _geometry([b, c], [a, b], [c, a])

    first = deduplicate(geometry, tolerance=0.0, merge_chains=True)
    second = deduplicate(geometry, tolerance=0.0, merge_chains=True)

    assert first[1].tolist() == [0, 4]
    np.testing.assert_array_equal(
        first[0],
        np.asarray([b, c, a, b], dtype=np.float32),
    )
    assert first[0].tobytes() == second[0].tobytes()
    assert first[1].tobytes() == second[1].tobytes()


def test_deduplicate_multiple_components_follow_first_edge_order() -> None:
    a = (0.0, 0.0, 0.0)
    b = (1.0, 0.0, 0.0)
    c = (2.0, 0.0, 0.0)
    x = (10.0, 0.0, 0.0)
    y = (11.0, 0.0, 0.0)
    z = (12.0, 0.0, 0.0)
    geometry = _geometry([a, b], [b, c], [x, y], [y, z])

    output = deduplicate(geometry, tolerance=0.0, merge_chains=True)
    lines = _lines(output)

    assert len(lines) == 2
    np.testing.assert_array_equal(lines[0], np.asarray([a, b, c], dtype=np.float32))
    np.testing.assert_array_equal(lines[1], np.asarray([x, y, z], dtype=np.float32))


def test_deduplicate_removes_empty_point_and_zero_length_lines() -> None:
    point = (1.0, 1.0, 1.0)
    a = (0.0, 0.0, 0.0)
    b = (2.0, 0.0, 0.0)
    geometry = _geometry([], [point], [point, point], [a, b])

    output = deduplicate(geometry, tolerance=0.0, merge_chains=True)

    assert output[1].tolist() == [0, 2]
    np.testing.assert_array_equal(output[0], np.asarray([a, b], dtype=np.float32))

    empty = deduplicate(_geometry([], [point], [point, point]), tolerance=0.0)
    assert empty[0].shape == (0, 3)
    assert empty[0].dtype == np.float32
    assert empty[1].tolist() == [0]
    assert empty[1].dtype == np.int32


@pytest.mark.parametrize(
    "points",
    [(), ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))],
)
def test_deduplicate_rejects_negative_tolerance_before_empty_input(
    points: tuple[tuple[float, float, float], ...],
) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(E.deduplicate(tolerance=-1.0)(G.polyline(points=points)))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "tolerance" in str(exc_info.value.__cause__)


@pytest.mark.parametrize("tolerance", [np.nan, np.inf, -np.inf])
def test_deduplicate_public_api_rejects_nonfinite_tolerance(
    tolerance: float,
) -> None:
    with pytest.raises(ValueError, match="tolerance"):
        E.deduplicate(tolerance=tolerance)


def test_deduplicate_does_not_mutate_input_and_returns_packed_dtypes() -> None:
    geometry = _geometry(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        [(2.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
    )
    coords_before = geometry[0].copy()
    offsets_before = geometry[1].copy()

    output = deduplicate(geometry, tolerance=0.0)

    np.testing.assert_array_equal(geometry[0], coords_before)
    np.testing.assert_array_equal(geometry[1], offsets_before)
    assert output[0].dtype == np.float32
    assert output[1].dtype == np.int32
    assert output[1][0] == 0
    assert output[1][-1] == output[0].shape[0]


def test_deduplicate_checks_resource_budget_before_packing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry = _geometry(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
    )
    module = importlib.import_module("grafix.core.effects.deduplicate")

    def fail_pack(*_args: object, **_kwargs: object) -> tuple[np.ndarray, np.ndarray]:
        raise AssertionError("resource preflight より前に pack された")

    monkeypatch.setattr(module, "_pack_chains", fail_pack)
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=10,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="deduplicate",
    ):
        deduplicate(geometry, tolerance=0.0, merge_chains=False)


def test_deduplicate_branch_checks_output_line_budget_before_packing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    center = (0.0, 0.0, 0.0)
    geometry = _geometry(
        [center, (1.0, 0.0, 0.0)],
        [center, (0.0, 1.0, 0.0)],
        [center, (-1.0, 0.0, 0.0)],
    )
    module = importlib.import_module("grafix.core.effects.deduplicate")

    def fail_pack(*_args: object, **_kwargs: object) -> tuple[np.ndarray, np.ndarray]:
        raise AssertionError("line budget preflight より前に pack された")

    monkeypatch.setattr(module, "_pack_chains", fail_pack)
    budget = ResourceBudget(
        max_output_vertices=100,
        max_output_lines=2,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="lines=3",
    ):
        module.deduplicate(geometry, tolerance=0.0, merge_chains=True)
