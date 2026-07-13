"""isocontour effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.effects.isocontour import isocontour
from grafix.core.realize import realize


def test_isocontour_returns_closed_loops() -> None:
    mask = G.polygon(n_sides=64, scale=50.0)
    out = realize(
        E.isocontour(
            grid_pitch=1.0,
            spacing=5.0,
            phase=0.0,
            max_dist=20.0,
            mode="inside",
            gamma=1.0,
            level_step=1,
        )(mask)
    )

    assert out.coords.shape[0] > 0
    assert out.offsets.size >= 2
    np.testing.assert_allclose(out.coords[:, 2], 0.0, rtol=0.0, atol=1e-4)
    for i in range(int(out.offsets.size) - 1):
        s = int(out.offsets[i])
        e = int(out.offsets[i + 1])
        ring = out.coords[s:e]
        assert ring.shape[0] >= 4
        np.testing.assert_allclose(ring[0], ring[-1], rtol=0.0, atol=1e-6)


def test_isocontour_level_step_reduces_levels() -> None:
    mask = G.polygon(n_sides=64, scale=50.0)
    dense = realize(
        E.isocontour(
            grid_pitch=1.0,
            spacing=2.0,
            max_dist=20.0,
            mode="inside",
            level_step=1,
        )(mask)
    )
    sparse = realize(
        E.isocontour(
            grid_pitch=1.0,
            spacing=2.0,
            max_dist=20.0,
            mode="inside",
            level_step=2,
        )(mask)
    )

    assert int(sparse.offsets.size) < int(dense.offsets.size)


def test_isocontour_activate_false_is_noop() -> None:
    mask = G.polygon(n_sides=8, scale=30.0)
    out = realize(E.isocontour(activate=False)(mask))
    expected = realize(mask)
    np.testing.assert_allclose(out.coords, expected.coords, rtol=0.0, atol=1e-6)
    assert out.offsets.tolist() == expected.offsets.tolist()


def test_isocontour_empty_mask_returns_empty() -> None:
    empty_mask = G.polygon(activate=False)
    out = realize(E.isocontour(grid_pitch=1.0, spacing=2.0, max_dist=10.0)(empty_mask))
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]


def test_isocontour_outer_hole_on_tilted_plane() -> None:
    outer_xy = np.asarray([[0, 0], [12, 0], [12, 12], [0, 12], [0, 0]], dtype=np.float32)
    hole_xy = np.asarray([[4, 4], [4, 8], [8, 8], [8, 4], [4, 4]], dtype=np.float32)
    xy = np.concatenate([outer_xy, hole_xy], axis=0)
    coords = np.column_stack([xy, xy[:, 0] + xy[:, 1]]).astype(np.float32)
    offsets = np.asarray([0, outer_xy.shape[0], xy.shape[0]], dtype=np.int32)

    out_coords, out_offsets = isocontour(
        (coords, offsets),
        grid_pitch=0.5,
        spacing=2.0,
        max_dist=4.0,
        mode="inside",
    )

    assert out_offsets.size > 1
    np.testing.assert_allclose(
        out_coords[:, 2], out_coords[:, 0] + out_coords[:, 1], rtol=0.0, atol=2e-5
    )
