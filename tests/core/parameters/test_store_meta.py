import json

import pytest

from grafix.core.parameters import FrameParamRecord, ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.codec import (
    decode_param_store_result,
    dumps_param_store,
    encode_param_store,
    loads_param_store_result,
)
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.invariants import assert_invariants
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.state import ParamState, ParamStateSnapshot
from grafix.core.parameters.ui_ops import update_state_from_ui


def test_snapshot_includes_meta_state_and_ordinal():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-1", arg="r")
    record = FrameParamRecord(
        key=key,
        base=0.5,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        effective=0.5,
        source="code",
        explicit=True,
    )

    merge_frame_params(store, [record])

    snap = store_snapshot(store)
    assert key in snap
    meta, state, ordinal, label = snap[key]
    assert meta.kind == "float"
    assert meta.ui_min == 0.0
    assert state.ui_value == 0.5
    assert state.override is False
    assert ordinal == 1
    assert_invariants(store)


def test_snapshot_omits_state_without_meta():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-2", arg="r")
    # meta を登録せず state だけ作る（UI 先行で値が入るケースを模擬）。
    update_state_from_ui(
        store,
        key,
        1.0,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        override=True,
    )

    snap = store_snapshot(store)
    assert key not in snap
    assert_invariants(store)


def test_json_roundtrip_preserves_meta_and_state():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-3", arg="r")
    record = FrameParamRecord(
        key=key,
        base=0.1,
        meta=ParamMeta(kind="float", ui_min=-1.0, ui_max=1.0, choices=None),
        effective=0.1,
        source="code",
        explicit=False,
    )
    merge_frame_params(store, [record])
    update_state_from_ui(store, key, 0.1, meta=record.meta, override=True)

    payload = dumps_param_store(store)
    loaded = loads_param_store_result(payload).store

    snap = store_snapshot(loaded)
    meta, state, ordinal, label = snap[key]
    assert meta.kind == "float"
    assert meta.ui_min == -1.0
    assert meta.ui_max == 1.0
    assert state.override is True
    assert state.ui_value == 0.1
    assert ordinal == 1
    assert_invariants(loaded)


def test_codec_roundtrip_emits_json_arrays_and_restores_vec3_cc_key_tuple():
    store = ParamStore()
    key = ParameterKey(op="scale", site_id="site-v", arg="p")
    record = FrameParamRecord(
        key=key,
        base=(0.0, 0.0, 0.0),
        meta=ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0),
        effective=(0.0, 0.0, 0.0),
        source="code",
        explicit=True,
    )
    merge_frame_params(store, [record])
    stored_meta = store.get_meta(key)
    assert stored_meta is not None
    update_state_from_ui(store, key, (0.0, 0.0, 0.0), meta=stored_meta, cc_key=(1, None, 3))

    payload = encode_param_store(store)
    state_payload = payload["states"][0]
    assert state_payload["ui_value"] == [0.0, 0.0, 0.0]
    assert state_payload["cc_key"] == [1, None, 3]

    loaded = decode_param_store_result(payload).store

    snap = store_snapshot(loaded)
    _meta, state, _ordinal, _label = snap[key]
    assert state.ui_value == (0.0, 0.0, 0.0)
    assert state.cc_key == (1, None, 3)
    assert_invariants(loaded)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "ui_value",
            (0.0, 0.0, 0.0),
            "ui_value must be a three-item list",
        ),
        (
            "cc_key",
            (1, None, 3),
            "cc_key must be an int, a three-item list, or null",
        ),
    ],
)
def test_direct_decode_rejects_python_tuple_for_json_array_fields(
    field: str,
    value: object,
    reason: str,
) -> None:
    store = ParamStore()
    key = ParameterKey(op="scale", site_id="strict-json-array", arg="p")
    meta = ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=(0.0, 0.0, 0.0),
                meta=meta,
                effective=(0.0, 0.0, 0.0),
                source="code",
                explicit=True,
            )
        ],
    )
    payload = encode_param_store(store)
    payload["states"][0][field] = value

    result = decode_param_store_result(payload)

    assert result.store.get_state(key) is None
    assert any(
        issue.section == "states"
        and issue.index == 0
        and reason in issue.reason
        for issue in result.issues
    )


def test_json_roundtrip_canonicalizes_rgb_ui_value_to_tuple():
    store = ParamStore()
    key = ParameterKey(op="style", site_id="site-rgb", arg="color")
    meta = ParamMeta(kind="rgb", ui_min=0, ui_max=255)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=(0, 0, 0),
                meta=meta,
                effective=(0, 0, 0),
                source="code",
                explicit=True,
            )
        ],
    )
    update_state_from_ui(store, key, (1, 2, 3), meta=meta, override=True)

    loaded = loads_param_store_result(dumps_param_store(store)).store
    snap = store_snapshot(loaded)
    _meta, state, _ordinal, _label = snap[key]
    assert state.ui_value == (1, 2, 3)
    assert isinstance(state.ui_value, tuple)
    assert_invariants(loaded)


def test_encode_drops_state_without_meta():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-no-meta", arg="r")
    update_state_from_ui(
        store,
        key,
        1.0,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        override=True,
    )

    payload_obj = json.loads(dumps_param_store(store))
    assert payload_obj.get("states", []) == []


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported parameter kind"):
        ParamMeta(kind="__unknown__")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("explicit", 1),
        ("initial_override", 1),
    ],
)
def test_store_rejects_non_bool_internal_flags(field: str, value: object) -> None:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="strict-flags", arg="r")
    kwargs = {
        "base_value": 1.0,
        "explicit": False,
        "initial_override": None,
    }
    kwargs[field] = value

    with pytest.raises(TypeError, match="exact bool"):
        store._ensure_state(key, **kwargs)  # type: ignore[arg-type]

    assert store.get_state(key) is None


def test_store_rejects_non_bool_explicit_update() -> None:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="strict-explicit", arg="r")

    with pytest.raises(TypeError, match="exact bool"):
        store._set_explicit(key, 1)  # type: ignore[arg-type]


def test_snapshot_rejects_corrupt_non_bool_override() -> None:
    state = ParamState(override=True, ui_value=1.0)
    state.override = 1  # type: ignore[assignment]

    with pytest.raises(TypeError, match="state.override must be an exact bool"):
        ParamStateSnapshot.from_state(state)
