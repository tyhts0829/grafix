from __future__ import annotations

import multiprocessing as mp
import os
import time
from collections.abc import Callable
from typing import Any, cast

import pytest

from grafix.core.geometry import Geometry
from grafix.core.layer import LayerStyleDefaults
from grafix.core.parameters import ParamStore
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


def test_workers_report_ready_and_normal_close_leaves_no_children() -> None:
    mp_draw = MpDraw(_empty_draw, n_worker=2)
    procs = list(mp_draw._procs)
    worker_pids = {int(proc.pid) for proc in procs if proc.pid is not None}

    assert mp_draw._ready_worker_pids == worker_pids

    mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
    result = _wait_for_result(mp_draw)
    assert result.error is None
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


def test_scene_runner_propagates_worker_death_without_sync_fallback() -> None:
    draw_calls = 0

    def draw(_t: float) -> Geometry:
        nonlocal draw_calls
        draw_calls += 1
        return Geometry.create(op="concat")

    error = MpDrawWorkerError(worker="dead", pid=123, exitcode=7)
    dead_mp_draw = _DeadMpDraw(error)
    runner = SceneRunner(draw, perf=PerfCollector(enabled=False), n_worker=1)
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
