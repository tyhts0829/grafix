"""polygon プリミティブのポリライン形状に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.core.geometry import Geometry
from grafix.core.realize import realize
from grafix.core.primitives import polygon as _polygon_module  # noqa: F401


def test_polygon_polyline_is_closed() -> None:
    """開始点を終端に重ねた閉じたポリラインになる。"""
    sides = 5
    g = Geometry.create("polygon", params={"n_sides": sides})

    realized = realize(g)

    assert realized.coords.shape == (sides + 1, 3)
    assert realized.offsets.tolist() == [0, sides + 1]
    np.testing.assert_array_equal(realized.coords[0], realized.coords[-1])


def test_polygon_phase_rotates_first_vertex() -> None:
    """phase[deg] により頂点開始角が回転する。"""
    sides = 4

    g0 = Geometry.create("polygon", params={"n_sides": sides, "phase": 0.0})
    r0 = realize(g0)
    np.testing.assert_allclose(r0.coords[0], [0.5, 0.0, 0.0], rtol=0.0, atol=1e-6)

    g90 = Geometry.create("polygon", params={"n_sides": sides, "phase": 90.0})
    r90 = realize(g90)
    np.testing.assert_allclose(r90.coords[0], [0.0, 0.5, 0.0], rtol=0.0, atol=1e-6)


def test_polygon_center_and_scale_affect_coords() -> None:
    """center/scale が座標に反映される。"""
    g = Geometry.create(
        "polygon",
        params={
            "n_sides": 4,
            "center": (10.0, 20.0, 30.0),
            "scale": 2.0,
        },
    )
    realized = realize(g)
    np.testing.assert_allclose(realized.coords[0], [11.0, 20.0, 30.0], rtol=0.0, atol=1e-6)


def test_polygon_clamps_n_sides_lt_3() -> None:
    """n_sides < 3 は 3 にクランプされる。"""
    g = Geometry.create("polygon", params={"n_sides": 1})
    realized = realize(g)
    assert realized.coords.shape == (4, 3)
    assert realized.offsets.tolist() == [0, 4]


def test_polygon_sweep_partial_is_closed_by_chord() -> None:
    """sweep<360 のとき、外周の途中で止めて弦で閉じる。"""
    sides = 36  # 10° 刻み
    sweep = 300.0
    g = Geometry.create("polygon", params={"n_sides": sides, "sweep": sweep})
    realized = realize(g)

    assert realized.coords.shape == (32, 3)  # 0..300° の 31 点 + 閉じる 1 点
    np.testing.assert_array_equal(realized.coords[0], realized.coords[-1])

    expected_end = np.array(
        [
            0.5 * np.cos(np.deg2rad(sweep)),
            0.5 * np.sin(np.deg2rad(sweep)),
            0.0,
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(
        realized.coords[-2], expected_end, rtol=0.0, atol=1e-6
    )


def test_polygon_sweep_non_multiple_includes_endpoint() -> None:
    """sweep が 1 ステップ角の整数倍でない場合、端点（途中の点）を含める。"""
    sides = 36  # 10° 刻み
    sweep = 305.0
    g = Geometry.create("polygon", params={"n_sides": sides, "sweep": sweep})
    realized = realize(g)

    assert realized.coords.shape == (33, 3)  # 0..300° の 31 点 + 305° + 閉じる 1 点
    np.testing.assert_array_equal(realized.coords[0], realized.coords[-1])

    expected_end = np.array(
        [
            0.5 * np.cos(np.deg2rad(sweep)),
            0.5 * np.sin(np.deg2rad(sweep)),
            0.0,
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(
        realized.coords[-2], expected_end, rtol=0.0, atol=1e-6
    )
