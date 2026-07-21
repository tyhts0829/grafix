"""lsystem プリミティブのテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives.lsystem import (
    _expand_preset,
    _turtle_to_geom_tuple,
    lsystem as raw_lsystem,
)
from grafix.core.realize import RealizeError, realize
from grafix.core.primitives import lsystem as _lsystem_module  # noqa: F401


def test_lsystem_is_deterministic() -> None:
    """同じパラメータなら決定的に同じ出力になる。"""
    params = {
        "kind": "plant",
        "iters": 3,
        "center": (10.0, 20.0, 30.0),
        "heading": 90.0,
        "angle": 25.0,
        "step": 2.0,
        "jitter": 0.05,
        "seed": 123,
    }
    r1 = realize(G.lsystem(**params))
    r2 = realize(G.lsystem(**params))
    np.testing.assert_array_equal(r1.coords, r2.coords)
    np.testing.assert_array_equal(r1.offsets, r2.offsets)


def test_lsystem_iters_zero_uses_axiom() -> None:
    """iters==0 のとき axiom をそのまま解釈する。"""
    realized = realize(
        G.lsystem(
            kind="custom",
            axiom="F",
            rules="",
            iters=0,
            center=(0.0, 0.0, 1.0),
            heading=0.0,
            angle=90.0,
            step=1.0,
            jitter=0.0,
            seed=0,
        )
    )
    assert realized.coords.shape == (2, 3)
    assert realized.offsets.tolist() == [0, 2]
    np.testing.assert_allclose(realized.coords[0], [0.0, 0.0, 1.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[1], [1.0, 0.0, 1.0], rtol=0.0, atol=1e-6)


def test_lsystem_custom_rules_invalid_line_warns_and_is_ignored() -> None:
    """custom rules の不正行は warning を出して無視し、処理は継続する。"""
    with pytest.warns(UserWarning, match=r"rules の 1 行目"):
        realized = realize(
            G.lsystem(
                kind="custom",
                axiom="F",
                rules="F",
                iters=1,
                center=(0.0, 0.0, 0.0),
                heading=0.0,
                angle=90.0,
                step=1.0,
                jitter=0.0,
                seed=0,
            )
        )
    assert realized.coords.shape == (2, 3)
    assert realized.offsets.tolist() == [0, 2]
    np.testing.assert_allclose(realized.coords[0], [0.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[1], [1.0, 0.0, 0.0], rtol=0.0, atol=1e-6)


def test_lsystem_extra_close_bracket_warns_and_is_ignored() -> None:
    """余分な ']' は warning を出して無視する。"""
    with pytest.warns(UserWarning, match=r"余分"):
        realized = realize(
            G.lsystem(
                kind="custom",
                axiom="F]",
                rules="",
                iters=0,
                center=(0.0, 0.0, 0.0),
                heading=0.0,
                angle=90.0,
                step=1.0,
                jitter=0.0,
                seed=0,
            )
        )
    assert realized.coords.shape == (2, 3)
    assert realized.offsets.tolist() == [0, 2]


def test_lsystem_unclosed_open_bracket_warns_and_keeps_lines() -> None:
    """閉じていない '[' は warning を出し、得られた線は可能な範囲で返す。"""
    with pytest.warns(UserWarning, match=r"閉じていない"):
        realized = realize(
            G.lsystem(
                kind="custom",
                axiom="F[+F",
                rules="",
                iters=0,
                center=(0.0, 0.0, 0.0),
                heading=0.0,
                angle=90.0,
                step=1.0,
                jitter=0.0,
                seed=0,
            )
        )

    assert realized.coords.shape == (4, 3)
    assert realized.offsets.tolist() == [0, 2, 4]
    # branch (1,0)->(1,1), trunk (0,0)->(1,0) の 2 本になる（順序は実装由来）。
    np.testing.assert_allclose(realized.coords[0], [1.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[1], [1.0, 1.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[2], [0.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[3], [1.0, 0.0, 0.0], rtol=0.0, atol=1e-6)


def test_lsystem_cached_preset_returns_fresh_writable_arrays() -> None:
    """展開cacheを使ってもraw geometryを呼出し間で共有しない。"""

    first_coords, first_offsets = raw_lsystem(kind="plant", iters=4)
    second_coords, second_offsets = raw_lsystem(kind="plant", iters=4)

    np.testing.assert_array_equal(first_coords, second_coords)
    np.testing.assert_array_equal(first_offsets, second_offsets)
    assert first_coords.flags.writeable
    assert first_offsets.flags.writeable
    assert not np.shares_memory(first_coords, second_coords)
    assert not np.shares_memory(first_offsets, second_offsets)


@pytest.mark.parametrize(
    ("kwargs", "parameter"),
    [
        ({"iters": -1}, "iters"),
        ({"step": 0.0}, "step"),
        ({"step": -0.01}, "step"),
        ({"jitter": -0.01}, "jitter"),
        ({"seed": -1}, "seed"),
    ],
)
def test_lsystem_rejects_invalid_domain_before_empty_program(
    kwargs: dict[str, int | float],
    parameter: str,
) -> None:
    with pytest.raises(RealizeError) as exc_info:
        realize(G.lsystem(kind="custom", axiom="", rules="", **kwargs))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert parameter in str(exc_info.value.__cause__)


@pytest.mark.parametrize(("kind", "iters"), [("plant", 4), ("circuit", 6)])
@pytest.mark.parametrize("jitter", [0.01, 0.08, 0.25])
@pytest.mark.parametrize("seed", [0, 20260719])
def test_lsystem_batched_preset_random_values_match_scalar_draws(
    kind: str,
    iters: int,
    jitter: float,
    seed: int,
) -> None:
    """presetの一括乱数生成はscalar drawと同じ系列・geometryを保つ。"""

    program = _expand_preset(kind, iters)
    arguments = {
        "program": program,
        "start_xy": (1.25, -2.5),
        "heading_deg": 81.5,
        "angle_deg": 23.25,
        "step": 1.75,
        "jitter": jitter,
        "seed": seed,
        "z": 3.75,
    }
    batch_coords, batch_offsets = _turtle_to_geom_tuple(
        **arguments,
        batch_random=True,
    )
    scalar_coords, scalar_offsets = _turtle_to_geom_tuple(
        **arguments,
        batch_random=False,
    )

    np.testing.assert_array_equal(batch_coords, scalar_coords)
    np.testing.assert_array_equal(batch_offsets, scalar_offsets)
