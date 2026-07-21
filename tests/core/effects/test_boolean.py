"""boolean effect の閉領域演算と決定性を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.effects.boolean import boolean, boolean_meta
from grafix.core.realize import realize
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


def _square(
    minimum_x: float,
    minimum_y: float,
    maximum_x: float,
    maximum_y: float,
) -> list[tuple[float, float, float]]:
    return [
        (minimum_x, minimum_y, 0.0),
        (maximum_x, minimum_y, 0.0),
        (maximum_x, maximum_y, 0.0),
        (minimum_x, maximum_y, 0.0),
        (minimum_x, minimum_y, 0.0),
    ]


def _signed_area(g: tuple[np.ndarray, np.ndarray]) -> float:
    coords, offsets = g
    total = 0.0
    for index in range(int(offsets.size) - 1):
        ring = coords[int(offsets[index]) : int(offsets[index + 1]), :2]
        core = ring[:-1]
        following = np.roll(core, -1, axis=0)
        total += 0.5 * float(
            np.sum(
                core[:, 0] * following[:, 1]
                - following[:, 0] * core[:, 1],
                dtype=np.float64,
            )
        )
    return total


@pytest.mark.parametrize(
    ("mode", "expected_area", "expected_offsets"),
    [
        ("union", 7.0, [0, 9]),
        ("intersection", 1.0, [0, 5]),
        ("difference", 3.0, [0, 7]),
        ("xor", 6.0, [0, 7, 14]),
    ],
)
def test_boolean_four_modes_have_expected_area(
    mode: str,
    expected_area: float,
    expected_offsets: list[int],
) -> None:
    first = _geometry(_square(0.0, 0.0, 2.0, 2.0))
    second = _geometry(_square(1.0, 1.0, 3.0, 3.0))

    result = boolean(first, second, mode=mode)

    assert _signed_area(result) == pytest.approx(expected_area, abs=1e-6)
    assert result[1].tolist() == expected_offsets
    for index in range(int(result[1].size) - 1):
        ring = result[0][int(result[1][index]) : int(result[1][index + 1])]
        np.testing.assert_array_equal(ring[0], ring[-1])


def test_boolean_handles_disjoint_and_touching_regions() -> None:
    first = _geometry(_square(0.0, 0.0, 1.0, 1.0))
    disjoint = _geometry(_square(2.0, 0.0, 3.0, 1.0))
    touching = _geometry(_square(1.0, 0.0, 2.0, 1.0))

    disjoint_union = boolean(first, disjoint, mode="union")
    disjoint_intersection = boolean(first, disjoint, mode="intersection")
    touching_union = boolean(first, touching, mode="union")
    touching_intersection = boolean(first, touching, mode="intersection")

    assert disjoint_union[1].tolist() == [0, 5, 10]
    assert _signed_area(disjoint_union) == pytest.approx(2.0)
    assert disjoint_intersection[1].tolist() == [0]
    assert touching_union[1].tolist() == [0, 5]
    assert _signed_area(touching_union) == pytest.approx(2.0)
    assert touching_intersection[1].tolist() == [0]


def test_boolean_difference_uses_input_order() -> None:
    outer = _geometry(_square(0.0, 0.0, 4.0, 4.0))
    inner = _geometry(_square(1.0, 1.0, 2.0, 2.0))

    outer_minus_inner = boolean(outer, inner, mode="difference")
    inner_minus_outer = boolean(inner, outer, mode="difference")

    assert _signed_area(outer_minus_inner) == pytest.approx(15.0)
    assert inner_minus_outer[0].shape == (0, 3)
    assert inner_minus_outer[1].tolist() == [0]


def test_boolean_preserves_hole_island_hierarchy_and_winding() -> None:
    area = _geometry(
        _square(0.0, 0.0, 10.0, 10.0),
        _square(2.0, 2.0, 8.0, 8.0),
        _square(4.0, 4.0, 6.0, 6.0),
    )

    result = boolean(area, _geometry(), mode="union")

    assert result[1].size == 4
    areas: list[float] = []
    for index in range(3):
        start = int(result[1][index])
        stop = int(result[1][index + 1])
        line = result[0][start:stop, :2]
        core = line[:-1]
        following = np.roll(core, -1, axis=0)
        areas.append(
            0.5
            * float(
                np.sum(
                    core[:, 0] * following[:, 1]
                    - following[:, 0] * core[:, 1],
                    dtype=np.float64,
                )
            )
        )
    assert areas[0] > 0.0
    assert areas[1] < 0.0
    assert areas[2] > 0.0
    assert sum(areas) == pytest.approx(68.0)


def test_boolean_output_is_independent_of_winding_seam_and_ring_order() -> None:
    outer = _square(0.0, 0.0, 10.0, 10.0)
    hole = _square(2.0, 2.0, 8.0, 8.0)
    base = _geometry(outer, hole)

    outer_core = outer[:-1]
    outer_shifted = outer_core[2:] + outer_core[:2]
    outer_shifted.append(outer_shifted[0])
    hole_core = list(reversed(hole[:-1]))
    hole_shifted = hole_core[1:] + hole_core[:1]
    hole_shifted.append(hole_shifted[0])
    reordered = _geometry(hole_shifted, outer_shifted)

    first = boolean(base, _geometry(), mode="union")
    second = boolean(reordered, _geometry(), mode="union")

    np.testing.assert_array_equal(first[0], second[0])
    np.testing.assert_array_equal(first[1], second[1])


@pytest.mark.parametrize(
    ("mode", "left_empty", "right_empty", "expected_area"),
    [
        ("union", False, True, 4.0),
        ("union", True, False, 4.0),
        ("intersection", False, True, 0.0),
        ("intersection", True, False, 0.0),
        ("difference", False, True, 4.0),
        ("difference", True, False, 0.0),
        ("xor", False, True, 4.0),
        ("xor", True, False, 4.0),
    ],
)
def test_boolean_obeys_empty_set_laws(
    mode: str,
    left_empty: bool,
    right_empty: bool,
    expected_area: float,
) -> None:
    empty = _geometry()
    square = _geometry(_square(0.0, 0.0, 2.0, 2.0))
    left = empty if left_empty else square
    right = empty if right_empty else square

    result = boolean(left, right, mode=mode)

    assert _signed_area(result) == pytest.approx(expected_area)


def test_boolean_restores_a_tilted_plane() -> None:
    first_xy = np.asarray(_square(0.0, 0.0, 2.0, 2.0), dtype=np.float64)
    second_xy = np.asarray(_square(1.0, 1.0, 3.0, 3.0), dtype=np.float64)

    def tilt(points: np.ndarray) -> list[tuple[float, float, float]]:
        return [
            (float(x), float(y), float(3.0 + x + 2.0 * y))
            for x, y, _z in points
        ]

    result = boolean(
        _geometry(tilt(first_xy)),
        _geometry(tilt(second_xy)),
        mode="intersection",
    )

    residual = result[0][:, 2] - (
        3.0 + result[0][:, 0] + 2.0 * result[0][:, 1]
    )
    np.testing.assert_allclose(residual, 0.0, rtol=0.0, atol=2e-5)


@pytest.mark.parametrize(
    "invalid",
    [
        _geometry(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)]
        ),
        _geometry(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
        ),
    ],
)
def test_boolean_rejects_open_or_degenerate_ring(
    invalid: tuple[np.ndarray, np.ndarray],
) -> None:
    with pytest.raises(ValueError, match="boolean"):
        boolean(invalid, _geometry(), mode="union")


def test_boolean_rejects_non_coplanar_inputs() -> None:
    first = _geometry(_square(0.0, 0.0, 2.0, 2.0))
    second_line = [
        (x, y, z + 1.0)
        for (x, y, z) in _square(0.0, 0.0, 2.0, 2.0)
    ]

    with pytest.raises(ValueError, match="同一"):
        boolean(first, _geometry(second_line), mode="union")


def test_boolean_rejects_nonplanar_single_input() -> None:
    nonplanar = _geometry(
        [
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 2.0, 1.0),
            (0.0, 2.0, 0.0),
            (0.0, 0.0, 0.0),
        ]
    )
    with pytest.raises(ValueError, match="同一"):
        boolean(nonplanar, _geometry(), mode="union")


def test_boolean_checks_resource_budget_and_preserves_input() -> None:
    first = _geometry(_square(0.0, 0.0, 2.0, 2.0))
    second = _geometry(_square(1.0, 1.0, 3.0, 3.0))
    first_before = (first[0].copy(), first[1].copy())
    second_before = (second[0].copy(), second[1].copy())
    budget = ResourceBudget(
        max_output_vertices=4,
        max_output_lines=10,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(
        ResourceLimitError,
        match="boolean",
    ):
        boolean(first, second, mode="intersection")

    np.testing.assert_array_equal(first[0], first_before[0])
    np.testing.assert_array_equal(first[1], first_before[1])
    np.testing.assert_array_equal(second[0], second_before[0])
    np.testing.assert_array_equal(second[1], second_before[1])
    assert all(meta.description for meta in boolean_meta.values())


def test_boolean_output_has_packed_dtypes_and_is_repeatable() -> None:
    first = _geometry(_square(0.0, 0.0, 2.0, 2.0))
    second = _geometry(_square(1.0, 1.0, 3.0, 3.0))

    first_result = boolean(first, second, mode="xor")
    second_result = boolean(first, second, mode="xor")

    assert first_result[0].dtype == np.float32
    assert first_result[1].dtype == np.int32
    np.testing.assert_array_equal(first_result[0], second_result[0])
    np.testing.assert_array_equal(first_result[1], second_result[1])


def test_boolean_lazy_api_requires_two_inputs_and_chain_head() -> None:
    first = G.circle(radius=2.0, segments=24, center=(0.0, 0.0, 0.0))
    second = G.circle(radius=2.0, segments=24, center=(1.0, 0.0, 0.0))

    with pytest.raises(TypeError, match="2 個"):
        E.boolean()(first)
    with pytest.raises(TypeError, match="チェーンの先頭"):
        E.scale().boolean()(first)

    base = realize(E.boolean(mode="intersection")(first, second))
    moved = realize(
        E.boolean(mode="intersection").translate(delta=(3.0, 4.0, 0.0))(
            first,
            second,
        )
    )

    np.testing.assert_allclose(
        moved.coords,
        base.coords + np.asarray([3.0, 4.0, 0.0], dtype=np.float32),
        rtol=0.0,
        atol=1e-6,
    )
    np.testing.assert_array_equal(moved.offsets, base.offsets)
