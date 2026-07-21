"""primitive/effect 共通 OpRegistry の契約を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, replace
from enum import Enum
from inspect import signature
from typing import Any, cast

import numpy as np
import pytest

import grafix.core.primitive_registry as primitive_registry_module
import grafix.core.effect_registry as effect_registry_module
from grafix.core.builtins import (
    ensure_builtin_effect_registered,
    ensure_builtin_effects_registered,
    ensure_builtin_ops_registered,
    ensure_builtin_primitive_registered,
    ensure_builtin_primitives_registered,
)
from grafix.core.effect_registry import effect
from grafix.core.op_registry import OpKind, OpRegistry, OpSpec
from grafix.core.parameters.meta import ParamMeta
from grafix.core.primitive_registry import PrimitiveFunc, primitive
from grafix.core.realized_geometry import GeomTuple

Evaluator = Callable[..., object]


def _evaluator(*_args: object) -> object:
    return object()


def _spec(
    *,
    kind: OpKind = "primitive",
    evaluator: Evaluator = _evaluator,
    meta: Mapping[str, ParamMeta] | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> OpSpec[Evaluator]:
    return OpSpec(
        evaluator=evaluator,
        meta={} if meta is None else meta,
        defaults={} if defaults is None else defaults,
        param_order=() if meta is None else tuple(meta),
        ui_visible={},
        n_inputs=0 if kind == "primitive" else 1,
        kind=kind,
    )


def _empty_geometry() -> GeomTuple:
    return (
        np.empty((0, 3), dtype=np.float32),
        np.zeros((1,), dtype=np.int32),
    )


def test_op_spec_copies_mappings_and_is_frozen() -> None:
    choices = ["a", "b"]
    meta = {"x": ParamMeta(kind="choice", choices=choices)}
    defaults = {"x": "a"}
    rules = {"x": lambda _values: True}
    spec = OpSpec(
        evaluator=_evaluator,
        meta=meta,
        defaults=defaults,
        param_order=("x",),
        ui_visible=rules,
        n_inputs=0,
        kind="primitive",
    )

    meta["stale"] = ParamMeta(kind="int")
    defaults["stale"] = 2
    rules["stale"] = lambda _values: False
    choices.append("stale")

    assert tuple(spec.meta) == ("x",)
    assert spec.meta["x"].choices == ("a", "b")
    assert dict(spec.defaults) == {"x": "a"}
    assert tuple(spec.ui_visible) == ("x",)
    with pytest.raises(TypeError):
        spec.meta["y"] = ParamMeta(kind="int")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        spec.n_inputs = 1  # type: ignore[misc]


def test_op_spec_normalizes_defaults_with_parameter_validator() -> None:
    spec = OpSpec(
        evaluator=_evaluator,
        meta={
            "count": ParamMeta(kind="int"),
            "offset": ParamMeta(kind="vec3"),
        },
        defaults={
            "count": np.int64(3),
            "offset": (np.float32(1.0), np.int64(2), 3.0),
        },
        param_order=("count", "offset"),
        ui_visible={},
        n_inputs=0,
        kind="primitive",
    )

    assert spec.defaults == {"count": 3, "offset": (1.0, 2.0, 3.0)}
    assert type(spec.defaults["count"]) is int
    assert all(type(value) is float for value in spec.defaults["offset"])


@pytest.mark.parametrize(
    ("meta", "defaults"),
    [
        ({"count": ParamMeta(kind="int")}, {}),
        ({}, {"count": 1}),
    ],
)
def test_op_spec_rejects_mismatched_meta_and_defaults(
    meta: Mapping[str, ParamMeta],
    defaults: Mapping[str, object],
) -> None:
    with pytest.raises(ValueError, match="meta/default"):
        OpSpec(
            evaluator=_evaluator,
            meta=meta,
            defaults=defaults,
            param_order=tuple(meta),
            ui_visible={},
            n_inputs=0,
            kind="primitive",
        )


def test_op_spec_rejects_mutable_or_wrong_typed_parameter_default() -> None:
    with pytest.raises(TypeError, match="vec3"):
        OpSpec(
            evaluator=_evaluator,
            meta={"offset": ParamMeta(kind="vec3")},
            defaults={"offset": [1.0, 2.0, 3.0]},
            param_order=("offset",),
            ui_visible={},
            n_inputs=0,
            kind="primitive",
        )


def test_decorator_rejects_mutable_code_owned_default() -> None:
    mutable_default = [1.0, 2.0]

    def mutable_default_primitive(
        *,
        points: object = mutable_default,
    ) -> GeomTuple:
        _ = points
        return _empty_geometry()

    with pytest.raises(TypeError, match="immutable"):
        primitive(mutable_default_primitive)


def test_decorator_rejects_enum_code_owned_default() -> None:
    class MutableEnum(Enum):
        ITEM = []

    def enum_default_primitive(*, mode: object = MutableEnum.ITEM) -> GeomTuple:
        _ = mode
        return _empty_geometry()

    with pytest.raises(TypeError, match="immutable"):
        primitive(enum_default_primitive)


@pytest.mark.parametrize(
    "ui_visible",
    (
        {1: lambda _values: True},
        {"": lambda _values: True},
        {"x": []},
    ),
)
def test_op_spec_rejects_noncanonical_ui_visible_entries(
    ui_visible: Mapping[object, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        OpSpec(
            evaluator=_evaluator,
            meta={"x": ParamMeta(kind="float")},
            defaults={"x": 1.0},
            param_order=("x",),
            ui_visible=ui_visible,  # type: ignore[arg-type]
            n_inputs=0,
            kind="primitive",
        )


def test_decorators_reject_wrapper_owned_callable_arguments() -> None:
    def reserved_primitive(
        *,
        activate: bool = True,
        key: str | None = None,
        instance_key: str | None = None,
        shared: bool = False,
    ) -> GeomTuple:
        _ = activate, key, instance_key, shared
        return _empty_geometry()

    def reserved_effect(
        g: GeomTuple,
        *,
        activate: bool = True,
        key: str | None = None,
        instance_key: str | None = None,
        shared: bool = False,
    ) -> GeomTuple:
        _ = activate, key, instance_key, shared
        return g

    def reserved_geometry_input(activate: GeomTuple) -> GeomTuple:
        return activate

    with pytest.raises(ValueError, match="wrapper 予約引数"):
        primitive(reserved_primitive)
    with pytest.raises(ValueError, match="wrapper 予約引数"):
        effect(reserved_effect)
    with pytest.raises(ValueError, match="wrapper 予約引数"):
        effect(reserved_geometry_input)


def test_primitive_decorator_rejects_non_keyword_passable_arguments() -> None:
    def positional_only(value: float = 1.0, /) -> GeomTuple:
        _ = value
        return _empty_geometry()

    def variadic(*values: float) -> GeomTuple:
        _ = values
        return _empty_geometry()

    with pytest.raises(TypeError, match="keyword"):
        primitive(positional_only)
    with pytest.raises(TypeError, match="可変位置引数"):
        primitive(variadic)


def test_effect_decorator_requires_unambiguous_geometry_inputs() -> None:
    def insufficient(first: GeomTuple) -> GeomTuple:
        return first

    def keyword_only(*, g: GeomTuple) -> GeomTuple:
        return g

    def variadic_geometry(*geometries: GeomTuple) -> GeomTuple:
        return geometries[0]

    def default_geometry(g: GeomTuple = _empty_geometry()) -> GeomTuple:
        return g

    with pytest.raises(TypeError, match="2 個"):
        effect(n_inputs=2)(insufficient)
    with pytest.raises(TypeError, match="位置引数"):
        effect(keyword_only)
    with pytest.raises(TypeError, match="位置引数"):
        effect(variadic_geometry)
    with pytest.raises(TypeError, match="default"):
        effect(default_geometry)


def test_effect_decorator_rejects_non_keyword_passable_operation_arguments() -> None:
    def positional_only(
        g: GeomTuple,
        amount: float = 1.0,
        /,
    ) -> GeomTuple:
        _ = amount
        return g

    def variadic(g: GeomTuple, *amounts: float) -> GeomTuple:
        _ = amounts
        return g

    with pytest.raises(TypeError, match="keyword"):
        effect(positional_only)
    with pytest.raises(TypeError, match="可変位置引数"):
        effect(variadic)


@pytest.mark.parametrize("n_inputs", [True, 1.0, "1"])
@pytest.mark.parametrize("kind", ["primitive", "effect"])
def test_op_spec_rejects_implicitly_convertible_n_inputs(
    kind: OpKind,
    n_inputs: object,
) -> None:
    with pytest.raises(TypeError, match="n_inputs.*int"):
        OpSpec(
            evaluator=_evaluator,
            meta={},
            defaults={},
            param_order=(),
            ui_visible={},
            n_inputs=n_inputs,  # type: ignore[arg-type]
            kind=kind,
        )


def test_op_spec_normalizes_index_integer_n_inputs() -> None:
    spec = OpSpec(
        evaluator=_evaluator,
        meta={},
        defaults={},
        param_order=(),
        ui_visible={},
        n_inputs=np.int64(1),  # type: ignore[arg-type]
        kind="effect",
    )

    assert spec.n_inputs == 1
    assert type(spec.n_inputs) is int


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("param_order", (1,)),
        ("description", object()),
        ("accepted_args", (1,)),
        ("accepts_var_kwargs", 1),
    ],
)
def test_op_spec_rejects_implicit_metadata_conversion(
    field: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {
        "evaluator": _evaluator,
        "meta": {},
        "defaults": {},
        "param_order": (),
        "ui_visible": {},
        "n_inputs": 0,
        "kind": "primitive",
    }
    kwargs[field] = value

    with pytest.raises(TypeError):
        OpSpec(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "n_inputs", "message"),
    [
        ("primitive", 1, "0 である"),
        ("effect", 0, "1 以上"),
    ],
)
def test_op_spec_rejects_n_inputs_outside_kind_range(
    kind: OpKind,
    n_inputs: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OpSpec(
            evaluator=_evaluator,
            meta={},
            defaults={},
            param_order=(),
            ui_visible={},
            n_inputs=n_inputs,
            kind=kind,
        )


@pytest.mark.parametrize("n_inputs", [True, 1.0, "1"])
def test_effect_decorator_rejects_implicitly_convertible_n_inputs(
    n_inputs: object,
) -> None:
    with pytest.raises(TypeError, match="n_inputs.*int"):
        effect(n_inputs=n_inputs)  # type: ignore[arg-type]


def test_registry_requires_explicit_replace_and_advances_revision() -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind="primitive")
    first = _spec()
    second = _spec(evaluator=lambda *_args: "second")

    assert registry.revision == 0
    registry.register("sample", first)
    assert registry["sample"] is first
    assert registry.revision == 1

    with pytest.raises(ValueError, match="既に登録"):
        registry.register("sample", second)
    assert registry["sample"] is first
    assert registry.revision == 1

    registry.register("sample", second, replace=True)
    assert registry["sample"] is second
    assert registry.revision == 2


def test_builtin_catalog_restores_cached_modules_after_live_registry_clear() -> None:
    ensure_builtin_ops_registered()
    primitive_registry = primitive_registry_module.primitive_registry
    effect_registry = effect_registry_module.effect_registry
    original_primitives = dict(primitive_registry.items())
    original_effects = dict(effect_registry.items())
    circle_spec = primitive_registry["circle"]
    scale_spec = effect_registry["scale"]

    try:
        primitive_registry.replace_all({})
        effect_registry.replace_all({})

        assert ensure_builtin_primitive_registered("circle")
        assert ensure_builtin_effect_registered("scale")
        assert primitive_registry["circle"] is circle_spec
        assert effect_registry["scale"] is scale_spec

        ensure_builtin_primitives_registered()
        ensure_builtin_effects_registered()
        assert len(primitive_registry) == 20
        assert len(effect_registry) == 37
    finally:
        primitive_registry.replace_all(original_primitives)
        effect_registry.replace_all(original_effects)


def test_builtin_ensure_does_not_replace_explicit_live_override() -> None:
    ensure_builtin_primitive_registered("circle")
    registry = primitive_registry_module.primitive_registry
    original = dict(registry.items())
    replacement = replace(registry["circle"], description="explicit replacement")

    try:
        registry.replace_all({"circle": replacement})

        assert not ensure_builtin_primitive_registered("circle")
        assert registry["circle"] is replacement
    finally:
        registry.replace_all(original)


@pytest.mark.parametrize("invalid", (1, object()))
def test_registry_rejects_implicitly_stringifiable_operation_name(
    invalid: object,
) -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind="primitive")

    with pytest.raises(TypeError, match="空でない文字列"):
        registry.register(cast(str, invalid), _spec())
    with pytest.raises(TypeError, match="空でない文字列"):
        registry.describe(cast(str, invalid))
    with pytest.raises(TypeError, match="空でない文字列"):
        registry.replace_all(cast(Mapping[str, OpSpec[Evaluator]], {invalid: _spec()}))


def test_registry_rejects_empty_operation_name() -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind="primitive")

    with pytest.raises(ValueError, match="空でない文字列"):
        registry.register("", _spec())


@pytest.mark.parametrize("kind", ("primitive", "effect"))
def test_registry_rejects_reserved_concat_without_advancing_revision(kind: OpKind) -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind=kind)

    with pytest.raises(ValueError, match="予約"):
        registry.register("concat", _spec(kind=kind))

    assert registry.revision == 0
    assert "concat" not in registry


def test_registry_rejects_spec_from_other_kind() -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind="primitive")

    with pytest.raises(ValueError, match="effect spec"):
        registry.register("wrong-kind", _spec(kind="effect"))

    assert registry.revision == 0


def test_public_decorators_disable_overwrite_by_default() -> None:
    assert signature(primitive).parameters["overwrite"].default is False
    assert signature(effect).parameters["overwrite"].default is False
    assert signature(primitive).parameters["cache_policy"].default == "content"
    assert signature(effect).parameters["cache_policy"].default == "content"


@pytest.mark.parametrize("overwrite", [1, 0, "false", None])
def test_public_decorators_reject_non_bool_overwrite(overwrite: object) -> None:
    with pytest.raises(TypeError, match="overwrite"):
        primitive(overwrite=overwrite)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="overwrite"):
        effect(overwrite=overwrite)  # type: ignore[arg-type]


@pytest.mark.parametrize("replace", [1, 0, "false", None])
def test_registry_rejects_non_bool_replace(replace: object) -> None:
    registry: OpRegistry[Evaluator] = OpRegistry(kind="primitive")

    with pytest.raises(TypeError, match="replace"):
        registry.register(
            "sample",
            _spec(),
            replace=replace,  # type: ignore[arg-type]
        )

    assert registry.revision == 0


def test_op_spec_rejects_unknown_cache_policy() -> None:
    with pytest.raises(ValueError, match="cache_policy"):
        OpSpec(
            evaluator=_evaluator,
            meta={},
            defaults={},
            param_order=(),
            ui_visible={},
            n_inputs=0,
            kind="primitive",
            cache_policy="frame",  # type: ignore[arg-type]
        )


def test_primitive_decorator_records_none_cache_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    @primitive_registry_module.primitive(cache_policy="none")
    def live_shape() -> GeomTuple:
        return _empty_geometry()

    assert registry["live_shape"].cache_policy == "none"
    assert registry.describe("live_shape").cache_policy == "none"


def test_primitive_replace_clears_stale_metadata_and_default_is_no_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    monkeypatch.setattr(primitive_registry_module, "primitive_registry", registry)

    @primitive_registry_module.primitive(
        meta={"x": ParamMeta(kind="float")},
        ui_visible={"x": lambda _values: True},
    )
    def replace_target(*, x: float = 1.0) -> GeomTuple:
        _ = x
        return _empty_geometry()

    first = registry["replace_target"]
    assert tuple(first.meta) == ("activate", "x")
    assert dict(first.defaults) == {"activate": True, "x": 1.0}
    assert first.param_order == ("activate", "x")
    assert tuple(first.ui_visible) == ("x",)
    first_revision = registry.revision

    with pytest.raises(ValueError, match="既に登録"):

        @primitive_registry_module.primitive
        def replace_target(*, y: float = 2.0) -> GeomTuple:
            _ = y
            return _empty_geometry()

    assert registry.revision == first_revision
    assert registry["replace_target"] is first

    @primitive_registry_module.primitive(overwrite=True)
    def replace_target(*, y: float = 2.0) -> GeomTuple:
        _ = y
        return _empty_geometry()

    replacement = registry["replace_target"]
    assert replacement is not first
    assert replacement.meta == {}
    assert replacement.defaults == {}
    assert replacement.param_order == ()
    assert replacement.ui_visible == {}
    assert registry.revision == first_revision + 1
