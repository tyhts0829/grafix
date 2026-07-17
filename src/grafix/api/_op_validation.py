"""G/E の operation 引数を DAG 作成前に検証する。"""

from __future__ import annotations

from collections.abc import Mapping
from difflib import get_close_matches
from typing import Any

from grafix.core.op_registry import OpSpec


def _suggest(name: str, candidates: tuple[str, ...]) -> str:
    matches = get_close_matches(name, candidates, n=1, cutoff=0.55)
    if not matches:
        return ""
    return f"。{matches[0]!r} の誤りですか？"


def validate_operation_kwargs(
    *,
    op: str,
    spec: OpSpec[Any],
    params: Mapping[str, Any],
) -> None:
    """unknown keyword と choice 値を eager に検証する。

    ``activate`` のような wrapper 所有引数も受け入れるため、元 callable の
    signature だけでなく registry の defaults/meta も正規の引数集合に含める。
    """

    allowed = tuple(
        dict.fromkeys((*spec.accepted_args, *spec.defaults.keys(), *spec.meta.keys()))
    )
    unknown = (
        ()
        if spec.accepts_var_kwargs
        else tuple(sorted(set(params) - set(allowed)))
    )
    if unknown:
        rendered = ", ".join(
            f"{name!r}{_suggest(name, allowed)}" for name in unknown
        )
        raise TypeError(f"{spec.kind} {op!r} に不明な引数があります: {rendered}")

    for name, value in params.items():
        meta = spec.meta.get(name)
        if meta is None or meta.kind != "choice" or meta.choices is None:
            continue
        choices = tuple(meta.choices)
        if value not in choices:
            hint = _suggest(str(value), tuple(str(choice) for choice in choices))
            raise ValueError(
                f"{spec.kind} {op!r} の {name!r} は {choices!r} から選択してください"
                f": {value!r}{hint}"
            )


__all__ = ["validate_operation_kwargs"]
