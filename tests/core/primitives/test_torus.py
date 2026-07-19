"""torus プリミティブのワイヤーフレーム形状に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.core.geometry import Geometry
from grafix.core.primitives.torus import torus
from grafix.core.realize import realize
from grafix.core.primitives import torus as _torus_module  # noqa: F401


def _assert_polylines_closed(coords: np.ndarray, offsets: np.ndarray) -> None:
    """各ポリラインが閉じていることを検証する。"""
    for i in range(int(offsets.shape[0]) - 1):
        start = int(offsets[i])
        end = int(offsets[i + 1])
        np.testing.assert_array_equal(coords[start], coords[end - 1])


def test_torus_offsets_and_closed_polylines() -> None:
    """子午線+緯線の本数と offsets、閉ポリラインを満たす。"""
    major_segments = 8
    minor_segments = 6
    g = Geometry.create(
        "torus",
        params={
            "major_radius": 2.0,
            "minor_radius": 0.5,
            "major_segments": major_segments,
            "minor_segments": minor_segments,
        },
    )

    realized = realize(g)

    meridian_len = minor_segments + 1
    parallel_len = major_segments + 1
    expected_coords_n = major_segments * meridian_len + minor_segments * parallel_len

    assert realized.coords.shape == (expected_coords_n, 3)
    assert realized.offsets.shape == (major_segments + minor_segments + 1,)
    assert realized.offsets[0] == 0
    assert realized.offsets[-1] == expected_coords_n

    expected_offsets = [0]
    for i in range(major_segments):
        expected_offsets.append((i + 1) * meridian_len)
    base = major_segments * meridian_len
    for j in range(minor_segments):
        expected_offsets.append(base + (j + 1) * parallel_len)

    assert realized.offsets.tolist() == expected_offsets
    _assert_polylines_closed(realized.coords, realized.offsets)


def test_torus_center_and_scale_affect_coords() -> None:
    """center/scale が座標に反映される。"""
    params = {
        "major_radius": 2.0,
        "minor_radius": 0.5,
        "major_segments": 7,
        "minor_segments": 5,
    }

    base = realize(Geometry.create("torus", params=params))

    scaled = realize(
        Geometry.create(
            "torus",
            params={
                **params,
                "center": (10.0, 20.0, 30.0),
                "scale": 2.0,
            },
        )
    )

    center_vec = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    expected = base.coords * np.float32(2.0) + center_vec
    np.testing.assert_array_equal(scaled.coords, expected)


def test_torus_clamps_segments_lt_3() -> None:
    """major_segments/minor_segments < 3 は 3 にクランプされる。"""
    g = Geometry.create(
        "torus",
        params={
            "major_segments": 2,
            "minor_segments": 1,
        },
    )
    realized = realize(g)

    major_segments = 3
    minor_segments = 3
    meridian_len = minor_segments + 1
    parallel_len = major_segments + 1
    expected_coords_n = major_segments * meridian_len + minor_segments * parallel_len

    assert realized.coords.shape == (expected_coords_n, 3)
    assert realized.offsets.tolist() == [0, 4, 8, 12, 16, 20, 24]
    _assert_polylines_closed(realized.coords, realized.offsets)


def test_torus_raw_arrays_are_fresh_writable_and_non_sharing() -> None:
    """direct pack後もraw primitive APIの所有権契約を維持する。"""

    params = {"major_segments": 12, "minor_segments": 9}
    coords_a, offsets_a = torus(**params)
    coords_b, offsets_b = torus(**params)

    assert coords_a.flags.writeable
    assert offsets_a.flags.writeable
    assert coords_b.flags.writeable
    assert offsets_b.flags.writeable
    assert not np.shares_memory(coords_a, coords_b)
    assert not np.shares_memory(offsets_a, offsets_b)

    expected_coords = coords_b.copy()
    expected_offsets = offsets_b.copy()
    coords_a[0, 0] = np.float32(123.0)
    offsets_a[0] = np.int32(1)
    np.testing.assert_array_equal(coords_b, expected_coords)
    np.testing.assert_array_equal(offsets_b, expected_offsets)
