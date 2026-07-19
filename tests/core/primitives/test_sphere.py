"""sphere プリミティブの出力形状と基本仕様に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import G
from grafix.core.geometry import Geometry
from grafix.core.primitives.sphere import _sphere_base_geometry, sphere
from grafix.core.realize import realize
from grafix.core.primitives import sphere as _sphere_module  # noqa: F401


def test_sphere_realize_returns_valid_realized_geometry() -> None:
    """coords/offsets の基本不変条件を満たす。"""
    g = Geometry.create(
        "sphere",
        params={"subdivisions": 0, "style": "latlon", "line_mode": "both"},
    )
    realized = realize(g)

    assert realized.coords.dtype == np.float32
    assert realized.coords.ndim == 2
    assert realized.coords.shape[1] == 3
    assert realized.coords.shape[0] > 0

    assert realized.offsets.dtype == np.int32
    assert realized.offsets.ndim == 1
    assert realized.offsets.size > 1
    assert int(realized.offsets[0]) == 0
    assert int(realized.offsets[-1]) == realized.coords.shape[0]


def test_sphere_subdivisions_is_clamped() -> None:
    """subdivisions は 0..5 にクランプされ、範囲外は端値と同一結果になる。"""
    g0 = Geometry.create(
        "sphere",
        params={"subdivisions": 0, "style": "latlon", "line_mode": "both"},
    )
    r0 = realize(g0)

    g_neg = Geometry.create(
        "sphere",
        params={"subdivisions": -999, "style": "latlon", "line_mode": "both"},
    )
    r_neg = realize(g_neg)

    np.testing.assert_array_equal(r_neg.coords, r0.coords)
    np.testing.assert_array_equal(r_neg.offsets, r0.offsets)

    g5 = Geometry.create(
        "sphere",
        params={"subdivisions": 5, "style": "latlon", "line_mode": "both"},
    )
    r5 = realize(g5)

    g_hi = Geometry.create(
        "sphere",
        params={"subdivisions": 999, "style": "latlon", "line_mode": "both"},
    )
    r_hi = realize(g_hi)

    np.testing.assert_array_equal(r_hi.coords, r5.coords)
    np.testing.assert_array_equal(r_hi.offsets, r5.offsets)


@pytest.mark.parametrize(
    ("parameter", "value"),
    (("style", "unknown"), ("line_mode", "diagonal")),
)
def test_sphere_semantic_choices_reject_unknown_values(parameter: str, value: str) -> None:
    """未知の意味名を別のstyleやline modeへ黙って置換しない。"""
    params = {"style": "latlon", "line_mode": "both", parameter: value}
    with pytest.raises(ValueError, match=f"sphere.*{parameter}"):
        G.sphere(**params)


def test_sphere_center_and_scale_affect_coords() -> None:
    """center/scale が座標に反映される。"""
    g = Geometry.create(
        "sphere",
        params={
            "style": "zigzag",
            "subdivisions": 0,
            "center": (10.0, 20.0, 30.0),
            "scale": 3.0,
        },
    )
    realized = realize(g)

    # zigzag の先頭点は (0, +R, 0)。R=0.5。
    np.testing.assert_allclose(realized.coords[0], [10.0, 21.5, 30.0], rtol=0.0, atol=1e-6)


@pytest.mark.parametrize("style", ("latlon", "zigzag", "icosphere", "rings"))
def test_sphere_raw_arrays_are_fresh_writable_and_do_not_share_cache(style: str) -> None:
    """配置前cacheを使っても、raw primitive APIは独立したwritable配列を返す。"""

    params = {"subdivisions": 2, "style": style, "line_mode": "both"}
    coords_a, offsets_a = sphere(**params)
    coords_b, offsets_b = sphere(**params)

    assert coords_a.flags.writeable
    assert offsets_a.flags.writeable
    assert coords_b.flags.writeable
    assert offsets_b.flags.writeable
    assert not np.shares_memory(coords_a, coords_b)
    assert not np.shares_memory(offsets_a, offsets_b)

    coords_expected = coords_b.copy()
    offsets_expected = offsets_b.copy()
    coords_a[0, 0] = np.float32(123.0)
    offsets_a[0] = np.int32(1)
    np.testing.assert_array_equal(coords_b, coords_expected)
    np.testing.assert_array_equal(offsets_b, offsets_expected)


def test_sphere_cached_base_is_immutable() -> None:
    """内部cache自体は書き換え不能とし、後続出力を汚染させない。"""

    coords, offsets = _sphere_base_geometry("icosphere", 2, 0)
    assert not coords.flags.writeable
    assert not offsets.flags.writeable
