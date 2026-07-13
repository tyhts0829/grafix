"""primitive/effect 共通 OpRegistry の契約を検証する。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError
from inspect import signature
from typing import Any

import numpy as np
import pytest

import grafix.core.primitive_registry as primitive_registry_module
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
    defaults = {"x": 1.0}
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
    assert dict(spec.defaults) == {"x": 1.0}
    assert tuple(spec.ui_visible) == ("x",)
    with pytest.raises(TypeError):
        spec.meta["y"] = ParamMeta(kind="int")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        spec.n_inputs = 1  # type: ignore[misc]


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
