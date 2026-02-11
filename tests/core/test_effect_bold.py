"""core.effects.bold をテスト。"""

from __future__ import annotations

import numpy as np

from grafix.core.effects.bold import bold
from grafix.core.realized_geometry import GeomTuple


def _geometry(*, coords: list[tuple[float, float, float]], offsets: list[int]) -> GeomTuple:
    c = np.asarray(coords, dtype=np.float32)
    o = np.asarray(offsets, dtype=np.int32)
    return c, o


def test_bold_empty_inputs_returns_empty_geometry() -> None:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    out_coords, out_offsets = bold((coords, offsets))
    assert out_coords.shape == (0, 3)
    assert out_coords.dtype == np.float32
    assert out_offsets.tolist() == [0]
    assert out_offsets.dtype == np.int32


def test_bold_count_le_1_is_noop() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)],
        offsets=[0, 2],
    )
    out_coords, out_offsets = bold((base_coords, base_offsets), count=1, radius=1.0)
    assert out_coords is base_coords
    assert out_offsets is base_offsets


def test_bold_radius_le_0_is_noop() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)],
        offsets=[0, 2],
    )
    out_coords, out_offsets = bold((base_coords, base_offsets), count=3, radius=0.0)
    assert out_coords is base_coords
    assert out_offsets is base_offsets


def test_bold_repeats_geometry_and_preserves_offsets_structure() -> None:
    base_coords, base_offsets = _geometry(
        coords=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 1.0, 0.0),
            (10.0, 2.0, 0.0),
        ],
        offsets=[0, 2, 5],
    )

    out_coords, out_offsets = bold((base_coords, base_offsets), count=3, radius=1.0, seed=123)

    assert out_coords.dtype == np.float32
    assert out_offsets.dtype == np.int32

    assert out_coords.shape == (15, 3)
    assert out_offsets.tolist() == [0, 2, 5, 7, 10, 12, 15]

    n = int(base_coords.shape[0])
    assert np.allclose(out_coords[:n], base_coords, atol=1e-6)

    for k in range(3):
        s = k * n
        e = s + n
        delta = out_coords[s:e].astype(np.float64, copy=False) - base_coords.astype(
            np.float64, copy=False
        )
        assert np.allclose(delta[:, 2], 0.0, atol=1e-6)
        assert np.allclose(delta[:, 0], delta[0, 0], atol=1e-6)
        assert np.allclose(delta[:, 1], delta[0, 1], atol=1e-6)


def test_bold_is_deterministic_for_same_seed() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        offsets=[0, 3],
    )

    out1_coords, out1_offsets = bold((base_coords, base_offsets), count=5, radius=1.0, seed=999)
    out2_coords, out2_offsets = bold((base_coords, base_offsets), count=5, radius=1.0, seed=999)

    assert out1_offsets.tolist() == out2_offsets.tolist()
    assert np.allclose(out1_coords, out2_coords, atol=0.0)
