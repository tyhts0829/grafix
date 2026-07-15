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


def _session_with_dirty_explicit_override(
    primary: Path,
) -> tuple[ParamStore, ParameterKey, ParamStoreAutosave]:
    store = ParamStore()
    key = ParameterKey(op="circle", site_id="site", arg="radius")
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=1.0)
    merge_frame_params(
        store,
        [FrameParamRecord(key=key, base=0.25, meta=meta, explicit=True)],
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
        lambda: SimpleNamespace(midi_inputs=()),
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
        lambda: SimpleNamespace(midi_inputs=(), window_pos_draw=(0, 0)),
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

    class Midi:
        def save(self) -> None:
            calls.append("save midi")

        def close(self) -> None:
            calls.append("close midi")

    midi = cast(Any, Midi())

    class Window:
        def set_location(self, *_args: object) -> None:
            calls.append("place draw")

    class DrawWindow:
        window = Window()
        transport = object()
        is_recording = False

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("create draw")

        def close(self) -> None:
            calls.append("close draw")
            midi.save()
            midi.close()

        def draw_frame(self) -> None:
            pass

    class FailedGUI:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("create gui")
            raise RuntimeError("GUI construction failed")

    monkeypatch.setattr(presets_module, "_autoload_preset_modules", lambda: None)
    monkeypatch.setattr(
        runner_module,
        "runtime_config",
        lambda: SimpleNamespace(
            midi_inputs=(),
            window_pos_draw=(0, 0),
            window_pos_parameter_gui=(10, 10),
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
