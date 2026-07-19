"""laplace_field_grid プリミティブの基本動作テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.primitives.laplace_field_grid import (
    _split_by_mask,
    laplace_field_grid as raw_laplace_field_grid,
)
from grafix.core.realize import RealizeError, realize
from grafix.core.primitives import laplace_field_grid as _laplace_field_grid_module  # noqa: F401


def _assert_realized_basic_invariants(coords: np.ndarray, offsets: np.ndarray) -> None:
    assert coords.ndim == 2
    assert coords.shape[1] == 3
    assert offsets.ndim == 1
    assert offsets.size >= 1
    assert int(offsets[0]) == 0
    assert int(offsets[-1]) == int(coords.shape[0])
    assert np.all(np.diff(offsets.astype(np.int64)) >= 0)
    assert np.isfinite(coords).all()


@pytest.mark.parametrize("preset", ["cylinder_uniform", "mobius", "exp"])
def test_laplace_field_grid_runs_and_finite(preset: str) -> None:
    """各 preset で例外なく実行でき、NaN/Inf を含まない。"""
    params: dict[str, object] = {
        "preset": preset,
        "u_min": -4.0,
        "u_max": 4.0,
        "v_min": -4.0,
        "v_max": 4.0,
        "n_u": 8,
        "n_v": 8,
        "samples": 200,
    }
    if preset == "cylinder_uniform":
        params.update(
            {
                "a": 1.0,
                "U": 1.0,
                "gap": 0.01,
                "draw_boundary": True,
                "boundary_samples": 200,
            }
        )
    elif preset == "mobius":
        params.update(
            {
                "alpha_re": 1.0,
                "alpha_im": 0.0,
                "beta_re": 0.2,
                "beta_im": 0.1,
                "gamma_re": 0.05,
                "gamma_im": 0.0,
                "delta_re": 1.0,
                "delta_im": 0.0,
            }
        )
    else:  # preset == "exp"
        params.update({"k_re": 0.35, "k_im": 0.6})

    g = Geometry.create("laplace_field_grid", params=params)
    realized = realize(g)
    _assert_realized_basic_invariants(realized.coords, realized.offsets)
    assert realized.coords.shape[0] > 0


def test_laplace_field_grid_cylinder_respects_gap_mask() -> None:
    """cylinder_uniform で円内部（gap 込み）に点が侵入しない。"""
    a = 1.0
    gap = 0.02
    g = Geometry.create(
        "laplace_field_grid",
        params={
            "preset": "cylinder_uniform",
            "u_min": -4.0,
            "u_max": 4.0,
            "v_min": -4.0,
            "v_max": 4.0,
            "n_u": 10,
            "n_v": 10,
            "samples": 250,
            "a": a,
            "U": 1.0,
            "gap": gap,
            "draw_boundary": False,
        },
    )
    realized = realize(g)
    _assert_realized_basic_invariants(realized.coords, realized.offsets)

    r = np.hypot(realized.coords[:, 0], realized.coords[:, 1])
    assert float(np.min(r)) >= a * (1.0 + gap) - 1e-5


def test_laplace_field_grid_rejects_invalid_samples() -> None:
    """samples<2 は ValueError。"""
    g = Geometry.create(
        "laplace_field_grid",
        params={
            "preset": "exp",
            "n_u": 2,
            "n_v": 2,
            "samples": 1,
        },
    )
    with pytest.raises(RealizeError):
        realize(g)


def test_laplace_field_grid_allows_a_zero() -> None:
    """a=0 でも例外にならない（円柱なし＝一様場の退化ケース）。"""
    g = Geometry.create(
        "laplace_field_grid",
        params={
            "preset": "cylinder_uniform",
            "u_min": -2.0,
            "u_max": 2.0,
            "v_min": -2.0,
            "v_max": 2.0,
            "n_u": 6,
            "n_v": 6,
            "samples": 120,
            "a": 0.0,
            "U": 1.0,
            "gap": 0.02,
            "draw_boundary": True,
        },
    )
    realized = realize(g)
    _assert_realized_basic_invariants(realized.coords, realized.offsets)
    assert realized.coords.shape[0] > 0


def test_laplace_field_grid_allows_U_zero() -> None:
    """U=0 でも例外にならない（線は省略され、境界のみ描画される）。"""
    g = Geometry.create(
        "laplace_field_grid",
        params={
            "preset": "cylinder_uniform",
            "u_min": -2.0,
            "u_max": 2.0,
            "v_min": -2.0,
            "v_max": 2.0,
            "n_u": 6,
            "n_v": 6,
            "samples": 120,
            "a": 1.0,
            "U": 0.0,
            "gap": 0.02,
            "draw_boundary": True,
            "boundary_samples": 200,
        },
    )
    realized = realize(g)
    _assert_realized_basic_invariants(realized.coords, realized.offsets)
    assert realized.coords.shape[0] > 0


def test_laplace_field_grid_presets_are_distinct() -> None:
    """preset の切り替えで座標分布が変わる（退行防止の最小チェック）。"""

    base: dict[str, object] = {
        "u_min": -3.0,
        "u_max": 3.0,
        "v_min": -3.0,
        "v_max": 3.0,
        "n_u": 6,
        "n_v": 6,
        "samples": 120,
    }

    g_cyl = Geometry.create(
        "laplace_field_grid",
        params={
            **base,
            "preset": "cylinder_uniform",
            "a": 1.0,
            "U": 1.0,
            "gap": 0.01,
            "draw_boundary": False,
        },
    )
    g_mob = Geometry.create(
        "laplace_field_grid",
        params={
            **base,
            "preset": "mobius",
            "alpha_re": 1.0,
            "alpha_im": 0.0,
            "beta_re": 0.3,
            "beta_im": 0.2,
            "gamma_re": 0.1,
            "gamma_im": 0.0,
            "delta_re": 1.0,
            "delta_im": 0.0,
        },
    )
    g_exp = Geometry.create(
        "laplace_field_grid",
        params={**base, "preset": "exp", "k_re": 0.4, "k_im": 0.8},
    )

    r_cyl = realize(g_cyl)
    r_mob = realize(g_mob)
    r_exp = realize(g_exp)

    def bbox(coords: np.ndarray) -> np.ndarray:
        mins = np.min(coords[:, 0:2], axis=0)
        maxs = np.max(coords[:, 0:2], axis=0)
        return np.concatenate([mins, maxs], axis=0)

    b_cyl = bbox(r_cyl.coords)
    b_mob = bbox(r_mob.coords)
    b_exp = bbox(r_exp.coords)

    assert not np.allclose(b_cyl, b_mob)
    assert not np.allclose(b_cyl, b_exp)
    assert not np.allclose(b_mob, b_exp)


@pytest.mark.parametrize(
    "mask",
    [
        np.ones(12, dtype=np.bool_),
        np.zeros(12, dtype=np.bool_),
        np.array(
            [False, True, True, False, True, False, True, True, True, False],
            dtype=np.bool_,
        ),
    ],
)
def test_split_by_mask_fast_paths_preserve_runs(mask: np.ndarray) -> None:
    """all/none/mixedの各経路が2点以上のTrue runだけを順番に返す。"""

    points = np.arange(mask.size * 3, dtype=np.float64).reshape((-1, 3))
    expected: list[np.ndarray] = []
    start = -1
    for index, keep in enumerate(mask):
        if bool(keep) and start < 0:
            start = index
        elif not bool(keep) and start >= 0:
            if index - start >= 2:
                expected.append(points[start:index])
            start = -1
    if start >= 0 and mask.size - start >= 2:
        expected.append(points[start:])

    actual = _split_by_mask(points, mask)
    assert len(actual) == len(expected)
    for actual_piece, expected_piece in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_piece, expected_piece)
        assert np.shares_memory(actual_piece, points)


def test_laplace_empty_output_keeps_transform_parameters_lazy() -> None:
    """線が無い場合は従来どおりcenter/scale/rotateを評価しない。"""

    coords, offsets = raw_laplace_field_grid(
        preset="exp",
        n_u=0,
        n_v=0,
        samples=2,
        center=object(),  # type: ignore[arg-type]
        scale=object(),  # type: ignore[arg-type]
        rotate=object(),  # type: ignore[arg-type]
    )

    assert coords.shape == (0, 3)
    assert offsets.tolist() == [0]
