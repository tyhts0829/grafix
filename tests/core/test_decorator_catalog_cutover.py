"""decorator registration と immutable catalog 選択規則を固定する。"""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from grafix import E, G, P
from grafix.api import preset
from grafix.core.authoring_definitions import (
    RegistrationTarget,
    default_authoring_definitions,
    registration_scope,
)
from grafix.core.builtins import (
    builtin_operation_catalog,
    builtin_operation_manifest,
)
from grafix.core.geometry import Geometry
from grafix.core.operation_authoring import effect, primitive
from grafix.core.operation_catalog import bind_operation_catalog
from grafix.core.operation_declaration import operation_declaration
from grafix.core.operation_selector import selector_spec
from grafix.core.preset_catalog import bind_preset_catalog


def _empty_geometry() -> tuple[list[object], list[object]]:
    return [], []


def test_all_public_decorators_use_the_scoped_registration_target_only() -> None:
    target = RegistrationTarget()

    with registration_scope(target):

        @primitive(meta={})
        def catalog_cutover_shape() -> tuple[list[object], list[object]]:
            return _empty_geometry()

        @effect(meta={})
        def catalog_cutover_warp(
            geometry: tuple[list[object], list[object]],
        ) -> tuple[list[object], list[object]]:
            return geometry

        @preset(meta={})
        def catalog_cutover_scene() -> Geometry:
            return Geometry.create(op="concat")

    snapshot = target.snapshot()
    assert snapshot.operations.resolve("primitive", "catalog_cutover_shape")
    assert snapshot.operations.resolve("effect", "catalog_cutover_warp")
    assert snapshot.presets["catalog_cutover_scene"]

    primitive_decl = operation_declaration(catalog_cutover_shape)
    effect_decl = operation_declaration(catalog_cutover_warp)
    assert primitive_decl is snapshot.operations.resolve(
        "primitive", "catalog_cutover_shape"
    ).declaration
    assert effect_decl is snapshot.operations.resolve(
        "effect", "catalog_cutover_warp"
    ).declaration


def test_builtin_direct_import_does_not_change_default_authoring_definitions() -> None:
    before = default_authoring_definitions.snapshot()

    module = importlib.import_module("grafix.core.primitives.circle")

    after = default_authoring_definitions.snapshot()
    assert tuple(before.operations) == tuple(after.operations)
    assert tuple(before.presets) == tuple(after.presets)
    manifest = {
        (item.kind, item.name): item for item in builtin_operation_manifest()
    }
    item = manifest[("primitive", "circle")]
    declaration = operation_declaration(getattr(module, item.attribute))
    assert builtin_operation_catalog().resolve(
        "primitive", "circle"
    ).declaration is declaration


def test_bound_operation_catalog_is_a_stable_dispatch_snapshot() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @primitive(meta={"amount": {"kind": "float"}})
        def catalog_snapshot_shape(
            *, amount: float = 1.0
        ) -> tuple[list[object], list[object]]:
            _ = amount
            return _empty_geometry()

    catalog_a = target.snapshot().operations
    declaration_a = catalog_a.resolve(
        "primitive", "catalog_snapshot_shape"
    ).declaration
    declaration_b = replace(
        declaration_a,
        schema=replace(
            declaration_a.schema,
            defaults={"activate": True, "amount": 2.0},
        ),
    )
    target.register(declaration_b, overwrite=True)
    catalog_b = target.snapshot().operations

    with bind_operation_catalog(catalog_a):
        factory_a = G.catalog_snapshot_shape
    with bind_operation_catalog(catalog_b):
        factory_b = G.catalog_snapshot_shape

    assert dict(factory_a().args)["amount"] == 1.0
    assert dict(factory_b().args)["amount"] == 2.0


def test_effect_builder_keeps_the_exact_entry_used_at_step_creation() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @effect(meta={"amount": {"kind": "float"}})
        def catalog_snapshot_effect(
            geometry: tuple[list[object], list[object]],
            *,
            amount: float = 1.0,
        ) -> tuple[list[object], list[object]]:
            _ = amount
            return geometry

    catalog_a = target.snapshot().operations
    declaration_a = catalog_a.resolve(
        "effect", "catalog_snapshot_effect"
    ).declaration
    declaration_b = replace(
        declaration_a,
        schema=replace(
            declaration_a.schema,
            defaults={"activate": True, "amount": 2.0},
        ),
    )
    target.register(declaration_b, overwrite=True)
    catalog_b = target.snapshot().operations

    with bind_operation_catalog(catalog_a):
        builder_a = E.catalog_snapshot_effect()
    with bind_operation_catalog(catalog_b):
        geometry = builder_a(Geometry.create(op="concat"))

    assert dict(geometry.args)["amount"] == 1.0


def test_selector_schema_is_not_an_evaluator_catalog_entry() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @primitive(meta={"amount": {"kind": "float"}})
        def catalog_selector_shape(
            *, amount: float = 1.0
        ) -> tuple[list[object], list[object]]:
            _ = amount
            return _empty_geometry()

    catalog = target.snapshot().operations
    before = tuple(catalog)

    spec = selector_spec(catalog, kind="primitive", n_inputs=0)

    assert spec.schema.meta["target"].choices == ("catalog_selector_shape",)
    assert tuple(catalog) == before
    assert ("primitive", spec.op) not in catalog
    assert not hasattr(spec, "evaluator")


def test_selector_cache_tracks_schema_fingerprint_not_evaluator_fingerprint() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @primitive(meta={"amount": {"kind": "float", "description": "amount"}})
        def selector_fingerprint_shape(
            *, amount: float = 1.0
        ) -> tuple[list[object], list[object]]:
            _ = amount
            return _empty_geometry()

    first_catalog = target.snapshot().operations
    first_entry = first_catalog.resolve("primitive", "selector_fingerprint_shape")
    first_selector = selector_spec(first_catalog, kind="primitive", n_inputs=0)

    def evaluation_changed(
        *, amount: float = 1.0
    ) -> tuple[list[object], list[object]]:
        _ = amount + 1.0
        return _empty_geometry()

    evaluation_changed.__name__ = "selector_fingerprint_shape"
    with registration_scope(target):
        primitive(
            overwrite=True,
            meta={"amount": {"kind": "float", "description": "amount"}},
        )(evaluation_changed)
    second_catalog = target.snapshot().operations
    second_entry = second_catalog.resolve("primitive", "selector_fingerprint_shape")
    second_selector = selector_spec(second_catalog, kind="primitive", n_inputs=0)

    assert first_entry.evaluation_fingerprint != second_entry.evaluation_fingerprint
    assert first_entry.schema_fingerprint == second_entry.schema_fingerprint
    assert second_selector is first_selector

    with registration_scope(target):
        primitive(
            overwrite=True,
            meta={"amount": {"kind": "float", "description": "changed"}},
        )(evaluation_changed)
    third_catalog = target.snapshot().operations
    third_selector = selector_spec(third_catalog, kind="primitive", n_inputs=0)

    assert third_selector.fingerprint != second_selector.fingerprint


def test_preset_namespace_uses_an_explicit_immutable_catalog() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @preset(meta={})
        def catalog_bound_preset() -> Geometry:
            return Geometry.create(op="concat")

    with pytest.raises(AttributeError, match="未登録"):
        _ = P.catalog_bound_preset

    with bind_preset_catalog(target.snapshot().presets):
        assert P.catalog_bound_preset().op == "concat"
