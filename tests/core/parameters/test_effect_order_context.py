from __future__ import annotations

import pytest

from grafix import E
from grafix.core.operation_authoring import effect
from grafix.core.geometry import Geometry
from grafix.core.parameters.context import (
    current_effect_order_snapshot,
    current_frame_params,
    parameter_context,
    parameter_context_from_snapshot,
)
from grafix.core.parameters.effect_order_ops import (
    begin_effect_chain_generation,
    reset_effect_order,
    set_effect_order,
    store_effect_order_snapshot,
)
from grafix.core.parameters.effects import EffectStepKey
from grafix.core.parameters.store import ParamStore
from grafix.core.realized_geometry import GeomTuple


@effect
def effect_order_context_first(g: GeomTuple) -> GeomTuple:
    return g


@effect
def effect_order_context_second(g: GeomTuple) -> GeomTuple:
    return g


def _keys_for_chain(
    store: ParamStore,
    chain_id: str,
) -> tuple[EffectStepKey, ...]:
    return tuple(
        (step.op, step.site_id)
        for step in store.effect_chain_topologies()[chain_id]
    )


def test_parameter_context_freezes_effect_order_snapshot_for_whole_frame() -> None:
    source = Geometry.create(op="effect-order-context-source")
    builder = E.scale(key="context-scale").rotate(key="context-rotate")
    store = ParamStore()
    with parameter_context(store):
        builder(source)
    first, second = _keys_for_chain(store, builder.chain_id)
    assert set_effect_order(
        store,
        chain_id=builder.chain_id,
        order=(second, first),
    )
    expected = store_effect_order_snapshot(store)

    assert current_effect_order_snapshot() == {}
    with parameter_context(store):
        assert current_effect_order_snapshot() == expected
        assert reset_effect_order(store, chain_id=builder.chain_id)
        assert current_effect_order_snapshot() == expected
    assert current_effect_order_snapshot() == {}
    assert store.effect_steps()[first] == (builder.chain_id, 0)
    assert store.effect_steps()[second] == (builder.chain_id, 1)


def test_parameter_context_from_snapshot_sets_and_restores_effect_order() -> None:
    outer = {
        "outer-chain": (
            ("second", "outer-second"),
            ("first", "outer-first"),
        )
    }
    inner = {
        "inner-chain": (
            ("b", "inner-b"),
            ("a", "inner-a"),
        )
    }

    with parameter_context_from_snapshot(
        {},
        effect_order_snapshot=outer,
    ):
        assert current_effect_order_snapshot() == outer
        with parameter_context_from_snapshot(
            {},
            effect_order_snapshot=inner,
        ):
            assert current_effect_order_snapshot() == inner
        assert current_effect_order_snapshot() == outer
    assert current_effect_order_snapshot() == {}


def test_effect_topology_is_recorded_without_parameter_metadata() -> None:
    source = Geometry.create(op="effect-order-buffer-source")
    builder = E.effect_order_context_first(
        key="buffer-first"
    ).effect_order_context_second(key="buffer-second")

    with parameter_context_from_snapshot({}) as buffer:
        builder(source)

    assert buffer is not None
    assert len(buffer.effect_chains) == 1
    record = buffer.effect_chains[0]
    assert record.chain_id == builder.chain_id
    assert [(step.op, step.n_inputs, step.code_index) for step in record.steps] == [
        ("effect_order_context_first", 1, 0),
        ("effect_order_context_second", 1, 1),
    ]
    assert buffer.records == []


def test_failed_parameter_context_does_not_commit_effect_topology() -> None:
    source = Geometry.create(op="effect-order-failed-source")
    builder = E.scale(key="failed-scale").rotate(key="failed-rotate")
    store = ParamStore()

    with pytest.raises(RuntimeError, match="draw failed"):
        with parameter_context(store):
            builder(source)
            frame_params = current_frame_params()
            assert frame_params is not None
            assert frame_params.effect_chains
            raise RuntimeError("draw failed")

    assert builder.chain_id not in store.effect_chain_topologies()


def test_failed_complete_observation_does_not_finish_reload_generation() -> None:
    source = Geometry.create(op="effect-order-generation-source")
    old_builder = E.effect_order_context_first(
        key="generation-old-first"
    ).effect_order_context_second(key="generation-old-second")
    store = ParamStore()
    with parameter_context(store):
        old_builder(source)
    assert old_builder.chain_id in store.effect_chain_topologies()

    begin_effect_chain_generation(store)
    with pytest.raises(RuntimeError, match="new source failed"):
        with parameter_context(store):
            frame_params = current_frame_params()
            assert frame_params is not None
            frame_params.complete_effect_chain_observation()
            raise RuntimeError("new source failed")

    assert old_builder.chain_id in store.effect_chain_topologies()

    with parameter_context(store):
        frame_params = current_frame_params()
        assert frame_params is not None
        frame_params.complete_effect_chain_observation()

    assert old_builder.chain_id not in store.effect_chain_topologies()
