"""operation selector の catalog metadata と公開表示 identity を提供する。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import get_close_matches
from operator import index
from typing import Any, Literal, SupportsIndex, TypeAlias, cast
from weakref import WeakKeyDictionary

from .builtins import (
    ensure_builtin_effects_registered,
    ensure_builtin_primitives_registered,
)
from .effect_registry import EffectFunc
from .op_registry import OpRegistry, OpSpec
from .parameters.meta import ParamMeta
from .primitive_registry import PrimitiveFunc
from .realized_geometry import RealizedGeometry

import grafix.core.effect_registry as effect_registry_module
import grafix.core.primitive_registry as primitive_registry_module

SelectorKind = Literal["primitive", "effect"]

PRIMITIVE_SELECTOR_OP = "_grafix_select_primitive"
_EFFECT_SELECTOR_PREFIX = "_grafix_select_effect_"
_TARGET_ARG = "target"
_TARGET_PARAM_PREFIX = "@"

_TARGET_META_DESCRIPTION = (
    "この呼び出しで実行する登録済み operation を選択する。"
)


class _NoSelectableOperationsError(ValueError):
    """指定 kind/arity の selector 候補が 1 件も無いことを表す。"""


_SelectorFingerprint: TypeAlias = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _SelectorCacheEntry:
    """selector catalog fingerprint と registry 世代を束ねる。"""

    fingerprint: _SelectorFingerprint
    spec: OpSpec[Any]
    revision: int


_SELECTOR_CACHE: WeakKeyDictionary[
    object,
    dict[str, _SelectorCacheEntry],
] = WeakKeyDictionary()


def validate_effect_selector_n_inputs(n_inputs: object) -> int:
    """effect selector の arity を厳密な正整数として返す。"""

    if isinstance(n_inputs, bool):
        raise TypeError("effect selector の n_inputs は int である必要があります")
    try:
        count = int(index(cast(SupportsIndex, n_inputs)))
    except TypeError:
        raise TypeError(
            "effect selector の n_inputs は int である必要があります"
        ) from None
    if count < 1:
        raise ValueError("effect selector の n_inputs は 1 以上である必要があります")
    return count


def effect_selector_op(n_inputs: int) -> str:
    """effect arity に対応する private selector op 名を返す。"""

    count = validate_effect_selector_n_inputs(n_inputs)
    return f"{_EFFECT_SELECTOR_PREFIX}{count}"


def selector_kind(op: str) -> SelectorKind | None:
    """private selector op の種別を返す。通常 operation なら None。"""

    op_s = str(op)
    if op_s == PRIMITIVE_SELECTOR_OP:
        return "primitive"
    if op_s.startswith(_EFFECT_SELECTOR_PREFIX):
        suffix = op_s.removeprefix(_EFFECT_SELECTOR_PREFIX)
        if suffix.isdigit() and int(suffix) >= 1:
            return "effect"
    return None


def selector_effect_n_inputs(op: str) -> int | None:
    """private effect selector op から arity を返す。"""

    op_s = str(op)
    if not op_s.startswith(_EFFECT_SELECTOR_PREFIX):
        return None
    suffix = op_s.removeprefix(_EFFECT_SELECTOR_PREFIX)
    if not suffix.isdigit() or int(suffix) < 1:
        return None
    return int(suffix)


def selector_param_key(target: str, arg: str) -> str:
    """target/arg を衝突しない ParameterKey.arg へ符号化する。"""

    target_s = str(target)
    return f"{_TARGET_PARAM_PREFIX}{len(target_s)}:{target_s}{str(arg)}"


def decode_selector_param_key(arg: str) -> tuple[str, str] | None:
    """selector parameter key を ``(target, original_arg)`` へ戻す。"""

    text = str(arg)
    if not text.startswith(_TARGET_PARAM_PREFIX):
        return None
    colon = text.find(":", 1)
    if colon < 0:
        return None
    length_text = text[1:colon]
    if not length_text.isdigit():
        return None
    target_length = int(length_text)
    target_start = colon + 1
    target_end = target_start + target_length
    if target_end > len(text):
        return None
    target = text[target_start:target_end]
    original_arg = text[target_end:]
    if not target or not original_arg:
        return None
    return target, original_arg


def selector_display_arg(op: str, arg: str) -> str:
    """GUI/Help/snippet 用に selector の内部 arg 名を公開名へ戻す。"""

    if selector_kind(op) is None:
        return str(arg)
    decoded = decode_selector_param_key(arg)
    if decoded is None:
        return str(arg)
    _target, original_arg = decoded
    return original_arg


def selector_search_terms(op: str, arg: str) -> tuple[str, ...]:
    """内部 namespace を漏らさない selector row の検索語を返す。"""

    if selector_kind(op) is None:
        return (str(arg),)
    decoded = decode_selector_param_key(arg)
    if decoded is None:
        return (str(arg),)
    target, original_arg = decoded
    return target, original_arg


def selector_help_identity(op: str, arg: str) -> str | None:
    """selector row の公開 Help identity を返す。通常 operation なら None。"""

    kind = selector_kind(op)
    if kind is None:
        return None
    prefix = "G.select" if kind == "primitive" else "E.select"
    decoded = decode_selector_param_key(arg)
    if decoded is None:
        return f"{prefix}.{str(arg)}"
    target, original_arg = decoded
    return f"{prefix}.{target}.{original_arg}"


def _unreachable_primitive(
    _args: tuple[tuple[str, Any], ...],
) -> RealizedGeometry:
    raise RuntimeError("primitive selector は実 Geometry node として評価できません")


def _unreachable_effect(
    _inputs: Sequence[RealizedGeometry],
    _args: tuple[tuple[str, Any], ...],
) -> RealizedGeometry:
    raise RuntimeError("effect selector は実 Geometry node として評価できません")


def _public_specs(
    registry: OpRegistry[Any],
    *,
    n_inputs: int | None,
) -> tuple[tuple[str, OpSpec[Any]], ...]:
    return tuple(
        (name, spec)
        for name, spec in sorted(registry.items())
        if not name.startswith("_")
        and (n_inputs is None or int(spec.n_inputs) == int(n_inputs))
    )


def _selector_fingerprint(
    entries: tuple[tuple[str, OpSpec[Any]], ...],
) -> _SelectorFingerprint:
    return tuple((name, id(spec)) for name, spec in entries)


def _selector_ui_rule(
    *,
    target: str,
    arg: str,
    arg_keys: Mapping[str, str],
    target_rule: Any,
):
    activate_key = arg_keys.get("activate")

    def visible(values: Mapping[str, Any]) -> bool:
        if str(values.get(_TARGET_ARG, "")) != target:
            return False
        if arg != "activate" and activate_key is not None:
            if not bool(values.get(activate_key, True)):
                return False
        if target_rule is None:
            return True
        target_values = {
            original_arg: values.get(encoded_arg)
            for original_arg, encoded_arg in arg_keys.items()
        }
        return bool(target_rule(target_values))

    return visible


def _selector_spec(
    *,
    private_op: str,
    kind: SelectorKind,
    n_inputs: int,
    entries: tuple[tuple[str, OpSpec[Any]], ...],
) -> OpSpec[Any]:
    names = tuple(name for name, _spec in entries)
    if not names:
        arity = "" if kind == "primitive" else f"（n_inputs={int(n_inputs)}）"
        raise _NoSelectableOperationsError(
            f"選択可能な {kind}{arity} が登録されていません"
        )

    meta: dict[str, ParamMeta] = {
        _TARGET_ARG: ParamMeta(
            kind="choice",
            choices=names,
            display_name="Operation",
            description=_TARGET_META_DESCRIPTION,
        )
    }
    defaults: dict[str, Any] = {_TARGET_ARG: names[0]}
    param_order: list[str] = [_TARGET_ARG]
    ui_visible: dict[str, Any] = {}

    for target, target_spec in entries:
        ordered_args = tuple(
            dict.fromkeys((*target_spec.param_order, *target_spec.meta.keys()))
        )
        arg_keys = {
            arg: selector_param_key(target, arg)
            for arg in ordered_args
            if arg in target_spec.meta
        }
        for arg in ordered_args:
            target_meta = target_spec.meta.get(arg)
            if target_meta is None:
                continue
            encoded_arg = arg_keys[arg]
            meta[encoded_arg] = replace(
                target_meta,
                display_name=target_meta.display_name or str(arg),
            )
            if arg in target_spec.defaults:
                defaults[encoded_arg] = target_spec.defaults[arg]
            param_order.append(encoded_arg)
            ui_visible[encoded_arg] = _selector_ui_rule(
                target=target,
                arg=arg,
                arg_keys=arg_keys,
                target_rule=target_spec.ui_visible.get(arg),
            )

    evaluator: PrimitiveFunc | EffectFunc
    evaluator = (
        _unreachable_primitive
        if kind == "primitive"
        else _unreachable_effect
    )
    return OpSpec(
        evaluator=evaluator,
        meta=meta,
        defaults=defaults,
        param_order=tuple(param_order),
        ui_visible=ui_visible,
        n_inputs=int(n_inputs),
        kind=kind,
        description=f"Grafix internal {kind} selector metadata",
        doc="DAG 作成時に実 operation へ lower される private selector。",
        source=__file__,
        provenance=f"{__name__}.{private_op}",
        accepted_args=tuple(param_order),
        required_args=(),
        accepts_var_kwargs=False,
        cache_policy="none",
    )


def _ensure_selector_spec(
    *,
    registry: OpRegistry[Any],
    private_op: str,
    kind: SelectorKind,
    n_inputs: int,
) -> OpSpec[Any]:
    cached = _cached_selector_spec(registry, private_op)
    if cached is not None:
        return cached

    entries = _public_specs(
        registry,
        n_inputs=None if kind == "primitive" else int(n_inputs),
    )
    fingerprint = _selector_fingerprint(entries)
    by_op = _SELECTOR_CACHE.get(registry)
    previous = None if by_op is None else by_op.get(private_op)
    if (
        previous is not None
        and previous.fingerprint == fingerprint
        and private_op in registry
        and registry[private_op] is previous.spec
    ):
        assert by_op is not None
        by_op[private_op] = _SelectorCacheEntry(
            fingerprint=fingerprint,
            spec=previous.spec,
            revision=int(registry.revision),
        )
        return previous.spec

    spec = _selector_spec(
        private_op=private_op,
        kind=kind,
        n_inputs=n_inputs,
        entries=entries,
    )
    registry.register(private_op, spec, replace=private_op in registry)
    if by_op is None:
        by_op = {}
        _SELECTOR_CACHE[registry] = by_op
    by_op[private_op] = _SelectorCacheEntry(
        fingerprint=fingerprint,
        spec=spec,
        revision=int(registry.revision),
    )
    return spec


def _cached_selector_spec(
    registry: OpRegistry[Any],
    private_op: str,
) -> OpSpec[Any] | None:
    """registry revision が未変更なら catalog 走査なしで selector spec を返す。"""

    by_op = _SELECTOR_CACHE.get(registry)
    cached = None if by_op is None else by_op.get(private_op)
    if (
        cached is None
        or cached.revision != int(registry.revision)
        or private_op not in registry
        or registry[private_op] is not cached.spec
    ):
        return None
    return cached.spec


def ensure_primitive_selector_spec() -> OpSpec[PrimitiveFunc]:
    """current primitive registry 用の private selector spec を返す。"""

    registry = primitive_registry_module.primitive_registry
    cached = _cached_selector_spec(registry, PRIMITIVE_SELECTOR_OP)
    if cached is not None:
        return cached
    ensure_builtin_primitives_registered()
    return _ensure_selector_spec(
        registry=registry,
        private_op=PRIMITIVE_SELECTOR_OP,
        kind="primitive",
        n_inputs=0,
    )


def ensure_effect_selector_spec(n_inputs: int) -> OpSpec[EffectFunc]:
    """current effect registry の arity 別 private selector spec を返す。"""

    count = validate_effect_selector_n_inputs(n_inputs)
    private_op = effect_selector_op(count)
    registry = effect_registry_module.effect_registry
    cached = _cached_selector_spec(registry, private_op)
    if cached is not None:
        return cached
    ensure_builtin_effects_registered()
    return _ensure_selector_spec(
        registry=registry,
        private_op=private_op,
        kind="effect",
        n_inputs=count,
    )


def ensure_selector_spec_registered(op: str) -> bool:
    """private selector ``op`` を current process の registry へ登録する。"""

    kind = selector_kind(op)
    try:
        if kind == "primitive":
            ensure_primitive_selector_spec()
            return True
        if kind == "effect":
            n_inputs = selector_effect_n_inputs(op)
            if n_inputs is None:
                return False
            ensure_effect_selector_spec(n_inputs)
            return True
    except _NoSelectableOperationsError:
        # 保存済み/worker 由来の selector group は、現在の process に同じ
        # kind/arity の operation が無くても GUI 全体を壊さず表示する。
        return False
    return False


def _target_error(
    *,
    kind: SelectorKind,
    target: str,
    choices: tuple[str, ...],
    n_inputs: int | None,
) -> ValueError:
    hint_match = get_close_matches(str(target), choices, n=1, cutoff=0.55)
    hint = "" if not hint_match else f"。{hint_match[0]!r} の誤りですか？"
    arity = "" if n_inputs is None else f"（n_inputs={int(n_inputs)}）"
    available = ", ".join(repr(choice) for choice in choices) or "（なし）"
    return ValueError(
        f"選択可能な {kind}{arity} に {target!r} はありません{hint}。"
        f"利用可能な候補: {available}"
    )


def validate_selector_target(
    *,
    kind: SelectorKind,
    target: str,
    selector_spec: OpSpec[Any],
    n_inputs: int | None,
) -> str:
    """selector spec の現在候補に target が含まれることを検証する。"""

    target_s = str(target)
    target_meta = selector_spec.meta[_TARGET_ARG]
    choices = tuple(target_meta.choices or ())
    if target_s.startswith("_") or target_s not in choices:
        raise _target_error(
            kind=kind,
            target=target_s,
            choices=choices,
            n_inputs=n_inputs,
        )
    return target_s


def validate_primitive_selector_target(target: str) -> str:
    """primitive selector の base target を current catalog で検証する。"""

    return validate_selector_target(
        kind="primitive",
        target=str(target),
        selector_spec=ensure_primitive_selector_spec(),
        n_inputs=None,
    )


def validate_effect_selector_target(target: str, *, n_inputs: int) -> str:
    """effect selector の base target を arity 別 catalog で検証する。"""

    count = validate_effect_selector_n_inputs(n_inputs)
    try:
        selector_spec = ensure_effect_selector_spec(count)
    except _NoSelectableOperationsError:
        raise _target_error(
            kind="effect",
            target=str(target),
            choices=(),
            n_inputs=count,
        ) from None
    return validate_selector_target(
        kind="effect",
        target=str(target),
        selector_spec=selector_spec,
        n_inputs=count,
    )


__all__ = [
    "PRIMITIVE_SELECTOR_OP",
    "SelectorKind",
    "decode_selector_param_key",
    "effect_selector_op",
    "ensure_effect_selector_spec",
    "ensure_primitive_selector_spec",
    "ensure_selector_spec_registered",
    "selector_display_arg",
    "selector_effect_n_inputs",
    "selector_help_identity",
    "selector_kind",
    "selector_param_key",
    "selector_search_terms",
    "validate_effect_selector_n_inputs",
    "validate_effect_selector_target",
    "validate_primitive_selector_target",
    "validate_selector_target",
]
