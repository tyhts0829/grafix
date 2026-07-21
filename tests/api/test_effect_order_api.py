from __future__ import annotations

from contextlib import nullcontext

import numpy as np
import pytest

from grafix import E, G
from grafix.api._operation_selector import effect_selector_op
from grafix.api.effects import EffectBuilder
from grafix.core.effect_registry import effect, effect_registry
from grafix.core.geometry import Geometry
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.effect_order_ops import set_effect_order
from grafix.core.parameters.effects import EffectStepKey
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple


def _normal_step_key(step: object) -> EffectStepKey:
    return str(getattr(step, "parameter_op")), str(getattr(step, "site_id"))


def _selector_step_key(step: object) -> EffectStepKey:
    return effect_selector_op(int(getattr(step, "n_inputs"))), str(
        getattr(step, "site_id")
    )


def _unary_recipe(geometry: Geometry) -> list[Geometry]:
    """外側から最初の非 unary node までの recipe を返す。"""

    result: list[Geometry] = []
    current = geometry
    while len(current.inputs) == 1:
        result.append(current)
        current = current.inputs[0]
    result.append(current)
    return result


def _observe(
    store: ParamStore,
    builder: EffectBuilder,
    source: Geometry,
) -> Geometry:
    with parameter_context(store):
        return builder(source)


def test_effect_order_override_changes_actual_geometry_dag_order() -> None:
    source = Geometry.create(op="effect-order-source")
    builder = (
        E.scale(scale=(2.0, 3.0, 1.0), key="ordered-scale")
        .rotate(rotation=(0.0, 0.0, 25.0), key="ordered-rotate")
        .translate(delta=(4.0, 5.0, 6.0), key="ordered-translate")
    )
    store = ParamStore()

    code_order_geometry = _observe(store, builder, source)
    scale_key, rotate_key, translate_key = (
        _normal_step_key(step) for step in builder.steps
    )
    assert [node.op for node in _unary_recipe(code_order_geometry)] == [
        "translate",
        "rotate",
        "scale",
        "effect-order-source",
    ]

    assert set_effect_order(
        store,
        chain_id=builder.chain_id,
        order=(translate_key, scale_key, rotate_key),
    )
    reordered_geometry = _observe(store, builder, source)
    recipe = _unary_recipe(reordered_geometry)

    assert [node.op for node in recipe] == [
        "rotate",
        "scale",
        "translate",
        "effect-order-source",
    ]
    assert dict(recipe[0].args)["rotation"] == (0.0, 0.0, 25.0)
    assert dict(recipe[1].args)["scale"] == (2.0, 3.0, 1.0)
    assert dict(recipe[2].args)["delta"] == (4.0, 5.0, 6.0)
    assert reordered_geometry.id != code_order_geometry.id


def test_selector_keeps_target_and_parameters_when_reordered() -> None:
    source = Geometry.create(op="effect-selector-order-source")
    builder = E.rotate(
        rotation=(0.0, 0.0, 15.0),
        key="fixed-effect",
    ).select(
        target="translate",
        params_by_target={
            "translate": {
                "delta": (7.0, 8.0, 9.0),
            }
        },
        key="selected-effect",
    )
    store = ParamStore()

    code_order_geometry = _observe(store, builder, source)
    fixed_key = _normal_step_key(builder.steps[0])
    selector_key = _selector_step_key(builder.steps[1])
    assert [node.op for node in _unary_recipe(code_order_geometry)] == [
        "translate",
        "rotate",
        "effect-selector-order-source",
    ]

    assert set_effect_order(
        store,
        chain_id=builder.chain_id,
        order=(selector_key, fixed_key),
    )
    reordered_geometry = _observe(store, builder, source)
    recipe = _unary_recipe(reordered_geometry)

    assert [node.op for node in recipe] == [
        "rotate",
        "translate",
        "effect-selector-order-source",
    ]
    assert dict(recipe[0].args)["rotation"] == (0.0, 0.0, 15.0)
    assert dict(recipe[1].args)["delta"] == (7.0, 8.0, 9.0)
    assert selector_key[0] == effect_selector_op(1)
    assert selector_key[0] != recipe[1].op


def test_repeated_operation_steps_keep_their_own_parameters_when_reordered() -> None:
    source = Geometry.create(op="repeated-effect-order-source")
    builder = E.rotate(
        rotation=(0.0, 0.0, 10.0),
        key="repeated-rotate-first",
    ).rotate(
        rotation=(0.0, 0.0, 70.0),
        key="repeated-rotate-second",
    )
    store = ParamStore()

    _observe(store, builder, source)
    first_key, second_key = (
        _normal_step_key(step) for step in builder.steps
    )
    assert set_effect_order(
        store,
        chain_id=builder.chain_id,
        order=(second_key, first_key),
    )

    recipe = _unary_recipe(_observe(store, builder, source))

    assert [node.op for node in recipe] == [
        "rotate",
        "rotate",
        "repeated-effect-order-source",
    ]
    assert dict(recipe[0].args)["rotation"] == (0.0, 0.0, 10.0)
    assert dict(recipe[1].args)["rotation"] == (0.0, 0.0, 70.0)


def test_selector_target_change_preserves_its_order_identity() -> None:
    source = Geometry.create(op="selector-target-change-source")
    first_builder = E.select(
        target="translate",
        params_by_target={
            "translate": {"delta": (2.0, 3.0, 4.0)},
        },
        key="stable-selector",
    ).rotate(
        rotation=(0.0, 0.0, 15.0),
        key="selector-companion",
    )
    store = ParamStore()
    _observe(store, first_builder, source)
    selector_key = _selector_step_key(first_builder.steps[0])
    rotate_key = _normal_step_key(first_builder.steps[1])
    assert set_effect_order(
        store,
        chain_id=first_builder.chain_id,
        order=(rotate_key, selector_key),
    )

    changed_target_builder = E.select(
        target="scale",
        params_by_target={
            "scale": {"scale": (2.0, 3.0, 1.0)},
        },
        key="stable-selector",
    ).rotate(
        rotation=(0.0, 0.0, 15.0),
        key="selector-companion",
    )
    assert changed_target_builder.chain_id == first_builder.chain_id

    recipe = _unary_recipe(_observe(store, changed_target_builder, source))

    assert store.effect_order_overrides()[first_builder.chain_id] == (
        rotate_key,
        selector_key,
    )
    assert [node.op for node in recipe] == [
        "scale",
        "rotate",
        "selector-target-change-source",
    ]
    assert dict(recipe[0].args)["scale"] == (2.0, 3.0, 1.0)


def test_effect_builder_uses_current_spec_arity_for_topology_and_dag() -> None:
    original_specs = dict(effect_registry.items())
    try:
        @effect
        def effect_builder_current_arity(first: GeomTuple) -> GeomTuple:
            return first

        builder = E.effect_builder_current_arity(key="current-arity")

        def replacement(
            first: GeomTuple,
            _second: GeomTuple,
        ) -> GeomTuple:
            return first

        replacement.__name__ = "effect_builder_current_arity"
        effect(overwrite=True, n_inputs=2)(replacement)

        first = G.line(length=2.0, key="current-arity-first")
        second = G.line(length=3.0, key="current-arity-second")
        store = ParamStore()
        with parameter_context(store):
            geometry = builder(first, second)

        assert geometry.inputs == (first, second)
        topology = store.effect_chain_topologies()[builder.chain_id]
        assert len(topology) == 1
        assert topology[0].n_inputs == 2
        np.testing.assert_array_equal(realize(geometry).coords, realize(first).coords)
    finally:
        effect_registry.replace_all(original_specs)


@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("selector", [False, True])
def test_deferred_effect_builder_revalidates_params_against_current_spec(
    recording: bool,
    selector: bool,
) -> None:
    original_specs = dict(effect_registry.items())
    try:
        @effect(meta={"x": ParamMeta(kind="int")})
        def effect_builder_current_meta(
            g: GeomTuple,
            *,
            x: int = 1,
        ) -> GeomTuple:
            _ = x
            return g

        builder = (
            E.select(
                target="effect_builder_current_meta",
                params_by_target={"effect_builder_current_meta": {"x": 2}},
                key="current-meta-selector",
            )
            if selector
            else E.effect_builder_current_meta(x=2, key="current-meta-normal")
        )

        def replacement(
            g: GeomTuple,
            *,
            x: bool = False,
        ) -> GeomTuple:
            _ = x
            return g


        replacement.__name__ = "effect_builder_current_meta"
        effect(
            overwrite=True,
            meta={"x": ParamMeta(kind="bool")},
        )(replacement)

        context = parameter_context(ParamStore()) if recording else nullcontext()
        with context, pytest.raises(TypeError, match="x"):
            builder(G.line(key="current-meta-source"))
    finally:
        effect_registry.replace_all(original_specs)
