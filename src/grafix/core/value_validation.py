"""公開境界と内部 DTO が共有する軽量な scalar 検証。"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from math import copysign, isfinite
from numbers import Real
from typing import SupportsIndex, cast


def _canonical_immutable_value_detailed(value: object, *, name: str) -> object:
    """不正箇所を含む診断を生成しながら immutable tree を検証する。"""

    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        float_value = cast(float, value)
        if not isfinite(float_value):
            raise ValueError(f"{name} に非有限な float は使用できません")
        if float_value == 0.0 and copysign(1.0, float_value) < 0.0:
            return 0.0
        return float_value
    if value_type is tuple:
        return tuple(
            _canonical_immutable_value_detailed(item, name=f"{name}[{index}]")
            for index, item in enumerate(cast(tuple[object, ...], value))
        )
    raise TypeError(
        f"{name} は None/bool/int/float/str と exact tuple だけからなる"
        " immutable 値である必要があります"
    )


class _InvalidCanonicalImmutableValue(Exception):
    """高速検証から詳細なエラー生成へ切り替えるための内部 signal。"""


def _canonical_immutable_value_fast(value: object) -> object:
    """正規 tuple tree を alias-free のまま再利用する common path。"""

    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        float_value = cast(float, value)
        if not isfinite(float_value):
            raise _InvalidCanonicalImmutableValue
        if float_value == 0.0 and copysign(1.0, float_value) < 0.0:
            return 0.0
        return float_value
    if value_type is tuple:
        source = cast(tuple[object, ...], value)
        changed: list[object] | None = None
        for index, item in enumerate(source):
            normalized = _canonical_immutable_value_fast(item)
            if normalized is item:
                continue
            if changed is None:
                changed = list(source)
            changed[index] = normalized
        return source if changed is None else tuple(changed)
    raise _InvalidCanonicalImmutableValue


def canonical_immutable_value(value: object, *, name: str) -> object:
    """Geometry 引数用の exact immutable scalar/tuple tree を検証する。

    mutable container や scalar subclass を暗黙変換せず拒否し、有限な
    ``float`` の負のゼロだけを canonical な ``0.0`` にそろえる。正規値は
    もともと immutable なので同じ tuple tree を再利用し、不正入力時だけ
    要素 path を含む診断を構築する。
    """

    try:
        return _canonical_immutable_value_fast(value)
    except _InvalidCanonicalImmutableValue:
        return _canonical_immutable_value_detailed(value, name=name)


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
    "canonical_immutable_value",
    "exact_bool",
    "exact_integer",
    "exact_string",
    "exact_string_choice",
    "finite_real",
    "positive_integer_pair",
    "rgb01_tuple",
]
