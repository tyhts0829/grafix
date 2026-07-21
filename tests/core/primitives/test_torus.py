"""torus プリミティブのワイヤーフレーム形状に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives.torus import torus
from grafix.core.realize import RealizeError, realize
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
    g = G.torus(
        major_radius=2.0,
        minor_radius=0.5,
        major_segments=major_segments,
        minor_segments=minor_segments,
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

    base = realize(G.torus(**params))

    scaled = realize(
        G.torus(
            **params,
            center=(10.0, 20.0, 30.0),
            scale=2.0,
        )
    )

    center_vec = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    expected = base.coords * np.float32(2.0) + center_vec
    np.testing.assert_array_equal(scaled.coords, expected)


@pytest.mark.parametrize(
    ("major_segments", "minor_segments"),
    [(2, 3), (3, 2)],
)
def test_torus_rejects_segments_lt_3(
    major_segments: int,
    minor_segments: int,
) -> None:
    """公開 G 経路は 3 未満の分割数を拒否する。"""

    with pytest.raises(RealizeError) as exc_info:
        realize(
            G.torus(
                major_segments=major_segments,
                minor_segments=minor_segments,
            )
        )
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "major_segments/minor_segments は 3 以上" in str(
        exc_info.value.__cause__
    )


@pytest.mark.parametrize("name", ["major_radius", "minor_radius"])
def test_torus_rejects_negative_radius(name: str) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(G.torus(**{name: -0.1}))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "major_radius/minor_radius" in str(exc_info.value.__cause__)


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
