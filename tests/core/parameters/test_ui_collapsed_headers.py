from __future__ import annotations

from grafix.core.parameters import ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.codec import (
    dumps_param_store,
    loads_param_store_result,
)
from grafix.core.parameters.effect_order_ops import merge_frame_effect_chains
from grafix.core.parameters.effects import EffectStepTopology
from grafix.core.parameters.frame_params import (
    FrameEffectChainRecord,
    FrameParamRecord,
)
from grafix.core.parameters.invariants import assert_invariants
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.prune_ops import prune_groups


def _polyhedron_records(site_id: str) -> list[FrameParamRecord]:
    meta = ParamMeta(kind="int", ui_min=0, ui_max=4)
    return [
        FrameParamRecord(
            key=ParameterKey(op="polyhedron", site_id=site_id, arg="type_index"),
            base=0,
            meta=meta,
            effective=0,
            source="code",
            explicit=False,
        )
    ]


def test_ui_collapsed_headers_are_preserved_on_json_roundtrip():
    store = ParamStore()
    store._collapsed_headers_ref().update(
        {
            "style:global",
            "primitive:circle:c:1",
            "effect_chain:chain:1",
        }
    )

    loaded = loads_param_store_result(dumps_param_store(store)).store
    assert loaded._collapsed_headers_ref() == {
        "style:global",
        "primitive:circle:c:1",
        "effect_chain:chain:1",
    }
    assert_invariants(loaded)


def test_reconcile_migrates_collapsed_header_state_for_primitive_groups():
    old_site_id = "old-site"
    new_site_id = "new-site"

    original = ParamStore()
    merge_frame_params(original, _polyhedron_records(old_site_id))
    original._collapsed_headers_ref().add(f"primitive:polyhedron:{old_site_id}")

    # 永続化ロード相当（loaded_groups を持つ状態にする）
    store = loads_param_store_result(dumps_param_store(original)).store

    # 新 site_id のグループを観測（=site_id がズレた状態を再現）
    merge_frame_params(store, _polyhedron_records(new_site_id))

    collapsed = store._collapsed_headers_ref()
    assert f"primitive:polyhedron:{old_site_id}" not in collapsed
    assert f"primitive:polyhedron:{new_site_id}" in collapsed
    assert_invariants(store)


def test_prune_removes_collapsed_header_state_for_removed_groups_and_unused_chains():
    store = ParamStore()
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)

    merge_frame_params(store, _polyhedron_records("p0"))
    store._collapsed_headers_ref().add("primitive:polyhedron:p0")

    merge_frame_effect_chains(
        store,
        [
            FrameEffectChainRecord(
                chain_id="c1",
                steps=(EffectStepTopology("scale", "s0", 1, 0),),
            )
        ],
        observation_complete=False,
    )
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=ParameterKey(op="scale", site_id="s0", arg="x"),
                base=0.0,
                meta=meta,
                effective=0.0,
                source="code",
                explicit=True,
            )
        ],
    )
    store._collapsed_headers_ref().add("effect_chain:c1")

    prune_groups(store, [("polyhedron", "p0"), ("scale", "s0")])

    collapsed = store._collapsed_headers_ref()
    assert "primitive:polyhedron:p0" not in collapsed
    assert "effect_chain:c1" not in collapsed
    assert_invariants(store)
