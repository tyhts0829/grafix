from __future__ import annotations

# ruff: noqa: E402 -- pyglet option must be set before importing DrawWindowSystem.

import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pyglet

# Unit tests construct DrawWindowSystem without a real window. Disable pyglet's import-time
# shadow context so the test remains usable in CI/headless sessions.
pyglet.options["shadow_window"] = False

from grafix.core.layer import LayerStyleDefaults
from grafix.core.capture_manifest import RecordingManifest, capture_manifest_path_for
from grafix.core.capture_provenance import CaptureProvenanceBuilder
from grafix.core.output_paths import VersionedPathAllocator
from grafix.core.parameters import (
    EffectStepTopology,
    FrameEffectChainRecord,
    ParamStore,
)
from grafix.core.parameters.effect_order_ops import merge_frame_effect_chains
from grafix.core.pipeline import RealizedLayer
from grafix.core.runtime_config import runtime_config
from grafix.interactive.midi import MidiSession
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
import grafix.interactive.runtime.draw_window_system as draw_window_module
from grafix.interactive.runtime.export_job_system import (
    ExportJobResult,
    ExportJobStatus,
    ExportKind,
    FrameExportSnapshot,
)
from grafix.interactive.runtime.frame_clock import TransportClock
from grafix.interactive.runtime.monitor import RuntimeMonitor
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.runtime.source_reload import SourceReloadResult
from grafix.interactive.render_settings import RenderSettings
from grafix.export import capture as capture_module
from grafix.export.capture import CaptureService


_DEFAULTS = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)


def _provenance_draw(_t: float) -> list[object]:
    return []


class _CountingProvenanceBuilder:
    def __init__(self, draw: object, store: ParamStore) -> None:
        self.inner = CaptureProvenanceBuilder(
            cast(Any, draw),
            config=runtime_config(),
            parameter_source="code",
            parameter_store_path=None,
            parameter_load_provenance=store.load_provenance,
            seed=1847,
        )
        self.calls: list[dict[str, object]] = []

    def frame(self, store: ParamStore, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return self.inner.frame(store, **cast(Any, kwargs))


def test_source_reload_rolls_back_when_worker_swap_fails() -> None:
    def replacement_draw(_t: float) -> list[object]:
        return []

    result = SourceReloadResult(
        status="reloaded",
        generation=3,
        draw=replacement_draw,
        source="/tmp/sketch.py",
    )

    class _Controller:
        def __init__(self) -> None:
            self.rollback_calls: list[int] = []

        def poll(self, *, force: bool, retain_rollback: bool) -> SourceReloadResult:
            assert force is True
            assert retain_rollback is True
            return result

        def rollback_generation(self, generation: int) -> object:
            self.rollback_calls.append(int(generation))
            return replacement_draw

    class _RejectingRunner:
        def replace_draw(self, draw: object) -> None:
            assert draw is replacement_draw
            raise RuntimeError("worker did not start")

    controller = _Controller()
    monitor = RuntimeMonitor()
    system = object.__new__(DrawWindowSystem)
    system._source_reload = cast(Any, controller)
    system._scene_runner = cast(Any, _RejectingRunner())
    system._monitor = monitor

    assert system._poll_source_reload(force=True) is False
    assert controller.rollback_calls == [3]
    diagnostics = monitor.diagnostic_center.snapshot()
    assert len(diagnostics) == 1
    assert diagnostics[0].category == "reload"
    assert {action.action_id for action in diagnostics[0].actions} == {
        "copy",
        "open",
        "retry",
    }


def test_successful_source_reload_begins_effect_chain_generation() -> None:
    def replacement_draw(_t: float) -> list[object]:
        return []

    result = SourceReloadResult(
        status="reloaded",
        generation=4,
        draw=replacement_draw,
        source="/tmp/sketch.py",
    )

    class _Controller:
        def __init__(self) -> None:
            self.accepted: list[int] = []

        def poll(self, *, force: bool, retain_rollback: bool) -> SourceReloadResult:
            assert force is True
            assert retain_rollback is True
            return result

        def accept_generation(self, generation: int) -> None:
            self.accepted.append(int(generation))

    class _Runner:
        def replace_draw(self, draw: object) -> None:
            assert draw is replacement_draw

    store = ParamStore()
    assert merge_frame_effect_chains(
        store,
        [
            FrameEffectChainRecord(
                chain_id="old-generation-chain",
                steps=(
                    EffectStepTopology(
                        op="scale",
                        site_id="old-generation-site",
                        n_inputs=1,
                        code_index=0,
                    ),
                ),
            )
        ],
    )
    controller = _Controller()
    system = object.__new__(DrawWindowSystem)
    system._source_reload = cast(Any, controller)
    system._scene_runner = cast(Any, _Runner())
    system._store = store
    system._monitor = None

    assert system._poll_source_reload(force=True) is True
    assert controller.accepted == [4]
    # reload自体ではlast-good GUI stateを保持し、最初の成功evaluationで確定する。
    assert "old-generation-chain" in store.effect_chain_topologies()
    assert merge_frame_effect_chains(
        store,
        [],
        observation_complete=True,
    )
    assert "old-generation-chain" not in store.effect_chain_topologies()


class _FakeMonitor:
    def __init__(self) -> None:
        self.frame_errors: list[str | None] = []
        self.frame_error_details: list[tuple[str, str | None]] = []

    def set_frame_error(
        self,
        message: str | None,
        *,
        details: str = "",
        source: str | None = None,
    ) -> None:
        self.frame_errors.append(message)
        self.frame_error_details.append((details, source))


class _FakeSceneRunner:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.last_evaluation_succeeded: bool | None = None
        self.run_kwargs: list[dict[str, object]] = []

    def run(self, *_args: object, **_kwargs: object) -> list[RealizedLayer]:
        self.run_kwargs.append(dict(_kwargs))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            self.last_evaluation_succeeded = False
            raise outcome
        layers, status = cast(tuple[list[RealizedLayer], bool | None], outcome)
        self.last_evaluation_succeeded = status
        return layers


def _make_scene_only_system(
    *, runner: _FakeSceneRunner, monitor: _FakeMonitor, last_good: list[RealizedLayer]
) -> DrawWindowSystem:
    system = object.__new__(DrawWindowSystem)
    system._scene_runner = cast(Any, runner)
    system._store = ParamStore()
    system._monitor = cast(Any, monitor)
    system._last_realized_layers = last_good
    system._last_frame_error = None
    return system


def test_scene_error_renders_last_good_until_a_new_success(caplog: pytest.LogCaptureFixture) -> None:
    last_good = cast(list[RealizedLayer], [object()])
    recovered = cast(list[RealizedLayer], [object()])
    runner = _FakeSceneRunner(
        [
            ValueError("broken sketch"),
            (last_good, None),  # mp-draw result waiting: not a recovery yet
            (recovered, True),
        ]
    )
    monitor = _FakeMonitor()
    system = _make_scene_only_system(
        runner=runner,
        monitor=monitor,
        last_good=last_good,
    )

    failed_frame = system._evaluate_scene(
        0.0,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )
    assert failed_frame is last_good
    assert system._last_realized_layers is last_good
    assert system._last_frame_error == "ValueError: broken sketch"
    assert monitor.frame_errors == ["ValueError: broken sketch"]
    assert "ValueError: broken sketch" in monitor.frame_error_details[0][0]
    assert monitor.frame_error_details[0][1] is not None
    assert "rendering the last successful frame" in caplog.text

    pending_frame = system._evaluate_scene(
        0.1,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )
    assert pending_frame is last_good
    assert system._last_frame_error == "ValueError: broken sketch"
    assert monitor.frame_errors == ["ValueError: broken sketch"]

    recovered_frame = system._evaluate_scene(
        0.2,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )
    assert recovered_frame is recovered
    assert system._last_realized_layers is recovered
    assert system._last_frame_error is None
    assert monitor.frame_errors == ["ValueError: broken sketch", None]


def test_frame_error_summary_uses_actionable_root_cause() -> None:
    try:
        try:
            raise ValueError("samples を減らしてください")
        except ValueError as cause:
            raise RuntimeError("Geometry evaluation failed") from cause
    except RuntimeError as error:
        summary = DrawWindowSystem._frame_error_summary(error)

    assert summary == "ValueError: samples を減らしてください"


def test_scene_error_logs_each_distinct_summary_only_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    last_good = cast(list[RealizedLayer], [object()])
    runner = _FakeSceneRunner(
        [
            ValueError("same failure"),
            ValueError("same failure"),
            TypeError("different failure"),
        ]
    )
    monitor = _FakeMonitor()
    system = _make_scene_only_system(
        runner=runner,
        monitor=monitor,
        last_good=last_good,
    )

    for t in (0.0, 0.1, 0.2):
        assert (
            system._evaluate_scene(
                t,
                cc_snapshot=None,
                defaults=_DEFAULTS,
                recording=False,
            )
            is last_good
        )

    messages = [
        record.message
        for record in caplog.records
        if "rendering the last successful frame" in record.message
    ]
    assert len(messages) == 2
    assert system._last_frame_error == "TypeError: different failure"


def test_last_good_frame_keeps_the_mp_worker_evaluation_time() -> None:
    realized = cast(list[RealizedLayer], [object()])
    runner = _FakeSceneRunner([(realized, True)])
    runner.last_evaluation_t = 0.25
    system = _make_scene_only_system(
        runner=runner,
        monitor=_FakeMonitor(),
        last_good=[],
    )

    system._evaluate_scene(
        1.0,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )

    assert system._last_frame_t == pytest.approx(0.25)


def test_batched_mp_success_updates_capture_time_without_clearing_later_error() -> None:
    """realized success の t は取り込み、より新しい error 表示は保つ。"""

    realized = cast(list[RealizedLayer], [object()])
    runner = _FakeSceneRunner([(realized, None)])
    runner.last_realized_t = 0.25
    system = _make_scene_only_system(
        runner=runner,
        monitor=_FakeMonitor(),
        last_good=cast(list[RealizedLayer], [object()]),
    )
    system._last_frame_t = 0.1
    system._last_frame_error = "ValueError: later frame failed"

    returned = system._evaluate_scene(
        1.0,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )

    assert returned is realized
    # SVG/PNG/G-code manifest が参照する時刻は、transport t=1.0 や
    # error frame の t ではなく、実際に描画出力となった success t。
    assert system._last_frame_t == pytest.approx(0.25)
    # frame 0.25 は error より新しい回復ではないため、banner は消さない。
    assert system._last_frame_error == "ValueError: later frame failed"


def test_scene_evaluation_passes_current_transport_epoch() -> None:
    runner = _FakeSceneRunner([([], True)])
    system = _make_scene_only_system(
        runner=runner,
        monitor=_FakeMonitor(),
        last_good=[],
    )
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        playing=False,
    )
    system._clock.seek(3.0)

    system._evaluate_scene(
        3.0,
        cc_snapshot=None,
        defaults=_DEFAULTS,
        recording=False,
    )

    assert runner.run_kwargs[-1]["transport_epoch"] == system._clock.epoch


def test_midi_frame_snapshot_distinguishes_live_frozen_and_disabled() -> None:
    class Midi:
        def __init__(self) -> None:
            self.poll_calls = 0

        def poll_pending(self) -> int:
            self.poll_calls += 1
            return 0

        def snapshot(self) -> dict[int, float]:
            return {7: 0.75}

    system = object.__new__(DrawWindowSystem)
    midi = Midi()
    system._midi_session = MidiSession(
        controller=cast(Any, midi),
        frozen_values={7: 0.25},
    )

    live = system._midi_frame_snapshot()
    assert live is not None
    assert live.source == "midi_live"
    assert live[7] == pytest.approx(0.75)
    assert midi.poll_calls == 1

    system._midi_session = MidiSession(
        controller=None,
        frozen_values={7: 0.25},
    )
    frozen = system._midi_frame_snapshot()
    assert frozen is not None
    assert frozen.source == "midi_frozen"
    assert frozen[7] == pytest.approx(0.25)

    system._midi_session = None
    assert system._midi_frame_snapshot() is None


def test_capture_snapshot_re_evaluates_with_final_quality(tmp_path: Path) -> None:
    runner = _FakeSceneRunner([([], True)])
    system = _make_scene_only_system(
        runner=runner,
        monitor=_FakeMonitor(),
        last_good=[],
    )
    provenance_builder = _CountingProvenanceBuilder(
        _provenance_draw,
        system._store,
    )
    system._provenance_builder = cast(Any, provenance_builder)
    system._provenance_frame_index = 0
    system._midi_session = None
    system._clock = cast(Any, SimpleNamespace(t=lambda: 1.25, epoch=0))
    system._recording = cast(Any, SimpleNamespace(is_recording=False))
    system._settings = cast(Any, SimpleNamespace(canvas_size=(100, 80)))
    system._style = cast(
        Any,
        SimpleNamespace(
            resolve=lambda: SimpleNamespace(
                bg_color_rgb01=(1.0, 1.0, 1.0),
                global_line_color_rgb01=(0.0, 0.0, 0.0),
                global_thickness=0.01,
            )
        ),
    )
    system._last_frame_t = 0.0

    snapshot = system.final_capture_frame()

    assert runner.run_kwargs[-1]["quality"] == "final"
    assert isinstance(snapshot, FrameExportSnapshot)
    assert snapshot.t == pytest.approx(1.25)
    assert snapshot.canvas_size == (100, 80)
    assert snapshot.provenance is not None
    assert snapshot.provenance.frame.quality == "final"
    assert snapshot.provenance.frame.frame_index == 0
    assert len(provenance_builder.calls) == 1

    captured = CaptureService().export(snapshot, tmp_path / "thumbnail.svg")
    manifest = json.loads(captured.manifest_path.read_text(encoding="utf-8"))

    assert captured.path.is_file()
    assert manifest["frame"]["t"] == pytest.approx(1.25)
    assert manifest["output"]["canvas_size"] == {"width": 100, "height": 80}


class _RenderFailure(RuntimeError):
    pass


class _FakeRenderer:
    def __init__(self) -> None:
        self.ctx = SimpleNamespace(screen=SimpleNamespace(use=lambda: None))

    def viewport(self, _width: int, _height: int) -> None:
        pass

    def clear(self, _color: tuple[float, float, float]) -> None:
        pass

    def render_layer(self, **_kwargs: object) -> object:
        raise _RenderFailure("GL render failed")


class _CollectingRenderer(_FakeRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.render_calls: list[dict[str, object]] = []

    def render_layer(self, **kwargs: object) -> object:
        self.render_calls.append(dict(kwargs))
        return SimpleNamespace(draw_vertices=0, draw_lines=0)


class _FakeStyleResolver:
    def resolve(self) -> object:
        return SimpleNamespace(
            bg_color_rgb01=(1.0, 1.0, 1.0),
            global_line_color_rgb01=(0.0, 0.0, 0.0),
            global_thickness=0.01,
        )


class _FakeRecording:
    is_recording = False


def _make_provenance_preview_system(
    *,
    frame_count: int,
    draw: object = _provenance_draw,
    recording: object | None = None,
    clock: object | None = None,
) -> tuple[DrawWindowSystem, _CountingProvenanceBuilder]:
    store = ParamStore()
    builder = _CountingProvenanceBuilder(draw, store)
    runner = _FakeSceneRunner([([], True) for _ in range(frame_count)])
    system = object.__new__(DrawWindowSystem)
    system._perf = PerfCollector(enabled=False)
    system._poll_export_results = lambda: None
    system._source_reload = None
    system._midi_session = None
    system._renderer = cast(Any, _FakeRenderer())
    system._framebuffer_size = lambda: (100, 100)
    system._style = cast(Any, _FakeStyleResolver())
    system._recording = cast(
        Any,
        _FakeRecording() if recording is None else recording,
    )
    system._recording_capture = None
    system._clock = cast(
        Any,
        (
            SimpleNamespace(
                t=lambda: 2.5,
                epoch=0,
                is_playing=False,
                speed=1.0,
            )
            if clock is None
            else clock
        ),
    )
    system._scene_runner = cast(Any, runner)
    system._store = store
    system._settings = SimpleNamespace(canvas_size=(100, 100))
    system._last_realized_layers = []
    system._last_frame_t = 0.0
    system._last_export_snapshot = None
    system._last_export_provenance_token = None
    system._last_frame_error = None
    system._last_capture_queue_notice = None
    system._monitor = None
    system._pending_export_requests = deque()
    system._provenance_builder = cast(Any, builder)
    system._provenance_frame_index = 0
    return system, builder


def test_changed_preview_does_not_materialize_provenance() -> None:
    system, builder = _make_provenance_preview_system(frame_count=120)

    for _ in range(120):
        # slider edit と同じく、毎 fresh frame で store revision を変える。
        system._store._touch()
        system.draw_frame()

    assert builder.calls == []
    assert system._provenance_frame_index == 120
    assert system._last_export_snapshot is not None
    assert system._last_export_snapshot.provenance is None
    token = system._last_export_provenance_token
    assert token is not None
    assert token.store_revision == system._store.revision
    assert token.frame_index == 119


def test_shutdown_re_evaluates_when_preview_parameter_revision_is_stale() -> None:
    system, builder = _make_provenance_preview_system(frame_count=2)
    system._store._touch()
    # MP worker が一つ前の parameter revision を表示した状況を再現する。
    system._scene_runner.last_realized_snapshot_revision = 0

    system.draw_frame()

    preview = system._last_export_snapshot
    token = system._last_export_provenance_token
    assert preview is not None and preview.provenance is None
    assert token is not None
    assert token.store_revision == 0
    assert token.store_revision != system._store.revision
    assert builder.calls == []

    capture = system._shutdown_export_snapshot()

    assert capture.provenance is not None
    assert capture.provenance.frame.quality == "final"
    assert capture.provenance.frame.parameters.revision == system._store.revision
    assert system._scene_runner.run_kwargs[-1]["quality"] == "final"
    assert len(builder.calls) == 1


def test_draw_frame_marks_only_new_results_as_fresh_renderer_admission() -> None:
    realized = cast(
        RealizedLayer,
        SimpleNamespace(
            realized=object(),
            cache_key=("held-result", (1, 1)),
            color=(0.0, 0.0, 0.0),
            thickness=0.01,
        ),
    )
    system, _builder = _make_provenance_preview_system(frame_count=0)
    runner = _FakeSceneRunner(
        [
            ([realized], True),
            ([realized], None),
        ]
    )
    runner.last_realized_snapshot_revision = 0
    renderer = _CollectingRenderer()
    system._scene_runner = cast(Any, runner)
    system._renderer = cast(Any, renderer)
    system._perf = PerfCollector(enabled=True, console_output=False)

    system.draw_frame()
    system.draw_frame()

    assert [call["scene_serial"] for call in renderer.render_calls] == [1, 1]
    assert [call["snapshot_revision"] for call in renderer.render_calls] == [0, 0]
    snapshot = system._perf.snapshot()
    assert snapshot.preview_samples == 2
    assert snapshot.preview_fresh_results == 1
    assert snapshot.preview_max_consecutive_stale_frames == 1


def test_gl_render_error_is_not_swallowed_by_scene_error_boundary() -> None:
    realized = cast(
        RealizedLayer,
        SimpleNamespace(
            realized=object(),
            cache_key=object(),
            color=(0.0, 0.0, 0.0),
            thickness=0.01,
        ),
    )
    runner = _FakeSceneRunner([([realized], True)])
    system = object.__new__(DrawWindowSystem)
    system._perf = PerfCollector(enabled=False)
    system._poll_export_results = lambda: None
    system._midi_session = None
    system._renderer = cast(Any, _FakeRenderer())
    system._framebuffer_size = lambda: (100, 100)
    system._style = cast(Any, _FakeStyleResolver())
    system._recording = cast(Any, _FakeRecording())
    system._clock = cast(Any, SimpleNamespace(t=lambda: 0.0))
    system._scene_runner = cast(Any, runner)
    system._store = ParamStore()
    system._last_realized_layers = []
    system._last_frame_error = None
    system._monitor = None
    system._pending_export_requests = deque()

    with pytest.raises(_RenderFailure, match="GL render failed"):
        system.draw_frame()


def test_recording_frame_mirrors_time_without_advancing_transport_epoch() -> None:
    class Clock:
        epoch = 7
        is_playing = False
        speed = 1.0

        def __init__(self) -> None:
            self.synchronized: list[float] = []

        def synchronize(self, t: float) -> None:
            self.synchronized.append(float(t))

        def seek(self, _t: float) -> None:
            raise AssertionError("recording mirror must not seek/increment epoch")

    class Recording:
        is_recording = True

        def t(self) -> float:
            return 2.25

        def write_frame(self, _screen: object) -> None:
            pass

    clock = Clock()
    runner = _FakeSceneRunner([([], True)])
    system = object.__new__(DrawWindowSystem)
    system._perf = PerfCollector(enabled=False)
    system._poll_export_results = lambda: None
    system._midi_session = None
    system._renderer = cast(Any, _FakeRenderer())
    system._framebuffer_size = lambda: (100, 100)
    system._style = cast(Any, _FakeStyleResolver())
    system._recording = cast(Any, Recording())
    system._clock = cast(Any, clock)
    system._scene_runner = cast(Any, runner)
    system._store = ParamStore()
    system._settings = SimpleNamespace(canvas_size=(100, 100))
    system._last_realized_layers = []
    system._last_frame_t = 0.0
    system._last_frame_error = None
    system._monitor = None
    system._pending_export_requests = deque()

    system.draw_frame()

    assert clock.synchronized == [2.25]
    assert runner.run_kwargs[-1]["transport_epoch"] == 7


def test_recording_materializes_only_the_first_fresh_frame_provenance() -> None:
    class Clock:
        epoch = 4
        is_playing = False
        speed = 1.0

        def synchronize(self, _t: float) -> None:
            return

    class Recording:
        is_recording = True

        def __init__(self) -> None:
            self.write_calls = 0

        def t(self) -> float:
            return 3.25

        def write_frame(self, _screen: object) -> None:
            self.write_calls += 1

    recording = Recording()
    system, builder = _make_provenance_preview_system(
        frame_count=2,
        recording=recording,
        clock=Clock(),
    )
    capture = SimpleNamespace(provenance=None)
    system._recording_capture = capture

    system.draw_frame()
    system.draw_frame()

    assert recording.write_calls == 2
    assert len(builder.calls) == 1
    assert capture.provenance is not None
    assert capture.provenance.frame.t == pytest.approx(3.25)
    assert capture.provenance.frame.frame_index == 0
    assert capture.provenance.frame.quality == "final"
    assert system._provenance_frame_index == 2
    assert system._last_export_snapshot is not None
    assert system._last_export_snapshot.provenance is None


def test_recording_scene_error_pauses_without_writing_last_good_frame() -> None:
    class Clock:
        epoch = 3
        is_playing = False
        speed = 1.0

        def synchronize(self, _t: float) -> None:
            return

    class Recording:
        is_recording = True

        def __init__(self) -> None:
            self.write_calls = 0
            self.paused_errors: list[str] = []

        def t(self) -> float:
            return 4.0

        def write_frame(self, _screen: object) -> None:
            self.write_calls += 1

        def pause_frame(self, error: str) -> None:
            self.paused_errors.append(error)

    previous_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 100),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=3.5,
    )
    recording = Recording()
    runner = _FakeSceneRunner([ValueError("broken recording scene")])
    system = object.__new__(DrawWindowSystem)
    system._perf = PerfCollector(enabled=False)
    system._poll_export_results = lambda: None
    system._midi_session = None
    system._renderer = cast(Any, _FakeRenderer())
    system._framebuffer_size = lambda: (100, 100)
    system._style = cast(Any, _FakeStyleResolver())
    system._recording = cast(Any, recording)
    system._clock = cast(Any, Clock())
    system._scene_runner = cast(Any, runner)
    system._store = ParamStore()
    system._settings = SimpleNamespace(canvas_size=(100, 100))
    system._last_realized_layers = []
    system._last_frame_t = 3.5
    system._last_export_snapshot = previous_snapshot
    system._last_frame_error = None
    system._monitor = None
    system._pending_export_requests = deque()

    system.draw_frame()

    assert recording.write_calls == 0
    assert recording.paused_errors == ["ValueError: broken recording scene"]
    assert recording.t() == pytest.approx(4.0)
    assert system._last_export_snapshot is previous_snapshot


def test_transport_shortcuts_pause_step_reset_and_change_speed() -> None:
    system = object.__new__(DrawWindowSystem)
    system._fps = 20.0
    system._recording = cast(Any, SimpleNamespace(is_recording=False))
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=1.0,
    )

    system._on_key_press(pyglet.window.key.SPACE, 0)
    assert system.transport.is_playing is False
    assert system.transport.t() == pytest.approx(1.0)

    system._on_key_press(pyglet.window.key.RIGHT, 0)
    assert system.transport.t() == pytest.approx(1.05)
    system._on_key_press(pyglet.window.key.LEFT, 0)
    assert system.transport.t() == pytest.approx(1.0)

    system._on_key_press(pyglet.window.key.BRACKETRIGHT, 0)
    assert system.transport.speed == pytest.approx(2.0)
    system._on_key_press(pyglet.window.key.BRACKETLEFT, 0)
    assert system.transport.speed == pytest.approx(1.0)

    system._on_key_press(pyglet.window.key.HOME, 0)
    assert system.transport.t() == pytest.approx(0.0)


def test_svg_captures_are_versioned_and_write_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_export_svg(
        _layers: object, path: Path, *, canvas_size: tuple[int, int]
    ) -> Path:
        assert canvas_size == (320, 240)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>", encoding="utf-8")
        return path

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(320, 240))
    system._capture_paths = VersionedPathAllocator()
    system._capture_service = CaptureService(path_allocator=system._capture_paths)
    system._svg_output_path = tmp_path / "piece.svg"
    system._last_realized_layers = []
    system._last_frame_t = 1.25
    system._last_export_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(320, 240),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=1.25,
    )

    first = system.save_svg()
    second = system.save_svg()

    assert first == tmp_path / "piece.svg"
    assert second == tmp_path / "piece_001.svg"
    manifest_path = capture_manifest_path_for(first)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["t"] == pytest.approx(1.25)
    assert payload["format"] == "svg"
    assert payload["artifact_paths"] == [str(first)]


def test_direct_svg_after_source_reload_keeps_the_visible_frame_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def old_draw(_t: float) -> list[object]:
        return []

    def new_draw(_t: float) -> list[object]:
        return []

    setattr(old_draw, "__grafix_source_bytes__", b"old source generation")
    setattr(new_draw, "__grafix_source_bytes__", b"new source generation")

    def fake_export_svg(
        _layers: object,
        path: Path,
        *,
        canvas_size: tuple[int, int],
    ) -> Path:
        assert canvas_size == (100, 100)
        path.write_text("<svg/>", encoding="utf-8")
        return path

    system, old_builder = _make_provenance_preview_system(
        frame_count=1,
        draw=old_draw,
    )
    system.draw_frame()
    visible = system._last_export_snapshot
    assert visible is not None and visible.provenance is None

    new_builder = _CountingProvenanceBuilder(new_draw, system._store)

    class Controller:
        def __init__(self) -> None:
            self.accepted: list[int] = []

        def poll(
            self,
            *,
            force: bool,
            retain_rollback: bool,
        ) -> SourceReloadResult:
            assert force is True
            assert retain_rollback is True
            return SourceReloadResult(
                status="reloaded",
                generation=1,
                draw=new_draw,
                source=tmp_path / "sketch.py",
            )

        def accept_generation(self, generation: int) -> None:
            self.accepted.append(int(generation))

    controller = Controller()
    system._source_reload = cast(Any, controller)
    replaced: list[object] = []
    system._scene_runner.replace_draw = lambda draw: replaced.append(draw)
    monkeypatch.setattr(
        system,
        "_new_provenance_builder",
        lambda _draw: new_builder,
    )

    assert system._poll_source_reload(force=True) is True
    assert controller.accepted == [1]
    assert replaced == [new_draw]
    assert system._provenance_builder is new_builder

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    system._capture_paths = VersionedPathAllocator()
    system._capture_service = CaptureService(path_allocator=system._capture_paths)
    system._svg_output_path = tmp_path / "piece.svg"

    saved = system.save_svg()

    assert saved == tmp_path / "piece.svg"
    assert len(old_builder.calls) == 1
    assert new_builder.calls == []
    payload = json.loads(
        capture_manifest_path_for(saved).read_text(encoding="utf-8")
    )
    assert (
        payload["source"]["hash"]["value"]
        == old_builder.inner.session.source.sha256
    )
    assert payload["frame"]["index"] == 0
    assert payload["frame"]["quality"] == "draft"


def test_svg_request_before_first_draw_uses_first_visible_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exported_layers: list[tuple[RealizedLayer, ...]] = []

    def fake_export_svg(
        layers: object, path: Path, *, canvas_size: tuple[int, int]
    ) -> Path:
        assert canvas_size == (320, 240)
        exported_layers.append(cast(tuple[RealizedLayer, ...], tuple(layers)))
        path.write_text("<svg>visible</svg>", encoding="utf-8")
        return path

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    monitor_updates: list[dict[str, object]] = []
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(999, 999))
    system._capture_paths = VersionedPathAllocator()
    system._capture_service = CaptureService(path_allocator=system._capture_paths)
    system._svg_output_path = tmp_path / "piece.svg"
    system._last_realized_layers = []
    system._last_frame_t = -1.0
    system._last_export_snapshot = None
    system._last_capture_queue_notice = None
    system._pending_export_requests = deque()
    system._export_jobs = cast(Any, _FakeExportJobs())
    system._monitor = cast(
        Any,
        SimpleNamespace(
            set_capture_queue=lambda **kwargs: monitor_updates.append(dict(kwargs))
        ),
    )
    visible_layer = cast(RealizedLayer, object())
    first_visible = FrameExportSnapshot(
        layers=(visible_layer,),
        canvas_size=(320, 240),
        background_color_rgb01=(0.1, 0.2, 0.3),
        t=2.75,
    )

    system._on_key_press(pyglet.window.key.S, 0)

    assert not (tmp_path / "piece.svg").exists()
    assert len(system._pending_export_requests) == 1
    assert monitor_updates[-1]["request_count"] == 1
    assert "Saved SVG" not in capsys.readouterr().out

    assert system._submit_pending_exports(first_visible) == 1

    saved = tmp_path / "piece.svg"
    assert saved.read_text(encoding="utf-8") == "<svg>visible</svg>"
    assert exported_layers == [(visible_layer,)]
    assert not system._pending_export_requests
    assert monitor_updates[-1]["request_count"] == 0
    payload = json.loads(
        capture_manifest_path_for(saved).read_text(encoding="utf-8")
    )
    assert payload["t"] == pytest.approx(2.75)
    assert payload["canvas_size"] == {"width": 320, "height": 240}
    assert payload["artifact_paths"] == [str(saved)]
    assert f"Saved SVG: {saved}" in capsys.readouterr().out


def test_svg_key_after_first_draw_saves_keypress_snapshot_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exported_layers: list[tuple[RealizedLayer, ...]] = []

    def fake_export_svg(
        layers: object, path: Path, *, canvas_size: tuple[int, int]
    ) -> Path:
        exported_layers.append(cast(tuple[RealizedLayer, ...], tuple(layers)))
        path.write_text("<svg/>", encoding="utf-8")
        return path

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    visible_layer = cast(RealizedLayer, object())
    visible = FrameExportSnapshot(
        layers=(visible_layer,),
        canvas_size=(160, 120),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=1.5,
    )
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(999, 999))
    system._capture_paths = VersionedPathAllocator()
    system._capture_service = CaptureService(path_allocator=system._capture_paths)
    system._svg_output_path = tmp_path / "piece.svg"
    system._last_export_snapshot = visible
    system._last_capture_queue_notice = None
    system._pending_export_requests = deque()
    system._export_jobs = cast(Any, _FakeExportJobs())
    system._monitor = None

    system._on_key_press(pyglet.window.key.S, 0)

    saved = tmp_path / "piece.svg"
    assert saved.exists()
    assert exported_layers == [(visible_layer,)]
    assert not system._pending_export_requests
    payload = json.loads(
        capture_manifest_path_for(saved).read_text(encoding="utf-8")
    )
    assert payload["t"] == pytest.approx(1.5)
    assert payload["canvas_size"] == {"width": 160, "height": 120}


@pytest.mark.parametrize("collision_kind", ["artifact", "manifest"])
def test_svg_late_collision_preserves_external_file_and_retries_next_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision_kind: str,
) -> None:
    def fake_export_svg(
        _layers: object, path: Path, *, canvas_size: tuple[int, int]
    ) -> Path:
        assert canvas_size == (320, 240)
        path.write_bytes(b"new svg")
        return path

    real_publish = capture_module.publish_capture_generation
    collided_path: Path | None = None
    first_call = True

    def publish_with_late_collision(**kwargs: Any) -> object:
        nonlocal collided_path, first_call
        if first_call:
            first_call = False
            artifact = cast(tuple[Path, ...], kwargs["artifact_paths"])[0]
            collided_path = (
                artifact
                if collision_kind == "artifact"
                else cast(Path, kwargs["manifest_path"])
            )
            collided_path.write_bytes(b"external")
        return real_publish(**kwargs)

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    monkeypatch.setattr(
        capture_module,
        "publish_capture_generation",
        publish_with_late_collision,
    )
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(320, 240))
    system._capture_paths = VersionedPathAllocator()
    system._capture_service = CaptureService(path_allocator=system._capture_paths)
    system._svg_output_path = tmp_path / "piece.svg"
    system._last_realized_layers = []
    system._last_frame_t = 4.5
    system._last_export_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(320, 240),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=4.5,
    )

    saved = system.save_svg()

    assert saved == tmp_path / "piece_001.svg"
    assert collided_path is not None
    assert collided_path.read_bytes() == b"external"
    if collision_kind == "manifest":
        # manifest publish failure後、今回 link したbase artifactだけをrollbackする。
        assert not (tmp_path / "piece.svg").exists()
    assert saved.read_bytes() == b"new svg"
    payload = json.loads(
        capture_manifest_path_for(saved).read_text(encoding="utf-8")
    )
    assert payload["t"] == pytest.approx(4.5)
    assert payload["artifact_paths"] == [str(saved)]


class _FakeExportJobs:
    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []
        self.results: list[ExportJobResult] = []
        self.accepting = True

    def submit(self, **kwargs: object) -> object:
        self.submissions.append(dict(kwargs))
        return SimpleNamespace(job_id=len(self.submissions))

    @property
    def can_submit(self) -> bool:
        return bool(self.accepting)

    def poll(self) -> list[ExportJobResult]:
        results, self.results = self.results, []
        return results


def test_pending_capture_materializes_the_first_fresh_frame_once(
    tmp_path: Path,
) -> None:
    system, builder = _make_provenance_preview_system(frame_count=1)
    jobs = _FakeExportJobs()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._capture_paths = VersionedPathAllocator()
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"

    assert system._queue_export_request(ExportKind.PNG) is True
    system.draw_frame()

    assert len(builder.calls) == 1
    assert len(jobs.submissions) == 1
    captured = cast(FrameExportSnapshot, jobs.submissions[0]["snapshot"])
    assert captured.provenance is not None
    assert captured.provenance.frame.t == pytest.approx(2.5)
    assert captured.provenance.frame.frame_index == 0
    assert captured.provenance.frame.quality == "final"
    expected = builder.inner.frame(
        system._store,
        t=2.5,
        frame_index=0,
        quality="final",
        origin="interactive",
    )
    assert captured.provenance == expected
    assert system._last_export_snapshot is not None
    assert system._last_export_snapshot.provenance is None
    assert not system._pending_export_requests


class _DrainingExportJobs:
    """内部 pending も受理し、poll ごとに 1 件成功させる close-drain 用 fake。"""

    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []
        self._active: list[tuple[int, dict[str, object]]] = []
        self.close_calls = 0

    @property
    def can_submit(self) -> bool:
        return True

    @property
    def has_work(self) -> bool:
        return bool(self._active)

    def submit(self, **kwargs: object) -> object:
        job_id = len(self.submissions) + 1
        submission = dict(kwargs)
        self.submissions.append(submission)
        self._active.append((job_id, submission))
        return SimpleNamespace(job_id=job_id)

    def poll(self) -> list[ExportJobResult]:
        if not self._active:
            return []
        job_id, submission = self._active.pop(0)
        return [
            ExportJobResult(
                job_id=job_id,
                kind=cast(ExportKind, submission["kind"]),
                status=ExportJobStatus.SUCCESS,
                output_path=cast(Path, submission["output_path"]),
                paths=(),
            )
        ]

    def close(self) -> None:
        assert not self._active
        self.close_calls += 1


def test_async_capture_reservations_do_not_collide_before_files_exist(
    tmp_path: Path,
) -> None:
    jobs = _FakeExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    system._pending_export_requests = deque()
    snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=2.5,
    )

    system._queue_export_request(ExportKind.PNG)
    system._queue_export_request(ExportKind.PNG)
    system._submit_pending_exports(snapshot)

    paths = [cast(Path, submission["output_path"]) for submission in jobs.submissions]
    assert paths == [tmp_path / "piece.png", tmp_path / "piece_001.png"]

    completed_path = paths[0]
    jobs.results.append(
        ExportJobResult(
            job_id=1,
            kind=ExportKind.PNG,
            status=ExportJobStatus.SUCCESS,
            output_path=completed_path,
            paths=(completed_path,),
        )
    )
    system._poll_export_results()
    # Production ExportJobSystem は artifact + manifest を親側 transaction で
    # 公開する。この fake は path reservation/FIFO だけを検査する。


def test_async_export_failure_is_published_to_shared_diagnostic_center(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "piece.png"
    jobs = _FakeExportJobs()
    jobs.results.append(
        ExportJobResult(
            job_id=1,
            kind=ExportKind.PNG,
            status=ExportJobStatus.ERROR,
            output_path=output_path,
            paths=(),
            error="resvg failed",
        )
    )
    system = object.__new__(DrawWindowSystem)
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {1: (0.0, "png")}
    system._pending_export_requests = deque()
    system._capture_request_limit = 17
    system._last_capture_queue_notice = None
    system._monitor = RuntimeMonitor()

    system._poll_export_results()

    diagnostics = system._monitor.diagnostic_center.snapshot()
    assert len(diagnostics) == 1
    event = diagnostics[0]
    assert event.category == "export"
    assert event.source == str(output_path)
    assert event.details == "resvg failed"
    assert tuple(action.action_id for action in event.actions) == ("copy",)


def test_each_rapid_capture_key_press_becomes_a_fifo_submission(
    tmp_path: Path,
) -> None:
    jobs = _FakeExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._pending_export_requests = deque()
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=2.5,
    )

    system._on_key_press(pyglet.window.key.P, 0)
    system._on_key_press(pyglet.window.key.G, 0)
    system._on_key_press(pyglet.window.key.P, 0)
    system._submit_pending_exports(snapshot)

    assert [submission["kind"] for submission in jobs.submissions] == [
        ExportKind.PNG,
        ExportKind.GCODE,
        ExportKind.PNG,
    ]
    assert [submission["output_path"] for submission in jobs.submissions] == [
        tmp_path / "piece.png",
        tmp_path / "piece.gcode",
        tmp_path / "piece_001.png",
    ]
    assert not system._pending_export_requests


def test_capture_request_uses_frame_visible_at_keypress(tmp_path: Path) -> None:
    jobs = _FakeExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._pending_export_requests = deque()
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    visible_a = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=1.25,
    )
    later_b = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(0.0, 0.0, 0.0),
        t=9.0,
    )
    system._last_export_snapshot = visible_a

    assert system._queue_export_request(ExportKind.PNG)
    # 次の draw が B になっても、既に ExportJobSystem が保持する A を変更しない。
    system._last_export_snapshot = later_b
    system._submit_pending_exports(later_b)

    assert len(jobs.submissions) == 1
    assert jobs.submissions[0]["snapshot"] is visible_a
    assert cast(FrameExportSnapshot, jobs.submissions[0]["snapshot"]).t == pytest.approx(
        1.25
    )


def test_paused_repeated_capture_shares_the_same_visible_snapshot(
    tmp_path: Path,
) -> None:
    jobs = _FakeExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._pending_export_requests = deque()
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    visible = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(0.5, 0.5, 0.5),
        t=3.0,
    )
    system._last_export_snapshot = visible

    assert all(system._queue_export_request(ExportKind.PNG) for _ in range(3))

    assert [submission["snapshot"] for submission in jobs.submissions] == [
        visible,
        visible,
        visible,
    ]


def test_full_export_queue_rejects_capture_without_reserving_a_path(
    tmp_path: Path,
) -> None:
    jobs = _FakeExportJobs()
    jobs.accepting = False
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._pending_export_requests = deque()
    system._queue_export_request(ExportKind.PNG)
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=2.5,
    )

    system._submit_pending_exports(snapshot)
    assert not jobs.submissions
    assert not system._pending_export_requests

    jobs.accepting = True
    later_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(0.0, 0.0, 0.0),
        t=99.0,
    )
    system._last_export_snapshot = later_snapshot
    assert system._queue_export_request(ExportKind.PNG)
    assert jobs.submissions[0]["output_path"] == tmp_path / "piece.png"
    assert jobs.submissions[0]["snapshot"] is later_snapshot


def test_deferred_capture_intents_are_bounded_and_rejection_is_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()

    accepted = [system._queue_export_request(ExportKind.PNG) for _ in range(18)]

    assert accepted == [True] * 17 + [False]
    assert len(system._pending_export_requests) == 17
    output = capsys.readouterr().out
    assert "Capture rejected: PNG" in output
    assert "requests=17/17" in output


def test_pre_frame_capture_limit_is_shared_by_svg_png_and_gcode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()
    system._last_export_snapshot = None
    system._monitor = None

    for _ in range(8):
        system._on_key_press(pyglet.window.key.S, 0)
    accepted_png = [system._queue_export_request(ExportKind.PNG) for _ in range(9)]
    rejected_gcode = system._queue_export_request(ExportKind.GCODE)

    assert accepted_png == [True] * 9
    assert rejected_gcode is False
    assert len(system._pending_export_requests) == 17
    output = capsys.readouterr().out
    assert "Capture rejected: G-code" in output
    assert "requests=17/17" in output


def test_close_drains_bound_and_unbound_capture_requests_in_fifo_order(
    tmp_path: Path,
) -> None:
    jobs = _DrainingExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._export_jobs = cast(Any, jobs)
    system._pending_capture_by_job = {}
    system._pending_export_requests = deque()
    system._png_output_path = tmp_path / "piece.png"
    system._gcode_output_path = tmp_path / "piece.gcode"
    earlier_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=2.5,
    )
    last_displayed_snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(0.0, 0.0, 0.0),
        t=9.0,
    )
    system._last_export_snapshot = None
    system._queue_export_request(ExportKind.PNG)
    system._pending_export_requests[-1].snapshot = earlier_snapshot
    system._queue_export_request(ExportKind.GCODE)
    system._last_export_snapshot = last_displayed_snapshot
    system._recording = cast(Any, SimpleNamespace(is_recording=False))
    system._midi_session = None
    system._scene_runner = cast(Any, SimpleNamespace(close=lambda: None))
    system._renderer = cast(Any, SimpleNamespace(release=lambda: None))
    system.window = cast(Any, SimpleNamespace(close=lambda: None))

    system.close()
    system.close()

    assert [submission["kind"] for submission in jobs.submissions] == [
        ExportKind.PNG,
        ExportKind.GCODE,
    ]
    assert [submission["snapshot"] for submission in jobs.submissions] == [
        earlier_snapshot,
        last_displayed_snapshot,
    ]
    assert not system._pending_export_requests
    assert system._pending_capture_by_job == {}
    assert jobs.close_calls == 1


def test_close_releases_remaining_resources_and_raises_first_cleanup_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    first_error = RuntimeError("export close failed")

    class FaultyExportJobs:
        has_work = False

        def poll(self) -> list[ExportJobResult]:
            calls.append("poll exports")
            return []

        def close(self) -> None:
            calls.append("close exports")
            raise first_error

    class Midi:
        def save(self) -> None:
            calls.append("save midi")

        def close(self) -> None:
            calls.append("close midi")

    def stop_recording(*, timeout_s: float, stop_reason: str) -> None:
        assert stop_reason == "shutdown"
        calls.append("stop recording")

    def close_scene() -> None:
        calls.append("close scene")
        raise RuntimeError("secondary scene close failure")

    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()
    system._pending_capture_by_job = {}
    system._export_jobs = cast(Any, FaultyExportJobs())
    system._recording = cast(Any, SimpleNamespace(is_recording=True))
    system.stop_video_recording = stop_recording
    system._midi_session = MidiSession(
        controller=cast(Any, Midi()),
        frozen_values=None,
    )
    system._scene_runner = cast(Any, SimpleNamespace(close=close_scene))
    system._renderer = cast(
        Any,
        SimpleNamespace(release=lambda: calls.append("release renderer")),
    )

    def switch_context() -> None:
        calls.append("switch context")
        raise RuntimeError("secondary context activation failure")

    system.window = cast(
        Any,
        SimpleNamespace(
            switch_to=switch_context,
            close=lambda: calls.append("close window"),
        ),
    )

    with pytest.raises(RuntimeError, match="export close failed") as exc_info:
        system.close()

    assert exc_info.value is first_error
    assert calls == [
        "stop recording",
        "poll exports",
        "close exports",
        "poll exports",
        "save midi",
        "close midi",
        "close scene",
        "switch context",
        "release renderer",
        "close window",
    ]
    logged = [record.getMessage() for record in caplog.records]
    assert all("close PNG/G-code export worker" not in message for message in logged)
    assert any("close scene runner" in message for message in logged)
    assert any("activate draw GL context" in message for message in logged)
    system.close()


def test_export_shutdown_deadline_cancels_remaining_work_explicitly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class StuckExportJobs:
        has_work = True

        def __init__(self) -> None:
            self.cancel_calls = 0

        def poll(self) -> list[ExportJobResult]:
            return []

        def cancel(self) -> bool:
            self.cancel_calls += 1
            self.has_work = False
            return True

    jobs = StuckExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()
    system._pending_capture_by_job = {}
    system._last_capture_queue_notice = None
    system._monitor = None
    system._export_jobs = cast(Any, jobs)

    completed = system._drain_exports_on_close(timeout_s=0.0)

    assert completed is False
    assert jobs.cancel_calls == 1
    assert "Capture shutdown deadline reached" in capsys.readouterr().out


def test_close_shares_capture_deadline_and_cancels_exports_after_video_timeout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckExportJobs:
        has_work = True

        def __init__(self) -> None:
            self.cancel_calls = 0
            self.close_calls = 0

        def poll(self) -> list[ExportJobResult]:
            return []

        def cancel(self) -> bool:
            self.cancel_calls += 1
            self.has_work = False
            return True

        def close(self) -> None:
            self.close_calls += 1

    now = [10.0]
    monkeypatch.setattr(draw_window_module.time, "monotonic", lambda: now[0])
    timeout_error = TimeoutError("video encoder timed out")
    video_timeouts: list[float] = []

    def stop_recording(*, timeout_s: float, stop_reason: str) -> None:
        assert stop_reason == "shutdown"
        video_timeouts.append(float(timeout_s))
        # ffmpeg finalize が capture 全体 budget を使い切った想定。
        now[0] = 15.0
        raise timeout_error

    jobs = StuckExportJobs()
    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()
    system._pending_capture_by_job = {}
    system._last_capture_queue_notice = None
    system._monitor = None
    system._export_jobs = cast(Any, jobs)
    system._recording = cast(Any, SimpleNamespace(is_recording=True))
    system.stop_video_recording = stop_recording
    system._midi_session = None
    system._scene_runner = cast(Any, SimpleNamespace(close=lambda: None))
    system._renderer = cast(Any, SimpleNamespace(release=lambda: None))
    system.window = cast(Any, SimpleNamespace(close=lambda: None))

    with pytest.raises(TimeoutError, match="video encoder") as exc_info:
        system.close(timeout_s=5.0)

    assert exc_info.value is timeout_error
    assert video_timeouts == [5.0]
    assert jobs.cancel_calls == 1
    assert jobs.close_calls == 1
    assert "Capture shutdown deadline reached" in capsys.readouterr().out


def test_close_switches_to_draw_context_before_renderer_release() -> None:
    calls: list[str] = []
    system = object.__new__(DrawWindowSystem)
    system._pending_export_requests = deque()
    system._pending_capture_by_job = {}
    system._export_jobs = cast(
        Any,
        SimpleNamespace(
            has_work=False,
            poll=lambda: [],
            close=lambda: calls.append("close exports"),
        ),
    )
    system._recording = cast(Any, SimpleNamespace(is_recording=False))
    system._midi_session = None
    system._scene_runner = cast(
        Any, SimpleNamespace(close=lambda: calls.append("close scene"))
    )
    system._renderer = cast(
        Any, SimpleNamespace(release=lambda: calls.append("release renderer"))
    )
    system.window = cast(
        Any,
        SimpleNamespace(
            switch_to=lambda: calls.append("switch context"),
            close=lambda: calls.append("close window"),
        ),
    )

    system.close()

    assert calls[-3:] == ["switch context", "release renderer", "close window"]


def test_partial_draw_window_initialization_releases_acquired_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Window:
        def push_handlers(self, **_kwargs: object) -> None:
            calls.append("push handlers")

        def switch_to(self) -> None:
            calls.append("switch context")

        def close(self) -> None:
            calls.append("close window")

    class Renderer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("create renderer")

        def release(self) -> None:
            calls.append("release renderer")

    class Jobs:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("create exports")

        def close(self) -> None:
            calls.append("close exports")

    monkeypatch.setattr(draw_window_module, "create_draw_window", lambda _settings: Window())
    monkeypatch.setattr(draw_window_module, "DrawRenderer", Renderer)
    monkeypatch.setattr(
        draw_window_module,
        "output_path_for_draw",
        lambda **kwargs: tmp_path / f"piece.{kwargs['ext']}",
    )
    monkeypatch.setattr(
        draw_window_module,
        "default_png_output_path",
        lambda *_args, **_kwargs: tmp_path / "piece.png",
    )
    monkeypatch.setattr(
        draw_window_module,
        "default_video_output_path",
        lambda *_args, **_kwargs: tmp_path / "piece.mp4",
    )
    monkeypatch.setattr(draw_window_module, "ExportJobSystem", Jobs)

    def fail_scene_runner(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("scene runner initialization failed")

    monkeypatch.setattr(draw_window_module, "SceneRunner", fail_scene_runner)

    with pytest.raises(RuntimeError, match="scene runner initialization failed"):
        DrawWindowSystem(
            lambda _t: None,
            settings=RenderSettings(canvas_size=(100, 80)),
            defaults=_DEFAULTS,
            store=ParamStore(),
            n_worker=0,
        )

    assert calls[-4:] == [
        "close exports",
        "switch context",
        "release renderer",
        "close window",
    ]


def test_layer_gcode_allocator_avoids_stale_layer_files(tmp_path: Path) -> None:
    existing = tmp_path / "piece_layer001_ink.gcode"
    existing.write_text("old", encoding="utf-8")
    layer = cast(RealizedLayer, SimpleNamespace(layer=SimpleNamespace(name="ink")))
    snapshot = FrameExportSnapshot(
        layers=(layer,),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=3.0,
    )
    system = object.__new__(DrawWindowSystem)
    system._capture_paths = VersionedPathAllocator()
    system._gcode_output_path = tmp_path / "piece.gcode"

    allocated = system._allocate_gcode_layers_path(snapshot)

    assert allocated == tmp_path / "piece_001.gcode"
    assert existing.read_text(encoding="utf-8") == "old"


class _FakeVideoRecording:
    def __init__(self) -> None:
        self.is_recording = False
        self.path: Path | None = None
        self.current_t = 0.0
        self.stop_timeout_s: float | None = None

    def start(self, **kwargs: object) -> None:
        self.path = cast(Path, kwargs["output_path"])
        self.current_t = float(kwargs["t0"])
        self.is_recording = True

    def t(self) -> float:
        return self.current_t

    def stop_to_staging(
        self,
        *,
        timeout_s: float,
        stop_reason: str,
        abort_reason: str | None,
    ) -> object | None:
        self.stop_timeout_s = float(timeout_s)
        self.is_recording = False
        if self.path is None:
            return None
        staging_path = self.path.with_name(f".{self.path.name}.staging")
        staging_path.write_bytes(b"video")
        return SimpleNamespace(
            staging_path=staging_path,
            output_path=self.path,
            recording=RecordingManifest(
                fps=60.0,
                frame_count=0,
                stop_reason=stop_reason,
                abort_reason=abort_reason,
            ),
        )


class _ConstraintWindow:
    def __init__(self, *, width: int = 640, height: int = 480) -> None:
        self.width = int(width)
        self.height = int(height)
        self.constraint_calls: list[tuple[str, int, int]] = []

    def set_minimum_size(self, width: int, height: int) -> None:
        self.constraint_calls.append(("minimum", int(width), int(height)))

    def set_maximum_size(self, width: int, height: int) -> None:
        self.constraint_calls.append(("maximum", int(width), int(height)))


def _video_system_with_constraint_window(
    *,
    tmp_path: Path,
    recording: _FakeVideoRecording,
    playing: bool,
) -> tuple[DrawWindowSystem, _ConstraintWindow]:
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._video_output_path = tmp_path / "piece.mp4"
    system._recording = cast(Any, recording)
    system._recording_capture = None
    system._preview_was_playing_before_recording = None
    system._recording_window_constraints_locked = False
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=2.0,
        playing=bool(playing),
    )
    system._framebuffer_size = lambda: (1280, 960)
    window = _ConstraintWindow(width=640, height=480)
    system.window = cast(Any, window)
    return system, window


def test_video_recording_locks_window_size_and_restores_constraints_on_stop(
    tmp_path: Path,
) -> None:
    recording = _FakeVideoRecording()
    system, window = _video_system_with_constraint_window(
        tmp_path=tmp_path,
        recording=recording,
        playing=False,
    )

    system.start_video_recording()
    assert window.constraint_calls == [
        ("minimum", 640, 480),
        ("maximum", 640, 480),
    ]
    assert system._recording_window_constraints_locked is True

    recording.current_t = 2.5
    system.stop_video_recording()

    assert window.constraint_calls == [
        ("minimum", 640, 480),
        ("maximum", 640, 480),
        (
            "maximum",
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
        ),
        ("minimum", 320, 320),
    ]
    assert system._recording_window_constraints_locked is False


def test_restore_window_constraints_attempts_both_and_keeps_first_error(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    first_error = RuntimeError("maximum failed")

    class FailingConstraintWindow(_ConstraintWindow):
        def set_maximum_size(self, width: int, height: int) -> None:
            del width, height
            calls.append("maximum")
            raise first_error

        def set_minimum_size(self, width: int, height: int) -> None:
            del width, height
            calls.append("minimum")
            raise RuntimeError("minimum failed")

    system, _window = _video_system_with_constraint_window(
        tmp_path=tmp_path,
        recording=_FakeVideoRecording(),
        playing=False,
    )
    system.window = cast(Any, FailingConstraintWindow())
    system._recording_window_constraints_locked = True

    with pytest.raises(RuntimeError) as exc_info:
        system._restore_draw_window_resize_constraints()

    assert exc_info.value is first_error
    assert calls == ["maximum", "minimum"]
    assert system._recording_window_constraints_locked is True


def test_video_recording_start_failure_restores_window_constraints_and_transport(
    tmp_path: Path,
) -> None:
    class FailingStartRecording(_FakeVideoRecording):
        def start(self, **_kwargs: object) -> None:
            raise RuntimeError("encoder start failed")

    recording = FailingStartRecording()
    system, window = _video_system_with_constraint_window(
        tmp_path=tmp_path,
        recording=recording,
        playing=True,
    )

    with pytest.raises(RuntimeError, match="encoder start failed"):
        system.start_video_recording()

    assert system.transport.is_playing is True
    assert system._recording_capture is None
    assert window.constraint_calls == [
        ("minimum", 640, 480),
        ("maximum", 640, 480),
        (
            "maximum",
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
        ),
        ("minimum", 320, 320),
    ]
    assert system._recording_window_constraints_locked is False


def test_video_recording_stop_failure_still_restores_window_constraints(
    tmp_path: Path,
) -> None:
    class FailingStopRecording(_FakeVideoRecording):
        def stop_to_staging(
            self,
            *,
            timeout_s: float,
            stop_reason: str,
            abort_reason: str | None,
        ) -> object | None:
            del stop_reason, abort_reason
            self.stop_timeout_s = float(timeout_s)
            self.is_recording = False
            raise TimeoutError("encoder stop failed")

    recording = FailingStopRecording()
    system, window = _video_system_with_constraint_window(
        tmp_path=tmp_path,
        recording=recording,
        playing=False,
    )
    system.start_video_recording()

    with pytest.raises(TimeoutError, match="encoder stop failed"):
        system.stop_video_recording()

    assert window.constraint_calls[-2:] == [
        (
            "maximum",
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
            draw_window_module._RESTORED_DRAW_WINDOW_MAX_SIZE,
        ),
        ("minimum", 320, 320),
    ]
    assert system._recording_window_constraints_locked is False


def test_video_capture_uses_a_versioned_path_and_manifest(tmp_path: Path) -> None:
    base_path = tmp_path / "piece.mp4"
    base_path.write_bytes(b"old video")
    recording = _FakeVideoRecording()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._video_output_path = base_path
    system._recording = cast(Any, recording)
    system._recording_capture = None
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=4.25,
        playing=False,
    )
    system._framebuffer_size = lambda: (200, 160)

    system.start_video_recording()
    assert recording.path == tmp_path / "piece_001.mp4"
    assert system.transport.epoch == 1
    recording.current_t = 4.75
    system.stop_video_recording()

    assert base_path.read_bytes() == b"old video"
    payload = json.loads(
        capture_manifest_path_for(tmp_path / "piece_001.mp4").read_text(
            encoding="utf-8"
        )
    )
    assert payload["schema_version"] == 2
    assert payload["t"] == pytest.approx(4.25)
    assert payload["format"] == "mp4"
    assert payload["output"]["size"] == {"width": 200, "height": 160}
    assert payload["recording"] == {
        "fps": 60.0,
        "frame_count": 0,
        "dropped_frame_count": 0,
        "duplicated_frame_count": 0,
        "error_count": 0,
        "error_policy": "pause",
        "stop_reason": "user_stop",
        "abort_reason": None,
        "last_error": None,
    }
    assert system.transport.t() == pytest.approx(4.75)
    assert system.transport.is_playing is False
    assert system.transport.epoch == 2


def test_video_capture_restores_playing_state_at_the_recorded_end_time(
    tmp_path: Path,
) -> None:
    recording = _FakeVideoRecording()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._video_output_path = tmp_path / "piece.mp4"
    system._recording = cast(Any, recording)
    system._recording_capture = None
    system._preview_was_playing_before_recording = None
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=2.0,
        playing=True,
    )
    system._framebuffer_size = lambda: (200, 160)

    system.start_video_recording()
    assert system.transport.is_playing is False
    recording.current_t = 2.5
    system.stop_video_recording()

    assert system.transport.t() == pytest.approx(2.5)
    assert system.transport.is_playing is True


def test_video_artifact_and_manifest_retry_together_after_late_collision(
    tmp_path: Path,
) -> None:
    recording = _FakeVideoRecording()
    system = object.__new__(DrawWindowSystem)
    system._settings = SimpleNamespace(canvas_size=(100, 80))
    system._capture_paths = VersionedPathAllocator()
    system._video_output_path = tmp_path / "piece.mp4"
    system._recording = cast(Any, recording)
    system._recording_capture = None
    system._preview_was_playing_before_recording = None
    system._clock = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=3.0,
        playing=False,
    )
    system._framebuffer_size = lambda: (200, 160)

    system.start_video_recording()
    first_path = cast(Path, recording.path)
    external_manifest = capture_manifest_path_for(first_path)
    external_manifest.write_text("external", encoding="utf-8")
    system.stop_video_recording()

    retried_path = tmp_path / "piece_001.mp4"
    assert not first_path.exists()
    assert external_manifest.read_text(encoding="utf-8") == "external"
    assert retried_path.read_bytes() == b"video"
    payload = json.loads(
        capture_manifest_path_for(retried_path).read_text(encoding="utf-8")
    )
    assert payload["artifact_paths"] == [str(retried_path)]
    assert payload["t"] == pytest.approx(3.0)
