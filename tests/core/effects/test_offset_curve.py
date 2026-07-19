"""offset_curve effect の方向、平面復元、出力順を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.core.effects.offset_curve import offset_curve, offset_curve_meta
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
    offsets = np.zeros((len(lines) + 1,), dtype=np.int32)
    if lines:
        offsets[1:] = np.cumsum([len(line) for line in lines], dtype=np.int32)
    return coords, offsets


def _lines(g: tuple[np.ndarray, np.ndarray]) -> list[np.ndarray]:
    coords, offsets = g
    return [
        coords[int(offsets[index]) : int(offsets[index + 1])]
        for index in range(int(offsets.size) - 1)
    ]


def _square(*, clockwise: bool = False) -> list[tuple[float, float, float]]:
    core = [
        (0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
        (2.0, 2.0, 0.0),
        (0.0, 2.0, 0.0),
    ]
    if clockwise:
        core.reverse()
    return [*core, core[0]]


def _area(line: np.ndarray) -> float:
    core = line[:-1, :2]
    following = np.roll(core, -1, axis=0)
    return 0.5 * float(
        np.sum(
            core[:, 0] * following[:, 1]
            - following[:, 0] * core[:, 1],
            dtype=np.float64,
        )
    )


def test_offset_curve_open_line_left_right_and_both() -> None:
    line = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    left = _lines(offset_curve(line, distance=0.5, side="left"))
    right = _lines(offset_curve(line, distance=0.5, side="right"))
    both = _lines(offset_curve(line, distance=0.5, side="both"))

    np.testing.assert_allclose(
        left[0],
        [[0.0, 0.5, 0.0], [2.0, 0.5, 0.0]],
        rtol=0.0,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        right[0],
        [[0.0, -0.5, 0.0], [2.0, -0.5, 0.0]],
        rtol=0.0,
        atol=1e-6,
    )
    np.testing.assert_array_equal(both[0], left[0])
    np.testing.assert_array_equal(both[1], right[0])


def test_offset_curve_left_follows_reversed_input_direction() -> None:
    forward = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    reversed_line = _geometry([(2.0, 0.0, 0.0), (0.0, 0.0, 0.0)])

    forward_left = _lines(
        offset_curve(forward, distance=0.5, side="left")
    )[0]
    reverse_left = _lines(
        offset_curve(reversed_line, distance=0.5, side="left")
    )[0]

    np.testing.assert_allclose(forward_left[:, 1], 0.5, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(reverse_left[:, 1], -0.5, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(
        reverse_left[:, 0],
        [2.0, 0.0],
        rtol=0.0,
        atol=1e-6,
    )


def test_offset_curve_count_order_and_keep_original() -> None:
    line = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    result = _lines(
        offset_curve(
            line,
            distance=0.25,
            side="both",
            count=2,
            keep_original=True,
        )
    )

    assert len(result) == 5
    expected_y = (0.25, -0.25, 0.5, -0.5, 0.0)
    for output, y in zip(result, expected_y):
        np.testing.assert_allclose(output[:, 1], y, rtol=0.0, atol=1e-6)


def test_offset_curve_join_styles_change_corner_geometry() -> None:
    corner = _geometry(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0)]
    )

    round_line = _lines(
        offset_curve(corner, distance=0.25, side="right", join="round")
    )[0]
    mitre_line = _lines(
        offset_curve(corner, distance=0.25, side="right", join="mitre")
    )[0]
    bevel_line = _lines(
        offset_curve(corner, distance=0.25, side="right", join="bevel")
    )[0]

    assert round_line.shape[0] > bevel_line.shape[0]
    assert mitre_line.shape[0] < round_line.shape[0]
    assert not np.array_equal(mitre_line, bevel_line)


def test_offset_curve_splits_backtracking_cusp_into_stable_fragments() -> None:
    cusp = _geometry(
        [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (6.0, 0.0, 0.0),
        ]
    )

    first = _lines(offset_curve(cusp, distance=0.25, side="left"))
    second = _lines(offset_curve(cusp, distance=0.25, side="left"))

    assert len(first) == 2
    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])
    np.testing.assert_allclose(first[0][:, 0], [0.0, 2.0, 4.0, 6.0])
    np.testing.assert_allclose(first[0][:, 1], 0.25)
    np.testing.assert_allclose(first[1][:, 0], [2.0, 4.0])
    np.testing.assert_allclose(first[1][:, 1], -0.25)


def test_offset_curve_closed_ring_follows_winding_and_closes_output() -> None:
    counterclockwise = _geometry(_square(clockwise=False))
    clockwise = _geometry(_square(clockwise=True))

    ccw_left = _lines(
        offset_curve(counterclockwise, distance=0.2, side="left")
    )[0]
    cw_left = _lines(
        offset_curve(clockwise, distance=0.2, side="left")
    )[0]

    np.testing.assert_array_equal(ccw_left[0], ccw_left[-1])
    np.testing.assert_array_equal(cw_left[0], cw_left[-1])
    assert _area(ccw_left) > 0.0
    assert _area(cw_left) < 0.0
    assert float(np.min(ccw_left[:, 0])) > 0.19
    assert float(np.min(cw_left[:, 0])) < -0.19


def test_offset_curve_restores_xz_and_tilted_planes() -> None:
    xz = _geometry(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 2.0)]
    )
    tilted = _geometry(
        [
            (0.0, 0.0, 1.0),
            (2.0, 0.0, 3.0),
            (2.0, 2.0, 7.0),
        ]
    )

    xz_result = offset_curve(xz, distance=0.2, side="both")
    tilted_result = offset_curve(tilted, distance=0.2, side="both")

    np.testing.assert_allclose(xz_result[0][:, 1], 0.0, rtol=0.0, atol=1e-6)
    tilted_residual = tilted_result[0][:, 2] - (
        1.0 + tilted_result[0][:, 0] + 2.0 * tilted_result[0][:, 1]
    )
    np.testing.assert_allclose(tilted_residual, 0.0, rtol=0.0, atol=2e-5)


def test_offset_curve_uses_principal_plane_for_a_single_3d_line() -> None:
    line = _geometry([(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)])

    result = _lines(offset_curve(line, distance=0.5, side="left"))[0]

    direction = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    offset_vector = result[0].astype(np.float64)
    assert float(np.dot(offset_vector, direction)) == pytest.approx(0.0, abs=2e-6)
    assert float(np.linalg.norm(offset_vector)) == pytest.approx(0.5, abs=2e-6)


def test_offset_curve_uses_documented_principal_plane_for_z_axis_line() -> None:
    line = _geometry([(0.0, 0.0, 0.0), (0.0, 0.0, 2.0)])

    result = _lines(offset_curve(line, distance=0.5, side="left"))[0]

    np.testing.assert_allclose(
        result,
        [[0.5, 0.0, 0.0], [0.5, 0.0, 2.0]],
        rtol=0.0,
        atol=1e-6,
    )


def test_offset_curve_uses_one_common_plane_for_multiple_lines() -> None:
    geometry = _geometry(
        [(0.0, 0.0, 0.0), (0.0, 0.0, 2.0)],
        [(1.0, 0.0, 2.0), (3.0, 0.0, 2.0)],
    )

    result = offset_curve(geometry, distance=0.25, side="both")

    assert result[1].size == 5
    np.testing.assert_allclose(result[0][:, 1], 0.0, rtol=0.0, atol=1e-6)


def test_offset_curve_rejects_nonplanar_or_rank_zero_input() -> None:
    nonplanar = _geometry(
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ]
    )
    point = _geometry([(0.0, 0.0, 0.0)])

    with pytest.raises(ValueError, match="offset_curve"):
        offset_curve(nonplanar, distance=0.1)
    with pytest.raises(ValueError, match="offset_curve"):
        offset_curve(point, distance=0.1)


@pytest.mark.parametrize(
    ("distance", "count"),
    [
        (0.0, 1),
        (-1.0, 1),
        (float("nan"), 1),
        (1.0, 0),
    ],
)
def test_offset_curve_invalid_growth_parameter_is_identity(
    distance: float,
    count: int,
) -> None:
    geometry = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    result = offset_curve(geometry, distance=distance, count=count)

    assert result[0] is geometry[0]
    assert result[1] is geometry[1]


def test_offset_curve_empty_is_identity_and_nonfinite_geometry_is_rejected() -> None:
    empty = _geometry()

    result = offset_curve(empty, distance=0.5)

    assert result[0] is empty[0]
    assert result[1] is empty[1]

    nonfinite = _geometry([(0.0, 0.0, 0.0), (np.nan, 1.0, 0.0)])
    with pytest.raises(ValueError, match="非有限"):
        offset_curve(nonfinite, distance=0.5)


def test_offset_curve_checks_resource_budget_before_packing() -> None:
    geometry = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=10,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="offset_curve",
    ):
        offset_curve(geometry, distance=0.5, side="both")


def test_offset_curve_stops_accumulating_fragments_at_resource_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module("grafix.core.effects.offset_curve")
    geometry = _geometry([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    budget = ResourceBudget(
        max_output_vertices=100,
        max_output_lines=1,
        max_output_bytes=10_000,
    )

    def unexpected_pack(*_args: object, **_kwargs: object) -> None:
        pytest.fail("resource limit 後に packed output を確保してはならない")

    monkeypatch.setattr(module, "_pack_output", unexpected_pack)
    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="offset_curve",
    ):
        offset_curve(
            geometry,
            distance=0.5,
            side="both",
            count=1_000_000,
        )


def test_offset_curve_preflights_empty_backend_attempts() -> None:
    bow_tie = _geometry(
        [
            (0.0, 0.0, 0.0),
            (2.0, 2.0, 0.0),
            (0.0, 2.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
        ]
    )
    budget = ResourceBudget(
        max_output_vertices=100,
        max_output_lines=1,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="offset_curve",
    ):
        offset_curve(
            bow_tie,
            distance=0.2,
            side="left",
            count=1_000_000,
        )


def test_offset_curve_preserves_input_and_returns_repeatable_packed_dtypes() -> None:
    geometry = _geometry(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0)]
    )
    before = (geometry[0].copy(), geometry[1].copy())

    first = offset_curve(geometry, distance=0.2, side="both", count=2)
    second = offset_curve(geometry, distance=0.2, side="both", count=2)

    np.testing.assert_array_equal(geometry[0], before[0])
    np.testing.assert_array_equal(geometry[1], before[1])
    assert first[0].dtype == np.float32
    assert first[1].dtype == np.int32
    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])
    assert all(meta.description for meta in offset_curve_meta.values())
