"""preset declaration と session-local catalog の契約を検証する。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from grafix.core.operation_schema import ParameterOpSchema
from grafix.core.parameters.meta import ParamMeta
from grafix.core.preset_catalog import (
    PresetCatalogBuilder,
    PresetDeclaration,
)


def _func(*, count: int = 1) -> list[object]:
    _ = count
    return []


def _invoker(**_kwargs: object) -> list[object]:
    return []


def _declaration(name: str) -> PresetDeclaration:
    return PresetDeclaration(
        name=name,
        func=_func,
        invoker=_invoker,
        schema=ParameterOpSchema(
            meta={"count": ParamMeta(kind="int")},
            defaults={"count": 1},
            param_order=("count",),
            ui_visible={},
        ),
    )


def test_preset_declaration_owns_one_immutable_parameter_schema() -> None:
    meta = {"count": ParamMeta(kind="int")}
    defaults = {"count": 1}
    schema = ParameterOpSchema(
        meta=meta,
        defaults=defaults,
        param_order=("count",),
        ui_visible={},
    )
    declaration = PresetDeclaration(
        name="grid",
        func=_func,
        invoker=_invoker,
        schema=schema,
    )
    meta.clear()
    defaults.clear()

    assert declaration.schema is schema
    assert tuple(declaration.schema.meta) == ("count",)
    assert dict(declaration.schema.defaults) == {"count": 1}
    assert declaration.display_op == "preset.grid"
    with pytest.raises(TypeError):
        declaration.schema.meta["other"] = ParamMeta(kind="int")  # type: ignore[index]
    with pytest.raises(TypeError):
        declaration.schema.defaults["count"] = 2  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        declaration.name = "changed"  # type: ignore[misc]


def test_preset_declaration_requires_exact_parameter_schema() -> None:
    with pytest.raises(TypeError, match="ParameterOpSchema"):
        PresetDeclaration(
            name="grid",
            func=_func,
            invoker=_invoker,
            schema=object(),  # type: ignore[arg-type]
        )


def test_same_preset_name_is_isolated_between_catalogs() -> None:
    first_builder = PresetCatalogBuilder()
    second_builder = PresetCatalogBuilder()
    first = _declaration("shared")
    second = _declaration("shared")

    first_builder.register(first)
    second_builder.register(second)
    first_catalog = first_builder.freeze()
    second_catalog = second_builder.freeze()

    assert first_catalog["shared"] is first
    assert second_catalog["shared"] is second


def test_preset_duplicate_does_not_change_builder_or_existing_snapshot() -> None:
    builder = PresetCatalogBuilder()
    first = _declaration("shared")
    second = _declaration("shared")
    builder.register(first)
    before = builder.freeze()

    with pytest.raises(ValueError, match="既に登録"):
        builder.register(second)

    assert before["shared"] is first
    assert builder.freeze()["shared"] is first
