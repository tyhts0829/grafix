"""lowpass effect（高周波除去）の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple


@primitive
def lowpass_test_zigzag() -> GeomTuple:
    """交互に上下するジグザグ線を返す（高周波低減の確認用）。"""
    n = 101
    x = np.arange(n, dtype=np.float32)
    y = np.where((np.arange(n) % 2) == 0, 1.0, -1.0).astype(np.float32)
    coords = np.stack([x, y, np.zeros_like(x)], axis=1).astype(np.float32, copy=False)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


@primitive
def lowpass_test_almost_closed_square() -> GeomTuple:
    """ほぼ閉じた四角形（端点が近い）を返す（auto closed の確認用）。"""
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 10.0, 0.0],
            [0.0, 10.0, 0.0],
            [0.005, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


def test_lowpass_reduces_zigzag_energy() -> None:
    g = G.lowpass_test_zigzag()
    base = realize(g)
    out = realize(E.lowpass(step=1.0, sigma=3.0, closed="open")(g))

    base_y = base.coords[:, 1]
    out_y = out.coords[:, 1]
    assert float(np.std(out_y)) < float(np.std(base_y)) * 0.3


def test_lowpass_noop_when_sigma_is_zero() -> None:
    g = G.lowpass_test_zigzag()
    base = realize(g)
    out = realize(E.lowpass(step=1.0, sigma=0.0)(g))

    np.testing.assert_allclose(out.coords, base.coords, rtol=0.0, atol=0.0)
    assert out.offsets.tolist() == base.offsets.tolist()


def test_lowpass_auto_closed_outputs_closed_polyline() -> None:
    g = G.lowpass_test_almost_closed_square()
    out = realize(E.lowpass(step=2.0, sigma=2.0, closed="auto")(g))

    assert out.offsets.tolist() == [0, out.coords.shape[0]]
    assert out.coords.shape[0] >= 4
    assert np.array_equal(out.coords[0], out.coords[out.coords.shape[0] - 1])
