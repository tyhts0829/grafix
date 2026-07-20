# ruff: noqa: E402 -- pyglet option must be set before importing runner.

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pyglet
import pytest

pyglet.options["shadow_window"] = False

import grafix.api.runner as runner_module
import grafix.api.presets as presets_module
import grafix.interactive.runtime.parameter_gui_system as gui_system_module
from grafix.core.parameters import FrameParamRecord, ParamMeta, ParamStore, ParameterKey
from grafix.core.parameters.autosave import ParamStoreAutosave
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.persistence import (
    load_param_store,
    load_param_store_with_recovery,
    param_store_recovery_path,
    save_param_store_recovery,
)
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.runtime_config import RuntimeConfigFallback
from grafix.interactive.runtime.monitor import RuntimeMonitor
from grafix.interactive.runtime.diagnostics import DiagnosticAction, DiagnosticEvent


def test_config_fallback_is_published_to_shared_diagnostic_center(
    tmp_path: Path,
) -> None:
    source = tmp_path / "config.yaml"
    monitor = RuntimeMonitor()
    fallback = RuntimeConfigFallback(
        summary="RuntimeError: unknown key",
        details="traceback with nearest key",
        source=source,
    )

    event = runner_module._publish_runtime_config_fallback(monitor, fallback)

    assert event.category == "config"
    assert event.source == str(source)
    assert event.details == "traceback with nearest key"
    assert tuple(action.action_id for action in event.actions) == ("copy", "open")
    assert monitor.snapshot().diagnostics == (event,)


def _session_with_dirty_explicit_override(
    primary: Path,
) -> tuple[ParamStore, ParameterKey, ParamStoreAutosave]:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=0.25,
                meta=meta,
                effective=0.25,
                source="code",
                explicit=True,
            )
        ],
    )
    autosave = ParamStoreAutosave(
        store,
        param_store_recovery_path(primary),
        save=save_param_store_recovery,
    )
    ok, error = update_state_from_ui(
        store,
        key,
        0.9,
        meta=meta,
        override=True,
    )
    assert ok and error is None
    return store, key, autosave


def test_abnormal_shutdown_flushes_recovery_without_finalizing_primary(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    store, key, autosave = _session_with_dirty_explicit_override(primary)

    runner_module._persist_param_store_on_shutdown(
        store=store,
        primary_path=primary,
        autosave=autosave,
        session_completed_cleanly=False,
    )

    assert not primary.exists()
    assert recovery.exists()
    recovered = load_param_store_with_recovery(primary).get_state(key)
    assert recovered is not None
    assert recovered.ui_value == pytest.approx(0.9)
    assert recovered.override is True


def test_clean_shutdown_promotes_primary_and_removes_recovery(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    store, key, autosave = _session_with_dirty_explicit_override(primary)

    runner_module._persist_param_store_on_shutdown(
        store=store,
        primary_path=primary,
        autosave=autosave,
        session_completed_cleanly=True,
    )

    assert primary.exists()
    assert not recovery.exists()
    finalized = load_param_store(primary).get_state(key)
    assert finalized is not None
    assert finalized.ui_value == pytest.approx(0.9)
    assert finalized.override is False


def test_recovered_session_actions_are_wired_to_shared_diagnostic_center(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "store.json"
    recovery = param_store_recovery_path(primary)
    store, key, autosave = _session_with_dirty_explicit_override(primary)
    autosave.flush()
    recovered = load_param_store_with_recovery(primary)
    recovered_autosave = ParamStoreAutosave(
        recovered,
        recovery,
        save=save_param_store_recovery,
    )
    monitor = RuntimeMonitor()

    session = runner_module._install_parameter_diagnostic_actions(
        monitor=monitor,
        store=recovered,
        primary_path=primary,
        autosave=recovered_autosave,
        history=None,
        snapshot_slots=None,
        open_source=lambda _source: None,
    )

    assert session is not None
    snapshot = monitor.snapshot()
    assert snapshot.recovered_session is True
    recovered_event = next(
        event for event in snapshot.diagnostics if event.summary == "Recovered session"
    )
    assert tuple(action.action_id for action in recovered_event.actions) == (
        "keep",
        "discard",
        "compare",
    )

    compare = next(
        action for action in recovered_event.actions if action.action_id == "compare"
    )
    assert monitor.diagnostic_center.dispatch_action(recovered_event, compare)
    assert any(
        event.summary == "Recovered session comparison"
        for event in monitor.snapshot().diagnostics
    )

    keep = next(action for action in recovered_event.actions if action.action_id == "keep")
    assert monitor.diagnostic_center.dispatch_action(recovered_event, keep)
    assert monitor.snapshot().recovered_session is False
    assert not recovery.exists()
    kept = load_param_store(primary).get_state(key)
    assert kept is not None
    assert kept.ui_value == pytest.approx(0.9)


def test_retry_action_retries_autosave_and_clears_failure(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "store.json"
    store, _key, autosave = _session_with_dirty_explicit_override(primary)
    attempts = 0

    def flaky_save(current: ParamStore, path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("disk full")
        save_param_store_recovery(current, path)

    autosave._save = flaky_save
    with pytest.raises(OSError, match="disk full"):
        autosave.flush()

    monitor = RuntimeMonitor()
    monitor.set_autosave(
        status=autosave.status,
        error=autosave.last_error,
        source=str(autosave.path),
    )
    runner_module._install_parameter_diagnostic_actions(
        monitor=monitor,
        store=store,
        primary_path=None,
        autosave=autosave,
        history=None,
        snapshot_slots=None,
        open_source=lambda _source: None,
    )
    failed = next(event for event in monitor.snapshot().diagnostics if event.category == "save")
    retry = next(action for action in failed.actions if action.action_id == "retry")

    assert monitor.diagnostic_center.dispatch_action(failed, retry)
    assert attempts == 2
    assert monitor.snapshot().autosave_status == "clean"
    assert failed not in monitor.snapshot().diagnostics


def test_shutdown_save_failure_is_published_to_shared_center(tmp_path: Path) -> None:
    primary = tmp_path / "store.json"
    store, _key, autosave = _session_with_dirty_explicit_override(primary)

    def fail_save(_store: ParamStore, _path: Path) -> None:
        raise OSError("read-only volume")

    autosave._save = fail_save
    monitor = RuntimeMonitor()

    with pytest.raises(OSError, match="read-only volume"):
        runner_module._persist_param_store_on_shutdown(
            store=store,
            primary_path=primary,
            autosave=autosave,
            session_completed_cleanly=False,
            monitor=monitor,
        )

    diagnostic = monitor.snapshot().diagnostics[-1]
    assert diagnostic.category == "save"
    assert diagnostic.summary == "Parameter save failed during shutdown"
    assert "OSError: read-only volume" in diagnostic.details


def test_open_action_uses_runner_source_handler(tmp_path: Path) -> None:
    source = tmp_path / "sketch.py"
    source.write_text("pass\n", encoding="utf-8")
    opened: list[str] = []
    monitor = RuntimeMonitor()
    runner_module._install_parameter_diagnostic_actions(
        monitor=monitor,
        store=ParamStore(),
        primary_path=None,
        autosave=None,
        history=None,
        snapshot_slots=None,
        open_source=opened.append,
    )
    action = DiagnosticAction("open", "Open source")
    event = monitor.publish_diagnostic(
        DiagnosticEvent(
            category="scene",
            severity="error",
            summary="draw failed",
            source=f"{source}:10",
            actions=(action,),
        )
    )

    assert monitor.diagnostic_center.dispatch_action(event, action)
    assert opened == [f"{source}:10"]


def test_diagnostic_source_path_accepts_file_line_suffix(tmp_path: Path) -> None:
    source = tmp_path / "sketch.py"
    source.write_text("pass\n", encoding="utf-8")

    assert runner_module._diagnostic_source_path(f"{source}:42") == source.resolve()


def test_cleanup_steps_continue_after_failure_and_raise_the_first_error() -> None:
    calls: list[str] = []
    first_error = RuntimeError("GUI close failed")

    def fail_gui_close() -> None:
        calls.append("gui")
        raise first_error

    def close_draw_window() -> None:
        calls.append("draw")

    with pytest.raises(RuntimeError, match="GUI close failed") as exc_info:
        runner_module._run_cleanup_steps(
            [
                ("close GUI", fail_gui_close),
                ("close draw window", close_draw_window),
            ]
        )

    assert exc_info.value is first_error
    assert calls == ["gui", "draw"]


def test_cleanup_steps_preserve_the_session_error_over_cleanup_errors() -> None:
    calls: list[str] = []
    session_error = ValueError("draw loop failed")

    def fail_cleanup() -> None:
        calls.append("cleanup")
        raise RuntimeError("secondary cleanup failure")

    def final_cleanup() -> None:
        calls.append("final")

    with pytest.raises(ValueError, match="draw loop failed") as exc_info:
        runner_module._run_cleanup_steps(
            [
                ("failing cleanup", fail_cleanup),
                ("final cleanup", final_cleanup),
            ],
            initial_error=session_error,
        )

    assert exc_info.value is session_error
    assert calls == ["cleanup", "final"]


def test_cleanup_steps_catch_base_exceptions_and_keep_the_first_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    first_error = CleanupFault("first")

    def fail_first() -> None:
        calls.append("first")
        raise first_error

    def fail_second() -> None:
        calls.append("second")
        raise CleanupFault("second")

    def finish() -> None:
        calls.append("finish")

    with pytest.raises(CleanupFault) as exc_info:
        runner_module._run_cleanup_steps(
            [
                ("first", fail_first),
                ("second", fail_second),
                ("finish", finish),
            ]
        )

    assert exc_info.value is first_error
    assert calls == ["first", "second", "finish"]
    logged = [record.getMessage() for record in caplog.records]
    assert all("first" not in message for message in logged)
    assert any("second" in message for message in logged)


def test_midi_save_failure_still_closes_the_owned_input_port() -> None:
    calls: list[str] = []
    save_error = RuntimeError("snapshot write failed")

    class Midi:
        def save(self) -> None:
            calls.append("save")
            raise save_error

        def close(self) -> None:
            calls.append("close")

    with pytest.raises(RuntimeError, match="snapshot write failed") as exc_info:
        runner_module._close_midi_controller(cast(Any, Midi()))

    assert exc_info.value is save_error
    assert calls == ["save", "close"]


def test_acquisition_failure_closes_midi_created_before_draw_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Midi:
        def save(self) -> None:
            calls.append("save midi")

        def close(self) -> None:
            calls.append("close midi")

    midi = cast(Any, Midi())
    monkeypatch.setattr(
        runner_module,
        "runtime_config",
        lambda: SimpleNamespace(
            midi_inputs=(),
            window_pos_draw=(0, 0),
            window_pos_parameter_gui=(10, 10),
            parameter_gui_window_size=(800, 1000),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "output_path_for_draw",
        lambda **_kwargs: tmp_path / "midi.json",
    )
    monkeypatch.setattr(
        runner_module,
        "default_param_store_path",
        lambda *_args, **_kwargs: tmp_path / "params.json",
    )
    monkeypatch.setattr(runner_module, "create_midi_controller", lambda **_kwargs: midi)

    def fail_after_midi(**_kwargs: object) -> None:
        raise RuntimeError("frozen snapshot load failed")

    monkeypatch.setattr(
        runner_module,
        "maybe_load_frozen_cc_snapshot",
        fail_after_midi,
    )

    with pytest.raises(RuntimeError, match="frozen snapshot load failed"):
        runner_module.run(
            lambda _t: None,
            parameter_gui=False,
            parameter_persistence=False,
        )

    assert calls == ["save midi", "close midi"]


def test_failure_after_draw_window_construction_runs_registered_closer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Midi:
        def save(self) -> None:
            calls.append("save midi")

        def close(self) -> None:
            calls.append("close midi")

    midi = cast(Any, Midi())

    class Window:
        def get_requested_size(self) -> tuple[int, int]:
            return 800, 800

        def get_location(self) -> tuple[int, int]:
            return 0, 0

        def set_location(self, *_args: object) -> None:
            raise RuntimeError("window placement failed")

    class DrawWindow:
        window = Window()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("create draw")

        def close(self) -> None:
            calls.append("close draw")
            midi.save()
            midi.close()

    monkeypatch.setattr(
        runner_module,
        "runtime_config",
        lambda: SimpleNamespace(
            midi_inputs=(),
            window_pos_draw=(0, 0),
            window_pos_parameter_gui=(10, 10),
            parameter_gui_window_size=(800, 1000),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "output_path_for_draw",
        lambda **_kwargs: tmp_path / "midi.json",
    )
    monkeypatch.setattr(
        runner_module,
        "default_param_store_path",
        lambda *_args, **_kwargs: tmp_path / "params.json",
    )
    monkeypatch.setattr(runner_module, "create_midi_controller", lambda **_kwargs: midi)
    monkeypatch.setattr(
        runner_module,
        "maybe_load_frozen_cc_snapshot",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(runner_module, "DrawWindowSystem", DrawWindow)

    with pytest.raises(RuntimeError, match="window placement failed"):
        runner_module.run(
            lambda _t: None,
            parameter_gui=False,
            parameter_persistence=False,
        )

    assert calls == ["create draw", "close draw", "save midi", "close midi"]


def test_gui_construction_failure_closes_completed_draw_system_and_midi_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    autoload_configs: list[object] = []

    class Midi:
        def save(self) -> None:
            calls.append("save midi")

        def close(self) -> None:
            calls.append("close midi")

    midi = cast(Any, Midi())

    class Window:
        def get_requested_size(self) -> tuple[int, int]:
            return 800, 800

        def get_location(self) -> tuple[int, int]:
            return 0, 0

        def set_location(self, *_args: object) -> None:
            calls.append("place draw")

    class DrawWindow:
        window = Window()
        transport = object()
        is_recording = False
        capture_service = object()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("create draw")

        def close(self) -> None:
            calls.append("close draw")
            midi.save()
            midi.close()

        def draw_frame(self) -> None:
            pass

        def final_capture_frame(self) -> None:
            return None

        def record_parameter_revision_created(
            self,
            _revision: int,
            _timestamp_ns: int,
            _domain: str,
        ) -> None:
            return None

    effective_config = SimpleNamespace(
        midi_inputs=(),
        window_pos_draw=(0, 0),
        window_pos_parameter_gui=(10, 10),
        parameter_gui_window_size=(800, 1000),
    )

    class FailedGUI:
        def __init__(self, **_kwargs: object) -> None:
            assert callable(_kwargs["variation_thumbnail_capture"])
            assert _kwargs["effective_config"] is effective_config
            calls.append("create gui")
            raise RuntimeError("GUI construction failed")

    monkeypatch.setattr(
        presets_module,
        "_autoload_preset_modules",
        lambda cfg: autoload_configs.append(cfg),
    )
    monkeypatch.setattr(
        runner_module,
        "runtime_config",
        lambda: effective_config,
    )
    monkeypatch.setattr(
        runner_module,
        "output_path_for_draw",
        lambda **_kwargs: tmp_path / "midi.json",
    )
    monkeypatch.setattr(
        runner_module,
        "default_param_store_path",
        lambda *_args, **_kwargs: tmp_path / "params.json",
    )
    monkeypatch.setattr(runner_module, "create_midi_controller", lambda **_kwargs: midi)
    monkeypatch.setattr(
        runner_module,
        "maybe_load_frozen_cc_snapshot",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(runner_module, "DrawWindowSystem", DrawWindow)
    monkeypatch.setattr(gui_system_module, "ParameterGUIWindowSystem", FailedGUI)

    with pytest.raises(RuntimeError, match="GUI construction failed"):
        runner_module.run(
            lambda _t: None,
            parameter_gui=True,
            parameter_persistence=False,
        )

    assert calls == [
        "create draw",
        "place draw",
        "create gui",
        "close draw",
        "save midi",
        "close midi",
    ]
    assert autoload_configs == [effective_config]


def test_variation_thumbnail_path_size_and_missing_status(tmp_path: Path) -> None:
    base = tmp_path / "sketch_800x400.png"
    assert runner_module._variation_thumbnail_output_path(
        base,
        "  A/B candidate  ",
    ) == tmp_path / "sketch_800x400_A_B_candidate.png"
    assert runner_module._variation_thumbnail_size((800, 400)) == (320, 160)

    messages: list[str] = []
    imgui = SimpleNamespace(text_disabled=messages.append)
    missing = tmp_path / "missing.png"
    runner_module._draw_variation_thumbnail_status(imgui, missing)
    missing.write_bytes(b"png")
    runner_module._draw_variation_thumbnail_status(imgui, missing)

    assert messages == [
        f"Thumbnail unavailable (missing): {missing}",
        "Thumbnail: missing.png",
    ]
