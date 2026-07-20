"""Effect 引数を実行時の正規型へ検証する軽量 helper。"""

from __future__ import annotations

import math
import operator
from collections.abc import Sequence
from numbers import Real


def finite_vec3(
    value: tuple[float, float, float],
    *,
    name: str,
) -> tuple[float, float, float]:
    """tuple 一形の有限な3成分ベクトルを検証する。"""

    if not isinstance(value, tuple):
        raise TypeError(f"{name} は tuple である必要がある")
    if len(value) != 3:
        raise ValueError(f"{name} は3要素である必要がある")
    if any(isinstance(item, bool) or not isinstance(item, Real) for item in value):
        raise TypeError(f"{name} の各要素は bool 以外の実数である必要がある")
    result = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} の各要素は有限値である必要がある")
    return result


def integer_scalar(value: int, *, name: str) -> int:
    """bool や数値文字列を許容せず、整数スカラーを Python int へ正規化する。"""

    if isinstance(value, bool):
        raise TypeError(f"{name} は整数である必要がある")
    try:
        return operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{name} は整数である必要がある") from exc


def exact_bool(value: bool, *, name: str) -> bool:
    """bool 以外の truthy/falsy 値を許容せず、そのまま返す。"""

    if type(value) is not bool:
        raise TypeError(f"{name} は bool である必要がある")
    return value


def known_choice(
    value: str,
    *,
    choices: Sequence[str],
    name: str,
) -> str:
    """exact str かつ既知 choice の値をそのまま返す。"""

    if type(value) is not str:
        raise TypeError(f"{name} は str である必要がある")
    if value not in choices:
        expected = ", ".join(repr(choice) for choice in choices)
        raise ValueError(f"{name} は {expected} のいずれかである必要がある")
    return value


__all__ = ["exact_bool", "finite_vec3", "integer_scalar", "known_choice"]
