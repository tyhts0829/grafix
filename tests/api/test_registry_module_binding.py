"""公開 API が immutable catalog binding を読む契約を検証する。"""

from __future__ import annotations

from dataclasses import replace

from grafix import E, G, P
from grafix.api import preset
from grafix.core.authoring_definitions import RegistrationTarget, registration_scope
from grafix.core.geometry import Geometry
from grafix.core.operation_catalog import bind_operation_catalog
from grafix.core.preset_catalog import bind_preset_catalog
from grafix.core.operation_authoring import primitive
from grafix.core.operation_authoring import effect


def test_primitive_factory_captures_the_bound_catalog_entry() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @primitive(meta={"amount": {"kind": "float"}})
        def module_bound_primitive(
            *, amount: float = 1.0
        ) -> tuple[object, object]:
            raise AssertionError("Geometry recipe construction must not evaluate")

    catalog_a = target.snapshot().operations
    declaration = catalog_a.resolve("primitive", "module_bound_primitive").declaration
    target.register(
        replace(
            declaration,
            schema=replace(
                declaration.schema,
                defaults={"activate": True, "amount": 2.0},
            ),
        ),
        overwrite=True,
    )
    catalog_b = target.snapshot().operations

    with bind_operation_catalog(catalog_a):
        factory_a = G.module_bound_primitive
    with bind_operation_catalog(catalog_b):
        factory_b = G.module_bound_primitive

    assert dict(factory_a().args)["amount"] == 1.0
    assert dict(factory_b().args)["amount"] == 2.0


def test_effect_factory_and_builder_capture_their_exact_entry() -> None:
    target = RegistrationTarget()
    with registration_scope(target):

        @effect(meta={"amount": {"kind": "float"}})
        def module_bound_effect(
            geometry: tuple[object, object],
            *,
            amount: float = 1.0,
        ) -> tuple[object, object]:
            _ = amount
            return geometry

    catalog_a = target.snapshot().operations
    declaration = catalog_a.resolve("effect", "module_bound_effect").declaration
    with bind_operation_catalog(catalog_a):
        builder_a = E.module_bound_effect()

    target.register(
        replace(
            declaration,
            schema=replace(
                declaration.schema,
                defaults={"activate": True, "amount": 2.0},
            ),
        ),
        overwrite=True,
    )
    catalog_b = target.snapshot().operations

    with bind_operation_catalog(catalog_b):
        builder_b = E.module_bound_effect()
        geometry_a = builder_a(Geometry.create(op="concat"))
        geometry_b = builder_b(Geometry.create(op="concat"))

    assert dict(geometry_a.args)["amount"] == 1.0
    assert dict(geometry_b.args)["amount"] == 2.0


def test_deferred_preset_decorator_uses_target_active_at_decoration() -> None:
    decorator = preset(meta={})
    target = RegistrationTarget()

    def module_bound_preset() -> Geometry:
        return Geometry.create(op="concat")

    with registration_scope(target):
        wrapped = decorator(module_bound_preset)

    with bind_preset_catalog(target.snapshot().presets):
        assert P.module_bound_preset is wrapped
