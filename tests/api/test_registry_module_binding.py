from __future__ import annotations

from dataclasses import replace

import pytest

import grafix.core.effect_registry as effect_registry_module
import grafix.core.preset_registry as preset_registry_module
import grafix.core.primitive_registry as primitive_registry_module
from grafix import E, G, P
from grafix.api import preset
from grafix.core.geometry import Geometry
from grafix.core.op_registry import OpRegistry
from grafix.core.parameters.meta import ParamMeta
from grafix.core.preset_registry import PresetRegistry


def test_primitive_factory_reads_current_core_registry_when_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = OpRegistry(kind="primitive")
    monkeypatch.setattr(
        primitive_registry_module,
        "primitive_registry",
        initial,
    )

    @primitive_registry_module.primitive(meta={"amount": {"kind": "float"}})
    def module_bound_primitive(*, amount: float = 1.0) -> tuple[object, object]:
        raise AssertionError("Geometry recipe construction must not evaluate the primitive")

    factory = G.module_bound_primitive
    original_spec = initial["module_bound_primitive"]
    replacement = OpRegistry(kind="primitive")
    replacement.register(
        "module_bound_primitive",
        replace(
            original_spec,
            defaults={"activate": True, "amount": 2.0},
        ),
    )
    monkeypatch.setattr(
        primitive_registry_module,
        "primitive_registry",
        replacement,
    )

    geometry = factory()

    assert dict(geometry.args)["amount"] == 2.0


def test_effect_factory_and_builder_do_not_capture_previous_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = OpRegistry(kind="effect")
    monkeypatch.setattr(
        effect_registry_module,
        "effect_registry",
        initial,
    )

    @effect_registry_module.effect(meta={"amount": {"kind": "float"}})
    def module_bound_effect(
        geometry: tuple[object, object],
        *,
        amount: float = 1.0,
    ) -> tuple[object, object]:
        _ = amount
        return geometry

    factory = E.module_bound_effect
    builder = E.module_bound_effect()
    original_spec = initial["module_bound_effect"]
    replacement = OpRegistry(kind="effect")
    replacement.register(
        "module_bound_effect",
        replace(
            original_spec,
            meta={
                **original_spec.meta,
                "new_arg": ParamMeta(kind="float"),
            },
            defaults={
                **original_spec.defaults,
                "amount": 2.0,
                "new_arg": 4.0,
            },
            param_order=(*original_spec.param_order, "new_arg"),
            accepted_args=(*original_spec.accepted_args, "new_arg"),
        ),
    )
    monkeypatch.setattr(
        effect_registry_module,
        "effect_registry",
        replacement,
    )

    factory(new_arg=3.0)
    geometry = builder(Geometry.create(op="concat"))

    assert dict(geometry.args)["amount"] == 2.0


def test_deferred_preset_decorator_and_p_lookup_use_current_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = PresetRegistry()
    monkeypatch.setattr(
        preset_registry_module,
        "preset_registry",
        initial,
    )
    decorator = preset(meta={})

    replacement = PresetRegistry()
    monkeypatch.setattr(
        preset_registry_module,
        "preset_registry",
        replacement,
    )

    def module_bound_preset() -> Geometry:
        return Geometry.create(op="concat")

    wrapped = decorator(module_bound_preset)

    assert initial.revision == 0
    assert replacement.revision == 1
    assert replacement["preset.module_bound_preset"].func is wrapped
    assert P.module_bound_preset is wrapped
