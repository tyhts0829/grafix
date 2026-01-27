"""reaction_diffusion effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np

from grafix.api import E, G
from grafix.core.realize import realize


def test_reaction_diffusion_contour_non_empty() -> None:
    mask = G.polygon(n_sides=64, scale=50.0)
    out = realize(
        E.reaction_diffusion(
            mode="contour",
            grid_pitch=2.0,
            steps=0,
            seed=0,
            seed_radius=12.0,
            noise=0.0,
            level=0.5,
            min_points=2,
        )(mask)
    )
    assert out.coords.shape[0] > 0
    assert out.offsets.size >= 2


def test_reaction_diffusion_activate_false_is_noop() -> None:
    mask = G.polygon(n_sides=8, scale=30.0)
    out = realize(E.reaction_diffusion(activate=False)(mask))
    expected = realize(mask)
    np.testing.assert_allclose(out.coords, expected.coords, rtol=0.0, atol=1e-6)
    assert out.offsets.tolist() == expected.offsets.tolist()


def test_reaction_diffusion_empty_mask_returns_empty() -> None:
    empty_mask = G.polygon(activate=False)
    out = realize(
        E.reaction_diffusion(
            mode="contour",
            grid_pitch=2.0,
            steps=0,
            noise=0.0,
            seed_radius=10.0,
            level=0.5,
            min_points=2,
        )(empty_mask)
    )
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]


def test_reaction_diffusion_skeleton_smoke() -> None:
    mask = G.polygon(n_sides=64, scale=50.0)
    out = realize(
        E.reaction_diffusion(
            mode="skeleton",
            grid_pitch=2.0,
            steps=0,
            seed=0,
            seed_radius=25.0,
            noise=0.0,
            level=0.5,
            thinning_iters=20,
            min_points=2,
        )(mask)
    )
    assert out.coords.ndim == 2
    assert out.coords.shape[1] == 3
    assert out.offsets[0] == 0
    assert out.offsets[-1] == out.coords.shape[0]

