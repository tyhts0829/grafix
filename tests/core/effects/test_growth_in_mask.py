"""growth_in_mask effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.realize import realize


def test_growth_in_mask_returns_empty_for_invalid_mask_even_when_show_mask() -> None:
    mask = G.line(length=100.0)

    out = realize(E.growth_in_mask(seed_count=8, iters=100, show_mask=False)(mask))
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]

    out_show = realize(E.growth_in_mask(seed_count=8, iters=100, show_mask=True)(mask))
    assert out_show.coords.shape == (0, 3)
    assert out_show.offsets.tolist() == [0]


def test_growth_in_mask_is_deterministic_for_same_seed() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)

    out1 = realize(E.growth_in_mask(seed_count=3, iters=40, seed=123)(mask))
    out2 = realize(E.growth_in_mask(seed_count=3, iters=40, seed=123)(mask))

    np.testing.assert_allclose(out1.coords, out2.coords, rtol=0.0, atol=1e-6)
    assert out1.offsets.tolist() == out2.offsets.tolist()


def test_growth_in_mask_stays_inside_mask_bbox_on_xy_plane() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)
    realized_mask = realize(mask)

    out = realize(E.growth_in_mask(seed_count=2, iters=60, seed=1)(mask))
    assert out.coords.shape[0] > 0

    out_min = np.min(out.coords[:, 0:2], axis=0)
    out_max = np.max(out.coords[:, 0:2], axis=0)
    mask_min = np.min(realized_mask.coords[:, 0:2], axis=0)
    mask_max = np.max(realized_mask.coords[:, 0:2], axis=0)

    eps = 1e-2
    assert float(out_min[0]) >= float(mask_min[0]) - eps
    assert float(out_min[1]) >= float(mask_min[1]) - eps
    assert float(out_max[0]) <= float(mask_max[0]) + eps
    assert float(out_max[1]) <= float(mask_max[1]) + eps


def test_growth_in_mask_seed_count_zero_returns_empty_or_mask() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)
    realized_mask = realize(mask)

    out = realize(E.growth_in_mask(seed_count=0, iters=100, show_mask=False)(mask))
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]

    out_show = realize(E.growth_in_mask(seed_count=0, iters=100, show_mask=True)(mask))
    np.testing.assert_allclose(out_show.coords, realized_mask.coords, rtol=0.0, atol=1e-6)
    assert out_show.offsets.tolist() == realized_mask.offsets.tolist()

