from grafix.core.parameters import ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.ui_ops import update_state_from_ui


def test_update_state_from_ui_sets_value_and_override():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="s1", arg="r")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)

    success, err = update_state_from_ui(
        store,
        key,
        0.5,
        meta=meta,
        override=True,
    )

    assert success is True
    assert err is None
    state = store.get_state(key)
    assert state is not None
    assert state.ui_value == 0.5
    assert state.override is True


def test_update_state_from_ui_respects_errors():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="s1", arg="r")
    meta = ParamMeta(kind="int", ui_min=0, ui_max=10)

    success, err = update_state_from_ui(
        store,
        key,
        "bad",
        meta=meta,
    )

    assert success is False
    assert err is not None
    # state should not be created on error
    assert store.get_state(key) is None


def test_update_state_from_ui_rejects_cc_for_unsupported_rgb():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="s1", arg="color")
    meta = ParamMeta(kind="rgb", ui_min=0, ui_max=255)

    success, err = update_state_from_ui(
        store,
        key,
        (10, 20, 30),
        meta=meta,
        cc_key=12,
    )

    assert success is False
    assert err is not None
    assert store.get_state(key) is None


def test_update_state_from_ui_accepts_scalar_cc_for_float():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="s1", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)

    success, err = update_state_from_ui(
        store,
        key,
        0.5,
        meta=meta,
        cc_key=127,
    )

    assert success is True
    assert err is None
    state = store.get_state(key)
    assert state is not None
    assert state.cc_key == 127


def test_invalid_cc_does_not_modify_existing_state():
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="s1", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    assert update_state_from_ui(store, key, 0.25, meta=meta)[0]

    success, err = update_state_from_ui(
        store,
        key,
        0.75,
        meta=meta,
        cc_key=128,
    )

    assert success is False
    assert err is not None
    state = store.get_state(key)
    assert state is not None
    assert state.ui_value == 0.25
