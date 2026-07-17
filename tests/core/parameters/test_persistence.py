import json
import logging
import os
from pathlib import Path

import pytest

import grafix.core.parameters.persistence as persistence_module
from grafix.core.parameters import ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.codec import (
    PARAM_STORE_SCHEMA_VERSION,
    UnsupportedParamStoreSchemaError,
    dumps_param_store,
    loads_param_store_result,
)
from grafix.core.parameters.context import current_frame_params, parameter_context
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.invariants import assert_invariants
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.persistence import (
    default_param_store_path,
    finalize_param_store_session,
    load_param_store,
    load_param_store_with_recovery,
    param_store_recovery_path,
    save_param_store,
    save_param_store_recovery,
)
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.parameters.variations import (
    create_variation,
    is_parameter_locked,
    list_variations,
    restore_variation,
    set_parameters_locked,
)
from grafix.core.runtime_config import set_config_path


@pytest.fixture(autouse=True)
def _reset_runtime_config() -> None:
    set_config_path(None)
    yield
    set_config_path(None)


def _isolate_config_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))


def _make_draw_with_filename(filename: Path):
    code = compile("def draw(t: float):\n    return None\n", str(filename), "exec")
    ns: dict[str, object] = {}
    exec(code, ns)
    return ns["draw"]


def _merge_float_group(
    store: ParamStore,
    *,
    op: str,
    site_id: str,
) -> ParameterKey:
    key = ParameterKey(op=op, site_id=site_id, arg="amount")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.5,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                explicit=False,
            )
        ],
    )
    return key


def _store_with_float_value(
    value: float,
    *,
    explicit: bool = False,
) -> tuple[ParamStore, ParameterKey]:
    store = ParamStore()
    key = ParameterKey(op="variant", site_id="site", arg="amount")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.1,
                meta=meta,
                explicit=explicit,
            )
        ],
    )
    ok, error = update_state_from_ui(
        store,
        key,
        value,
        meta=meta,
        override=True,
    )
    assert ok and error is None
    return store, key


def _set_mtime(path: Path, value_ns: int) -> None:
    os.utime(path, ns=(int(value_ns), int(value_ns)))


def test_default_param_store_path_uses_data_dir_and_script_stem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _isolate_config_discovery(tmp_path, monkeypatch)

    def draw(t: float) -> None:
        return None

    path = default_param_store_path(draw)
    assert path.parts[0] == "data"
    assert path.parts[1] == "output"
    assert path.parts[2] == "param_store"
    assert path.parts[3] == "misc"
    assert path.name == f"{Path(__file__).stem}.json"
    assert path.suffix == ".json"


def test_default_param_store_path_mirrors_sketch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_config_discovery(tmp_path, monkeypatch)

    discovered = tmp_path / ".grafix" / "config.yaml"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    discovered.write_text(
        'paths:\n  output_dir: "./out"\n  sketch_dir: "../sketch"\n',
        encoding="utf-8",
    )

    output_root = discovered.parent / "out"

    draw_in_root = _make_draw_with_filename(tmp_path / "sketch" / "readme.py")
    assert default_param_store_path(draw_in_root) == output_root / "param_store" / "readme.json"
    assert default_param_store_path(draw_in_root, run_id="v1") == (
        output_root / "param_store" / "readme_v1.json"
    )

    draw_in_subdir = _make_draw_with_filename(tmp_path / "sketch" / "folder1" / "readme.py")
    assert default_param_store_path(draw_in_subdir) == (
        output_root / "param_store" / "folder1" / "readme.json"
    )
    assert default_param_store_path(draw_in_subdir, run_id="v1") == (
        output_root / "param_store" / "folder1" / "readme_v1.json"
    )

    draw_outside = _make_draw_with_filename(tmp_path / "outside.py")
    assert default_param_store_path(draw_outside) == (
        output_root / "param_store" / "misc" / "outside.json"
    )


def test_param_store_file_roundtrip(tmp_path: Path):
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-1", arg="radius")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.5,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                explicit=False,
            )
        ],
    )

    path = tmp_path / "dummy.json"
    save_param_store(store, path)
    loaded = load_param_store(path)

    snap = store_snapshot(loaded)
    meta, state, ordinal, _label = snap[key]
    assert meta.kind == "float"
    assert meta.ui_min == 0.0
    assert meta.ui_max == 1.0
    assert state.override is True
    assert state.ui_value == 0.5
    assert ordinal == 1
    assert loaded.load_provenance == "primary"
    assert_invariants(loaded)


def test_explicit_bool_uses_code_after_normal_load_and_ui_after_recovery() -> None:
    store = ParamStore()
    key = ParameterKey(op="switch", site_id="bool-site", arg="enabled")
    meta = ParamMeta(kind="bool")
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=True, meta=meta, explicit=True)],
    )
    ok, error = update_state_from_ui(
        store,
        key,
        False,
        meta=meta,
        override=True,
    )
    assert ok and error is None

    normal = loads_param_store_result(dumps_param_store(store)).store
    normal_state = normal.get_state(key)
    assert normal_state is not None
    assert normal_state.ui_value is False
    assert normal_state.override is False

    recovery = loads_param_store_result(
        dumps_param_store(store, preserve_explicit_overrides=True),
        preserve_explicit_overrides=True,
    ).store
    recovery_state = recovery.get_state(key)
    assert recovery_state is not None
    assert recovery_state.ui_value is False
    assert recovery_state.override is True


def test_saved_param_store_declares_current_schema_version() -> None:
    payload = json.loads(dumps_param_store(ParamStore()))

    assert payload["schema_version"] == PARAM_STORE_SCHEMA_VERSION


def test_versionless_payload_uses_explicit_legacy_migration(tmp_path: Path) -> None:
    store, key = _store_with_float_value(0.4)
    legacy_payload = json.loads(dumps_param_store(store))
    legacy_payload.pop("schema_version")
    result = loads_param_store_result(json.dumps(legacy_payload))
    assert result.migrated_legacy is True
    assert result.issues == ()

    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    loaded = load_param_store(path)

    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.4)
    assert loaded.load_provenance == "primary"
    assert [diagnostic.code for diagnostic in loaded.load_diagnostics] == [
        "legacy_migration"
    ]
    assert path.exists()
    assert list(tmp_path.glob("legacy.json.corrupt-*")) == []


def test_future_schema_is_rejected_without_quarantine_or_empty_fallback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "future.json"
    payload = {"schema_version": PARAM_STORE_SCHEMA_VERSION + 1}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnsupportedParamStoreSchemaError) as exc_info:
        load_param_store(path)

    assert exc_info.value.found_version == PARAM_STORE_SCHEMA_VERSION + 1
    assert path.read_text(encoding="utf-8") == json.dumps(payload)
    assert list(tmp_path.glob("future.json.corrupt-*")) == []


def test_partial_corruption_is_quarantined_before_invalid_entry_is_dropped(
    tmp_path: Path,
) -> None:
    store, key = _store_with_float_value(0.6)
    payload_obj = json.loads(dumps_param_store(store))
    payload_obj["states"].append(
        {
            "op": "broken",
            "arg": "amount",
            "ui_value": 0.9,
        }
    )
    original_payload = json.dumps(payload_obj)
    path = tmp_path / "partial.json"
    path.write_text(original_payload, encoding="utf-8")

    loaded = load_param_store(path)

    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.6)
    assert loaded.load_provenance == "quarantined"
    assert not path.exists()
    backups = list(tmp_path.glob("partial.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_payload
    assert len(loaded.load_diagnostics) == 1
    diagnostic = loaded.load_diagnostics[0]
    assert diagnostic.code == "partial_quarantine"
    assert diagnostic.backup_path == backups[0]
    assert "states[1]" in diagnostic.details


def test_repaired_partial_primary_survives_restart_before_any_user_change(
    tmp_path: Path,
) -> None:
    store, key = _store_with_float_value(0.6)
    payload_obj = json.loads(dumps_param_store(store))
    payload_obj["states"].append(
        {
            "op": "broken",
            "arg": "amount",
            "ui_value": 0.9,
        }
    )
    primary = tmp_path / "partial.json"
    primary.write_text(json.dumps(payload_obj), encoding="utf-8")
    recovery = param_store_recovery_path(primary)

    first_launch = load_param_store_with_recovery(primary)

    first_state = first_launch.get_state(key)
    assert first_state is not None
    assert first_state.ui_value == pytest.approx(0.6)
    assert first_launch.load_provenance == "quarantined"
    assert not primary.exists()
    assert recovery.is_file()

    # user operation/finalize を一度も行わず異常終了し、同じ path から再起動する。
    restarted = load_param_store_with_recovery(primary)

    restarted_state = restarted.get_state(key)
    assert restarted_state is not None
    assert restarted_state.ui_value == pytest.approx(0.6)
    assert restarted.load_provenance == "session_recovery"
    assert recovery.is_file()


def test_repaired_recovery_save_failure_rolls_quarantine_back_to_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _key = _store_with_float_value(0.6)
    payload_obj = json.loads(dumps_param_store(store))
    payload_obj["states"].append(
        {
            "op": "broken",
            "arg": "amount",
            "ui_value": 0.9,
        }
    )
    primary = tmp_path / "partial.json"
    original_payload = json.dumps(payload_obj)
    primary.write_text(original_payload, encoding="utf-8")

    def fail_recovery_save(_store: ParamStore, _path: Path) -> None:
        raise OSError("recovery save failed")

    monkeypatch.setattr(
        persistence_module,
        "save_param_store_recovery",
        fail_recovery_save,
    )

    with pytest.raises(OSError, match="recovery save failed"):
        load_param_store_with_recovery(primary)

    assert primary.read_text(encoding="utf-8") == original_payload
    assert list(tmp_path.glob("partial.json.corrupt-*")) == []
    assert not param_store_recovery_path(primary).exists()


def test_param_store_file_roundtrip_includes_named_variations(tmp_path: Path) -> None:
    store, key = _store_with_float_value(0.3)
    create_variation(
        store,
        "print candidate",
        note="first pass",
        seed=41,
        t=1.25,
        created_at=100.0,
    )
    ok, error = update_state_from_ui(
        store,
        key,
        0.9,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        override=True,
    )
    assert ok and error is None

    path = tmp_path / "store.json"
    save_param_store(store, path)
    loaded = load_param_store(path)

    assert [variation.name for variation in list_variations(loaded)] == [
        "print candidate"
    ]
    assert restore_variation(loaded, "print candidate") is True
    restored = loaded.get_state(key)
    assert restored is not None
    assert restored.ui_value == pytest.approx(0.3)


def test_session_recovery_preserves_live_explicit_override_until_clean_exit(
    tmp_path: Path,
) -> None:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site-1", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=0.25, meta=meta, explicit=True)],
    )
    ok, error = update_state_from_ui(
        store,
        key,
        0.9,
        meta=meta,
        override=True,
    )
    assert ok and error is None

    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    save_param_store_recovery(store, recovery)

    recovered = load_param_store_with_recovery(primary)
    recovered_state = recovered.get_state(key)
    assert recovered_state is not None
    assert recovered_state.ui_value == pytest.approx(0.9)
    assert recovered_state.override is True

    finalize_param_store_session(recovered, primary)
    assert not recovery.exists()
    clean_state = load_param_store(primary).get_state(key)
    assert clean_state is not None
    assert clean_state.ui_value == pytest.approx(0.9)
    assert clean_state.override is False


def test_newer_session_recovery_wins_over_primary(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, key = _store_with_float_value(0.2)
    recovery_store, _ = _store_with_float_value(0.8)
    save_param_store(primary_store, primary)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    loaded = load_param_store_with_recovery(primary)

    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.8)
    assert loaded.load_provenance == "session_recovery"


def test_session_recovery_includes_named_variations(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, _key = _store_with_float_value(0.2)
    recovery_store, key = _store_with_float_value(0.4)
    create_variation(
        recovery_store,
        "live candidate",
        note="not finalized yet",
        created_at=100.0,
    )
    ok, error = update_state_from_ui(
        recovery_store,
        key,
        0.8,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
        override=True,
    )
    assert ok and error is None
    save_param_store(primary_store, primary)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    loaded = load_param_store_with_recovery(primary)

    assert [variation.name for variation in list_variations(loaded)] == [
        "live candidate"
    ]
    assert restore_variation(loaded, "live candidate") is True
    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.4)


def test_session_recovery_roundtrip_preserves_parameter_locks(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, _ = _store_with_float_value(0.2)
    recovery_store, key = _store_with_float_value(0.4)
    assert set_parameters_locked(recovery_store, [key], locked=True) == (key,)
    save_param_store(primary_store, primary)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    loaded = load_param_store_with_recovery(primary)

    assert loaded.load_provenance == "session_recovery"
    assert is_parameter_locked(loaded, key) is True
    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.4)


def test_primary_wins_when_it_is_newer_than_session_recovery(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, key = _store_with_float_value(0.2)
    recovery_store, _ = _store_with_float_value(0.8)
    save_param_store(primary_store, primary)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(recovery, 1_700_000_000_000_000_000)
    _set_mtime(primary, 1_700_000_001_000_000_000)

    loaded = load_param_store_with_recovery(primary)

    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.2)
    # loader はデータを勝手に消さず、clean finalize に cleanup を任せる。
    assert recovery.exists()


def test_future_schema_recovery_is_rejected_without_fallback(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, _key = _store_with_float_value(0.2)
    save_param_store(primary_store, primary)
    recovery_payload = {"schema_version": PARAM_STORE_SCHEMA_VERSION + 1}
    recovery.write_text(json.dumps(recovery_payload), encoding="utf-8")
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    with pytest.raises(UnsupportedParamStoreSchemaError):
        load_param_store_with_recovery(primary)

    assert primary.exists()
    assert recovery.read_text(encoding="utf-8") == json.dumps(recovery_payload)
    assert list(tmp_path.glob("store.session.json.corrupt-*")) == []


def test_future_primary_is_not_overwritten_by_newer_compatible_recovery(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    future_payload = {"schema_version": PARAM_STORE_SCHEMA_VERSION + 1}
    primary.write_text(json.dumps(future_payload), encoding="utf-8")
    recovery_store, _key = _store_with_float_value(0.8)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    with pytest.raises(UnsupportedParamStoreSchemaError):
        load_param_store_with_recovery(primary)

    assert primary.read_text(encoding="utf-8") == json.dumps(future_payload)
    assert recovery.exists()


def test_corrupt_newer_recovery_is_quarantined_and_primary_is_loaded(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, key = _store_with_float_value(0.3)
    save_param_store(primary_store, primary)
    recovery.write_text("{broken recovery", encoding="utf-8")
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)

    with caplog.at_level(logging.WARNING):
        loaded = load_param_store_with_recovery(primary)

    state = loaded.get_state(key)
    assert state is not None
    assert state.ui_value == pytest.approx(0.3)
    assert not recovery.exists()
    backups = list(tmp_path.glob("store.session.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken recovery"
    assert "session recovery を退避" in caplog.text
    assert loaded.load_provenance == "quarantined"
    assert loaded.load_diagnostics[0].code == "recovery_quarantine"


def test_recovery_read_errors_are_not_misclassified_as_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    primary_store, _key = _store_with_float_value(0.3)
    recovery_store, _ = _store_with_float_value(0.8)
    save_param_store(primary_store, primary)
    save_param_store_recovery(recovery_store, recovery)
    _set_mtime(primary, 1_700_000_000_000_000_000)
    _set_mtime(recovery, 1_700_000_001_000_000_000)
    original_read_text = Path.read_text

    def fail_recovery_read(self: Path, *, encoding: str) -> str:
        if self == recovery:
            raise PermissionError(self)
        return original_read_text(self, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", fail_recovery_read)

    with pytest.raises(PermissionError):
        load_param_store_with_recovery(primary)
    assert recovery.exists()
    assert list(tmp_path.glob("store.session.json.corrupt-*")) == []


def test_finalize_keeps_recovery_when_primary_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    store, _key = _store_with_float_value(0.8, explicit=True)
    save_param_store_recovery(store, recovery)
    recovery_before = recovery.read_bytes()

    def fail_primary_save(_store: ParamStore, _path: Path) -> None:
        raise OSError("primary unavailable")

    monkeypatch.setattr(persistence_module, "save_param_store", fail_primary_save)

    with pytest.raises(OSError, match="primary unavailable"):
        finalize_param_store_session(store, primary)
    assert recovery.read_bytes() == recovery_before
    assert not primary.exists()


def test_save_param_store_keeps_loaded_group_before_first_frame(tmp_path: Path):
    path = tmp_path / "store.json"
    original = ParamStore()
    key = _merge_float_group(original, op="custom", site_id="loaded")
    save_param_store(original, path)

    loaded = load_param_store(path)
    assert key in store_snapshot(loaded)

    # run 開始後、1 frame も成功しないまま終了した場合を再現する。
    save_param_store(loaded, path)

    assert key in store_snapshot(load_param_store(path))


def test_save_param_store_keeps_loaded_group_hidden_by_condition(tmp_path: Path):
    path = tmp_path / "store.json"
    original = ParamStore()
    visible_key = _merge_float_group(original, op="branch", site_id="visible")
    hidden_key = _merge_float_group(original, op="branch", site_id="hidden")
    save_param_store(original, path)

    loaded = load_param_store(path)
    # この run では条件分岐の片側だけが実行された状態。
    _merge_float_group(loaded, op="branch", site_id="visible")
    save_param_store(loaded, path)

    reloaded = load_param_store(path)
    snapshot = store_snapshot(reloaded)
    assert visible_key in snapshot
    assert hidden_key in snapshot


def test_save_param_store_keeps_loaded_groups_after_failed_frame(tmp_path: Path):
    path = tmp_path / "store.json"
    original = ParamStore()
    reached_key = _merge_float_group(original, op="failed", site_id="reached")
    later_key = _merge_float_group(original, op="failed", site_id="later")
    save_param_store(original, path)

    loaded = load_param_store(path)
    with pytest.raises(RuntimeError, match="draw failed"):
        with parameter_context(loaded):
            frame_params = current_frame_params()
            assert frame_params is not None
            frame_params.record(
                key=reached_key,
                base=0.5,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                explicit=False,
            )
            # `later_key` を評価する前に draw が失敗した状態。
            raise RuntimeError("draw failed")
    save_param_store(loaded, path)

    snapshot = store_snapshot(load_param_store(path))
    assert reached_key in snapshot
    assert later_key in snapshot


def test_load_param_store_backs_up_broken_json(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    path = tmp_path / "broken.json"
    broken_payload = "{broken-json"
    path.write_text(broken_payload, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = load_param_store(path)

    assert store_snapshot(loaded) == {}
    assert_invariants(loaded)
    assert loaded.load_provenance == "quarantined"
    assert loaded.load_diagnostics[0].code == "load_quarantine"
    assert not path.exists()
    backups = list(tmp_path.glob("broken.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == broken_payload
    assert "壊れた ParamStore を退避しました" in caplog.text


def test_load_param_store_does_not_hide_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "store.json"
    path.write_text("{}", encoding="utf-8")

    def fail_read_text(self: Path, *, encoding: str) -> str:
        raise PermissionError(self)

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    with pytest.raises(PermissionError):
        load_param_store(path)


def test_save_param_store_keeps_existing_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "store.json"
    path.write_text("original\n", encoding="utf-8")

    def fail_replace(
        src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dst: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        raise OSError(f"replace failed: {src} -> {dst}")

    monkeypatch.setattr("grafix.core.atomic_write.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_param_store(ParamStore(), path)

    assert path.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".store.json.*.tmp")) == []


def test_save_param_store_prunes_unknown_arg_for_known_primitive(tmp_path: Path):
    # 登録（meta 取得）に必要なので、対象モジュールを明示的に import する。
    from grafix.core.primitives import line as _primitive_line  # noqa: F401

    store = ParamStore()
    known = ParameterKey(op="line", site_id="site-1", arg="length")
    unknown = ParameterKey(op="line", site_id="site-1", arg="__unknown__")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=known,
                base=1.0,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=2.0),
                explicit=False,
            ),
            FrameParamRecord(
                key=unknown,
                base=0.1,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                explicit=True,
            ),
        ],
    )

    path = tmp_path / "store.json"
    save_param_store(store, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    for section in ["states", "meta", "explicit"]:
        assert not any(
            it.get("op") == "line" and it.get("arg") == "__unknown__"
            for it in payload.get(section, [])
        )

    assert any(it.get("op") == "line" and it.get("arg") == "length" for it in payload["states"])
