from __future__ import annotations

import pytest

from grafix.api import E, G, L, P
from grafix.core.parameters import ParamStore
from grafix.core.parameters.context import parameter_context
from grafix.core.parameters.snapshot_ops import store_snapshot


def test_primitive_and_effect_keys_are_not_geometry_arguments() -> None:
    store = ParamStore()
    with parameter_context(store):
        source = G.line(key="source")
        result = E.scale(key="scaled", scale=(2.0, 2.0, 1.0))(source)

    assert "key" not in dict(source.args)
    assert "key" not in dict(result.args)
    site_ids = {(key.op, key.site_id) for key in store_snapshot(store)}
    assert any(op == "line" and site_id.endswith("|source") for op, site_id in site_ids)
    assert any(op == "scale" and site_id.endswith("|scaled") for op, site_id in site_ids)


def test_explicit_keys_separate_loop_instances() -> None:
    store = ParamStore()
    with parameter_context(store):
        for index in range(3):
            G.line(key=index)

    line_sites = {key.site_id for key in store_snapshot(store) if key.op == "line"}
    assert {site.rsplit("|", 1)[-1] for site in line_sites} == {"0", "1", "2"}


def test_layer_explicit_key_sets_stable_site_id() -> None:
    layer = L.layer(G.line(), key="outline")

    assert layer.site_id.endswith("|outline")


def test_instance_key_separates_loop_and_comprehension_instances() -> None:
    loop_store = ParamStore()
    with parameter_context(loop_store):
        for index in range(3):
            G.line(key="petal", instance_key=index)

    comprehension_store = ParamStore()
    with parameter_context(comprehension_store):
        [G.line(key="petal", instance_key=index) for index in range(3)]

    for store in (loop_store, comprehension_store):
        sites = {key.site_id for key in store_snapshot(store) if key.op == "line"}
        assert {site.rsplit("|instance:", 1)[-1] for site in sites} == {
            "0",
            "1",
            "2",
        }
        assert all("|petal|instance:" in site for site in sites)


def test_shared_true_intentionally_reuses_semantic_site_in_loop() -> None:
    store = ParamStore()
    with parameter_context(store):
        for _index in range(3):
            G.line(key="petals", shared=True)

    sites = {key.site_id for key in store_snapshot(store) if key.op == "line"}
    assert len(sites) == 1
    assert next(iter(sites)).endswith("|petals")


def test_instance_key_and_shared_true_are_mutually_exclusive_across_namespaces() -> None:
    with pytest.raises(ValueError, match="instance_key"):
        G.line(instance_key=0, shared=True)
    with pytest.raises(ValueError, match="instance_key"):
        E.scale(instance_key=0, shared=True)
    with pytest.raises(ValueError, match="instance_key"):
        L.layer(G.line(), instance_key=0, shared=True)
    with pytest.raises(ValueError, match="instance_key"):
        P(instance_key=0, shared=True)
