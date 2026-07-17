"""reaction_diffusion effect の実体変換に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.preview_quality import preview_quality_context
from grafix.core.realize import realize


def test_reaction_diffusion_contour_returns_closed_loops() -> None:
    mask = G.polygon(n_sides=64, scale=50.0)
    out = realize(
        E.reaction_diffusion(
            grid_pitch=2.0,
            steps=0,
            seed=0,
            seed_radius=12.0,
            noise=0.0,
            level=0.5,
            min_points=4,
        )(mask)
    )
    assert out.coords.shape[0] > 0
    assert out.offsets.size >= 2
    for i in range(int(out.offsets.size) - 1):
        s = int(out.offsets[i])
        e = int(out.offsets[i + 1])
        ring = out.coords[s:e]
        assert ring.shape[0] >= 4
        np.testing.assert_allclose(ring[0], ring[-1], rtol=0.0, atol=1e-6)


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
            grid_pitch=2.0,
            steps=0,
            noise=0.0,
            seed_radius=10.0,
            level=0.5,
            min_points=4,
        )(empty_mask)
    )
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]


def test_reaction_diffusion_is_deterministic_for_fixed_seed() -> None:
    mask = G.polygon(n_sides=24, scale=24.0)
    effect = E.reaction_diffusion(
        grid_pitch=1.5,
        steps=4,
        seed=37,
        seed_radius=4.0,
        noise=0.03,
        level=0.5,
        min_points=4,
    )

    first = realize(effect(mask))
    second = realize(effect(mask))

    np.testing.assert_array_equal(first.coords, second.coords)
    np.testing.assert_array_equal(first.offsets, second.offsets)


def test_reaction_diffusion_draft_caps_steps_and_reports_effective_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grafix.core.effects.reaction_diffusion as module

    seen_steps: list[int] = []

    def simulate(
        u0: np.ndarray,
        _v0: np.ndarray,
        _mask: np.ndarray,
        *,
        steps: int,
        **_kwargs: object,
    ) -> np.ndarray:
        seen_steps.append(int(steps))
        return np.zeros_like(u0)

    monkeypatch.setattr(module, "_gray_scott_simulate_masked", simulate)
    mask = G.polygon(n_sides=4, scale=10.0)
    with operation_diagnostic_context() as diagnostics:
        with preview_quality_context("draft"):
            realize(
                E.reaction_diffusion(
                    grid_pitch=2.0,
                    steps=5000,
                    seed_radius=0.0,
                    noise=0.0,
                    min_points=4,
                )(mask)
            )

    assert seen_steps == [600]
    assert any(
        item.op == "reaction_diffusion.steps"
        and item.original_value == 5000
        and item.effective_value == 600
        for item in diagnostics.snapshot()
    )
