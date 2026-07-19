"""growth effect の実体変換に関するテスト群。"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.preview_quality import preview_quality_context
from grafix.core.realize import realize


def _geometry_digest(geometry: tuple[np.ndarray, np.ndarray]) -> str:
    digest = hashlib.sha256()
    digest.update(geometry[0].tobytes())
    digest.update(geometry[1].tobytes())
    return digest.hexdigest()


def test_growth_insert_noop_reuses_unchanged_ring() -> None:
    import grafix.core.effects.growth as module

    ring = np.asarray(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    before = ring.tobytes()

    actual = module._insert_points_ring_xy(ring, target_spacing=2.0)

    assert actual is ring
    assert ring.tobytes() == before


def test_growth_build_prev_next_handles_multiple_rings_exactly() -> None:
    import grafix.core.effects.growth as module

    offsets = np.asarray([0, 4, 7, 12], dtype=np.int32)

    previous, following = module._build_prev_next(12, offsets)

    np.testing.assert_array_equal(
        previous,
        np.asarray([3, 0, 1, 2, 6, 4, 5, 11, 7, 8, 9, 10], dtype=np.int32),
    )
    np.testing.assert_array_equal(
        following,
        np.asarray([1, 2, 3, 0, 5, 6, 4, 8, 9, 10, 11, 7], dtype=np.int32),
    )


@pytest.mark.parametrize(
    ("quality", "iters", "boundary_mode", "expected_shape", "expected_sha256"),
    [
        (
            "final",
            1,
            "slide",
            (61, 3),
            "9b55c60ab27d115876c80faf31d74fcc79ec4ddad6a284e22c83e6565e39efb9",
        ),
        (
            "final",
            9,
            "slide",
            (70, 3),
            "071062eab5f7def176228d975e25b47be27ce187ddd83f4d07bd5cb435742e42",
        ),
        (
            "final",
            9,
            "bounce",
            (71, 3),
            "e6d8369f40c5e56e044561c6d9f4f54f155b46c4d76e0f7d1ca90ce0cdec4035",
        ),
        (
            "draft",
            64,
            "slide",
            (97, 3),
            "cdcef04db71dca81d58fe88be574876f9bd15eb0f39d68c3928faeb072ed2399",
        ),
        (
            "final",
            64,
            "slide",
            (162, 3),
            "26e9878be42d0045fac38bf43492c291ccc337b09df8c56a039ef80b27cd5ac1",
        ),
    ],
)
def test_growth_matches_frozen_iteration_and_quality_snapshots(
    quality: str,
    iters: int,
    boundary_mode: str,
    expected_shape: tuple[int, int],
    expected_sha256: str,
) -> None:
    import grafix.core.effects.growth as module

    realized_mask = realize(G.polygon(n_sides=32, scale=80.0))
    mask = (realized_mask.coords, realized_mask.offsets)
    with preview_quality_context(quality):  # type: ignore[arg-type]
        actual = module.growth(
            mask,
            seed_count=4,
            target_spacing=3.0,
            boundary_avoid=1.0,
            boundary_mode=boundary_mode,
            iters=iters,
            seed=37,
        )

    assert actual[0].shape == expected_shape
    assert _geometry_digest(actual) == expected_sha256


def test_growth_returns_empty_for_invalid_mask_even_when_show_mask() -> None:
    mask = G.line(length=100.0)

    out = realize(E.growth(seed_count=8, iters=100, show_mask=False)(mask))
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]

    out_show = realize(E.growth(seed_count=8, iters=100, show_mask=True)(mask))
    assert out_show.coords.shape == (0, 3)
    assert out_show.offsets.tolist() == [0]


def test_growth_is_deterministic_for_same_seed() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)

    out1 = realize(E.growth(seed_count=3, iters=40, seed=123)(mask))
    out2 = realize(E.growth(seed_count=3, iters=40, seed=123)(mask))

    np.testing.assert_allclose(out1.coords, out2.coords, rtol=0.0, atol=1e-6)
    assert out1.offsets.tolist() == out2.offsets.tolist()


def test_growth_stays_inside_mask_bbox_on_xy_plane() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)
    realized_mask = realize(mask)

    out = realize(E.growth(seed_count=2, iters=60, seed=1)(mask))
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


def test_growth_seed_count_zero_returns_empty_or_mask() -> None:
    mask = G.polygon(n_sides=4, scale=60.0)
    realized_mask = realize(mask)

    out = realize(E.growth(seed_count=0, iters=100, show_mask=False)(mask))
    assert out.coords.shape == (0, 3)
    assert out.offsets.tolist() == [0]

    out_show = realize(E.growth(seed_count=0, iters=100, show_mask=True)(mask))
    np.testing.assert_allclose(out_show.coords, realized_mask.coords, rtol=0.0, atol=1e-6)
    assert out_show.offsets.tolist() == realized_mask.offsets.tolist()


def test_growth_draft_caps_iterations_and_sets_total_point_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grafix.core.effects.growth as module

    seen_limits: list[tuple[int, int | None]] = []

    def simulate(
        rings_xy: list[np.ndarray],
        *,
        iters: int,
        max_total_points: int | None,
        **_kwargs: object,
    ) -> object:
        seen_limits.append((int(iters), max_total_points))
        point_count = int(sum(int(ring.shape[0]) for ring in rings_xy))
        grid_limit = _kwargs.get("max_force_grid_cells")
        return module._GrowthSimulationResult(
            rings_xy,
            int(iters),
            point_count,
            False,
            None,
            (
                int(grid_limit) + 1
                if isinstance(grid_limit, int)
                else 0
            ),
            int(grid_limit) if isinstance(grid_limit, int) else 0,
        )

    monkeypatch.setattr(module, "_simulate_growth_in_mask_xy", simulate)
    realized_mask = realize(G.polygon(n_sides=4, scale=60.0))
    mask = (realized_mask.coords, realized_mask.offsets)

    with operation_diagnostic_context() as diagnostics:
        with preview_quality_context("draft"):
            module.growth(mask, seed_count=2, iters=250, seed=12)
    with preview_quality_context("final"):
        module.growth(mask, seed_count=2, iters=250, seed=12)

    assert seen_limits == [
        (module.DRAFT_MAX_ITERS, module.DRAFT_MAX_TOTAL_POINTS),
        (250, None),
    ]
    assert any(
        item.op == "growth.iters"
        and item.original_value == 250
        and item.effective_value == module.DRAFT_MAX_ITERS
        for item in diagnostics.snapshot()
    )
    assert any(
        item.op == "growth.force_grid_cells"
        and item.effective_value == module.DRAFT_MAX_FORCE_GRID_CELLS
        for item in diagnostics.snapshot()
    )


def test_growth_total_point_budget_rejects_expansion_at_iteration_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grafix.core.effects.growth as module

    ring = np.asarray(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    monkeypatch.setattr(
        module,
        "_insert_points_ring_xy",
        lambda points, _spacing: np.repeat(points, 2, axis=0),
    )
    monkeypatch.setattr(
        module,
        "_compute_forces_numba",
        lambda points, **_kwargs: np.zeros_like(points),
    )
    monkeypatch.setattr(
        module,
        "_sample_sdf_grid_numba",
        lambda points, *_args: (
            -np.ones((points.shape[0],), dtype=np.float64),
            np.zeros((points.shape[0],), dtype=np.float64),
            np.zeros((points.shape[0],), dtype=np.float64),
        ),
    )
    monkeypatch.setattr(
        module,
        "_apply_boundary_constraints_numba",
        lambda points, displacement, *_args, **_kwargs: points + displacement,
    )

    result = module._simulate_growth_in_mask_xy(
        [ring],
        target_spacing=1.0,
        boundary_avoid=0.0,
        boundary_mode="slide",
        iters=2,
        sdf=np.zeros((2, 2), dtype=np.float64),
        sdf_origin_x=0.0,
        sdf_origin_y=0.0,
        sdf_pitch=1.0,
        max_total_points=5,
    )

    assert result.point_budget_hit
    assert result.rejected_total_points == 8
    assert result.max_total_points == 4
    assert result.iterations == 2
    np.testing.assert_array_equal(result.rings[0], ring)


def test_growth_draft_bounds_repulsion_hash_before_force_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import grafix.core.effects.growth as module

    first = np.asarray(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    second = first + 1.0e9
    seen_grid_shapes: list[tuple[int, int]] = []

    monkeypatch.setattr(
        module,
        "_insert_points_ring_xy",
        lambda points, _spacing: points,
    )

    def forces(
        points: np.ndarray,
        *,
        bounded_grid_width: int,
        bounded_grid_height: int,
        **_kwargs: object,
    ) -> np.ndarray:
        seen_grid_shapes.append((bounded_grid_width, bounded_grid_height))
        return np.zeros_like(points)

    monkeypatch.setattr(module, "_compute_forces_numba", forces)
    monkeypatch.setattr(
        module,
        "_sample_sdf_grid_numba",
        lambda points, *_args: (
            -np.ones((points.shape[0],), dtype=np.float64),
            np.zeros((points.shape[0],), dtype=np.float64),
            np.zeros((points.shape[0],), dtype=np.float64),
        ),
    )
    monkeypatch.setattr(
        module,
        "_apply_boundary_constraints_numba",
        lambda points, displacement, *_args, **_kwargs: points + displacement,
    )

    result = module._simulate_growth_in_mask_xy(
        [first, second],
        target_spacing=1.0,
        boundary_avoid=0.0,
        boundary_mode="slide",
        iters=1,
        sdf=np.zeros((2, 2), dtype=np.float64),
        sdf_origin_x=0.0,
        sdf_origin_y=0.0,
        sdf_pitch=1.0,
        max_total_points=32,
        max_force_grid_cells=128,
    )

    assert seen_grid_shapes
    width, height = seen_grid_shapes[0]
    assert width * height <= 128
    assert result.force_grid_requested_cells > 128
    assert result.force_grid_effective_cells == width * height
