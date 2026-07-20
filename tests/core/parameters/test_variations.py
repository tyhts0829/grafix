from __future__ import annotations

from pathlib import Path

import pytest

from grafix.core.parameters.autosave import ParamStoreAutosave
from grafix.core.parameters.codec import dumps_param_store, loads_param_store
from grafix.core.parameters.effects import EffectStepTopology
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.history import ParamStoreHistory
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.parameters.variations import (
    create_variation,
    delete_variation,
    diff_variation,
    duplicate_variation,
    is_parameter_locked,
    list_variations,
    locked_parameter_keys,
    morph_variations,
    randomize_parameters,
    rename_variation,
    restore_variation,
    set_parameters_locked,
)


FLOAT_META = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
EFFECT_CODE_ORDER = (("scale", "scale-site"), ("rotate", "rotate-site"))
EFFECT_UI_ORDER = tuple(reversed(EFFECT_CODE_ORDER))


def _add_reordered_effect_chain(store: ParamStore) -> None:
    assert store._effects_ref().record_chain(
        chain_id="chain-order",
        steps=(
            EffectStepTopology("scale", "scale-site", 1, 0),
            EffectStepTopology("rotate", "rotate-site", 1, 1),
        ),
    )
    assert store._effects_ref().set_order_override(
        "chain-order",
        EFFECT_UI_ORDER,
    )
    store._touch()


def _add_parameter(
    store: ParamStore,
    *,
    site_id: str = "site-1",
    arg: str = "amount",
    value: float = 0.25,
) -> ParameterKey:
    key = ParameterKey(op="wave", site_id=site_id, arg=arg)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=value,
                meta=FLOAT_META,
                explicit=False,
            )
        ],
    )
    return key


def _set_value(store: ParamStore, key: ParameterKey, value: float) -> None:
    ok, error = update_state_from_ui(store, key, value, meta=FLOAT_META)
    assert ok is True and error is None


def _value(store: ParamStore, key: ParameterKey) -> float:
    state = store.get_state(key)
    assert state is not None
    return float(state.ui_value)


def _add_typed_parameter(
    store: ParamStore,
    *,
    arg: str,
    value: object,
    meta: ParamMeta,
) -> ParameterKey:
    key = ParameterKey(op="explore", site_id="site", arg=arg)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=value,
                meta=meta,
                explicit=False,
            )
        ],
    )
    return key


def _set_typed_value(
    store: ParamStore,
    key: ParameterKey,
    value: object,
    *,
    override: bool = True,
    cc_key: int | tuple[int | None, int | None, int | None] | None = None,
) -> None:
    meta = store.get_meta(key)
    assert meta is not None
    ok, error = update_state_from_ui(
        store,
        key,
        value,
        meta=meta,
        override=override,
        cc_key=cc_key,
    )
    assert ok is True and error in {None, "choice_coerced"}


def _typed_value(store: ParamStore, key: ParameterKey) -> object:
    state = store.get_state(key)
    assert state is not None
    return state.ui_value


def test_create_list_rename_and_delete_advance_revision_on_real_changes() -> None:
    store = ParamStore()
    _add_parameter(store)
    revision = store.revision

    first = create_variation(
        store,
        "  quiet  ",
        note="low amplitude",
        seed=17,
        t=1.5,
        thumbnail_path=Path("thumbs/quiet.png"),
        created_at=100.0,
    )

    assert first.name == "quiet"
    assert first.created_at == 100.0
    assert first.note == "low amplitude"
    assert first.seed == 17
    assert first.t == 1.5
    assert first.thumbnail_path == "thumbs/quiet.png"
    assert list_variations(store) == (first,)
    assert store.revision == revision + 1

    with pytest.raises(ValueError, match="already exists"):
        create_variation(store, "quiet")
    assert store.revision == revision + 1

    assert rename_variation(store, "quiet", "still").name == "still"
    assert [variation.name for variation in list_variations(store)] == ["still"]
    assert store.revision == revision + 2

    assert rename_variation(store, "still", "still").name == "still"
    assert store.revision == revision + 2
    assert delete_variation(store, "unknown") is False
    assert store.revision == revision + 2
    assert delete_variation(store, "still") is True
    assert list_variations(store) == ()
    assert store.revision == revision + 3


@pytest.mark.parametrize(
    "invalid_name",
    (
        "line\nbreak",
        "tab\tname",
        "control\x00name",
        "line\u2028separator",
        "x" * 81,
    ),
)
def test_variation_names_reject_line_breaks_controls_and_overlong_text(
    invalid_name: str,
) -> None:
    store = ParamStore()
    _add_parameter(store)

    with pytest.raises(ValueError, match="variation name"):
        create_variation(store, invalid_name)

    create_variation(store, "valid")
    with pytest.raises(ValueError, match="variation name"):
        rename_variation(store, "valid", invalid_name)
    with pytest.raises(ValueError, match="variation name"):
        duplicate_variation(store, "valid", invalid_name)


def test_diff_reports_changed_and_new_parameters() -> None:
    store = ParamStore()
    original_key = _add_parameter(store)
    create_variation(store, "base", created_at=100.0)

    _set_value(store, original_key, 0.8)
    new_key = _add_parameter(store, site_id="site-2", arg="frequency", value=0.4)

    differences = diff_variation(store, "base")

    assert [(difference.key, difference.fields) for difference in differences] == [
        (original_key, ("ui_value",)),
        (new_key, ("added",)),
    ]


def test_restore_is_one_undoable_merge_and_preserves_new_parameters() -> None:
    store = ParamStore()
    original_key = _add_parameter(store)
    create_variation(store, "base", created_at=100.0)

    _set_value(store, original_key, 0.8)
    new_key = _add_parameter(store, site_id="site-2", arg="frequency", value=0.4)
    _set_value(store, new_key, 0.9)
    history = ParamStoreHistory(store)

    assert restore_variation(store, "base", history=history) is True
    assert _value(store, original_key) == pytest.approx(0.25)
    assert _value(store, new_key) == pytest.approx(0.9)
    assert history.undo_depth == 1

    assert history.undo() is True
    assert _value(store, original_key) == pytest.approx(0.8)
    assert _value(store, new_key) == pytest.approx(0.9)


def test_codec_roundtrip_keeps_variation_metadata_and_snapshot() -> None:
    store = ParamStore()
    key = _add_parameter(store)
    create_variation(
        store,
        "saved",
        note="candidate",
        seed=29,
        t=2.25,
        thumbnail_path="thumb.png",
        created_at=123.5,
    )
    _set_value(store, key, 0.95)

    loaded = loads_param_store(dumps_param_store(store))

    variations = list_variations(loaded)
    assert len(variations) == 1
    assert variations[0].name == "saved"
    assert variations[0].created_at == 123.5
    assert variations[0].note == "candidate"
    assert variations[0].seed == 29
    assert variations[0].t == 2.25
    assert variations[0].thumbnail_path == "thumb.png"
    assert restore_variation(loaded, "saved") is True
    assert _value(loaded, key) == pytest.approx(0.25)


def test_variation_codec_and_restore_include_effect_order_but_diff_does_not() -> None:
    store = ParamStore()
    _add_parameter(store)
    _add_reordered_effect_chain(store)
    create_variation(store, "reordered", created_at=100.0)

    assert store._effects_ref().reset_order("chain-order")
    store._touch()
    assert diff_variation(store, "reordered") == ()

    loaded = loads_param_store(dumps_param_store(store))
    assert loaded._effects_ref().effective_order("chain-order") == EFFECT_CODE_ORDER
    assert restore_variation(loaded, "reordered") is True
    assert loaded._effects_ref().effective_order("chain-order") == EFFECT_UI_ORDER
    assert diff_variation(loaded, "reordered") == ()


def test_loaded_variation_does_not_restore_order_after_effect_arity_change() -> None:
    store = ParamStore()
    topology = (
        EffectStepTopology("first", "first-site", 1, 0),
        EffectStepTopology("second", "second-site", 1, 1),
        EffectStepTopology("third", "third-site", 1, 2),
    )
    assert store._effects_ref().record_chain(
        chain_id="arity-chain",
        steps=topology,
    )
    assert store._effects_ref().set_order_override(
        "arity-chain",
        (
            ("first", "first-site"),
            ("third", "third-site"),
            ("second", "second-site"),
        ),
    )
    create_variation(store, "old-arity", created_at=100.0)
    loaded = loads_param_store(dumps_param_store(store))

    assert loaded._effects_ref().record_chain(
        chain_id="arity-chain",
        steps=(
            EffectStepTopology("first", "first-site", 2, 0),
            EffectStepTopology("second", "second-site", 1, 1),
            EffectStepTopology("third", "third-site", 1, 2),
        ),
    )
    loaded._touch()
    revision = loaded.revision

    assert restore_variation(loaded, "old-arity") is False
    assert loaded.revision == revision
    assert loaded.effect_order_overrides() == {}


def test_variation_change_is_seen_by_autosave(tmp_path: Path) -> None:
    store = ParamStore()
    _add_parameter(store)
    saves: list[tuple[int, Path]] = []
    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=0.0,
        clock=lambda: 10.0,
        save=lambda saved_store, path: saves.append((saved_store.revision, path)),
    )

    create_variation(store, "candidate", created_at=100.0)

    assert autosave.dirty is True
    assert autosave.tick(now=10.0) is True
    assert saves == [(store.revision, tmp_path / "store.json")]
    assert autosave.dirty is False


def test_parameter_lock_is_persistent_store_ui_state() -> None:
    store = ParamStore()
    first = _add_parameter(store, arg="first")
    second = _add_parameter(store, arg="second")
    revision = store.revision

    assert set_parameters_locked(store, [second, first, first], locked=True) == (
        first,
        second,
    )
    assert store.revision == revision + 1
    assert locked_parameter_keys(store) == (first, second)
    assert is_parameter_locked(store, first) is True

    # 同じ lock は revision/autosave を汚さない。
    assert set_parameters_locked(store, [first], locked=True) == ()
    assert store.revision == revision + 1

    loaded = loads_param_store(dumps_param_store(store))
    assert locked_parameter_keys(loaded) == (first, second)

    loaded_revision = loaded.revision
    assert set_parameters_locked(loaded, [first], locked=False) == (first,)
    assert locked_parameter_keys(loaded) == (second,)
    assert loaded.revision == loaded_revision + 1


def test_randomize_is_seeded_scoped_locked_and_one_history_transaction() -> None:
    store = ParamStore()
    float_key = _add_typed_parameter(
        store,
        arg="float",
        value=0.25,
        meta=ParamMeta(
            kind="float",
            ui_min=0.0,
            ui_max=1.0,
            recommended_range=(10.0, 20.0),
        ),
    )
    int_key = _add_typed_parameter(
        store,
        arg="int",
        value=2,
        meta=ParamMeta(kind="int", ui_min=2, ui_max=4),
    )
    vec_key = _add_typed_parameter(
        store,
        arg="vec",
        value=(0.0, 0.0, 0.0),
        meta=ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0),
    )
    rgb_key = _add_typed_parameter(
        store,
        arg="rgb",
        value=(0, 0, 0),
        meta=ParamMeta(kind="rgb", ui_min=10, ui_max=20),
    )
    locked_key = _add_typed_parameter(
        store,
        arg="locked",
        value=0.75,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
    )
    discrete_key = _add_typed_parameter(
        store,
        arg="label",
        value="keep",
        meta=ParamMeta(kind="str"),
    )
    no_range_key = _add_typed_parameter(
        store,
        arg="unbounded",
        value=3.0,
        meta=ParamMeta(kind="float"),
    )
    set_parameters_locked(store, [locked_key], locked=True)
    scope = [
        no_range_key,
        rgb_key,
        vec_key,
        discrete_key,
        locked_key,
        int_key,
        float_key,
    ]
    original = {key: _typed_value(store, key) for key in scope}
    history = ParamStoreHistory(store)
    table_revision = store.table_revision
    value_revision = store.value_revision
    style_revision = store.style_revision

    changed = randomize_parameters(store, scope, seed=1234, history=history)

    assert store.table_revision == table_revision
    assert store.value_revision == value_revision + 1
    assert store.style_revision == style_revision
    assert changed == (float_key, int_key, rgb_key, vec_key)
    assert 10.0 <= float(_typed_value(store, float_key)) <= 20.0
    assert _typed_value(store, int_key) in {2, 3, 4}
    assert all(-1.0 <= float(value) <= 1.0 for value in _typed_value(store, vec_key))
    assert all(10 <= int(value) <= 20 for value in _typed_value(store, rgb_key))
    assert _typed_value(store, locked_key) == original[locked_key]
    assert _typed_value(store, discrete_key) == original[discrete_key]
    assert _typed_value(store, no_range_key) == original[no_range_key]
    assert history.undo_depth == 1
    randomized = {key: _typed_value(store, key) for key in changed}

    assert history.undo() is True
    assert {key: _typed_value(store, key) for key in scope} == original
    assert is_parameter_locked(store, locked_key) is True
    # scope の順序や他 key の有無に依存せず、同じ seed/key は同じ値。
    assert randomize_parameters(store, [float_key], seed=1234) == (float_key,)
    assert _typed_value(store, float_key) == randomized[float_key]
    randomize_parameters(store, reversed(scope), seed=1234)
    assert {key: _typed_value(store, key) for key in changed} == randomized


def _variation_pair_store() -> tuple[ParamStore, dict[str, ParameterKey]]:
    store = ParamStore()
    specs = {
        "float": (0.0, ParamMeta(kind="float", ui_min=0.0, ui_max=10.0)),
        "int": (0, ParamMeta(kind="int", ui_min=-10, ui_max=10)),
        "vec": ((0.0, 10.0, 20.0), ParamMeta(kind="vec3")),
        "rgb": ((0, 10, 250), ParamMeta(kind="rgb")),
        "bool": (False, ParamMeta(kind="bool")),
        "choice": (
            "alpha",
            ParamMeta(kind="choice", choices=("alpha", "beta")),
        ),
        "str": ("A", ParamMeta(kind="str")),
        "font": ("font-a", ParamMeta(kind="font")),
    }
    keys = {
        name: _add_typed_parameter(store, arg=name, value=value, meta=meta)
        for name, (value, meta) in specs.items()
    }
    _set_typed_value(store, keys["choice"], "alpha", cc_key=1)
    create_variation(store, "A", created_at=100.0)

    b_values: dict[str, object] = {
        "float": 10.0,
        "int": 3,
        "vec": (10.0, 20.0, 30.0),
        "rgb": (255, 110, 0),
        "bool": True,
        "choice": "beta",
        "str": "B",
        "font": "font-b",
    }
    for name, value in b_values.items():
        _set_typed_value(
            store,
            keys[name],
            value,
            override=name != "bool",
            cc_key=2 if name == "choice" else None,
        )
    create_variation(store, "B", created_at=101.0)
    return store, keys


def test_morph_interpolates_numeric_and_records_one_undoable_operation() -> None:
    store, keys = _variation_pair_store()
    only_b = _add_typed_parameter(
        store,
        arg="only-b",
        value=42.0,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=100.0),
    )
    for key in keys.values():
        state = store.get_state(key)
        assert state is not None
        _set_typed_value(store, key, state.ui_value, cc_key=9)
    _set_typed_value(store, keys["float"], 99.0)
    _set_typed_value(store, keys["font"], "locked-current")
    set_parameters_locked(store, [keys["font"]], locked=True)
    before = {key: store.get_state(key) for key in (*keys.values(), only_b)}
    history = ParamStoreHistory(store)

    changed = morph_variations(
        store,
        "A",
        "B",
        0.5,
        keys=[*keys.values(), only_b],
        history=history,
    )

    assert keys["float"] in changed
    assert _typed_value(store, keys["float"]) == pytest.approx(5.0)
    assert _typed_value(store, keys["int"]) == 2
    assert _typed_value(store, keys["vec"]) == pytest.approx((5.0, 15.0, 25.0))
    assert _typed_value(store, keys["rgb"]) == (128, 60, 125)
    assert _typed_value(store, keys["bool"]) is True
    bool_state = store.get_state(keys["bool"])
    assert bool_state is not None and bool_state.override is False
    choice_state = store.get_state(keys["choice"])
    assert choice_state is not None
    assert choice_state.ui_value == "beta"
    assert choice_state.cc_key == 2
    assert _typed_value(store, keys["font"]) == "locked-current"
    assert _typed_value(store, only_b) == 42.0
    assert history.undo_depth == 1

    assert history.undo() is True
    for key, state in before.items():
        assert store.get_state(key) == state


def test_morph_endpoints_and_discrete_halfway_policy_are_explicit() -> None:
    store, keys = _variation_pair_store()
    scope = list(keys.values())

    morph_variations(store, "A", "B", 0.0, keys=scope)
    assert _typed_value(store, keys["float"]) == pytest.approx(0.0)
    assert _typed_value(store, keys["int"]) == 0
    assert _typed_value(store, keys["vec"]) == pytest.approx((0.0, 10.0, 20.0))
    assert _typed_value(store, keys["rgb"]) == (0, 10, 250)
    assert _typed_value(store, keys["bool"]) is False
    choice_state = store.get_state(keys["choice"])
    assert choice_state is not None
    assert choice_state.ui_value == "alpha"
    assert choice_state.cc_key == 1

    morph_variations(store, "A", "B", 0.499, keys=scope)
    assert _typed_value(store, keys["bool"]) is False
    assert _typed_value(store, keys["choice"]) == "alpha"
    assert _typed_value(store, keys["str"]) == "A"
    assert _typed_value(store, keys["font"]) == "font-a"

    morph_variations(store, "A", "B", 0.5, keys=scope)
    assert _typed_value(store, keys["bool"]) is True
    assert _typed_value(store, keys["choice"]) == "beta"
    assert _typed_value(store, keys["str"]) == "B"
    assert _typed_value(store, keys["font"]) == "font-b"

    morph_variations(store, "A", "B", 1.0, keys=scope)
    assert _typed_value(store, keys["float"]) == pytest.approx(10.0)
    assert _typed_value(store, keys["int"]) == 3
    assert _typed_value(store, keys["vec"]) == pytest.approx((10.0, 20.0, 30.0))
    assert _typed_value(store, keys["rgb"]) == (255, 110, 0)


@pytest.mark.parametrize("amount", [-0.01, 1.01, float("inf"), float("nan")])
def test_morph_rejects_amount_outside_unit_interval(amount: float) -> None:
    store, keys = _variation_pair_store()
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        morph_variations(store, "A", "B", amount, keys=keys.values())
