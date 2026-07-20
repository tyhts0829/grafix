"""G/E selector の target parameter 解決と実 operation への lowering を提供する。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from grafix.core.geometry import normalize_args
from grafix.core.op_registry import OpRegistry, OpSpec
from grafix.core.parameters.identity import identity_string
from grafix.core.operation_selector import (
    PRIMITIVE_SELECTOR_OP,
    SelectorKind,
    effect_selector_op,
    ensure_effect_selector_spec,
    ensure_primitive_selector_spec,
    selector_param_key,
    validate_effect_selector_n_inputs,
    validate_effect_selector_target,
    validate_selector_target,
)
from grafix.core.value_validation import exact_bool

import grafix.core.effect_registry as effect_registry_module
import grafix.core.primitive_registry as primitive_registry_module

from ._op_validation import validate_operation_kwargs
from ._param_resolution import resolve_api_params

ParamsByTarget: TypeAlias = Mapping[str, Mapping[str, Any]] | None
FrozenParamsByTarget: TypeAlias = tuple[
    tuple[str, tuple[tuple[str, Any], ...]],
    ...,
]


@dataclass(frozen=True, slots=True)
class ResolvedSelection:
    """selector が選んだ実 operation と Geometry 引数。"""

    selector_op: str
    target: str
    params: dict[str, Any]


def freeze_params_by_target(
    params_by_target: ParamsByTarget,
    *,
    kind: SelectorKind,
    n_inputs: int | None = None,
) -> FrozenParamsByTarget:
    """target別 kwargs を検証し、外側/内側 mapping から独立した値へ固定する。"""

    selector_spec: OpSpec[Any]
    if kind == "primitive":
        selector_spec = ensure_primitive_selector_spec()
        registry: OpRegistry[Any] = primitive_registry_module.primitive_registry
    else:
        if n_inputs is None:
            raise ValueError("effect selector には n_inputs が必要です")
        selector_spec = ensure_effect_selector_spec(n_inputs)
        registry = effect_registry_module.effect_registry

    if params_by_target is None:
        return ()
    if not isinstance(params_by_target, Mapping):
        raise TypeError("params_by_target は mapping または None である必要があります")

    frozen: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
    for raw_target, raw_params in params_by_target.items():
        target = validate_selector_target(
            kind=kind,
            target=identity_string(raw_target, name="params_by_target target"),
            selector_spec=selector_spec,
            n_inputs=n_inputs,
        )
        if not isinstance(raw_params, Mapping):
            raise TypeError(
                f"params_by_target[{target!r}] は mapping である必要があります"
            )
        params = dict(raw_params)
        if any(not isinstance(name, str) for name in params):
            raise TypeError("target parameter 名は str である必要があります")
        validate_operation_kwargs(op=target, spec=registry[target], params=params)
        frozen.append((target, normalize_args(params)))
    frozen.sort(key=lambda item: item[0])
    return tuple(frozen)


def _params_for_target(
    frozen: FrozenParamsByTarget,
    target: str,
) -> dict[str, Any]:
    for name, items in frozen:
        if name == target:
            return dict(items)
    return {}


def _resolve_selection(
    *,
    kind: SelectorKind,
    selector_op: str,
    selector_spec: OpSpec[Any],
    registry: OpRegistry[Any],
    base_target: str,
    target_explicit: bool,
    frozen_params: FrozenParamsByTarget,
    site_id: str,
    n_inputs: int | None,
) -> ResolvedSelection:
    target_is_explicit = exact_bool(
        target_explicit,
        name="target_explicit",
    )
    base_target_s = validate_selector_target(
        kind=kind,
        target=base_target,
        selector_spec=selector_spec,
        n_inputs=n_inputs,
    )
    resolved_target = resolve_api_params(
        op=selector_op,
        site_id=site_id,
        user_params={"target": base_target_s},
        defaults={},
        meta={"target": selector_spec.meta["target"]},
        explicit_args={"target"} if target_is_explicit else set(),
    )["target"]
    target = validate_selector_target(
        kind=kind,
        target=identity_string(resolved_target, name="resolved selector target"),
        selector_spec=selector_spec,
        n_inputs=n_inputs,
    )
    target_spec = registry[target]
    code_params = _params_for_target(frozen_params, target)
    validate_operation_kwargs(op=target, spec=target_spec, params=code_params)

    visible_user_params = {
        selector_param_key(target, arg): value
        for arg, value in code_params.items()
        if arg in target_spec.meta
    }
    visible_defaults = {
        selector_param_key(target, arg): value
        for arg, value in target_spec.defaults.items()
        if arg in target_spec.meta
    }
    visible_meta = {
        selector_param_key(target, arg): selector_spec.meta[
            selector_param_key(target, arg)
        ]
        for arg in target_spec.meta
    }
    resolved_visible = resolve_api_params(
        op=selector_op,
        site_id=site_id,
        user_params=visible_user_params,
        defaults=visible_defaults,
        meta=visible_meta,
    )

    params = {
        arg: value
        for arg, value in code_params.items()
        if arg not in target_spec.meta
    }
    params.update(
        {
            arg: resolved_visible[selector_param_key(target, arg)]
            for arg in target_spec.meta
            if selector_param_key(target, arg) in resolved_visible
        }
    )
    missing = tuple(arg for arg in target_spec.required_args if arg not in params)
    if missing:
        names = ", ".join(repr(name) for name in missing)
        raise TypeError(f"{kind} {target!r} に必要な引数がありません: {names}")
    validate_operation_kwargs(op=target, spec=target_spec, params=params)
    return ResolvedSelection(
        selector_op=selector_op,
        target=target,
        params=params,
    )


def resolve_primitive_selection(
    *,
    target: str,
    target_explicit: bool,
    params_by_target: FrozenParamsByTarget,
    site_id: str,
) -> ResolvedSelection:
    """primitive selector を解決し、実 target の Geometry 引数を返す。"""

    selector_spec = ensure_primitive_selector_spec()
    return _resolve_selection(
        kind="primitive",
        selector_op=PRIMITIVE_SELECTOR_OP,
        selector_spec=selector_spec,
        registry=primitive_registry_module.primitive_registry,
        base_target=target,
        target_explicit=target_explicit,
        frozen_params=params_by_target,
        site_id=site_id,
        n_inputs=None,
    )


def resolve_effect_selection(
    *,
    target: str,
    target_explicit: bool,
    n_inputs: int,
    params_by_target: FrozenParamsByTarget,
    site_id: str,
) -> ResolvedSelection:
    """effect selector を解決し、実 target の Geometry 引数を返す。"""

    count = validate_effect_selector_n_inputs(n_inputs)
    current_target = validate_effect_selector_target(
        target,
        n_inputs=count,
    )
    selector_op = effect_selector_op(count)
    selector_spec = ensure_effect_selector_spec(count)
    return _resolve_selection(
        kind="effect",
        selector_op=selector_op,
        selector_spec=selector_spec,
        registry=effect_registry_module.effect_registry,
        base_target=current_target,
        target_explicit=target_explicit,
        frozen_params=params_by_target,
        site_id=site_id,
        n_inputs=count,
    )


__all__ = [
    "FrozenParamsByTarget",
    "PRIMITIVE_SELECTOR_OP",
    "ParamsByTarget",
    "ResolvedSelection",
    "effect_selector_op",
    "ensure_effect_selector_spec",
    "ensure_primitive_selector_spec",
    "freeze_params_by_target",
    "resolve_effect_selection",
    "resolve_primitive_selection",
    "selector_param_key",
    "validate_effect_selector_n_inputs",
    "validate_effect_selector_target",
]
