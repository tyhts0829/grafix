"""translate effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.effects.translate import translate
from grafix.core.operation_authoring import primitive
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


def test_translate_fixed_random_matches_numpy_reference_exactly() -> None:
    rng = np.random.default_rng(20260719)
    source = rng.standard_normal((521, 3), dtype=np.float32)
    deltas = (
        (1.25, 0.0, 0.0),
        (0.0, -2.5, 0.75),
        (3.0, -4.0, 5.0),
    )
    offsets = np.array([0, 100, source.shape[0]], dtype=np.int32)
    input_before = source.copy()

    for delta in deltas:
        expected, expected_offsets = _translate_reference(
            (source, offsets),
            delta=delta,
        )
        actual, actual_offsets = translate((source, offsets), delta=delta)

        _assert_array_bits_equal(actual, expected)
        assert actual.flags.c_contiguous
        assert actual_offsets is offsets
        assert expected_offsets is offsets

    _assert_array_bits_equal(source, input_before)


def test_translate_zero_component_preserves_broadcast_signed_zero_bits() -> None:
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
