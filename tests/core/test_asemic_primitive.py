"""asemic primitive の最小テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import G
from grafix.core.primitives import asemic as asemic_module
from grafix.core.primitives.asemic import asemic as asemic_impl
from grafix.core.realize import RealizeError, realize


def test_asemic_impl_is_deterministic() -> None:
    a_coords, a_offsets = asemic_impl(seed=0, n_nodes=28, candidates=12)
    b_coords, b_offsets = asemic_impl(seed=0, n_nodes=28, candidates=12)

    assert np.array_equal(a_coords, b_coords)
    assert np.array_equal(a_offsets, b_offsets)


def test_asemic_same_char_has_same_shape_translated() -> None:
    single_coords, single_offsets = asemic_impl(text="A", seed=0, n_nodes=28, candidates=12)
    assert single_coords.shape[0] > 0

    double_coords, double_offsets = asemic_impl(text="AA", seed=0, n_nodes=28, candidates=12)
    n = int(single_coords.shape[0])
    assert int(double_coords.shape[0]) == 2 * n

    assert np.array_equal(double_coords[:n], single_coords)
    shift = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert np.array_equal(double_coords[n:], single_coords + shift)

    m = int(single_offsets.size)
    assert int(double_offsets.size) == 2 * m - 1
    assert np.array_equal(double_offsets[:m], single_offsets)
    assert np.array_equal(double_offsets[m:], single_offsets[1:] + n)


def test_asemic_newline_advances_by_line_height() -> None:
    single_coords, _single_offsets = asemic_impl(text="A", seed=0, n_nodes=28, candidates=12)
    assert single_coords.shape[0] > 0

    lh = 1.5
    two_lines_coords, _two_lines_offsets = asemic_impl(
        text="A\nA",
        seed=0,
        n_nodes=28,
        candidates=12,
        line_height=lh,
    )
    n = int(single_coords.shape[0])
    assert int(two_lines_coords.shape[0]) == 2 * n
    assert np.array_equal(two_lines_coords[:n], single_coords)

    shift = np.array([0.0, float(lh), 0.0], dtype=np.float32)
    assert np.array_equal(two_lines_coords[n:], single_coords + shift)


def test_asemic_wrap_by_box_width_increases_y_extent() -> None:
    unwrapped_coords, _unwrapped_offsets = asemic_impl(text="A A A", seed=0, n_nodes=28, candidates=12)
    wrapped_coords, _wrapped_offsets = asemic_impl(
        text="A A A",
        seed=0,
        n_nodes=28,
        candidates=12,
        use_bounding_box=True,
        box_width=2.0,  # em（scale=1.0 のためそのまま）
        line_height=2.0,
    )

    assert wrapped_coords.shape == unwrapped_coords.shape
    assert float(wrapped_coords[:, 1].max()) > float(unwrapped_coords[:, 1].max()) + 1.0


def test_asemic_period_is_literal_dot() -> None:
    dot_coords, dot_offsets = asemic_impl(text=".", seed=0, n_nodes=28, candidates=12)

    assert dot_coords.shape[0] > 0
    assert dot_offsets.tolist() == [0, int(dot_coords.shape[0])]
    assert np.array_equal(dot_coords[0], dot_coords[-1])

    span = dot_coords[:, :2].max(axis=0) - dot_coords[:, :2].min(axis=0)
    assert float(span[0]) < 0.2
    assert float(span[1]) < 0.2


def test_asemic_api_returns_valid_geometry() -> None:
    g = realize(G.asemic(text="A", seed=0, n_nodes=28, candidates=12))

    assert g.coords.dtype == np.float32
    assert g.offsets.dtype == np.int32
    assert g.offsets[0] == 0
    assert g.offsets[-1] == g.coords.shape[0]
    assert np.all(np.diff(g.offsets) >= 0)
    assert np.all(np.isfinite(g.coords))
    assert g.coords.shape[0] > 0


@pytest.mark.parametrize(
    ("kwargs", "parameter"),
    [
        ({"seed": -1}, "seed"),
        ({"n_nodes": -1}, "n_nodes"),
        ({"candidates": 0}, "candidates"),
        ({"stroke_min": -1}, "stroke_min"),
        ({"stroke_max": -1}, "stroke_max"),
        ({"stroke_min": 4, "stroke_max": 3}, "stroke_min"),
        ({"walk_min_steps": 0}, "walk_min_steps"),
        ({"walk_max_steps": 0}, "walk_max_steps"),
        ({"walk_min_steps": 3, "walk_max_steps": 2}, "walk_min_steps"),
        ({"bezier_samples": 1}, "bezier_samples"),
        ({"bezier_tension": -0.1}, "bezier_tension"),
        ({"bezier_tension": 1.1}, "bezier_tension"),
    ],
)
def test_asemic_rejects_out_of_domain_parameters_before_empty_text(
    kwargs: dict[str, int | float],
    parameter: str,
) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(G.asemic(text="", **kwargs))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert parameter in str(exc_info.value.__cause__)


def test_asemic_zero_nodes_returns_empty_geometry_for_regular_text() -> None:
    geometry = realize(G.asemic(text="A", n_nodes=0))

    assert geometry.coords.shape == (0, 3)
    assert geometry.offsets.tolist() == [0]


def test_asemic_rng_adjacency_matches_small_reference() -> None:
    points = np.asarray(
        [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [0.0, 0.0]],
        dtype=np.float64,
    )
    diff = points[:, None, :] - points[None, :, :]
    distance_sq = np.sum(diff * diff, axis=2)
    expected = [set() for _ in range(len(points))]
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            dij = float(distance_sq[i, j])
            blocked = any(
                k not in {i, j}
                and distance_sq[i, k] < dij
                and distance_sq[j, k] < dij
                for k in range(len(points))
            )
            if not blocked:
                expected[i].add(j)
                expected[j].add(i)

    assert asemic_module._build_rng_adjacency(points) == expected


def test_asemic_glyph_cache_is_bounded_and_reused_across_layouts() -> None:
    asemic_module._generate_asemic_glyph.cache_clear()

    asemic_impl(text="A", seed=7, center=(0.0, 0.0, 0.0), scale=1.0)
    after_first = asemic_module._generate_asemic_glyph.cache_info()
    asemic_impl(text="A", seed=7, center=(100.0, 20.0, 0.0), scale=4.0)
    after_second = asemic_module._generate_asemic_glyph.cache_info()

    assert after_first.misses == 1
    assert after_second.hits == 1
    assert after_second.currsize <= 256


def test_asemic_cached_glyph_arrays_are_read_only() -> None:
    asemic_module._generate_asemic_glyph.cache_clear()
    asemic_impl(text="A", seed=11)

    # 同じ key を直接取得し、cache が共有する配列の不変契約を確認する。
    seed_char = asemic_module._stable_hash64("11|A")
    polylines = asemic_module._generate_asemic_glyph(
        seed=int(seed_char),
        n_nodes=28,
        candidates=12,
        stroke_min=2,
        stroke_max=5,
        walk_min_steps=2,
        walk_max_steps=4,
        stroke_style="bezier",
        bezier_samples=12,
        bezier_tension=0.5,
    )

    assert polylines
    assert all(polyline.flags.writeable is False for polyline in polylines)


def test_asemic_raw_results_are_fresh_writable_and_non_sharing() -> None:
    for value in ("ABBA", ""):
        first_coords, first_offsets = asemic_impl(
            text=value, seed=123, n_nodes=28
        )
        second_coords, second_offsets = asemic_impl(
            text=value, seed=123, n_nodes=28
        )

        assert first_coords.flags.writeable
        assert first_offsets.flags.writeable
        assert second_coords.flags.writeable
        assert second_offsets.flags.writeable
        assert not np.shares_memory(first_coords, second_coords)
        assert not np.shares_memory(first_offsets, second_offsets)
        assert np.array_equal(first_coords, second_coords)
        assert np.array_equal(first_offsets, second_offsets)


def test_asemic_bezier_basis_cache_is_bounded_readonly_and_reused() -> None:
    asemic_module._bezier_basis.cache_clear()

    first = asemic_module._bezier_basis(12)
    second = asemic_module._bezier_basis(12)
    info = asemic_module._bezier_basis.cache_info()

    assert first is second
    assert info.hits == 1
    assert info.currsize <= 64
    assert all(values.flags.writeable is False for values in first)
