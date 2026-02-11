"""asemic primitive の最小テスト。"""

from __future__ import annotations

import numpy as np

from grafix.api import G
from grafix.core.primitives.asemic import asemic as asemic_impl
from grafix.core.realize import realize


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
