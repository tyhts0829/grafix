from __future__ import annotations

import numpy as np

from grafix.api import G
from grafix.core.realize import realize


def test_lissajous_realize_returns_single_polyline() -> None:
    realized = realize(G.lissajous())

    assert realized.coords.dtype == np.float32
    assert realized.offsets.dtype == np.int32
    assert realized.coords.shape == (512, 3)
    assert realized.offsets.tolist() == [0, 512]


def test_lissajous_is_deterministic_for_same_params() -> None:
    params = dict(
        a=3,
        b=2,
        phase=45.0,
        samples=300,
        turns=1.75,
        center=(0.0, 0.0, 0.0),
        scale=1.0,
    )
    a = realize(G.lissajous(**params))
    b = realize(G.lissajous(**params))

    assert np.array_equal(a.coords, b.coords)
    assert np.array_equal(a.offsets, b.offsets)


def test_lissajous_applies_center_and_scale() -> None:
    params = dict(a=3, b=2, phase=30.0, samples=240, turns=1.0)
    base = realize(G.lissajous(**params, center=(0.0, 0.0, 0.0), scale=1.0))
    transformed = realize(G.lissajous(**params, center=(10.0, -5.0, 2.0), scale=3.0))

    expected = base.coords * np.float32(3.0) + np.array([10.0, -5.0, 2.0], dtype=np.float32)
    assert np.allclose(transformed.coords, expected, atol=1e-6)
    assert transformed.offsets.tolist() == base.offsets.tolist()


def test_lissajous_is_not_forced_closed() -> None:
    realized = realize(
        G.lissajous(
            a=3,
            b=2,
            phase=0.0,
            samples=128,
            turns=0.75,
        )
    )

    assert not np.allclose(realized.coords[0], realized.coords[-1], atol=1e-6)


def test_lissajous_clamps_too_small_samples() -> None:
    realized = realize(G.lissajous(samples=1))

    assert realized.coords.shape == (2, 3)
    assert realized.offsets.tolist() == [0, 2]
