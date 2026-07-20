from __future__ import annotations

from grafix.core.parameters.codec import (
    decode_param_store_result,
    dumps_param_store,
    encode_param_store,
    loads_param_store_result,
)
from grafix.core.parameters.favorites import (
    favorite_parameter_key_set,
    favorite_parameter_keys,
    is_parameter_favorite,
    set_parameters_favorite,
)
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.invariants import assert_invariants
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.prune_ops import prune_groups
from grafix.core.parameters.reconcile_ops import migrate_group
from grafix.core.parameters.store import ParamStore


def _merge_radius(store: ParamStore, site_id: str) -> ParameterKey:
    key = ParameterKey(op="circle", site_id=site_id, arg="radius")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=1.0,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=10.0),
                effective=1.0,
                source="code",
                explicit=False,
            )
        ],
    )
    return key


def test_favorite_ui_state_roundtrips_through_param_store_codec() -> None:
    store = ParamStore()
    key = _merge_radius(store, "site-a")

    assert set_parameters_favorite(store, (key,), favorite=True) == (key,)
    assert set_parameters_favorite(store, (key,), favorite=True) == ()

    loaded = loads_param_store_result(dumps_param_store(store)).store

    assert favorite_parameter_keys(loaded) == (key,)
    assert loaded.favorite_revision == 1
    assert is_parameter_favorite(loaded, key) is True
    assert_invariants(loaded)


def test_favorite_decode_drops_orphan_and_reports_it() -> None:
    payload = encode_param_store(ParamStore())
    payload["ui"]["favorite_parameters"] = [
        {"op": "circle", "site_id": "missing", "arg": "radius"}
    ]

    result = decode_param_store_result(payload)

    assert favorite_parameter_keys(result.store) == ()
    assert any(
        issue.section == "ui.favorite_parameters"
        and issue.reason == "matching state/meta is missing"
        for issue in result.issues
    )


def test_reconcile_migrates_favorite_to_new_site() -> None:
    store = ParamStore()
    old_key = _merge_radius(store, "old-site")
    new_key = _merge_radius(store, "new-site")
    set_parameters_favorite(store, (old_key,), favorite=True)

    revision_before = store.favorite_revision
    migrate_group(store, ("circle", "old-site"), ("circle", "new-site"))

    assert favorite_parameter_keys(store) == (new_key,)
    assert store.favorite_revision > revision_before
    assert_invariants(store)


def test_prune_removes_favorite_with_parameter_group() -> None:
    store = ParamStore()
    key = _merge_radius(store, "removed-site")
    set_parameters_favorite(store, (key,), favorite=True)

    revision_before = store.favorite_revision
    prune_groups(store, (("circle", "removed-site"),))

    assert favorite_parameter_keys(store) == ()
    assert store.favorite_revision > revision_before
    assert_invariants(store)


def test_favorite_immutable_view_is_cached_by_favorite_revision() -> None:
    store = ParamStore()
    key = _merge_radius(store, "site-a")
    table_revision = store.table_revision

    first = favorite_parameter_key_set(store)
    assert favorite_parameter_key_set(store) is first

    set_parameters_favorite(store, (key,), favorite=True)
    second = favorite_parameter_key_set(store)
    assert second == frozenset({key})
    assert second is favorite_parameter_key_set(store)
    assert second is not first
    assert store.favorite_revision == 1
    assert store.table_revision == table_revision

    set_parameters_favorite(store, (key,), favorite=True)
    assert store.favorite_revision == 1
    assert favorite_parameter_key_set(store) is second


def test_bulk_favorite_change_advances_revision_once() -> None:
    store = ParamStore()
    keys = tuple(_merge_radius(store, f"site-{index:03}") for index in range(100))
    revision_before = store.favorite_revision

    assert set_parameters_favorite(store, keys, favorite=True) == keys
    assert store.favorite_revision == revision_before + 1
    assert favorite_parameter_key_set(store) == frozenset(keys)

    assert set_parameters_favorite(store, keys, favorite=False) == keys
    assert store.favorite_revision == revision_before + 2
    assert favorite_parameter_key_set(store) == frozenset()


def test_favorite_change_inside_patch_transaction_stays_out_of_undo_history() -> None:
    store = ParamStore()
    key = _merge_radius(store, "site-a")
    history = ParamStoreHistory(store)

    with history.transaction(source="parameter_gui", patch=True):
        set_parameters_favorite(store, (key,), favorite=True)

    assert favorite_parameter_keys(store) == (key,)
    assert history.undo_depth == 0
