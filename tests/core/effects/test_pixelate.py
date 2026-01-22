"""pixelate effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import RealizedGeometry


@primitive
def pixelate_test_diag_3_2() -> RealizedGeometry:
    """(0,0)->(3,2) 相当の斜め 1 セグメントを返す（Z は 0→4 にスナップされる）。"""
    coords = np.array([[0.1, 0.1, 0.4], [3.2, 2.1, 3.6]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def pixelate_test_nonuniform_step_negative() -> RealizedGeometry:
    """非等方 step + 負方向の斜め 1 セグメントを返す。"""
    coords = np.array([[4.1, 1.01, 0.0], [0.4, -0.6, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def pixelate_test_noop_input() -> RealizedGeometry:
    """no-op 判定用の 2 点ポリラインを返す。"""
    coords = np.array([[0.1, 0.2, 0.3], [1.1, 1.2, 1.3]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def pixelate_test_y_major_2_3() -> RealizedGeometry:
    """(0,0)->(2,3) 相当の斜め 1 セグメントを返す。"""
    coords = np.array([[0.1, 0.1, 0.0], [2.1, 3.1, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def pixelate_test_empty() -> RealizedGeometry:
    """空ジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.array([0], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


@primitive
def pixelate_test_single_point() -> RealizedGeometry:
    """1 点ポリライン（頂点数 1）を返す。"""
    coords = np.array([[0.49, 0.51, -0.49]], dtype=np.float32)
    offsets = np.array([0, 1], dtype=np.int32)
    return RealizedGeometry(coords=coords, offsets=offsets)


def _assert_axis_aligned_xy(coords: np.ndarray, *, atol: float = 1e-6) -> None:
    if coords.shape[0] < 2:
        return
    d = coords[1:, :2] - coords[:-1, :2]
    dx = d[:, 0]
    dy = d[:, 1]
    ok = np.isclose(dx, 0.0, atol=atol) | np.isclose(dy, 0.0, atol=atol)
    assert bool(np.all(ok))


def test_pixelate_diag_3_2_stepwise_and_z_interp() -> None:
    g = G.pixelate_test_diag_3_2()
    realized = realize(E.pixelate(step=(1.0, 1.0, 2.0))(g))

    expected_xy = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [2.0, 1.0],
            [3.0, 1.0],
            [3.0, 2.0],
        ],
        dtype=np.float32,
    )
    expected_z = np.array([0.0, 0.8, 1.6, 2.4, 3.2, 4.0], dtype=np.float32)

    assert realized.offsets.tolist() == [0, 6]
    np.testing.assert_allclose(realized.coords[:, :2], expected_xy, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[:, 2], expected_z, rtol=0.0, atol=1e-6)
    _assert_axis_aligned_xy(realized.coords)


def test_pixelate_corner_yx_changes_path() -> None:
    g = G.pixelate_test_diag_3_2()
    realized = realize(E.pixelate(step=(1.0, 1.0, 2.0), corner="yx")(g))

    expected_xy = np.array(
        [
            [0.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, 1.0],
            [2.0, 2.0],
            [3.0, 2.0],
        ],
        dtype=np.float32,
    )
    expected_z = np.array([0.0, 0.8, 1.6, 2.4, 3.2, 4.0], dtype=np.float32)

    assert realized.offsets.tolist() == [0, 6]
    np.testing.assert_allclose(realized.coords[:, :2], expected_xy, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[:, 2], expected_z, rtol=0.0, atol=1e-6)
    _assert_axis_aligned_xy(realized.coords)


def test_pixelate_corner_xy_on_y_major_changes_path() -> None:
    g = G.pixelate_test_y_major_2_3()

    auto = realize(E.pixelate(step=(1.0, 1.0, 1.0), corner="auto")(g))
    xy = realize(E.pixelate(step=(1.0, 1.0, 1.0), corner="xy")(g))

    expected_auto_xy = np.array(
        [
            [0.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [1.0, 2.0],
            [1.0, 3.0],
            [2.0, 3.0],
        ],
        dtype=np.float32,
    )
    expected_xy_xy = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [1.0, 2.0],
            [2.0, 2.0],
            [2.0, 3.0],
        ],
        dtype=np.float32,
    )

    assert auto.offsets.tolist() == [0, 6]
    assert xy.offsets.tolist() == [0, 6]
    np.testing.assert_allclose(auto.coords[:, :2], expected_auto_xy, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(xy.coords[:, :2], expected_xy_xy, rtol=0.0, atol=1e-6)
    _assert_axis_aligned_xy(auto.coords)
    _assert_axis_aligned_xy(xy.coords)


def test_pixelate_nonuniform_step_negative_direction() -> None:
    g = G.pixelate_test_nonuniform_step_negative()
    realized = realize(E.pixelate(step=(2.0, 0.5, 1.0))(g))

    expected_xy = np.array(
        [
            [4.0, 1.0],
            [4.0, 0.5],
            [2.0, 0.5],
            [2.0, 0.0],
            [2.0, -0.5],
            [0.0, -0.5],
        ],
        dtype=np.float32,
    )
    assert realized.offsets.tolist() == [0, 6]
    np.testing.assert_allclose(realized.coords[:, :2], expected_xy, rtol=0.0, atol=1e-6)
    _assert_axis_aligned_xy(realized.coords)


def test_pixelate_step_non_positive_is_noop() -> None:
    g = G.pixelate_test_noop_input()
    realized = realize(E.pixelate(step=(0.0, 1.0, 1.0))(g))
    expected = np.array([[0.1, 0.2, 0.3], [1.1, 1.2, 1.3]], dtype=np.float32)
    np.testing.assert_allclose(realized.coords, expected, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == [0, 2]


def test_pixelate_empty_and_single_point() -> None:
    g0 = G.pixelate_test_empty()
    r0 = realize(E.pixelate(step=(1.0, 1.0, 1.0))(g0))
    assert r0.coords.shape == (0, 3)
    assert r0.offsets.tolist() == [0]

    g1 = G.pixelate_test_single_point()
    r1 = realize(E.pixelate(step=(1.0, 1.0, 1.0))(g1))
    expected = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(r1.coords, expected, rtol=0.0, atol=1e-6)
    assert r1.offsets.tolist() == [0, 1]
