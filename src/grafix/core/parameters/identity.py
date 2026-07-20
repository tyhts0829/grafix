"""Parameter と effect topology が共有する canonical identity 検証。"""

from __future__ import annotations

from typing import TypeAlias

from grafix.core.value_validation import exact_string

GroupKey: TypeAlias = tuple[str, str]


def identity_string(value: object, *, name: str) -> str:
    """暗黙文字列化を行わず、空でない文字列 identity を返す。"""

    try:
        value = exact_string(value, name=name)
    except TypeError:
        raise TypeError(f"{name} は空でない文字列である必要があります") from None
    if not value:
        raise ValueError(f"{name} は空でない文字列である必要があります")
    return value


def group_key(value: object, *, name: str) -> GroupKey:
    """``(op, site_id)`` 一形の group identity を返す。"""

    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError(f"{name} は (op, site_id) tuple である必要があります")
    return (
        identity_string(value[0], name=f"{name}.op"),
        identity_string(value[1], name=f"{name}.site_id"),
    )


__all__ = ["GroupKey", "group_key", "identity_string"]
