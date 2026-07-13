from __future__ import annotations

from grafix.api import E, G, L
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
    layer = L.layer(G.line(), key="outline")[0]

    assert layer.site_id.endswith("|outline")
