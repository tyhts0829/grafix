"""evaluator から独立した operation parameter schema の契約を検証する。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields
from inspect import signature
from typing import Any

import numpy as np
import pytest

from grafix.core.operation_declaration import OpDeclaration, create_op_declaration
from grafix.core.operation_schema import ParameterOpSchema
from grafix.core.parameters.meta import ParamMeta


def _evaluator(*, count: int = 1) -> object:
    _ = count
    return object()


def _schema(
    *,
    meta: Mapping[str, ParamMeta] | None = None,
    defaults: Mapping[str, Any] | None = None,
    param_order: tuple[str, ...] | None = None,
    ui_visible: Mapping[str, object] | None = None,
) -> ParameterOpSchema:
    parameter_meta = {"count": ParamMeta(kind="int")} if meta is None else meta
    return ParameterOpSchema(
        meta=parameter_meta,
        defaults={"count": 1} if defaults is None else defaults,
        param_order=("count",) if param_order is None else param_order,
        ui_visible={} if ui_visible is None else ui_visible,
    )


def test_parameter_op_schema_copies_mappings_and_is_frozen() -> None:
    choices = ["draft", "final"]
    meta = {"quality": ParamMeta(kind="choice", choices=choices)}
    defaults = {"quality": "draft"}
    visible = {"quality": lambda _values: True}

    schema = ParameterOpSchema(
        meta=meta,
        defaults=defaults,
        param_order=("quality",),
        ui_visible=visible,
    )

    meta["stale"] = ParamMeta(kind="int")
    defaults["stale"] = 2
    visible["stale"] = lambda _values: False
    choices.append("stale")

    assert tuple(schema.meta) == ("quality",)
    assert schema.meta["quality"].choices == ("draft", "final")
    assert dict(schema.defaults) == {"quality": "draft"}
    assert tuple(schema.ui_visible) == ("quality",)
    with pytest.raises(TypeError):
        schema.meta["other"] = ParamMeta(kind="int")  # type: ignore[index]
    with pytest.raises(TypeError):
        schema.defaults["quality"] = "final"  # type: ignore[index]
    with pytest.raises(TypeError):
        schema.ui_visible["quality"] = lambda _values: False  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        schema.param_order = ()  # type: ignore[misc]


def test_parameter_op_schema_normalizes_defaults_with_parameter_validator() -> None:
    schema = ParameterOpSchema(
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
    )

    assert schema.defaults == {"count": 3, "offset": (1.0, 2.0, 3.0)}
    assert type(schema.defaults["count"]) is int
    assert all(type(value) is float for value in schema.defaults["offset"])


@pytest.mark.parametrize(
    ("meta", "defaults"),
    [
        ({"count": ParamMeta(kind="int")}, {}),
        ({}, {"count": 1}),
    ],
)
def test_parameter_op_schema_requires_same_meta_and_default_keys(
    meta: Mapping[str, ParamMeta],
    defaults: Mapping[str, object],
) -> None:
    with pytest.raises(ValueError, match="meta/default"):
        ParameterOpSchema(
            meta=meta,
            defaults=defaults,
            param_order=tuple(meta),
            ui_visible={},
        )


def test_parameter_op_schema_validates_meta_and_default_values() -> None:
    with pytest.raises(TypeError, match="ParamMeta"):
        ParameterOpSchema(
            meta={"count": object()},  # type: ignore[dict-item]
            defaults={"count": 1},
            param_order=("count",),
            ui_visible={},
        )

    with pytest.raises(TypeError, match="int"):
        _schema(defaults={"count": True})


@pytest.mark.parametrize(
    "param_order",
    [
        ("count",),
        ("count", "count"),
        ("count", "mode", "unknown"),
    ],
)
def test_parameter_op_schema_requires_param_order_to_cover_meta_once(
    param_order: tuple[str, ...],
) -> None:
    meta = {
        "count": ParamMeta(kind="int"),
        "mode": ParamMeta(kind="choice", choices=("a", "b")),
    }
    defaults = {"count": 1, "mode": "a"}

    with pytest.raises(ValueError, match="param_order"):
        _schema(meta=meta, defaults=defaults, param_order=param_order)


def test_parameter_op_schema_validates_ui_visible_entries() -> None:
    with pytest.raises(ValueError, match="ui_visible"):
        _schema(ui_visible={"unknown": lambda _values: True})

    with pytest.raises(TypeError, match="callable"):
        _schema(ui_visible={"count": object()})


def test_declaration_composes_schema_without_duplicating_schema_fields() -> None:
    schema = _schema()

    declaration = create_op_declaration(
        name="schema_composition",
        kind="primitive",
        evaluator=_evaluator,
        schema=schema,
        n_inputs=0,
    )

    assert declaration.schema is schema
    declaration_fields = {field.name for field in fields(OpDeclaration)}
    assert "schema" in declaration_fields
    assert declaration_fields.isdisjoint(
        {"meta", "defaults", "param_order", "ui_visible"}
    )


def test_declaration_factory_does_not_expose_legacy_schema_arguments() -> None:
    legacy_schema_fields = {"meta", "defaults", "param_order", "ui_visible"}
    constructor_parameters = set(signature(create_op_declaration).parameters)
    declaration = create_op_declaration(
        name="schema_contract",
        kind="primitive",
        evaluator=_evaluator,
        schema=_schema(),
        n_inputs=0,
    )

    assert constructor_parameters.isdisjoint(legacy_schema_fields)
    assert all(not hasattr(declaration, name) for name in legacy_schema_fields)


@pytest.mark.parametrize(
    ("legacy_name", "legacy_value"),
    [
        ("meta", {"count": ParamMeta(kind="int")}),
        ("defaults", {"count": 1}),
        ("param_order", ("count",)),
        ("ui_visible", {}),
    ],
)
def test_declaration_factory_rejects_legacy_schema_keywords(
    legacy_name: str,
    legacy_value: object,
) -> None:
    kwargs = {
        "name": "legacy_schema_keyword",
        "kind": "primitive",
        "evaluator": _evaluator,
        "schema": _schema(),
        "n_inputs": 0,
        legacy_name: legacy_value,
    }

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        create_op_declaration(**kwargs)  # type: ignore[arg-type]
