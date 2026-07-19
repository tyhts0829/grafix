"""spiral primitiveの形状・入力検証・resource契約を検証する。"""

from __future__ import annotations

import importlib
import math

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives.spiral import spiral
from grafix.core.realize import RealizeSession
from grafix.core.resource_budget import (
    ResourceBudget,
    ResourceLimitError,
    resource_budget_context,
)

spiral_module = importlib.import_module("grafix.core.primitives.spiral")


def test_spiral_default_raw_geometry_contract() -> None:
    coords, offsets = spiral()

    assert coords.dtype == np.float32
    assert offsets.dtype == np.int32
    assert coords.shape == (512, 3)
    assert offsets.shape == (2,)
    assert offsets.tolist() == [0, 512]
    assert coords.flags.c_contiguous
    assert offsets.flags.c_contiguous
    assert coords.flags.writeable
    assert offsets.flags.writeable
    assert np.isfinite(coords).all()
    np.testing.assert_array_equal(coords[:, 2], np.zeros(512, dtype=np.float32))


def test_spiral_interpolates_radius_and_applies_phase_and_center() -> None:
    coords, offsets = spiral(
        inner_radius=1.0,
        outer_radius=3.0,
        turns=0.25,
        phase=90.0,
        samples=3,
        center=(10.0, 20.0, 4.0),
    )

    np.testing.assert_allclose(coords[0], [10.0, 21.0, 4.0], atol=1e-6)
    np.testing.assert_allclose(coords[-1], [7.0, 20.0, 4.0], atol=1e-6)
    np.testing.assert_allclose(
        np.linalg.norm(coords[:, :2] - np.array([10.0, 20.0], dtype=np.float32), axis=1),
        [1.0, 2.0, 3.0],
        atol=1e-6,
    )
    assert offsets.tolist() == [0, 3]


def test_spiral_turns_sign_controls_rotation_direction() -> None:
    counterclockwise, _ = spiral(
        inner_radius=1.0,
        outer_radius=1.0,
        turns=0.25,
        samples=2,
    )
    clockwise, _ = spiral(
        inner_radius=1.0,
        outer_radius=1.0,
        turns=-0.25,
        samples=2,
    )

    np.testing.assert_allclose(counterclockwise[-1], [0.0, 1.0, 0.0], atol=1e-6)
    np.testing.assert_allclose(clockwise[-1], [0.0, -1.0, 0.0], atol=1e-6)


def test_spiral_reduces_huge_finite_phase_before_adding_turns() -> None:
    """360度周期の巨大phaseでもturnsを桁落ちさせない。"""

    phase = np.finfo(np.float64).max
    reduced = math.remainder(float(phase), 360.0)
    huge, huge_offsets = spiral(
        inner_radius=1.0,
        outer_radius=1.0,
        turns=0.25,
        phase=phase,
        samples=5,
    )
    reference, reference_offsets = spiral(
        inner_radius=1.0,
        outer_radius=1.0,
        turns=0.25,
        phase=float(reduced),
        samples=5,
    )

    np.testing.assert_array_equal(huge, reference)
    np.testing.assert_array_equal(huge_offsets, reference_offsets)
    assert not np.array_equal(huge[0], huge[-1])


def test_spiral_supports_inward_and_zero_turn_degenerate_curves() -> None:
    coords, offsets = spiral(
        inner_radius=2.0,
        outer_radius=0.5,
        turns=0.0,
        phase=180.0,
        samples=4,
    )

    np.testing.assert_allclose(coords[:, 0], [-2.0, -1.5, -1.0, -0.5], atol=1e-6)
    np.testing.assert_allclose(coords[:, 1:], 0.0, atol=1e-6)
    assert offsets.tolist() == [0, 4]


def test_spiral_minimum_sample_count_is_open_one_polyline() -> None:
    coords, offsets = spiral(
        inner_radius=0.0,
        outer_radius=1.0,
        turns=1.0,
        samples=2,
    )

    assert coords.shape == (2, 3)
    assert offsets.tolist() == [0, 2]
    assert not np.array_equal(coords[0], coords[-1])


@pytest.mark.parametrize("samples", [1, 0, -1])
def test_spiral_rejects_samples_below_two(samples: int) -> None:
    with pytest.raises(ValueError, match="samples は 2 以上"):
        spiral(samples=samples)


@pytest.mark.parametrize("samples", [float("nan"), float("inf"), "not-an-int"])
def test_spiral_rejects_non_integer_sample_values(samples: object) -> None:
    with pytest.raises(ValueError, match="samples は整数"):
        spiral(samples=samples)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("inner_radius", float("nan")),
        ("inner_radius", float("inf")),
        ("outer_radius", float("-inf")),
        ("turns", float("nan")),
        ("turns", float("inf")),
        ("phase", float("-inf")),
    ],
)
def test_spiral_rejects_non_finite_scalar_parameters(name: str, value: float) -> None:
    with pytest.raises(ValueError, match="有限"):
        spiral(**{name: value})


@pytest.mark.parametrize("name", ["inner_radius", "outer_radius"])
def test_spiral_rejects_negative_radius(name: str) -> None:
    with pytest.raises(ValueError, match="0 以上"):
        spiral(**{name: -0.01})


@pytest.mark.parametrize(
    "center",
    [
        (0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        (float("nan"), 0.0, 0.0),
        (0.0, float("inf"), 0.0),
        (0.0, 0.0, float("-inf")),
    ],
)
def test_spiral_rejects_invalid_center(center: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="center|有限"):
        spiral(center=center)  # type: ignore[arg-type]


def test_spiral_rejects_finite_values_that_overflow_float32_output() -> None:
    with pytest.raises(ValueError, match="float32"):
        spiral(outer_radius=1e100)
    with pytest.raises(ValueError, match="float32"):
        spiral(center=(0.0, 0.0, 1e100))


def test_spiral_accepts_large_inputs_when_actual_samples_fit_float32() -> None:
    """中心と半径の保守的な和ではなく、実際のsample範囲で判定する。"""

    coords, offsets = spiral(
        inner_radius=1e38,
        outer_radius=1e38,
        turns=0.0,
        phase=180.0,
        samples=2,
        center=(3e38, 0.0, 0.0),
    )

    assert offsets.tolist() == [0, 2]
    assert np.isfinite(coords).all()
    np.testing.assert_allclose(coords[:, 0], np.float32(2e38), rtol=1e-6)


def test_spiral_is_independent_of_numpy_underflow_policy() -> None:
    """有限subnormal入力を呼出元のnp.seterr設定に左右されず処理する。"""

    tiny = float(np.nextafter(0.0, 1.0))
    with np.errstate(all="raise"):
        coords, offsets = spiral(
            inner_radius=tiny,
            outer_radius=tiny,
            turns=tiny,
            samples=3,
        )

    assert offsets.tolist() == [0, 3]
    assert np.isfinite(coords).all()


def test_spiral_raw_calls_are_fresh_writable_and_do_not_mutate_input() -> None:
    center = [2.0, -3.0, 4.0]
    original_center = center.copy()
    first_coords, first_offsets = spiral(samples=8, center=center)  # type: ignore[arg-type]
    second_coords, second_offsets = spiral(samples=8, center=center)  # type: ignore[arg-type]

    assert center == original_center
    assert first_coords.flags.writeable
    assert first_offsets.flags.writeable
    assert second_coords.flags.writeable
    assert second_offsets.flags.writeable
    assert not np.shares_memory(first_coords, second_coords)
    assert not np.shares_memory(first_offsets, second_offsets)

    expected_coords = second_coords.copy()
    expected_offsets = second_offsets.copy()
    first_coords[0] = np.float32(123.0)
    first_offsets[0] = np.int32(1)
    np.testing.assert_array_equal(second_coords, expected_coords)
    np.testing.assert_array_equal(second_offsets, expected_offsets)


def test_spiral_realize_is_readonly_and_uses_content_cache() -> None:
    geometry = G.spiral(  # type: ignore[attr-defined]
        inner_radius=0.1,
        outer_radius=0.7,
        turns=-2.5,
        phase=15.0,
        samples=32,
    )

    with RealizeSession() as session:
        first = session.realize(geometry)
        second = session.realize(geometry)

    assert second is first
    assert not first.coords.flags.writeable
    assert not first.offsets.flags.writeable
    assert first.offsets.tolist() == [0, 32]


def test_spiral_resource_budget_accepts_exact_estimate() -> None:
    samples = 5
    expected_bytes = samples * (3 * 4 + 3 * 8) + 2 * 4
    budget = ResourceBudget(
        max_output_vertices=samples,
        max_output_lines=1,
        max_output_bytes=expected_bytes,
    )

    with resource_budget_context(budget):
        coords, offsets = spiral(samples=samples)

    assert coords.shape == (samples, 3)
    assert offsets.tolist() == [0, samples]


@pytest.mark.parametrize(
    "budget",
    [
        ResourceBudget(
            max_output_vertices=4,
            max_output_lines=1,
            max_output_bytes=10_000,
        ),
        ResourceBudget(
            max_output_vertices=5,
            max_output_lines=0,
            max_output_bytes=10_000,
        ),
        ResourceBudget(
            max_output_vertices=5,
            max_output_lines=1,
            max_output_bytes=5 * (3 * 4 + 3 * 8) + 2 * 4 - 1,
        ),
    ],
)
def test_spiral_resource_budget_rejects_one_over_limit_before_allocation(
    budget: ResourceBudget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_allocation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resource preflightより先に配列を確保した")

    monkeypatch.setattr(spiral_module.np, "linspace", fail_allocation)
    with resource_budget_context(budget), pytest.raises(ResourceLimitError, match="spiral"):
        spiral(samples=5)
