from __future__ import annotations

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.effects import EffectStepTopology
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.labels_ops import set_label
from grafix.core.parameters.memento import (
    capture_param_store_memento,
    restore_param_store_memento,
)
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.style import STYLE_GLOBAL_THICKNESS, style_key
from grafix.core.parameters.style_ops import ensure_style_entries
from grafix.core.parameters.ui_ops import update_state_from_ui


EFFECT_CODE_ORDER = (("scale", "scale-site"), ("rotate", "rotate-site"))
EFFECT_UI_ORDER = tuple(reversed(EFFECT_CODE_ORDER))


def _record_effect_chain(store: ParamStore) -> None:
    changed = store._effects_ref().record_chain(
        chain_id="chain-order",
        steps=(
            EffectStepTopology("scale", "scale-site", 1, 0),
            EffectStepTopology("rotate", "rotate-site", 1, 1),
        ),
    )
    if changed:
        store._touch()


def _populated_store() -> tuple[ParamStore, ParameterKey]:
    store = ParamStore()
    key = ParameterKey(op="wobble", site_id="site-1", arg="amount")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.25,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                explicit=True,
                chain_id="chain-1",
                step_index=2,
            )
        ],
    )
    update_state_from_ui(
        store,
        key,
        0.75,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        override=True,
        cc_key=17,
    )
    set_label(store, op=key.op, site_id=key.site_id, label="primary wobble")
    store._collapsed_headers_ref().add("effect_chain:chain-1")
    store._touch()
    return store, key


def test_memento_restores_gui_state_but_keeps_code_owned_structure_and_runtime() -> None:
    store, key = _populated_store()
    runtime = store._runtime_ref()
    runtime.loaded_groups.add(("runtime", "before"))
    memento = capture_param_store_memento(store)

    # GUI-owned 状態と code-owned 状態を両方変更する。
    state = store._get_state_ref(key)
    assert state is not None
    state.ui_value = 0.1
    state.override = False
    state.cc_key = None
    store._set_meta(
        key,
        ParamMeta(
            kind="float",
            ui_min=-10.0,
            ui_max=10.0,
            choices=("current-code-choice",),
        ),
    )
    store._set_explicit(key, False)
    store._labels_ref().set(key.op, key.site_id, "current code label")
    store._collapsed_headers_ref().clear()
    store._touch()

    # runtime は capture 後に進んだ内容も維持する。
    runtime.loaded_groups.add(("runtime", "after"))
    runtime_identity = id(runtime)
    revision_before_restore = store.revision
    assert restore_param_store_memento(store, memento) is True

    restored = store.get_state(key)
    assert restored is not None
    assert restored.ui_value == 0.75
    assert restored.override is True
    assert restored.cc_key == 17
    # range は GUI-owned なので戻るが、kind/choices は現在の code を保つ。
    assert store.get_meta(key) == ParamMeta(
        kind="float",
        ui_min=0.0,
        ui_max=1.0,
        choices=("current-code-choice",),
    )
    assert store._get_explicit_ref(key) is False
    assert store.get_label(key.op, key.site_id) == "current code label"
    assert store.get_ordinal(key.op, key.site_id) == 1
    assert store.get_effect_step(key.op, key.site_id) == ("chain-1", 2)
    assert store.chain_ordinals() == {"chain-1": 1}
    assert store._collapsed_headers_ref() == {"effect_chain:chain-1"}
    assert id(store._runtime_ref()) == runtime_identity
    assert store._runtime_ref().loaded_groups == {
        ("runtime", "before"),
        ("runtime", "after"),
    }
    assert store.revision > revision_before_restore


def test_memento_merge_preserves_a_parameter_discovered_after_capture() -> None:
    store, key = _populated_store()
    memento = capture_param_store_memento(store)

    new_key = ParameterKey(op="wobble", site_id="site-2", arg="frequency")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=new_key,
                base=2.0,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=8.0),
                explicit=False,
            )
        ],
    )
    update_state_from_ui(
        store,
        new_key,
        4.5,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=8.0),
        override=True,
        cc_key=23,
    )
    update_state_from_ui(
        store,
        key,
        0.1,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    )

    assert restore_param_store_memento(store, memento) is True
    assert store.get_state(key).ui_value == 0.75  # type: ignore[union-attr]
    discovered = store.get_state(new_key)
    assert discovered is not None
    assert discovered.ui_value == 4.5
    assert discovered.override is True
    assert discovered.cc_key == 23
    assert store.get_meta(new_key) == ParamMeta(kind="float", ui_min=0.0, ui_max=8.0)


def test_memento_skips_a_key_whose_current_code_kind_changed() -> None:
    store, key = _populated_store()
    memento = capture_param_store_memento(store)
    state = store._get_state_ref(key)
    assert state is not None
    state.ui_value = 7
    state.override = False
    state.cc_key = None
    store._set_meta(key, ParamMeta(kind="int", ui_min=0, ui_max=10))

    revision_before = store.revision
    assert restore_param_store_memento(store, memento) is False
    assert store.revision == revision_before
    assert store.get_state(key).ui_value == 7  # type: ignore[union-attr]
    assert store.get_meta(key) == ParamMeta(kind="int", ui_min=0, ui_max=10)


def test_memento_is_deep_and_can_be_restored_more_than_once() -> None:
    store, key = _populated_store()
    state = store._get_state_ref(key)
    assert state is not None
    state.ui_value = {"nested": [1, 2]}
    store._touch()
    memento = capture_param_store_memento(store)

    state.ui_value["nested"].append(3)
    assert restore_param_store_memento(store, memento) is True
    restored = store._get_state_ref(key)
    assert restored is not None
    assert restored.ui_value == {"nested": [1, 2]}

    restored.ui_value["nested"].append(99)
    assert restore_param_store_memento(store, memento) is True
    restored_again = store._get_state_ref(key)
    assert restored_again is not None
    assert restored_again.ui_value == {"nested": [1, 2]}


def test_restore_invalidates_cached_snapshot() -> None:
    store, key = _populated_store()
    memento = capture_param_store_memento(store)
    before = store_snapshot(store)

    update_state_from_ui(
        store,
        key,
        0.2,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    )
    assert restore_param_store_memento(store, memento) is True
    after = store_snapshot(store)

    assert after is not before
    assert after[key][1].ui_value == 0.75


def test_restore_style_value_advances_style_without_rebuilding_table() -> None:
    store = ParamStore()
    ensure_style_entries(
        store,
        background_color_rgb01=(1.0, 1.0, 1.0),
        global_thickness=0.01,
        global_line_color_rgb01=(0.0, 0.0, 0.0),
    )
    key = style_key(STYLE_GLOBAL_THICKNESS)
    meta = store.get_meta(key)
    assert meta is not None
    memento = capture_param_store_memento(store)
    assert update_state_from_ui(store, key, 0.005, meta=meta)[0]
    table_revision = store.table_revision
    style_revision = store.style_revision
    value_revision = store.value_revision

    assert restore_param_store_memento(store, memento) is True
    assert store.table_revision == table_revision
    assert store.style_revision == style_revision + 1
    assert store.value_revision == value_revision + 1


def test_restoring_the_same_memento_is_a_revision_noop() -> None:
    store, _key = _populated_store()
    memento = capture_param_store_memento(store)
    revision_before = store.revision

    assert restore_param_store_memento(store, memento) is False
    assert store.revision == revision_before


def test_memento_restores_gui_effect_order_without_replacing_code_topology() -> None:
    store = ParamStore()
    _record_effect_chain(store)
    assert store._effects_ref().set_order_override(
        "chain-order",
        EFFECT_UI_ORDER,
    )
    store._touch()
    memento = capture_param_store_memento(store)
    topology_before = store._effects_ref().topology("chain-order")

    assert store._effects_ref().reset_order("chain-order")
    store._touch()

    assert restore_param_store_memento(store, memento) is True
    assert store._effects_ref().effective_order("chain-order") == EFFECT_UI_ORDER
    assert store._effects_ref().topology("chain-order") == topology_before


def test_memento_can_restore_code_order_and_skips_incompatible_topology() -> None:
    store = ParamStore()
    _record_effect_chain(store)
    code_order_memento = capture_param_store_memento(store)
    assert store._effects_ref().set_order_override(
        "chain-order",
        EFFECT_UI_ORDER,
    )
    store._touch()

    assert restore_param_store_memento(store, code_order_memento) is True
    assert store._effects_ref().order_overrides() == {}
    assert store._effects_ref().set_order_override(
        "chain-order",
        EFFECT_UI_ORDER,
    )
    store._touch()
    reordered_memento = capture_param_store_memento(store)
    assert store._effects_ref().record_chain(
        chain_id="chain-order",
        steps=(
            EffectStepTopology("scale", "scale-site", 1, 0),
            EffectStepTopology("rotate", "rotate-site", 1, 1),
            EffectStepTopology("wobble", "wobble-site", 1, 2),
        ),
    )
    store._touch()
    revision_before = store.revision

    assert restore_param_store_memento(store, reordered_memento) is False
    assert store.revision == revision_before
    assert store._effects_ref().order_overrides() == {}


def test_memento_does_not_restore_order_after_effect_arity_change() -> None:
    store = ParamStore()
    initial_topology = (
        EffectStepTopology("first", "first-site", 1, 0),
        EffectStepTopology("second", "second-site", 1, 1),
        EffectStepTopology("third", "third-site", 1, 2),
    )
    assert store._effects_ref().record_chain(
        chain_id="arity-chain",
        steps=initial_topology,
    )
    assert store._effects_ref().set_order_override(
        "arity-chain",
        (
            ("first", "first-site"),
            ("third", "third-site"),
            ("second", "second-site"),
        ),
    )
    store._touch()
    memento = capture_param_store_memento(store)

    assert store._effects_ref().record_chain(
        chain_id="arity-chain",
        steps=(
            EffectStepTopology("first", "first-site", 2, 0),
            EffectStepTopology("second", "second-site", 1, 1),
            EffectStepTopology("third", "third-site", 1, 2),
        ),
    )
    store._touch()
    revision = store.revision

    assert restore_param_store_memento(store, memento) is False
    assert store.revision == revision
    assert store.effect_order_overrides() == {}
