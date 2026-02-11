"""core.effects.wobble をテスト。"""

from __future__ import annotations

import numpy as np

from grafix.core.effects.wobble import wobble
from grafix.core.realized_geometry import GeomTuple


def _line(coords: list[tuple[float, float, float]]) -> GeomTuple:
    c = np.asarray(coords, dtype=np.float32)
    o = np.asarray([0, c.shape[0]], dtype=np.int32)
    return c, o


def test_wobble_empty_inputs_returns_empty_geometry() -> None:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    out_coords, out_offsets = wobble((coords, offsets))
    assert out_coords.shape == (0, 3)
    assert out_coords.dtype == np.float32
    assert out_offsets.tolist() == [0]
    assert out_offsets.dtype == np.int32


def test_wobble_amplitude_zero_is_noop() -> None:
    base_coords, base_offsets = _line([(0.0, 1.0, 2.0), (10.0, 20.0, 30.0)])
    out_coords, out_offsets = wobble((base_coords, base_offsets), amplitude=(0.0, 0.0, 0.0))
    assert out_coords is base_coords
    assert out_offsets is base_offsets


def test_wobble_matches_componentwise_formula() -> None:
    base_coords, base_offsets = _line([(0.0, 0.0, 0.0), (10.0, 5.0, -2.0), (20.0, -3.0, 4.0)])
    out_coords, out_offsets = wobble(
        (base_coords, base_offsets),
        amplitude=(2.0, 3.0, 4.0),
        frequency=(0.05, 0.1, 0.2),
        phase=30.0,
    )

    v = base_coords.astype(np.float64, copy=False)
    phase_rad = float(np.deg2rad(30.0))
    expected = v.copy()
    expected[:, 0] = v[:, 0] + 2.0 * np.sin(2.0 * np.pi * 0.05 * v[:, 0] + phase_rad)
    expected[:, 1] = v[:, 1] + 3.0 * np.sin(2.0 * np.pi * 0.1 * v[:, 1] + phase_rad)
    expected[:, 2] = v[:, 2] + 4.0 * np.sin(2.0 * np.pi * 0.2 * v[:, 2] + phase_rad)

    assert out_coords.dtype == np.float32
    assert out_offsets is base_offsets
    assert np.allclose(out_coords, expected.astype(np.float32, copy=False), atol=1e-6)
