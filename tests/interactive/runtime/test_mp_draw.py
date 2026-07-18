from __future__ import annotations

import multiprocessing as mp
import os
import queue
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

import grafix.interactive.runtime.scene_runner as scene_runner_module
from grafix.api import G
from grafix.core.geometry import Geometry
from grafix.core.layer import LayerStyleDefaults
from grafix.core.operation_diagnostics import emit_operation_diagnostic
from grafix.core.parameters import (
    FrameParamRecord,
    MidiFrameSnapshot,
    ParameterKey,
    ParamMeta,
    ParamStore,
    parameter_context,
)
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.layer_style import (
    LAYER_STYLE_LINE_COLOR,
    LAYER_STYLE_LINE_THICKNESS,
    layer_style_key,
)
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.core.resource_budget import ResourceBudget
from grafix.core.preview_quality import current_preview_quality
from grafix.core.scene import normalize_scene
from grafix.interactive.runtime.mp_draw import (
    DrawResult,
    MpDraw,
    MpDrawWorkerError,
    _DrawTask,
    _SnapshotUpdate,
)
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.runtime.scene_runner import SceneRunner

_WAIT_TIMEOUT_S = 8.0


def _empty_draw(_t: float) -> Geometry:
    return Geometry.create(op="concat")


def _system_exit_draw(_t: float) -> Geometry:
    raise SystemExit(3)


def _os_exit_draw(_t: float) -> Geometry:
    os._exit(7)


def _draw_that_fails_at_one(t: float) -> Geometry:
    if float(t) >= 1.0:
        raise ValueError("intentional frame failure")
    return Geometry.create(op="concat")


def _draw_that_hangs_at_one(t: float) -> Geometry:
    if float(t) == 1.0:
        time.sleep(60.0)
    return Geometry.create(op="concat")


def _midi_parameter_draw(_t: float) -> Geometry:
    return G.circle(radius=0.25, key="midi-roundtrip")


def _quality_diagnostic_draw(_t: float) -> Geometry:
    quality = current_preview_quality()
    emit_operation_diagnostic(
        op="quality",
        original_value=quality,
        effective_value=quality,
        reason="quality roundtrip",
        severity="info",
    )
    return Geometry.create(op="concat")


def _wait_for_result(mp_draw: MpDraw) -> DrawResult:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        result = mp_draw.poll_latest()
        if result is not None:
            return result
        time.sleep(0.01)
    pytest.fail("mp-draw result timeout")


def _wait_for_worker_error(mp_draw: MpDraw) -> MpDrawWorkerError:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            mp_draw.poll_latest()
        except MpDrawWorkerError as exc:
            return exc
        time.sleep(0.01)
    pytest.fail("mp-draw worker death timeout")


@pytest.mark.parametrize("n_worker", [1, 2])
def test_workers_report_ready_and_normal_close_leaves_no_children(
    n_worker: int,
) -> None:
    """1 worker と従来の複数 worker が同じ lifecycle 契約を満たす。"""

    mp_draw = MpDraw(_empty_draw, n_worker=n_worker)
    procs = list(mp_draw._procs)
    worker_pids = {int(proc.pid) for proc in procs if proc.pid is not None}

    assert mp_draw._ready_worker_pids == worker_pids

    mp_draw.submit(t=0.125, snapshot_revision=0, snapshot={})
    result = _wait_for_result(mp_draw)
    assert result.error is None
    assert result.t == pytest.approx(0.125)
    assert len(result.layers) == 1

    mp_draw.close()
    mp_draw.close()

    with pytest.raises(RuntimeError) as exc_info:
        mp_draw.poll_latest()
    assert not isinstance(exc_info.value, MpDrawWorkerError)

    assert all(not proc.is_alive() for proc in procs)
    assert all(proc.exitcode == 0 for proc in procs)
    active_pids = {proc.pid for proc in mp.active_children()}
    assert worker_pids.isdisjoint(active_pids)


def test_mp_draw_rejects_zero_workers() -> None:
    with pytest.raises(ValueError, match="1 以上"):
        MpDraw(_empty_draw, n_worker=0)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_mp_draw_rejects_invalid_evaluation_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="evaluation_timeout"):
        MpDraw(_empty_draw, n_worker=1, evaluation_timeout=timeout)


def test_hung_evaluation_restarts_worker_and_recovers_without_child_leak() -> None:
    mp_draw = MpDraw(
        _draw_that_hangs_at_one,
        n_worker=1,
        evaluation_timeout=0.1,
    )
    old_procs = list(mp_draw._procs)
    all_worker_pids = {int(proc.pid) for proc in old_procs if proc.pid is not None}

    try:
        mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
        successful = _wait_for_result(mp_draw)
        assert successful.error is None
        assert successful.generation == 0

        mp_draw.submit(t=1.0, snapshot_revision=0, snapshot={})
        call_durations: list[float] = []
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while mp_draw.generation == 0 and time.monotonic() < deadline:
            started_at = time.monotonic()
            assert mp_draw.poll_latest() is None
            call_durations.append(time.monotonic() - started_at)
            time.sleep(0.01)

        assert mp_draw.generation == 1
        assert mp_draw.restart_count == 1
        assert mp_draw.last_restart_reason is not None
        assert "evaluation timeout" in mp_draw.last_restart_reason
        # timeout/restart の呼び出しは ready 待ちをせず、UI loop を有界に保つ。
        assert max(call_durations) < 0.75
        # restart 中も preview fallback は直近の成功 frame を保持する。
        assert mp_draw.latest_successful_result() is successful

        assert all(not proc.is_alive() for proc in old_procs)
        new_pids = {
            int(proc.pid) for proc in mp_draw._procs if proc.pid is not None
        }
        all_worker_pids.update(new_pids)
        assert new_pids.isdisjoint(
            {int(proc.pid) for proc in old_procs if proc.pid is not None}
        )

        # 新世代は snapshot ACK をまだ持たないため、task 同梱 snapshot だけで
        # 新しい revision を評価できなければならない。
        mp_draw.submit(t=0.25, snapshot_revision=7, snapshot={})
        recovered = _wait_for_result(mp_draw)
        assert recovered.error is None
        assert recovered.t == pytest.approx(0.25)
        assert recovered.generation == 1
        assert recovered.snapshot_revision == 7
        assert recovered.worker_pid in new_pids
    finally:
        mp_draw.close()

    active_pids = {
        int(proc.pid) for proc in mp.active_children() if proc.pid is not None
    }
    assert all_worker_pids.isdisjoint(active_pids)


def test_single_slot_task_queue_drops_old_frame_and_keeps_latest() -> None:
    """1-worker 相当の満杯 queue では待機中の古い frame だけを置換する。"""

    old = _DrawTask(
        frame_id=1,
        t=1.0,
        snapshot_revision=7,
        cc_snapshot=None,
    )
    latest = _DrawTask(
        frame_id=2,
        t=2.0,
        snapshot_revision=7,
        cc_snapshot=None,
    )
    task_q: queue.Queue[object] = queue.Queue(maxsize=1)
    task_q.put(old)

    mp_draw = object.__new__(MpDraw)
    mp_draw._task_q = cast(Any, task_q)
    mp_draw._ready_worker_pids = {101}
    mp_draw._worker_snapshot_revisions = {101: 7}
    mp_draw._pending_task = latest

    mp_draw._enqueue_pending()

    assert mp_draw._pending_task is None
    assert task_q.get_nowait() is latest
    assert mp_draw.task_enqueue_count == 1
    assert mp_draw.task_drop_count == 1


def test_error_result_keeps_last_successful_layers_for_preview() -> None:
    mp_draw = MpDraw(_draw_that_fails_at_one, n_worker=2)
    try:
        mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
        successful = _wait_for_result(mp_draw)
        assert successful.error is None
        assert successful.t == pytest.approx(0.0)
        assert mp_draw.latest_layers() is successful.layers

        mp_draw.submit(t=1.0, snapshot_revision=0, snapshot={})
        failed = _wait_for_result(mp_draw)
        assert failed.error is not None
        assert failed.t == pytest.approx(1.0)
        assert "intentional frame failure" in failed.error

        # poll_latest() は失敗を通知するが、preview 用 scene まで空にしない。
        assert mp_draw.latest_layers() is successful.layers
    finally:
        mp_draw.close()


def test_worker_roundtrip_preserves_frozen_midi_value_source() -> None:
    store = ParamStore()
    with parameter_context(store):
        _midi_parameter_draw(0.0)
    snapshot = store_snapshot(store)
    radius_key = next(
        key for key in snapshot if key.op == "circle" and key.arg == "radius"
    )
    radius_meta = store.get_meta(radius_key)
    assert radius_meta is not None
    ok, error = update_state_from_ui(
        store,
        radius_key,
        0.25,
        meta=radius_meta,
        override=False,
        cc_key=7,
    )
    assert ok and error is None

    mp_draw = MpDraw(_midi_parameter_draw, n_worker=1)
    try:
        mp_draw.submit(
            t=0.0,
            snapshot_revision=store.revision,
            snapshot=store_snapshot(store),
            cc_snapshot=MidiFrameSnapshot.from_mapping(
                {7: 0.5},
                source="midi_frozen",
            ),
        )
        result = _wait_for_result(mp_draw)
    finally:
        mp_draw.close()

    radius_record = next(record for record in result.records if record.key == radius_key)
    assert radius_record.source == "midi_frozen"
    assert radius_record.effective == pytest.approx(100.0)
    assert result.snapshot_revision == store.revision


def test_worker_result_carries_explicit_epoch() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    try:
        mp_draw.submit(
            t=4.25,
            snapshot_revision=0,
            snapshot={},
            epoch=7,
        )
        result = _wait_for_result(mp_draw)
        assert mp_draw.current_epoch == 7
        assert result.epoch == 7
        assert result.t == pytest.approx(4.25)
    finally:
        mp_draw.close()


def test_batched_drain_keeps_success_time_when_a_later_result_is_an_error() -> None:
    """batch の終端 error と preview 用 success を同じ result として混同しない。"""

    successful = DrawResult(
        frame_id=10,
        t=0.25,
        layers=normalize_scene(_empty_draw(0.25)),
        records=[],
        labels=[],
    )
    failed = DrawResult(
        frame_id=11,
        t=0.5,
        layers=[],
        records=[],
        labels=[],
        error="later frame failed",
    )
    result_q: queue.Queue[object] = queue.Queue()
    result_q.put(successful)
    result_q.put(failed)

    mp_draw = object.__new__(MpDraw)
    mp_draw._result_q = cast(Any, result_q)
    mp_draw._latest_received = None
    mp_draw._latest_successful = None
    mp_draw._completed_result_count = 0
    mp_draw._drain_result_queue()

    assert mp_draw._latest_received is failed
    latest_successful = mp_draw.latest_successful_result()
    assert latest_successful is successful
    assert latest_successful.t == pytest.approx(0.25)


def test_draw_result_keeps_legacy_constructor_shape() -> None:
    """t/epoch 追加後も旧 positional/keyword constructor を維持する。"""

    positional = DrawResult(1, [], [], [], "legacy error")
    keyword = DrawResult(
        frame_id=2,
        layers=[],
        records=[],
        labels=[],
        error=None,
    )

    assert positional.error == "legacy error"
    assert positional.t == pytest.approx(0.0)
    assert positional.epoch == 0
    assert positional.snapshot_revision == 0
    assert keyword.t == pytest.approx(0.0)
    assert keyword.epoch == 0
    assert keyword.snapshot_revision == 0


def test_result_drain_discards_old_epoch_and_keeps_diagnostic() -> None:
    stale_error = DrawResult(
        frame_id=10,
        layers=[],
        records=[],
        labels=[],
        error="old timeline failure",
        t=99.0,
        epoch=1,
    )
    fresh = DrawResult(
        frame_id=11,
        layers=normalize_scene(_empty_draw(2.0)),
        records=[],
        labels=[],
        t=2.0,
        epoch=2,
    )
    result_q: queue.Queue[object] = queue.Queue()
    result_q.put(stale_error)
    result_q.put(fresh)

    mp_draw = object.__new__(MpDraw)
    mp_draw._result_q = cast(Any, result_q)
    mp_draw._current_epoch = 2
    mp_draw._latest_received = None
    mp_draw._latest_successful = None
    mp_draw._completed_result_count = 0
    mp_draw._stale_result_count = 0
    mp_draw._last_stale_result = None
    mp_draw._drain_result_queue()

    assert mp_draw._latest_received is fresh
    assert mp_draw.latest_successful_result() is fresh
    assert mp_draw.completed_result_count == 2
    assert mp_draw.stale_result_count == 1
    assert mp_draw.last_stale_result == (10, 1, 2)


def test_result_drain_rejects_result_from_old_worker_generation() -> None:
    cached = DrawResult(
        frame_id=10,
        layers=normalize_scene(_empty_draw(0.0)),
        records=[],
        labels=[],
        generation=1,
    )
    stale = DrawResult(
        frame_id=999,
        layers=normalize_scene(_empty_draw(9.0)),
        records=[],
        labels=[],
        generation=0,
    )
    result_q: queue.Queue[object] = queue.Queue()
    result_q.put(stale)

    mp_draw = object.__new__(MpDraw)
    mp_draw._result_q = cast(Any, result_q)
    mp_draw._generation = 1
    mp_draw._current_epoch = 0
    mp_draw._latest_received = cached
    mp_draw._latest_successful = cached
    mp_draw._active_tasks_by_pid = {}
    mp_draw._completed_result_count = 0
    mp_draw._stale_generation_result_count = 0
    mp_draw._last_stale_generation_result = None

    mp_draw._drain_result_queue()

    assert mp_draw._latest_received is cached
    assert mp_draw.latest_successful_result() is cached
    assert mp_draw.completed_result_count == 0
    assert mp_draw.stale_generation_result_count == 1
    assert mp_draw.last_stale_generation_result == (999, 0, 1)


def test_begin_epoch_invalidates_cached_result_and_queued_task() -> None:
    cached = DrawResult(
        frame_id=3,
        layers=normalize_scene(_empty_draw(3.0)),
        records=[],
        labels=[],
        t=3.0,
        epoch=0,
    )
    task = _DrawTask(
        frame_id=4,
        t=4.0,
        snapshot_revision=0,
        cc_snapshot=None,
        epoch=0,
    )
    task_q: queue.Queue[object] = queue.Queue()
    task_q.put(task)

    mp_draw = object.__new__(MpDraw)
    mp_draw._closed = False
    mp_draw._procs = []
    mp_draw._current_epoch = 0
    mp_draw._result_q = cast(Any, queue.Queue())
    mp_draw._task_q = cast(Any, task_q)
    mp_draw._latest_received = cached
    mp_draw._latest_successful = cached
    mp_draw._pending_task = task

    assert mp_draw.begin_epoch(1) == 1
    assert mp_draw.current_epoch == 1
    assert mp_draw._latest_received is None
    assert mp_draw.latest_successful_result() is None
    assert mp_draw._pending_task is None
    assert task_q.empty()


@pytest.mark.parametrize(
    ("draw", "expected_exitcode"),
    [
        pytest.param(_system_exit_draw, 3, id="SystemExit"),
        pytest.param(_os_exit_draw, 7, id="os._exit"),
    ],
)
def test_fatal_draw_exit_fails_fast_with_worker_identity(
    draw: Callable[[float], Geometry], expected_exitcode: int
) -> None:
    mp_draw = MpDraw(draw, n_worker=2)
    workers = {(proc.name, proc.pid) for proc in mp_draw._procs}

    try:
        try:
            mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
        except MpDrawWorkerError as exc:
            error = exc
        else:
            error = _wait_for_worker_error(mp_draw)
    finally:
        mp_draw.close()

    assert (error.worker, error.pid) in workers
    assert error.exitcode == expected_exitcode
    assert f"exitcode={expected_exitcode}" in str(error)


def test_poll_detects_single_worker_death_without_fallback() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    dead = mp_draw._procs[0]
    dead.terminate()
    dead.join(timeout=_WAIT_TIMEOUT_S)

    try:
        with pytest.raises(MpDrawWorkerError) as exc_info:
            mp_draw.poll_latest()
    finally:
        mp_draw.close()

    assert exc_info.value.worker == dead.name
    assert exc_info.value.pid == dead.pid
    assert exc_info.value.exitcode == dead.exitcode


def test_submit_detects_all_worker_death_without_fallback() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    procs = list(mp_draw._procs)
    for proc in procs:
        proc.terminate()
    for proc in procs:
        proc.join(timeout=_WAIT_TIMEOUT_S)

    try:
        with pytest.raises(MpDrawWorkerError) as exc_info:
            mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
    finally:
        mp_draw.close()

    identities = {(proc.name, proc.pid, proc.exitcode) for proc in procs}
    error = exc_info.value
    assert (error.worker, error.pid, error.exitcode) in identities


class _TrackedQueue:
    def __init__(self) -> None:
        self.close_calls = 0
        self.join_thread_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    def join_thread(self) -> None:
        self.join_thread_calls += 1


def test_close_is_idempotent_and_joins_both_queue_threads() -> None:
    task_q = _TrackedQueue()
    result_q = _TrackedQueue()
    mp_draw = object.__new__(MpDraw)
    mp_draw._closed = False
    mp_draw._procs = []
    mp_draw._task_q = cast(Any, task_q)
    mp_draw._control_qs = []
    mp_draw._pending_snapshot_updates = {}
    mp_draw._queued_snapshot_revisions = {}
    mp_draw._control_index_by_pid = {}
    mp_draw._result_q = cast(Any, result_q)

    mp_draw.close()
    mp_draw.close()

    assert task_q.close_calls == 1
    assert task_q.join_thread_calls == 1
    assert result_q.close_calls == 1
    assert result_q.join_thread_calls == 1


class _DeadMpDraw:
    def __init__(self, error: MpDrawWorkerError) -> None:
        self.error = error
        self.close_calls = 0

    def submit(self, **_kwargs: object) -> None:
        raise self.error

    def close(self) -> None:
        self.close_calls += 1


class _BatchedSuccessThenErrorMpDraw:
    """success frame とより新しい error frame の同時 drain を模す。"""

    def __init__(self) -> None:
        self.success = DrawResult(
            frame_id=10,
            t=0.25,
            layers=normalize_scene(_empty_draw(0.25)),
            records=[],
            labels=[],
        )
        self.error = DrawResult(
            frame_id=11,
            t=0.5,
            layers=[],
            records=[],
            labels=[],
            error="later frame failed",
        )
        self.poll_calls = 0
        self.close_calls = 0

    def submit(self, **_kwargs: object) -> None:
        return

    def poll_latest(self) -> DrawResult | None:
        self.poll_calls += 1
        if self.poll_calls == 1:
            # MpDraw.poll_latest() は batch の最新 result（ここでは error）を
            # 通知する一方、latest_successful_result() は frame 10 を保持する。
            return self.error
        return None

    def latest_successful_result(self) -> DrawResult:
        return self.success

    def close(self) -> None:
        self.close_calls += 1


class _EpochMpDraw:
    """SceneRunner の epoch 遷移と fresh 待ちを決定的に模す。"""

    def __init__(self, result: DrawResult | None) -> None:
        self.result = result
        self.current_epoch = 0
        self.begin_calls: list[int] = []
        self.submitted_epochs: list[int] = []
        self._published = False
        self.close_calls = 0

    def begin_epoch(self, epoch: int | None = None) -> int:
        self.current_epoch = self.current_epoch + 1 if epoch is None else int(epoch)
        self.begin_calls.append(self.current_epoch)
        # cached old result を invalidation する MpDraw の契約を模す。
        self.result = None
        self._published = False
        return self.current_epoch

    def submit(self, **kwargs: object) -> None:
        self.submitted_epochs.append(int(cast(int, kwargs["epoch"])))

    def poll_latest(self) -> DrawResult | None:
        if self.result is None or self._published:
            return None
        self._published = True
        return self.result

    def latest_successful_result(self) -> DrawResult | None:
        if self.result is None or self.result.error is not None:
            return None
        return self.result

    def close(self) -> None:
        self.close_calls += 1


class _IdleMpDraw:
    """SceneRunner の dispatch 境界だけを観測する non-blocking fake。"""

    instances: list[_IdleMpDraw] = []

    def __init__(
        self,
        _draw: Callable[[float], Geometry],
        *,
        n_worker: int,
        evaluation_timeout: float | None,
    ) -> None:
        self.n_worker = int(n_worker)
        self.evaluation_timeout = evaluation_timeout
        self.submit_calls: list[dict[str, object]] = []
        self.close_calls = 0
        type(self).instances.append(self)

    def submit(self, **kwargs: object) -> None:
        self.submit_calls.append(dict(kwargs))

    def poll_latest(self) -> None:
        return None

    def latest_successful_result(self) -> None:
        return None

    def begin_epoch(self, _epoch: int | None = None) -> int:
        return 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.mark.parametrize("n_worker", [1, 2])
def test_scene_runner_uses_background_evaluation_for_positive_worker_count(
    monkeypatch: pytest.MonkeyPatch,
    n_worker: int,
) -> None:
    """preview の run は positive worker count で user draw を main 実行しない。"""

    draw_calls: list[float] = []

    def draw(t: float) -> Geometry:
        draw_calls.append(float(t))
        return Geometry.create(op="concat")

    _IdleMpDraw.instances = []
    monkeypatch.setattr(scene_runner_module, "MpDraw", _IdleMpDraw)
    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=n_worker)
    try:
        assert runner.run(
            1.25,
            store=ParamStore(),
            cc_snapshot=None,
            defaults=LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01),
            recording=False,
        ) == []

        fake = _IdleMpDraw.instances[-1]
        assert fake.n_worker == n_worker
        assert fake.evaluation_timeout == pytest.approx(5.0)
        assert len(fake.submit_calls) == 1
        assert fake.submit_calls[0]["t"] == pytest.approx(1.25)
        assert draw_calls == []
        assert runner.last_evaluation_succeeded is None
    finally:
        runner.close()

    assert fake.close_calls == 1


def test_scene_runner_passes_evaluation_timeout_to_mp_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _IdleMpDraw.instances = []
    monkeypatch.setattr(scene_runner_module, "MpDraw", _IdleMpDraw)
    runner = SceneRunner(
        _empty_draw,
        perf=PerfCollector(enabled=False),
        n_worker=1,
        evaluation_timeout=0.25,
    )
    try:
        assert _IdleMpDraw.instances[-1].evaluation_timeout == pytest.approx(0.25)
    finally:
        runner.close()


def test_scene_runner_replace_draw_retires_old_worker_and_keeps_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _IdleMpDraw.instances = []
    monkeypatch.setattr(scene_runner_module, "MpDraw", _IdleMpDraw)
    first_draw = _empty_draw

    def second_draw(_t: float) -> Geometry:
        return Geometry.create(op="concat")

    runner = SceneRunner(
        first_draw,
        perf=PerfCollector(enabled=False),
        n_worker=2,
        evaluation_timeout=0.75,
    )
    first_worker = _IdleMpDraw.instances[-1]
    runner.replace_draw(second_draw)
    second_worker = _IdleMpDraw.instances[-1]

    assert second_worker is not first_worker
    assert first_worker.close_calls == 1
    assert second_worker.n_worker == 2
    assert second_worker.evaluation_timeout == pytest.approx(0.75)
    assert runner._draw is second_draw
    assert runner._mp_draw is second_worker

    runner.close()
    assert second_worker.close_calls == 1


def test_scene_runner_replace_draw_failure_keeps_current_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _IdleMpDraw.instances = []
    monkeypatch.setattr(scene_runner_module, "MpDraw", _IdleMpDraw)
    runner = SceneRunner(
        _empty_draw,
        perf=PerfCollector(enabled=False),
        n_worker=1,
    )
    current_worker = _IdleMpDraw.instances[-1]

    def fail_to_start(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(scene_runner_module, "MpDraw", fail_to_start)
    with pytest.raises(RuntimeError, match="spawn failed"):
        runner.replace_draw(lambda _t: Geometry.create(op="concat"))

    assert runner._draw is _empty_draw
    assert runner._mp_draw is current_worker
    assert current_worker.close_calls == 0
    runner.close()
    assert current_worker.close_calls == 1


def test_scene_runner_zero_runs_synchronously_without_constructing_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw_calls: list[float] = []

    def draw(t: float) -> Geometry:
        draw_calls.append(float(t))
        return Geometry.create(op="concat")

    def unexpected_mp_draw(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("n_worker=0 must not construct MpDraw")

    monkeypatch.setattr(scene_runner_module, "MpDraw", unexpected_mp_draw)
    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=0)
    try:
        runner.run(
            2.5,
            store=ParamStore(),
            cc_snapshot=None,
            defaults=LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01),
            recording=False,
        )
        assert draw_calls == [2.5]
        assert runner.last_evaluation_succeeded is True
        assert runner.last_evaluation_t == pytest.approx(2.5)
        assert runner.last_realized_snapshot_revision == 0
    finally:
        runner.close()


def test_scene_runner_uses_draft_for_preview_and_final_for_recording() -> None:
    qualities: list[str] = []

    def draw(_t: float) -> Geometry:
        qualities.append(current_preview_quality())
        return Geometry.create(op="concat")

    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=0)
    try:
        for recording in (False, True):
            runner.run(
                0.0,
                store=ParamStore(),
                cc_snapshot=None,
                defaults=LayerStyleDefaults(
                    color=(0.0, 0.0, 0.0),
                    thickness=0.01,
                ),
                recording=recording,
            )
    finally:
        runner.close()

    assert qualities == ["draft", "final"]


def test_mp_draw_quality_roundtrips_into_worker_context() -> None:
    mp_draw = MpDraw(_quality_diagnostic_draw, n_worker=1)
    try:
        mp_draw.submit(
            t=0.0,
            snapshot_revision=0,
            snapshot={},
            quality="final",
        )
        result = _wait_for_result(mp_draw)
        assert result.error is None
        assert result.diagnostics[0].effective_value == "final"
        assert result.worker_lag_ms is not None
        assert result.worker_lag_ms >= 0.0
    finally:
        mp_draw.close()


def test_scene_runner_rejects_negative_worker_count() -> None:
    with pytest.raises(ValueError, match="0 以上"):
        SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=-1)


def test_recording_remains_synchronous_with_background_preview_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draw_calls: list[float] = []

    def draw(t: float) -> Geometry:
        draw_calls.append(float(t))
        return Geometry.create(op="concat")

    _IdleMpDraw.instances = []
    monkeypatch.setattr(scene_runner_module, "MpDraw", _IdleMpDraw)
    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=1)
    try:
        runner.run(
            3.75,
            store=ParamStore(),
            cc_snapshot=None,
            defaults=LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01),
            recording=True,
        )

        fake = _IdleMpDraw.instances[-1]
        assert draw_calls == [3.75]
        assert fake.submit_calls == []
        assert runner.last_evaluation_succeeded is True
        assert runner.last_evaluation_t == pytest.approx(3.75)
    finally:
        runner.close()


def test_scene_runner_propagates_worker_death_without_sync_fallback() -> None:
    draw_calls = 0

    def draw(_t: float) -> Geometry:
        nonlocal draw_calls
        draw_calls += 1
        return Geometry.create(op="concat")

    error = MpDrawWorkerError(worker="dead", pid=123, exitcode=7)
    dead_mp_draw = _DeadMpDraw(error)
    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, dead_mp_draw)

    with pytest.raises(MpDrawWorkerError) as exc_info:
        runner.run(
            0.0,
            store=ParamStore(),
            cc_snapshot=None,
            defaults=LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01),
            recording=False,
        )

    assert exc_info.value is error
    assert draw_calls == 0

    runner.close()
    runner.close()
    assert dead_mp_draw.close_calls == 1


def test_scene_runner_couples_output_time_to_batched_success_before_later_error() -> None:
    """後続 error の `t` ではなく、実際に realize した success の `t` を返す。"""

    batched = _BatchedSuccessThenErrorMpDraw()
    runner = SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, batched)
    store = ParamStore()
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    try:
        with pytest.raises(RuntimeError, match="later frame failed"):
            runner.run(
                1.0,
                store=store,
                cc_snapshot=None,
                defaults=defaults,
                recording=False,
            )

        # error frame 自身は realized output ではないため、その t=0.5 を
        # capture/manifest 用状態へ進めない。
        assert runner.last_evaluation_succeeded is False
        assert runner.last_evaluation_t is None
        assert runner.last_realized_t is None

        realized = runner.run(
            1.1,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
        )

        assert realized
        # error より後に到着した回復ではないため、error 解除用
        # status は None のまま。一方、出力時刻は実際に realize した
        # frame 10 の t=0.25 を返す。
        assert runner.last_evaluation_succeeded is None
        assert runner.last_output_updated is True
        assert runner.last_evaluation_t is None
        assert runner.last_realized_t == pytest.approx(0.25)
    finally:
        runner.close()

    assert batched.close_calls == 1


def test_scene_runner_does_not_rerealize_same_mp_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = DrawResult(
        frame_id=1,
        layers=normalize_scene(_empty_draw(1.0)),
        records=[],
        labels=[],
        t=1.0,
        snapshot_revision=0,
    )
    mp_draw = _EpochMpDraw(result)
    original_realize_scene = scene_runner_module.realize_scene
    realize_calls = 0

    def counted_realize_scene(*args: object, **kwargs: object):
        nonlocal realize_calls
        realize_calls += 1
        return original_realize_scene(*args, **kwargs)

    monkeypatch.setattr(
        scene_runner_module,
        "realize_scene",
        counted_realize_scene,
    )
    runner = SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, mp_draw)
    store = ParamStore()
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    try:
        first = runner.run(
            1.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
        )
        assert runner.last_output_updated is True
        color_key = layer_style_key("implicit:1", LAYER_STYLE_LINE_COLOR)
        thickness_key = layer_style_key(
            "implicit:1",
            LAYER_STYLE_LINE_THICKNESS,
        )
        color_meta = store.get_meta(color_key)
        thickness_meta = store.get_meta(thickness_key)
        assert color_meta is not None
        assert thickness_meta is not None
        assert update_state_from_ui(
            store,
            color_key,
            (255, 0, 0),
            meta=color_meta,
            override=True,
        )[0]
        assert update_state_from_ui(
            store,
            thickness_key,
            0.02,
            meta=thickness_meta,
            override=True,
        )[0]
        second = runner.run(
            2.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
        )
        third = runner.run(
            3.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
        )
        assert second[0].realized is first[0].realized
        assert third[0] is second[0]
        assert second[0].cache_key == first[0].cache_key
        assert first[0].color == (0.0, 0.0, 0.0)
        assert second[0].color == (1.0, 0.0, 0.0)
        assert second[0].thickness == pytest.approx(0.02)
        assert realize_calls == 1
        assert runner.last_realized_t == pytest.approx(1.0)
        assert runner.last_output_updated is False
        assert runner.is_waiting_for_fresh_result is True
    finally:
        runner.close()


def test_scene_runner_retains_recording_frame_until_fresh_preview_result() -> None:
    """録画終了時に録画前の mp cache へ巻き戻らない。"""

    old_preview = DrawResult(
        frame_id=1,
        layers=normalize_scene(_empty_draw(1.0)),
        records=[],
        labels=[],
        t=1.0,
        epoch=0,
        snapshot_revision=3,
    )
    epoch_mp = _EpochMpDraw(old_preview)
    runner = SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, epoch_mp)
    store = ParamStore()
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    try:
        runner.run(
            1.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
            transport_epoch=0,
        )
        assert runner.last_realized_t == pytest.approx(1.0)
        assert runner.last_realized_snapshot_revision == 3

        # 録画開始でも epoch を進め、以後は同期評価した t=5 の frame を
        # 実表示として保持する。
        recording_layers = runner.run(
            5.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=True,
            transport_epoch=1,
        )
        assert runner.last_realized_t == pytest.approx(5.0)
        assert runner.last_realized_snapshot_revision == store.revision

        # 録画終了は epoch を進めて old_preview を無効化する。fresh result が
        # 未到着でも同期録画 frame と t の組を維持する。
        waiting_layers = runner.run(
            5.1,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
            transport_epoch=2,
        )
        assert waiting_layers == recording_layers
        assert runner.last_realized_t == pytest.approx(5.0)
        assert runner.last_realized_snapshot_revision == store.revision
        assert runner.last_evaluation_succeeded is None
        assert runner.is_waiting_for_fresh_result is True
        assert epoch_mp.begin_calls == [1, 2]
        assert epoch_mp.submitted_epochs[-1] == 2
    finally:
        runner.close()


def test_scene_runner_seek_epoch_adopts_only_fresh_result_and_time() -> None:
    initial = DrawResult(
        frame_id=10,
        layers=normalize_scene(_empty_draw(2.0)),
        records=[],
        labels=[],
        t=2.0,
        epoch=0,
        snapshot_revision=4,
    )
    epoch_mp = _EpochMpDraw(initial)
    runner = SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, epoch_mp)
    store = ParamStore()
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    try:
        before_seek = runner.run(
            2.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
            transport_epoch=0,
        )
        assert runner.last_realized_t == pytest.approx(2.0)
        assert runner.last_realized_snapshot_revision == 4

        waiting = runner.run(
            20.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
            transport_epoch=1,
        )
        assert waiting == before_seek
        assert runner.last_realized_t == pytest.approx(2.0)
        assert runner.last_realized_snapshot_revision == 4
        assert runner.is_waiting_for_fresh_result is True

        epoch_mp.result = DrawResult(
            frame_id=11,
            layers=normalize_scene(_empty_draw(20.0)),
            records=[],
            labels=[],
            t=20.0,
            epoch=1,
            snapshot_revision=9,
        )
        epoch_mp._published = False
        fresh = runner.run(
            20.0,
            store=store,
            cc_snapshot=None,
            defaults=defaults,
            recording=False,
            transport_epoch=1,
        )
        assert fresh
        assert runner.last_realized_t == pytest.approx(20.0)
        assert runner.last_realized_snapshot_revision == 9
        assert runner.last_evaluation_t == pytest.approx(20.0)
        assert runner.is_waiting_for_fresh_result is False
    finally:
        runner.close()


def test_scene_runner_retries_success_observations_after_realize_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """realize 失敗で rollback された worker 観測を次回に再マージする。"""

    key = ParameterKey(op="line", site_id="worker-site", arg="length")
    record = FrameParamRecord(
        key=key,
        base=2.0,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=10.0),
        effective=2.0,
        source="code",
        explicit=True,
    )
    batched = _BatchedSuccessThenErrorMpDraw()
    batched.success = DrawResult(
        frame_id=10,
        t=0.25,
        layers=batched.success.layers,
        records=[record],
        labels=[],
    )

    realize_calls = 0

    def fail_once(*_args: object, **_kwargs: object) -> list[Any]:
        nonlocal realize_calls
        realize_calls += 1
        if realize_calls == 1:
            raise ValueError("main realize failed")
        return []

    monkeypatch.setattr(scene_runner_module, "realize_scene", fail_once)
    runner = SceneRunner(_empty_draw, perf=PerfCollector(enabled=False), n_worker=0)
    runner._mp_draw = cast(Any, batched)
    store = ParamStore()
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    try:
        # batch 終端の error を先に通知し、retained success を次回へ残す。
        with pytest.raises(RuntimeError, match="later frame failed"):
            runner.run(
                1.0,
                store=store,
                cc_snapshot=None,
                defaults=defaults,
                recording=False,
            )

        # retained success の records は frame buffer へ入るが、main realize 失敗に
        # より parameter_context が frame 全体を rollback する。
        with pytest.raises(ValueError, match="main realize failed"):
            runner.run(
                1.1,
                store=store,
                cc_snapshot=None,
                defaults=defaults,
                recording=False,
            )
        assert store.get_state(key) is None
        assert runner._last_merged_mp_success_frame_id is None
        assert runner.last_realized_t is None

        # 同じ success frame を retry し、今回は realize と context commit が成功する。
        assert (
            runner.run(
                1.2,
                store=store,
                cc_snapshot=None,
                defaults=defaults,
                recording=False,
            )
            == []
        )
        assert store.get_state(key) is not None
        assert runner._last_merged_mp_success_frame_id == 10
        assert runner.last_realized_t == pytest.approx(0.25)
    finally:
        runner.close()


def test_scene_runner_passes_resource_budget_to_realize_session() -> None:
    budget = ResourceBudget(
        max_output_vertices=123,
        max_output_lines=45,
        max_output_bytes=6_789,
    )
    runner = SceneRunner(
        _empty_draw,
        perf=PerfCollector(enabled=False),
        n_worker=0,
        resource_budget=budget,
    )
    try:
        assert runner._realize_session.resource_budget is budget
    finally:
        runner.close()


def _wait_until(predicate: Callable[[], bool], *, message: str) -> None:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(message)


def test_600_stable_frames_broadcast_snapshot_only_once() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    try:
        for frame in range(600):
            mp_draw.submit(
                t=float(frame),
                snapshot_revision=7,
                snapshot={},
            )

        result = _wait_for_result(mp_draw)
        assert result.error is None
        assert mp_draw.completed_result_count >= 1
        assert mp_draw.snapshot_broadcast_count == 1
        assert set(mp_draw.worker_snapshot_revisions.values()) == {7}
        assert mp_draw.snapshot_ack_count >= 2

        for frame in range(600, 660):
            mp_draw.submit(
                t=float(frame),
                snapshot_revision=7,
                snapshot={},
            )
        assert mp_draw.snapshot_broadcast_count == 1

        mp_draw.submit(t=661.0, snapshot_revision=8, snapshot={})

        def revision_8_was_acked() -> bool:
            mp_draw.poll_latest()
            return set(mp_draw.worker_snapshot_revisions.values()) == {8}

        _wait_until(
            revision_8_was_acked,
            message="snapshot revision 8 ack timeout",
        )
        assert mp_draw.snapshot_broadcast_count == 2
    finally:
        mp_draw.close()


def test_single_worker_uses_task_snapshot_without_duplicate_control_broadcast() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=1)
    try:
        for frame in range(30):
            mp_draw.submit(
                t=float(frame),
                snapshot_revision=7,
                snapshot={},
            )

        result = _wait_for_result(mp_draw)
        assert result.error is None
        assert result.snapshot_revision == 7
        assert mp_draw.snapshot_broadcast_count == 0
        assert mp_draw.snapshot_payload_copy_count == 1
        assert set(mp_draw.worker_snapshot_revisions.values()) == {7}

        mp_draw.submit(t=31.0, snapshot_revision=8, snapshot={})
        latest: DrawResult | None = None
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            candidate = mp_draw.poll_latest()
            if candidate is not None and candidate.snapshot_revision == 8:
                latest = candidate
                break
            time.sleep(0.005)
        assert latest is not None
        assert latest.snapshot_revision == 8
        assert mp_draw.snapshot_broadcast_count == 0
        assert mp_draw.snapshot_payload_copy_count == 2
    finally:
        mp_draw.close()


def test_mp_draw_emits_revision_and_frame_causal_events() -> None:
    events: list[tuple[str, int | None, int | None]] = []

    def record_event(
        name: str,
        *,
        frame_id: int | None = None,
        revision: int | None = None,
    ) -> None:
        events.append((name, frame_id, revision))

    mp_draw = MpDraw(
        _empty_draw,
        n_worker=1,
        event_callback=record_event,
    )
    try:
        mp_draw.submit(t=0.0, snapshot_revision=9, snapshot={})
        submitted_frame_id = mp_draw.last_submitted_frame_id
        result = _wait_for_result(mp_draw)

        assert result.frame_id == submitted_frame_id
        assert (
            "parameter_snapshot_built",
            None,
            9,
        ) in events
        assert (
            "mp_snapshot_sent",
            submitted_frame_id,
            9,
        ) in events
        assert ("mp_snapshot_applied", None, 9) in events
        assert (
            "mp_task_started",
            submitted_frame_id,
            9,
        ) in events
    finally:
        mp_draw.close()


def test_worker_rejects_unknown_and_stale_revision_and_acks_stale_update() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    try:
        mp_draw.submit(t=0.0, snapshot_revision=5, snapshot={})
        _wait_for_result(mp_draw)
        assert set(mp_draw.worker_snapshot_revisions.values()) == {5}

        rejected_before = mp_draw.rejected_task_count
        mp_draw._task_q.put(
            _DrawTask(
                frame_id=10_001,
                t=0.0,
                snapshot_revision=6,
                cc_snapshot=None,
            )
        )

        def unknown_was_rejected() -> bool:
            mp_draw.poll_latest()
            return mp_draw.rejected_task_count > rejected_before

        _wait_until(unknown_was_rejected, message="unknown revision rejection timeout")
        assert mp_draw.last_rejection == (6, 5, "unknown")

        rejected_before = mp_draw.rejected_task_count
        mp_draw._task_q.put(
            _DrawTask(
                frame_id=10_002,
                t=0.0,
                snapshot_revision=4,
                cc_snapshot=None,
            )
        )

        def stale_was_rejected() -> bool:
            mp_draw.poll_latest()
            return mp_draw.rejected_task_count > rejected_before

        _wait_until(stale_was_rejected, message="stale revision rejection timeout")
        assert mp_draw.last_rejection == (4, 5, "stale")

        ack_before = mp_draw.snapshot_ack_count
        mp_draw._control_qs[0].put(_SnapshotUpdate(revision=4, snapshot={}))

        def stale_was_acked() -> bool:
            mp_draw.poll_latest()
            return mp_draw.snapshot_ack_count > ack_before

        _wait_until(stale_was_acked, message="stale snapshot ack timeout")
        assert mp_draw.last_snapshot_ack == (4, 5, "stale")
    finally:
        mp_draw.close()


def test_rapid_revision_changes_keep_snapshot_control_backlog_bounded() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    try:
        for revision in range(1, 201):
            mp_draw.submit(
                t=float(revision),
                snapshot_revision=revision,
                snapshot={},
            )
            assert mp_draw.pending_snapshot_update_count <= 2
            assert mp_draw.queued_snapshot_update_count <= 2

        def final_revision_was_acked() -> bool:
            mp_draw.poll_latest()
            return set(mp_draw.worker_snapshot_revisions.values()) == {200}

        _wait_until(
            final_revision_was_acked,
            message="latest snapshot revision ack timeout",
        )
        assert mp_draw.snapshot_broadcast_count == 200
        assert mp_draw.pending_snapshot_update_count == 0
        assert mp_draw.queued_snapshot_update_count == 0
        assert mp_draw.rejected_task_count == 0
    finally:
        mp_draw.close()


@pytest.mark.parametrize("n_worker", [1, 2])
def test_revision_churn_keeps_results_moving_and_reaches_latest(
    n_worker: int,
) -> None:
    """GUI と同じ submit→poll 順でも revision ACK が draw を飢餓させない。"""

    mp_draw = MpDraw(_empty_draw, n_worker=n_worker)
    revisions_during_drag: list[int] = []
    try:
        for revision in range(1, 61):
            mp_draw.submit(
                t=float(revision),
                snapshot_revision=revision,
                snapshot={},
            )
            result = mp_draw.poll_latest()
            if result is not None:
                revisions_during_drag.append(int(result.snapshot_revision))
            assert mp_draw.pending_snapshot_update_count <= n_worker
            assert mp_draw.queued_snapshot_update_count <= n_worker
            time.sleep(0.005)

        # wall time そのものではなく、連続 edit 中にも評価が前進することを契約にする。
        assert len(revisions_during_drag) >= 2
        assert revisions_during_drag == sorted(set(revisions_during_drag))

        final_result: DrawResult | None = None
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            mp_draw.submit(
                t=60.0,
                snapshot_revision=60,
                snapshot={},
            )
            result = mp_draw.poll_latest()
            if result is not None and int(result.snapshot_revision) == 60:
                final_result = result
                break
            time.sleep(0.005)

        assert final_result is not None
        assert final_result.error is None
        assert mp_draw.rejected_task_count == 0
    finally:
        mp_draw.close()
