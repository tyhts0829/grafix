"""scale effect の実体変換に関するテスト群。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.effects.scale import scale as scale_effect
from grafix.core.primitive_registry import primitive
from grafix.core.realize import RealizeSession, realize

_CLOSED_ATOL = 1e-6


def _reference_scale(
    g: tuple[np.ndarray, np.ndarray],
    *,
    mode: str = "all",
    auto_center: bool = True,
    pivot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[np.ndarray, np.ndarray]:
    """高速化前の NumPy 演算を保持した test-only 参照実装。"""
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    mode_s = str(mode)
    if mode_s not in {"all", "by_line", "by_face"}:
        return coords, offsets

    sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])
    if sx == 1.0 and sy == 1.0 and sz == 1.0:
        return coords, offsets

    factors = np.array([sx, sy, sz], dtype=np.float64)
    if mode_s == "all":
        if auto_center:
            center = coords.astype(np.float64, copy=False).mean(axis=0)
        else:
            center = np.array(
                [float(pivot[0]), float(pivot[1]), float(pivot[2])],
                dtype=np.float64,
            )

        shifted = coords.astype(np.float64, copy=False) - center
        scaled = shifted * factors + center
        return scaled.astype(np.float32, copy=False), offsets

    coords64 = coords.astype(np.float64, copy=True)
    for i in range(int(offsets.size) - 1):
        start = int(offsets[i])
        end = int(offsets[i + 1])
        if end <= start:
            continue

        vertices = coords64[start:end]
        is_closed = vertices.shape[0] >= 2 and bool(
            np.allclose(
                vertices[0],
                vertices[-1],
                rtol=0.0,
                atol=_CLOSED_ATOL,
            )
        )
        if mode_s == "by_line":
            if is_closed:
                continue
            center = vertices.mean(axis=0)
        else:
            if not is_closed:
                continue
            center = vertices[:-1].mean(axis=0)

        coords64[start:end] = (vertices - center) * factors + center

    return coords64.astype(np.float32, copy=False), offsets


def _assert_float32_bitwise_equal(actual: np.ndarray, expected: np.ndarray) -> None:
    """配列 layout に依存せず float32 の全 bit を比較する。"""
    assert actual.dtype == expected.dtype == np.float32
    assert actual.shape == expected.shape
    actual_bits = np.ascontiguousarray(actual).view(np.uint32)
    expected_bits = np.ascontiguousarray(expected).view(np.uint32)
    np.testing.assert_array_equal(actual_bits, expected_bits)


@primitive
def scale_test_line2_xy() -> tuple[np.ndarray, np.ndarray]:
    """xy 平面上の 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def scale_test_line_centered_x() -> tuple[np.ndarray, np.ndarray]:
    """中心 (2,0,0) を持つ 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def scale_test_empty() -> tuple[np.ndarray, np.ndarray]:
    """空のジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


@primitive
def scale_test_mixed_open_and_closed() -> tuple[np.ndarray, np.ndarray]:
    """開ポリライン 1 本 + 閉曲線 1 本を返す。"""
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [9.0, -1.0, 0.0],
            [11.0, -1.0, 0.0],
            [11.0, 1.0, 0.0],
            [9.0, 1.0, 0.0],
            [9.0, -1.0, 0.0],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, 2, 7], dtype=np.int32)
    return coords, offsets


def test_scale_about_origin() -> None:
    g = G.scale_test_line2_xy()
    scaled = E.scale(auto_center=False, pivot=(0.0, 0.0, 0.0), scale=(2.0, 0.5, 1.0))(g)
    realized = realize(scaled)

    expected = np.array([[2.0, 1.0, 0.0], [6.0, 2.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == [0, 2]


def test_scale_auto_center_ignores_pivot() -> None:
    g = G.scale_test_line_centered_x()
    scaled = E.scale(auto_center=True, pivot=(100.0, 0.0, 0.0), scale=(2.0, 1.0, 1.0))(g)
    realized = realize(scaled)

    expected = np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)


def test_scale_pivot_used_when_auto_center_false() -> None:
    g = G.scale_test_line_centered_x()
    scaled = E.scale(auto_center=False, pivot=(1.0, 0.0, 0.0), scale=(2.0, 1.0, 1.0))(g)
    realized = realize(scaled)

    expected = np.array([[1.0, 0.0, 0.0], [5.0, 0.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)


def test_scale_empty_geometry_is_noop() -> None:
    g = G.scale_test_empty()
    scaled = E.scale(scale=(2.0, 2.0, 2.0))(g)
    realized = realize(scaled)

    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_scale_identity_reuses_realized_input_for_every_mode() -> None:
    g = G.scale_test_mixed_open_and_closed()
    scaled_geometries = [
        E.scale(mode=mode, scale=(1.0, 1.0, 1.0))(g) for mode in ("all", "by_line", "by_face")
    ]
    with RealizeSession() as session:
        base = session.realize(g)
        for scaled in scaled_geometries:
            assert session.realize(scaled) is base


def test_scale_by_line_scales_each_open_polyline_and_keeps_closed_ones() -> None:
    g = G.scale_test_mixed_open_and_closed()
    scaled = E.scale(mode="by_line", scale=(0.5, 0.5, 1.0))(g)
    realized = realize(scaled)

    expected = np.array(
        [
            [1.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [9.0, -1.0, 0.0],
            [11.0, -1.0, 0.0],
            [11.0, 1.0, 0.0],
            [9.0, 1.0, 0.0],
            [9.0, -1.0, 0.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == [0, 2, 7]


def test_scale_by_face_scales_each_closed_polyline_and_keeps_open_ones() -> None:
    g = G.scale_test_mixed_open_and_closed()
    scaled = E.scale(mode="by_face", scale=(0.5, 0.5, 1.0))(g)
    realized = realize(scaled)

    expected = np.array(
        [
            [0.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [9.5, -0.5, 0.0],
            [10.5, -0.5, 0.0],
            [10.5, 0.5, 0.0],
            [9.5, 0.5, 0.0],
            [9.5, -0.5, 0.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == [0, 2, 7]


def test_scale_all_matches_previous_operations_bitwise_for_fixed_random_input() -> None:
    rng = np.random.default_rng(20260719)
    exponents = rng.integers(-60, 61, size=(1024, 3))
    coords = (rng.standard_normal((1024, 3)) * np.exp2(exponents)).astype(np.float32)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    coords_before = coords.copy()
    offsets_before = offsets.copy()

    for auto_center in (True, False):
        expected_coords, _ = _reference_scale(
            (coords, offsets),
            mode="all",
            auto_center=auto_center,
            pivot=(1.25e20, -3.5e-20, 7.0),
            scale=(-1.75, 0.0, 3.125),
        )
        actual_coords, actual_offsets = scale_effect(
            (coords, offsets),
            mode="all",
            auto_center=auto_center,
            pivot=(1.25e20, -3.5e-20, 7.0),
            scale=(-1.75, 0.0, 3.125),
        )

        _assert_float32_bitwise_equal(actual_coords, expected_coords)
        assert actual_offsets is offsets

    _assert_float32_bitwise_equal(coords, coords_before)
    np.testing.assert_array_equal(offsets, offsets_before)


def test_scale_many_lines_matches_previous_operations_bitwise_for_fixed_random_input() -> None:
    rng = np.random.default_rng(20260719)
    line_count = 128
    vertices_per_line = 7
    offsets = np.arange(line_count + 1, dtype=np.int32) * vertices_per_line
    exponents = rng.integers(-60, 61, size=(int(offsets[-1]), 3))
    coords = (rng.standard_normal(exponents.shape) * np.exp2(exponents)).astype(np.float32)
    lines = coords.reshape(line_count, vertices_per_line, 3)
    lines[::3, -1] = lines[::3, 0]
    coords_before = coords.copy()
    offsets_before = offsets.copy()

    for mode in ("by_line", "by_face"):
        expected_coords, _ = _reference_scale(
            (coords, offsets),
            mode=mode,
            scale=(-1.75, 0.0, 3.125),
        )
        actual_coords, actual_offsets = scale_effect(
            (coords, offsets),
            mode=mode,
            scale=(-1.75, 0.0, 3.125),
        )

        _assert_float32_bitwise_equal(actual_coords, expected_coords)
        assert actual_offsets is offsets

    _assert_float32_bitwise_equal(coords, coords_before)
    np.testing.assert_array_equal(offsets, offsets_before)


def test_scale_many_variable_lines_preserves_empty_and_one_point_line_semantics() -> None:
    rng = np.random.default_rng(20260719)
    lengths = np.tile(np.array([0, 1, 2, 3, 5, 8, 0, 4], dtype=np.int32), 4)
    offsets = np.concatenate(
        [np.zeros((1,), dtype=np.int32), np.cumsum(lengths, dtype=np.int32)]
    )
    exponents = rng.integers(-40, 41, size=(int(offsets[-1]), 3))
    coords = (rng.standard_normal(exponents.shape) * np.exp2(exponents)).astype(np.float32)
    for line_index, length in enumerate(lengths):
        if length >= 2 and line_index % 3 == 0:
            coords[offsets[line_index + 1] - 1] = coords[offsets[line_index]]

    for mode in ("by_line", "by_face"):
        expected_coords, _ = _reference_scale(
            (coords, offsets),
            mode=mode,
            scale=(-0.5, 2.0, 0.0),
        )
        actual_coords, actual_offsets = scale_effect(
            (coords, offsets),
            mode=mode,
            scale=(-0.5, 2.0, 0.0),
        )

        _assert_float32_bitwise_equal(actual_coords, expected_coords)
        assert actual_offsets is offsets


def test_scale_bulk_closure_uses_xyz_absolute_tolerance_and_nan_is_open() -> None:
    below = np.nextafter(np.float32(1e-6), np.float32(0.0))
    at_float32 = np.float32(1e-6)
    above = np.nextafter(np.float32(1e-6), np.float32(np.inf))
    endpoints = np.array(
        [
            [below, 0.0, 0.0],
            [0.0, at_float32, 0.0],
            [0.0, 0.0, above],
            [0.0, 0.0, 0.0],
            [np.nan, 0.0, 0.0],
            [np.inf, 0.0, 0.0],
            [-np.inf, 0.0, 0.0],
            [-above, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    first_vertices = np.zeros_like(endpoints)
    first_vertices[4:, 0] = endpoints[4:, 0]
    lines = np.empty((8, 3, 3), dtype=np.float32)
    lines[:, 0] = first_vertices
    lines[:, 1] = np.array([2.0, 3.0, 4.0], dtype=np.float32)
    lines[:, 2] = endpoints
    coords = lines.reshape(-1, 3)
    offsets = np.arange(9, dtype=np.int32) * 3

    expected_coords, _ = _reference_scale(
        (coords, offsets),
        mode="by_line",
        scale=(0.5, 2.0, -1.0),
    )
    actual_coords, _ = scale_effect(
        (coords, offsets),
        mode="by_line",
        scale=(0.5, 2.0, -1.0),
    )

    _assert_float32_bitwise_equal(actual_coords, expected_coords)
    closed_lines = (0, 1, 3, 5, 6)
    for line_index in closed_lines:
        _assert_float32_bitwise_equal(actual_coords[3 * line_index : 3 * line_index + 3], lines[line_index])


def test_scale_raw_direct_call_layouts_and_noncanonical_offsets_match_reference() -> None:
    class ArraySubclass(np.ndarray):
        pass

    rng = np.random.default_rng(20260719)
    base = rng.standard_normal((24, 3)).astype(np.float32)
    base.reshape(8, 3, 3)[::2, -1] = base.reshape(8, 3, 3)[::2, 0]
    canonical_offsets = np.arange(9, dtype=np.int32) * 3

    wide = np.zeros((48, 3), dtype=np.float32)
    wide[::2] = base
    readonly = base.copy()
    readonly.setflags(write=False)
    layouts_and_offsets: list[tuple[np.ndarray, np.ndarray]] = [
        (np.asfortranarray(base), canonical_offsets),
        (wide[::2], canonical_offsets),
        (readonly, canonical_offsets),
        (base.view(ArraySubclass), canonical_offsets),
        (base.astype(np.float64), canonical_offsets.astype(np.int64)),
        (
            base[:9],
            np.array([0, 2, 4, 3, 5, 5, 6, 8, 9], dtype=np.int32),
        ),
    ]

    for coords, offsets in layouts_and_offsets:
        coords_before = coords.copy()
        offsets_before = offsets.copy()
        for mode in ("by_line", "by_face"):
            expected_coords, _ = _reference_scale(
                (coords, offsets),
                mode=mode,
                scale=(-0.5, 2.0, 0.0),
            )
            actual_coords, actual_offsets = scale_effect(
                (coords, offsets),
                mode=mode,
                scale=(-0.5, 2.0, 0.0),
            )

            _assert_float32_bitwise_equal(actual_coords, expected_coords)
            assert actual_offsets is offsets

        np.testing.assert_array_equal(coords, coords_before)
        np.testing.assert_array_equal(offsets, offsets_before)


def test_scale_bulk_processes_line_metadata_in_bounded_chunks() -> None:
    rng = np.random.default_rng(20260719)
    line_count = 8200
    coords = rng.standard_normal((line_count * 2, 3), dtype=np.float32)
    offsets = np.arange(line_count + 1, dtype=np.int32) * 2

    expected_coords, _ = _reference_scale(
        (coords, offsets),
        mode="by_line",
        scale=(-0.5, 2.0, 0.0),
    )
    actual_coords, actual_offsets = scale_effect(
        (coords, offsets),
        mode="by_line",
        scale=(-0.5, 2.0, 0.0),
    )

    _assert_float32_bitwise_equal(actual_coords, expected_coords)
    assert actual_offsets is offsets


def test_scale_empty_and_invalid_mode_do_not_evaluate_other_arguments() -> None:
    empty_coords = np.zeros((0, 3), dtype=np.float32)
    empty_offsets = np.zeros((1,), dtype=np.int32)
    invalid_coords = np.ones((1, 3), dtype=np.float32)
    invalid_offsets = np.array([0, 1], dtype=np.int32)

    empty_result = scale_effect(
        (empty_coords, empty_offsets),
        mode=object(),
        pivot=(),
        scale=(),
    )
    invalid_mode_result = scale_effect(
        (invalid_coords, invalid_offsets),
        mode="invalid",
        pivot=(),
        scale=(),
    )

    assert empty_result[0] is empty_coords
    assert empty_result[1] is empty_offsets
    assert invalid_mode_result[0] is invalid_coords
    assert invalid_mode_result[1] is invalid_offsets


def test_scale_all_large_noncanonical_shape_keeps_broadcast_error() -> None:
    coords = np.ones((512, 4), dtype=np.float32)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)

    with pytest.raises(ValueError):
        scale_effect(
            (coords, offsets),
            mode="all",
            auto_center=True,
            scale=(2.0, 3.0, 4.0),
        )


def test_scale_all_ndarray_subclass_uses_previous_ufunc_dispatch() -> None:
    with np.testing.suppress_warnings() as suppressor:
        suppressor.filter(PendingDeprecationWarning)
        coords = np.matrix(
            np.arange(1536, dtype=np.float32).reshape(512, 3),
        )
        offsets = np.array([0, coords.shape[0]], dtype=np.int32)

        with pytest.raises(ValueError):
            scale_effect(
                (coords, offsets),
                mode="all",
                auto_center=False,
                pivot=(0.0, 0.0, 0.0),
                scale=(2.0, 3.0, 4.0),
            )


def test_scale_all_preserves_overflow_warning_count() -> None:
    coords = np.full((512, 3), np.finfo(np.float32).max, dtype=np.float32)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    scale_factors = (1.0e308, 1.0e308, 1.0e308)

    with warnings.catch_warnings(record=True) as expected_warnings:
        warnings.simplefilter("always")
        _reference_scale(
            (coords, offsets),
            mode="all",
            auto_center=False,
            pivot=(0.0, 0.0, 0.0),
            scale=scale_factors,
        )
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter("always")
        scale_effect(
            (coords, offsets),
            mode="all",
            auto_center=False,
            pivot=(0.0, 0.0, 0.0),
            scale=scale_factors,
        )

    assert [warning.category for warning in actual_warnings] == [
        warning.category for warning in expected_warnings
    ]
    assert [str(warning.message) for warning in actual_warnings] == [
        str(warning.message) for warning in expected_warnings
    ]
