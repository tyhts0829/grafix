"""公開境界と内部 DTO が共有する軽量な scalar 検証。"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from math import isfinite
from numbers import Real
from typing import SupportsIndex, cast


def exact_bool(value: object, *, name: str) -> bool:
    """bool 以外の truthy/falsy 値を拒否し、そのまま返す。"""

    if type(value) is not bool:
        raise TypeError(f"{name} は bool である必要があります")
    return value


def exact_string(value: object, *, name: str) -> str:
    """str subclass や暗黙変換を拒否し、そのまま返す。"""

    if type(value) is not str:
        raise TypeError(f"{name} は str である必要があります")
    return value


def exact_string_choice(
    value: object,
    *,
    name: str,
    choices: Sequence[str],
) -> str:
    """str subclass や暗黙変換を拒否し、既知の文字列値を返す。"""

    value = exact_string(value, name=name)
    if value not in choices:
        expected = ", ".join(repr(choice) for choice in choices)
        raise ValueError(f"{name} は {expected} のいずれかである必要があります")
    return value


def exact_integer(
    value: object,
    *,
    name: str,
    minimum: int | None = None,
) -> int:
    """bool や暗黙変換を拒否し、整数 scalar を Python ``int`` で返す。"""

    if isinstance(value, bool):
        raise TypeError(f"{name} は int（整数）である必要があります")
    try:
        normalized = operator.index(cast(SupportsIndex, value))
    except TypeError:
        raise TypeError(f"{name} は int（整数）である必要があります") from None
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{name} は {minimum} 以上である必要があります")
    return normalized


def finite_real(
    value: object,
    *,
    name: str,
    minimum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    """bool と非数値を拒否し、有限な実数を Python ``float`` で返す。"""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} は有限な実数である必要があります")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{name} は有限な実数である必要があります")
    if minimum is not None:
        below_minimum = (
            normalized < minimum
            if minimum_inclusive
            else normalized <= minimum
        )
        if below_minimum:
            relation = "以上" if minimum_inclusive else "より大きい値"
            raise ValueError(f"{name} は {minimum:g} {relation}である必要があります")
    return normalized


def positive_integer_pair(
    value: object,
    *,
    name: str,
) -> tuple[int, int]:
    """2 要素 tuple を、正の厳密な整数ペアとして返す。"""

    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError(f"{name} は2要素の tuple である必要があります")
    return (
        exact_integer(value[0], name=f"{name}[0]", minimum=1),
        exact_integer(value[1], name=f"{name}[1]", minimum=1),
    )


def rgb01_tuple(
    value: object,
    *,
    name: str,
) -> tuple[float, float, float]:
    """canonical な3要素 RGB01 tuple を検証して返す。"""

    if type(value) is not tuple or len(value) != 3:
        raise TypeError(f"{name} は3要素の RGB01 tuple である必要があります")
    channels = tuple(
        finite_real(channel, name=f"{name}[{index}]", minimum=0.0)
        for index, channel in enumerate(value)
    )
    if any(channel > 1.0 for channel in channels):
        raise ValueError(f"{name} の各channelは0.0..1.0である必要があります")
    return cast(tuple[float, float, float], channels)


__all__ = [
    "exact_bool",
    "exact_integer",
    "exact_string",
    "exact_string_choice",
    "finite_real",
    "positive_integer_pair",
    "rgb01_tuple",
]
