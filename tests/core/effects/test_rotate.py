"""rotate effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.effects.rotate import rotate
from grafix.core.operation_authoring import primitive
from grafix.core.realize import RealizeSession, realize


def _rotate_reference(
    g: tuple[np.ndarray, np.ndarray],
    *,
    auto_center: bool = True,
    pivot: object = (0.0, 0.0, 0.0),
    rotation: object = (0.0, 0.0, 0.0),
) -> tuple[np.ndarray, np.ndarray]:
    """高速化前の実装と同じ演算順で比較結果を作る。"""
    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    rx_deg = float(rotation[0])  # type: ignore[index]
    ry_deg = float(rotation[1])  # type: ignore[index]
    rz_deg = float(rotation[2])  # type: ignore[index]
    if rx_deg == 0.0 and ry_deg == 0.0 and rz_deg == 0.0:
        return coords, offsets

    rx, ry, rz = np.deg2rad([rx_deg, ry_deg, rz_deg]).astype(np.float64)
    if auto_center:
        center = coords.astype(np.float64, copy=False).mean(axis=0)
    else:
        center = np.array(
            [
                float(pivot[0]),  # type: ignore[index]
                float(pivot[1]),  # type: ignore[index]
                float(pivot[2]),  # type: ignore[index]
            ],
            dtype=np.float64,
        )

    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rx_mat = np.array(
        [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]],
        dtype=np.float64,
    )
    ry_mat = np.array(
        [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]],
        dtype=np.float64,
    )
    rz_mat = np.array(
        [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    rot = rz_mat @ ry_mat @ rx_mat
    shifted = coords.astype(np.float64, copy=False) - center
    rotated = shifted @ rot.T + center
    return rotated.astype(np.float32, copy=False), offsets


def _assert_array_bits_equal(actual: np.ndarray, expected: np.ndarray) -> None:
    """配列の論理順に沿って dtype・shape・全 bit の一致を確認する。"""
    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes(order="C") == expected.tobytes(order="C")


@primitive
def rotate_test_line3() -> tuple[np.ndarray, np.ndarray]:
    """x 軸上の 3 点ポリラインを返す。"""
    coords = np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 3], dtype=np.int32)
    return coords, offsets


@primitive
def rotate_test_line2() -> tuple[np.ndarray, np.ndarray]:
    """x 軸上の 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def rotate_test_line_centered() -> tuple[np.ndarray, np.ndarray]:
    """中心 (2,0,0) を持つ 2 点ポリラインを返す。"""
    coords = np.array([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def rotate_test_empty() -> tuple[np.ndarray, np.ndarray]:
    """空のジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


def test_rotate_z_90_about_origin() -> None:
    g = G.rotate_test_line3()
    rotated = E.rotate(auto_center=False, pivot=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 90.0))(g)
    with RealizeSession() as session:
        base = session.realize(g)
        realized = session.realize(rotated)

    expected = np.array([[0.0, 1.0, 0.0], [0.0, 2.0, 0.0], [0.0, 3.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets is base.offsets
    assert not realized.coords.flags.writeable


def test_rotate_auto_center_ignores_pivot() -> None:
    g = G.rotate_test_line_centered()
    rotated = E.rotate(auto_center=True, pivot=(100.0, 0.0, 0.0), rotation=(0.0, 0.0, 180.0))(g)
    realized = realize(rotated)

    expected = np.array([[3.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)


def test_rotate_pivot_used_when_auto_center_false() -> None:
    g = G.rotate_test_line2()
    rotated = E.rotate(auto_center=False, pivot=(1.0, 0.0, 0.0), rotation=(0.0, 0.0, 90.0))(g)
    realized = realize(rotated)

    expected = np.array([[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)


def test_rotate_empty_geometry_is_noop() -> None:
    g = G.rotate_test_empty()
    rotated = E.rotate(rotation=(10.0, 20.0, 30.0))(g)
    realized = realize(rotated)

    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_rotate_identity_reuses_realized_input() -> None:
    g = G.rotate_test_line3()
    rotated = E.rotate(rotation=(0.0, -0.0, 0.0))(g)
    with RealizeSession() as session:
        base = session.realize(g)
        realized = session.realize(rotated)

    assert realized is base


def test_rotate_fixed_random_matches_numpy_reference_exactly() -> None:
    rng = np.random.default_rng(20260719)
    # large-input working-buffer 経路の閾値を超える canonical 入力を使う。
    source = rng.standard_normal((1537, 3), dtype=np.float32)
    source[:4] *= np.array([1.0e30, 1.0e20, 1.0e10], dtype=np.float32)
    cases = (
        (True, (999.0, 999.0, 999.0), (90.0, 0.0, 0.0)),
        (True, (-3.0, 4.0, 5.0), (0.0, -90.0, 0.0)),
        (False, (11.5, -7.25, 3.0), (0.0, 0.0, 90.0)),
        (False, (11.5, -7.25, 3.0), (17.25, -33.5, 71.125)),
        (False, (-1.0e20, 1.0e20, 0.25), (180.0, -360.0, 1.0e6)),
    )
    offsets = np.array([0, 100, source.shape[0]], dtype=np.int32)
    input_before = source.copy()

    for auto_center, pivot, rotation in cases:
        expected, expected_offsets = _rotate_reference(
            (source, offsets),
            auto_center=auto_center,
            pivot=pivot,
            rotation=rotation,
        )
        actual, actual_offsets = rotate(
            (source, offsets),
            auto_center=auto_center,
            pivot=pivot,
            rotation=rotation,
        )

        _assert_array_bits_equal(actual, expected)
        assert actual.flags.c_contiguous
        assert actual_offsets is offsets
        assert expected_offsets is offsets

    _assert_array_bits_equal(source, input_before)


def test_rotate_keeps_blas_orientation_at_float32_round_boundary() -> None:
    coord_bits = np.array(
        [
            [1473114668, 1481210468, 1479372857],
            [1436863722, 1481132386, 1482199458],
            [1482021985, 3627982138, 3601405920],
        ],
        dtype=np.uint32,
    )
    # 既知の丸め境界を fast-path 閾値より多く並べ、F-order working
    # buffer を使っても BLAS 積方向が保たれることを確認する。
    coords = np.tile(coord_bits.view(np.float32), (400, 1))
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    pivot = tuple(
        float.fromhex(value)
        for value in (
            "-0x1.bc3c9654a8272p+41",
            "-0x1.9fee9808e4870p+48",
            "0x1.8ca076421f4ebp+46",
        )
    )
    rotation = tuple(
        float.fromhex(value)
        for value in (
            "0x1.574acd30df8c3p+16",
            "0x1.88c9c51a1116cp+19",
            "-0x1.64f9e796b1f29p+15",
        )
    )

    expected, _ = _rotate_reference(
        (coords, offsets),
        auto_center=False,
        pivot=pivot,
        rotation=rotation,
    )
    actual, actual_offsets = rotate(
        (coords, offsets),
        auto_center=False,
        pivot=pivot,
        rotation=rotation,
    )

    _assert_array_bits_equal(actual, expected)
    assert actual.flags.c_contiguous
    assert actual_offsets is offsets


def test_rotate_transformed_result_reuses_offsets_and_does_not_mutate_input() -> None:
    coords = np.array(
        [[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0], [7.0, -8.0, 9.0]],
        dtype=np.float32,
    )
    offsets = np.array([0, 1, 3], dtype=np.int32)
    coords_before = coords.copy()
    offsets_before = offsets.copy()

    actual, actual_offsets = rotate(
        (coords, offsets),
        auto_center=False,
        pivot=(1.5, -2.0, 0.25),
        rotation=(13.0, -29.0, 47.0),
    )

    assert actual.dtype == np.float32
    assert actual.shape == coords.shape
    assert actual_offsets is offsets
    _assert_array_bits_equal(coords, coords_before)
    _assert_array_bits_equal(offsets, offsets_before)
