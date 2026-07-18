"""translate effect の実体変換に関するテスト群。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.effects.translate import translate
from grafix.core.primitive_registry import primitive
from grafix.core.realize import RealizeSession, realize


def _translate_reference(
    g: tuple[np.ndarray, np.ndarray],
    *,
    delta: object,
) -> tuple[np.ndarray, np.ndarray]:
    """高速化前の実装と同じ演算順で比較結果を作る。"""
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    dx, dy, dz = float(delta[0]), float(delta[1]), float(delta[2])  # type: ignore[index]
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        return coords, offsets

    delta_vec = np.array([dx, dy, dz], dtype=np.float32)
    return coords + delta_vec, offsets


def _assert_array_bits_equal(actual: np.ndarray, expected: np.ndarray) -> None:
    """配列の論理順に沿って dtype・shape・全 bit の一致を確認する。"""
    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes(order="C") == expected.tobytes(order="C")


@primitive
def translate_test_line2_xy() -> tuple[np.ndarray, np.ndarray]:
    """xy 平面上の 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def translate_test_empty() -> tuple[np.ndarray, np.ndarray]:
    """空のジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


def test_translate_adds_delta() -> None:
    g = G.translate_test_line2_xy()
    moved = E.translate(delta=(10.0, -2.0, 3.5))(g)
    with RealizeSession() as session:
        base = session.realize(g)
        realized = session.realize(moved)

    expected = np.array([[11.0, 0.0, 3.5], [13.0, 2.0, 3.5]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets is base.offsets
    assert not realized.coords.flags.writeable


def test_translate_zero_delta_is_noop() -> None:
    g = G.translate_test_line2_xy()
    moved = E.translate(delta=(0.0, 0.0, 0.0))(g)
    realized = realize(moved)

    expected = np.array([[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == [0, 2]


def test_translate_identity_reuses_realized_input() -> None:
    g = G.translate_test_line2_xy()
    moved = E.translate(delta=(0.0, -0.0, 0.0))(g)
    with RealizeSession() as session:
        base = session.realize(g)
        realized = session.realize(moved)

    assert realized is base


def test_translate_empty_geometry_is_noop() -> None:
    g = G.translate_test_empty()
    moved = E.translate(delta=(10.0, 20.0, 30.0))(g)
    realized = realize(moved)

    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_translate_fixed_random_matches_previous_implementation_exactly() -> None:
    rng = np.random.default_rng(20260719)
    source = rng.standard_normal((521, 3), dtype=np.float32)
    source[:4] = np.array(
        [
            [np.nan, np.inf, -np.inf],
            [np.finfo(np.float32).max, 1.0, -1.0],
            [-np.finfo(np.float32).max, -1.0, 1.0],
            [
                np.nextafter(np.float32(0.0), np.float32(1.0)),
                np.nextafter(np.float32(0.0), np.float32(-1.0)),
                0.0,
            ],
        ],
        dtype=np.float32,
    )
    strided_storage = np.empty((source.shape[0] * 2, 3), dtype=np.float32)
    strided_storage[::2] = source
    readonly = source.copy()
    readonly.setflags(write=False)
    layouts = (source.copy(), np.asfortranarray(source), strided_storage[::2], readonly)
    tiny = float(np.nextafter(np.float32(0.0), np.float32(1.0)))
    deltas = (
        (1.25, 0.0, 0.0),
        (0.0, -2.5, 0.75),
        (3.0, -4.0, 5.0),
        (np.nan, 1.0, 0.0),
        (np.inf, -np.inf, 1.0),
        (float(np.finfo(np.float32).max), 1.0, -1.0),
        (tiny, -tiny, tiny),
    )
    offsets = np.array([0, 100, source.shape[0]], dtype=np.int32)

    for coords in layouts:
        input_before = coords.tobytes(order="C")
        for delta in deltas:
            with np.errstate(all="ignore"):
                expected, expected_offsets = _translate_reference(
                    (coords, offsets),
                    delta=delta,
                )
                actual, actual_offsets = translate((coords, offsets), delta=delta)

            _assert_array_bits_equal(actual, expected)
            assert actual.flags.c_contiguous == expected.flags.c_contiguous
            assert actual.flags.f_contiguous == expected.flags.f_contiguous
            assert actual_offsets is offsets
            assert expected_offsets is offsets
            assert coords.tobytes(order="C") == input_before


def test_translate_zero_component_preserves_previous_signed_zero_bits() -> None:
    coords = np.zeros((512, 3), dtype=np.float32)
    coords[:, 1:] = np.float32(-0.0)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)

    expected, _ = _translate_reference(
        (coords, offsets),
        delta=(1.0, 0.0, -0.0),
    )
    actual, actual_offsets = translate(
        (coords, offsets),
        delta=(1.0, 0.0, -0.0),
    )

    _assert_array_bits_equal(actual, expected)
    assert actual_offsets is offsets


def test_translate_large_path_preserves_overflow_warning_count() -> None:
    coords = np.full((512, 3), np.finfo(np.float32).max, dtype=np.float32)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    delta = tuple([float(np.finfo(np.float32).max)] * 3)

    with warnings.catch_warnings(record=True) as expected_warnings:
        warnings.simplefilter("always")
        _translate_reference((coords, offsets), delta=delta)
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter("always")
        translate((coords, offsets), delta=delta)

    assert [warning.category for warning in actual_warnings] == [
        warning.category for warning in expected_warnings
    ]
    assert [str(warning.message) for warning in actual_warnings] == [
        str(warning.message) for warning in expected_warnings
    ]


@pytest.mark.parametrize("dtype", [np.float16, np.float64, np.int32])
def test_translate_raw_non_float32_preserves_numpy_dtype_semantics(
    dtype: type[np.generic],
) -> None:
    coords = np.array([[1, 2, 3], [-4, 5, -6]], dtype=dtype)
    offsets = np.array([0, 2], dtype=np.int64)
    delta = (0.25, -2.5, 8.0)
    expected, _ = _translate_reference((coords, offsets), delta=delta)
    actual, actual_offsets = translate((coords, offsets), delta=delta)

    _assert_array_bits_equal(actual, expected)
    assert actual_offsets is offsets
    _assert_array_bits_equal(coords, np.array([[1, 2, 3], [-4, 5, -6]], dtype=dtype))


def test_translate_parameter_evaluation_order_and_ignored_tail_are_unchanged() -> None:
    events: list[int] = []

    class Delta:
        def __getitem__(self, index: int) -> float:
            events.append(index)
            if index == 1:
                raise RuntimeError("second component")
            return float(index)

    coords = np.ones((1, 3), dtype=np.float32)
    offsets = np.array([0, 1], dtype=np.int32)
    with pytest.raises(RuntimeError, match="second component"):
        translate((coords, offsets), delta=Delta())  # type: ignore[arg-type]
    assert events == [0, 1]

    actual, _ = translate((coords, offsets), delta=(1.0, 2.0, 3.0, "ignored"))
    np.testing.assert_array_equal(actual, np.array([[2.0, 3.0, 4.0]], dtype=np.float32))


def test_translate_empty_input_does_not_evaluate_malformed_delta() -> None:
    coords = np.empty((0, 3), dtype=np.float32)
    offsets = np.array([0], dtype=np.int32)

    actual_coords, actual_offsets = translate((coords, offsets), delta=())  # type: ignore[arg-type]

    assert actual_coords is coords
    assert actual_offsets is offsets
