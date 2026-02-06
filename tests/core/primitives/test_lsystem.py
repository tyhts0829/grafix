"""lsystem プリミティブのテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.realize import realize
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
    r1 = realize(Geometry.create("lsystem", params=params))
    r2 = realize(Geometry.create("lsystem", params=params))
    np.testing.assert_array_equal(r1.coords, r2.coords)
    np.testing.assert_array_equal(r1.offsets, r2.offsets)


def test_lsystem_iters_zero_uses_axiom() -> None:
    """iters==0 のとき axiom をそのまま解釈する。"""
    realized = realize(
        Geometry.create(
            "lsystem",
            params={
                "kind": "custom",
                "axiom": "F",
                "rules": "",
                "iters": 0,
                "center": (0.0, 0.0, 1.0),
                "heading": 0.0,
                "angle": 90.0,
                "step": 1.0,
                "jitter": 0.0,
                "seed": 0,
            },
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
            Geometry.create(
                "lsystem",
                params={
                    "kind": "custom",
                    "axiom": "F",
                    "rules": "F",
                    "iters": 1,
                    "center": (0.0, 0.0, 0.0),
                    "heading": 0.0,
                    "angle": 90.0,
                    "step": 1.0,
                    "jitter": 0.0,
                    "seed": 0,
                },
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
            Geometry.create(
                "lsystem",
                params={
                    "kind": "custom",
                    "axiom": "F]",
                    "rules": "",
                    "iters": 0,
                    "center": (0.0, 0.0, 0.0),
                    "heading": 0.0,
                    "angle": 90.0,
                    "step": 1.0,
                    "jitter": 0.0,
                    "seed": 0,
                },
            )
        )
    assert realized.coords.shape == (2, 3)
    assert realized.offsets.tolist() == [0, 2]


def test_lsystem_unclosed_open_bracket_warns_and_keeps_lines() -> None:
    """閉じていない '[' は warning を出し、得られた線は可能な範囲で返す。"""
    with pytest.warns(UserWarning, match=r"閉じていない"):
        realized = realize(
            Geometry.create(
                "lsystem",
                params={
                    "kind": "custom",
                    "axiom": "F[+F",
                    "rules": "",
                    "iters": 0,
                    "center": (0.0, 0.0, 0.0),
                    "heading": 0.0,
                    "angle": 90.0,
                    "step": 1.0,
                    "jitter": 0.0,
                    "seed": 0,
                },
            )
        )

    assert realized.coords.shape == (4, 3)
    assert realized.offsets.tolist() == [0, 2, 4]
    # branch (1,0)->(1,1), trunk (0,0)->(1,0) の 2 本になる（順序は実装由来）。
    np.testing.assert_allclose(realized.coords[0], [1.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[1], [1.0, 1.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[2], [0.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(realized.coords[3], [1.0, 0.0, 0.0], rtol=0.0, atol=1e-6)
