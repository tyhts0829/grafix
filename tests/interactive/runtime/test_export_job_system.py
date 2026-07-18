from __future__ import annotations

import multiprocessing as mp
import os
import json
import queue
import time
import weakref
from collections import deque
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.core.capture_manifest import capture_manifest_path_for
from grafix.core.capture_provenance import CaptureProvenanceBuilder
from grafix.core.parameters import ParamStore
from grafix.core.runtime_config import runtime_config
from grafix.export import capture as capture_module
from grafix.interactive.runtime import export_job_system
from grafix.interactive.runtime.export_job_system import (
    ExportJob,
    ExportJobResult,
    ExportJobStatus,
    ExportJobSystem,
    ExportQueueFullError,
    ExportKind,
    FrameExportSnapshot,
)

_WAIT_TIMEOUT_S = 8.0


def _snapshot() -> FrameExportSnapshot:
    return FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
    )


def _sized_snapshot(byte_size: int) -> FrameExportSnapshot:
    coords_bytes = max(0, int(byte_size) - 4)
    layer = cast(
        Any,
        SimpleNamespace(
            realized=SimpleNamespace(
                coords=SimpleNamespace(nbytes=coords_bytes),
                offsets=SimpleNamespace(nbytes=4),
            )
        ),
    )
    return FrameExportSnapshot(
        layers=(layer,),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
    )


def test_frame_export_snapshot_rejects_non_finite_capture_time() -> None:
    with pytest.raises(ValueError, match="t"):
        FrameExportSnapshot(
            layers=(),
            canvas_size=(10, 10),
            background_color_rgb01=(1.0, 1.0, 1.0),
            t=float("nan"),
        )


def test_partial_queue_creation_closes_the_first_queue() -> None:
    calls: list[str] = []

    class Queue:
        def cancel_join_thread(self) -> None:
            calls.append("cancel")

        def close(self) -> None:
            calls.append("close")

        def join_thread(self) -> None:
            calls.append("join")

    class Context:
        def __init__(self) -> None:
            self.count = 0

        def Queue(self, **_kwargs: object) -> object:  # noqa: N802 - multiprocessing API
            self.count += 1
            if self.count == 1:
                return Queue()
            raise RuntimeError("second queue failed")

    system = object.__new__(ExportJobSystem)
    system._ctx = cast(Any, Context())

    with pytest.raises(RuntimeError, match="second queue failed"):
        system._create_queues()

    assert calls == ["cancel", "close", "join"]


def test_close_queue_attempts_every_step_and_raises_first_base_exception() -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    first_error = CleanupFault("cancel failed")

    class Queue:
        def cancel_join_thread(self) -> None:
            calls.append("cancel")
            raise first_error

        def close(self) -> None:
            calls.append("close")
            raise CleanupFault("close failed")

        def join_thread(self) -> None:
            calls.append("join")

    with pytest.raises(CleanupFault) as exc_info:
        ExportJobSystem._close_queue(cast(Any, Queue()), cancel=True)

    assert exc_info.value is first_error
    assert calls == ["cancel", "close", "join"]


def test_close_queues_continues_with_result_queue_after_task_queue_failure() -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    first_error = CleanupFault("task cancel failed")

    class Queue:
        def __init__(self, name: str, *, fail_cancel: bool = False) -> None:
            self.name = name
            self.fail_cancel = fail_cancel

        def cancel_join_thread(self) -> None:
            calls.append(f"{self.name}.cancel")
            if self.fail_cancel:
                raise first_error

        def close(self) -> None:
            calls.append(f"{self.name}.close")

        def join_thread(self) -> None:
            calls.append(f"{self.name}.join")

    system = object.__new__(ExportJobSystem)
    system._task_q = cast(Any, Queue("task", fail_cancel=True))
    system._result_q = cast(Any, Queue("result"))

    with pytest.raises(CleanupFault) as exc_info:
        system._close_queues(cancel_pending=True)

    assert exc_info.value is first_error
    assert calls == [
        "task.cancel",
        "task.close",
        "task.join",
        "result.close",
        "result.join",
    ]


def test_join_process_preserves_escalation_order_after_cleanup_failures() -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    first_error = CleanupFault("initial join failed")

    class Process:
        def __init__(self) -> None:
            self.join_count = 0
            self.alive = iter((True, True, False))

        def join(self, *, timeout: float) -> None:
            assert timeout == export_job_system._WORKER_JOIN_TIMEOUT_S
            self.join_count += 1
            calls.append(f"join:{self.join_count}")
            if self.join_count == 1:
                raise first_error

        def is_alive(self) -> bool:
            calls.append("is_alive")
            return next(self.alive)

        def terminate(self) -> None:
            calls.append("terminate")
            raise CleanupFault("terminate failed")

        def kill(self) -> None:
            calls.append("kill")

        def close(self) -> None:
            calls.append("close")
            raise CleanupFault("process close failed")

    with pytest.raises(CleanupFault) as exc_info:
        ExportJobSystem._join_process(cast(Any, Process()))

    assert exc_info.value is first_error
    assert calls == [
        "join:1",
        "is_alive",
        "terminate",
        "join:2",
        "is_alive",
        "kill",
        "join:3",
        "is_alive",
        "close",
    ]


def test_replace_worker_attempts_join_queues_and_recreation_after_failures() -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    first_error = CleanupFault("terminate failed")

    class Process:
        def is_alive(self) -> bool:
            calls.append("is_alive")
            return True

        def terminate(self) -> None:
            calls.append("terminate")
            raise first_error

    system = object.__new__(ExportJobSystem)
    system._proc = cast(Any, Process())

    def fail_join(_proc: object) -> None:
        calls.append("join")
        raise CleanupFault("join failed")

    def fail_close_queues(*, cancel_pending: bool) -> None:
        assert cancel_pending is True
        calls.append("close queues")
        raise CleanupFault("queue close failed")

    def create_queues() -> None:
        calls.append("create queues")

    system._join_process = fail_join
    system._close_queues = fail_close_queues
    system._create_queues = create_queues

    with pytest.raises(CleanupFault) as exc_info:
        system._replace_worker()

    assert exc_info.value is first_error
    assert calls == [
        "is_alive",
        "terminate",
        "join",
        "close queues",
        "create queues",
    ]
    assert system._proc is None


def test_close_treats_full_idle_sentinel_queue_as_pending_work() -> None:
    calls: list[str] = []

    class Process:
        def is_alive(self) -> bool:
            calls.append("is_alive")
            return True

    class FullQueue:
        def put_nowait(self, value: object) -> None:
            assert value is None
            calls.append("signal")
            raise queue.Full

    system = object.__new__(ExportJobSystem)
    system._closed = False
    system._in_flight = None
    system._pending = deque()
    system._completed = deque()
    system._proc = cast(Any, Process())
    system._task_q = cast(Any, FullQueue())
    system._join_process = lambda _proc: calls.append("join")
    system._close_queues = lambda *, cancel_pending: calls.append(
        f"close queues:{cancel_pending}"
    )

    system.close()

    assert calls == [
        "is_alive",
        "signal",
        "join",
        "close queues:True",
    ]
    assert system._proc is None


def test_worker_releases_completed_job_snapshot_before_waiting_for_next() -> None:
    """idle workerが直前の巨大geometryをloop localとして保持しない。"""

    class Probe:
        pass

    class TaskQueue:
        def __init__(self, job: ExportJob, probe_ref: weakref.ReferenceType[Probe]) -> None:
            self._job: ExportJob | None = job
            self._probe_ref = probe_ref

        def get(self) -> ExportJob | None:
            job = self._job
            if job is not None:
                self._job = None
                return job
            # 2回目のgetは実workerならblocking待機に入る地点。この前に
            # loop local `job` が解放され、snapshot内のprobeも回収済みである。
            assert self._probe_ref() is None
            return None

        def close(self) -> None:
            return

        def join_thread(self) -> None:
            return

    class ResultQueue:
        def __init__(self) -> None:
            self.messages: list[object] = []

        def put(self, message: object) -> None:
            self.messages.append(message)

        def close(self) -> None:
            return

        def join_thread(self) -> None:
            return

    def make_task_queue() -> tuple[TaskQueue, weakref.ReferenceType[Probe]]:
        probe = Probe()
        probe_ref = weakref.ref(probe)
        snapshot = FrameExportSnapshot(
            layers=(cast(Any, probe),),
            canvas_size=(10, 10),
            background_color_rgb01=(1.0, 1.0, 1.0),
        )
        job = ExportJob(
            job_id=1,
            kind=ExportKind.GCODE,
            snapshot=snapshot,
            output_path=Path("probe.gcode"),
            timeout_s=1.0,
        )
        return TaskQueue(job, probe_ref), probe_ref

    task_queue, probe_ref = make_task_queue()
    result_queue = ResultQueue()

    export_job_system._export_worker_main(  # noqa: SLF001 - worker lifecycle regression
        cast(Any, task_queue),
        cast(Any, result_queue),
        _success_backend,
    )

    assert probe_ref() is None
    assert any(isinstance(message, ExportJobResult) for message in result_queue.messages)


def _success_backend(job: ExportJob) -> tuple[Path, ...]:
    return (job.output_path,)


def _two_second_backend(job: ExportJob) -> tuple[Path, ...]:
    time.sleep(2.0)
    return (job.output_path,)


def _bounded_backend(job: ExportJob) -> tuple[Path, ...]:
    time.sleep(0.75)
    return (job.output_path,)


def _conditional_backend(job: ExportJob) -> tuple[Path, ...]:
    stem = job.output_path.stem
    if stem == "fail":
        raise ValueError("backend failure")
    if stem == "slow":
        time.sleep(2.0)
    if stem == "die":
        os._exit(7)
    return (job.output_path,)


def _wait_for_job(
    system: ExportJobSystem,
    job_id: int,
    *,
    collected: list[ExportJobResult] | None = None,
) -> ExportJobResult:
    results = [] if collected is None else collected
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        results.extend(system.poll())
        for result in results:
            if result.job_id == job_id:
                return result
        time.sleep(0.01)
    pytest.fail(f"export job timeout: job_id={job_id}")


def test_export_messages_are_immutable() -> None:
    snapshot = _snapshot()
    job = ExportJob(
        job_id=1,
        kind=ExportKind.PNG,
        snapshot=snapshot,
        output_path=Path("out.png"),
        timeout_s=1.0,
    )
    result = ExportJobResult(
        job_id=1,
        kind=ExportKind.PNG,
        status=ExportJobStatus.SUCCESS,
        output_path=Path("out.png"),
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.canvas_size = (1, 1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        job.timeout_s = 2.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.status = ExportJobStatus.ERROR  # type: ignore[misc]


def test_default_backend_delegates_encode_and_publish_to_capture_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    output_path = tmp_path / "frame.gcode"
    staging_dir = tmp_path / ".capture.export-1-test"
    staged_path = staging_dir / output_path.name
    manifest_path = capture_manifest_path_for(output_path)
    calls: list[tuple[str, object]] = []

    class CaptureServiceSpy:
        def encode(self, frame: object, path: object, **kwargs: object) -> tuple[Path, ...]:
            assert frame is snapshot
            assert Path(cast(Any, path)) == staged_path
            assert kwargs["mode"] == ExportKind.GCODE.value
            calls.append(("encode", path))
            return (staged_path,)

        def publish_staged(
            self,
            frame: object,
            path: object,
            staged_paths: object,
            **kwargs: object,
        ) -> SimpleNamespace:
            assert frame is snapshot
            assert Path(cast(Any, path)) == output_path
            assert tuple(cast(Any, staged_paths)) == (staged_path,)
            assert kwargs == {
                "mode": ExportKind.GCODE.value,
                "output_size": None,
            }
            calls.append(("publish", path))
            return SimpleNamespace(
                artifact_paths=(output_path,),
                manifest_path=manifest_path,
            )

    monkeypatch.setattr(export_job_system, "_CAPTURE_SERVICE", CaptureServiceSpy())
    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE,
        snapshot=snapshot,
        output_path=output_path,
        timeout_s=1.0,
        staging_dir=staging_dir,
    )

    staged = export_job_system._execute_export_job(job)
    committed = export_job_system._commit_staged_outputs(job, staged)

    assert committed == ((output_path,), manifest_path)
    assert calls == [("encode", staged_path), ("publish", output_path)]


def test_two_second_backend_does_not_block_frame_polling(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_two_second_backend, default_timeout_s=5.0)
    try:
        job = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=tmp_path / "slow.png",
        )

        frame_ticks = 0
        early_results: list[ExportJobResult] = []
        frame_deadline = time.monotonic() + 0.3
        while time.monotonic() < frame_deadline:
            before_poll = time.monotonic()
            early_results.extend(system.poll())
            assert time.monotonic() - before_poll < 0.1
            frame_ticks += 1
            time.sleep(0.01)

        assert frame_ticks >= 20
        assert all(result.job_id != job.job_id for result in early_results)
        result = _wait_for_job(system, job.job_id, collected=early_results)
        assert result.status is ExportJobStatus.SUCCESS
    finally:
        system.close()


def test_repeated_submit_uses_a_bounded_fifo_without_replacing_jobs(
    tmp_path: Path,
) -> None:
    system = ExportJobSystem(
        backend=_bounded_backend,
        default_timeout_s=5.0,
        max_pending_jobs=3,
    )
    jobs: list[ExportJob] = []
    collected: list[ExportJobResult] = []
    try:
        for index in range(4):
            job = system.submit(
                kind=ExportKind.PNG,
                snapshot=_snapshot(),
                output_path=tmp_path / f"frame_{index}.png",
            )
            jobs.append(job)

        assert system.in_flight_job == jobs[0]
        assert system.pending_job == jobs[1]
        assert system.pending_job_count == 3
        assert system.can_submit is False
        assert system.has_work is True
        with pytest.raises(ExportQueueFullError, match="満杯"):
            system.submit(
                kind=ExportKind.PNG,
                snapshot=_snapshot(),
                output_path=tmp_path / "rejected.png",
            )

        last_result = _wait_for_job(system, jobs[-1].job_id, collected=collected)
        assert last_result.status is ExportJobStatus.SUCCESS
        assert [
            result.job_id
            for result in collected
            if result.status is ExportJobStatus.SUCCESS
        ] == [job.job_id for job in jobs]
        assert system.has_work is False
    finally:
        system.close()


def test_capture_queue_enforces_aggregate_bytes_and_shares_same_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = _sized_snapshot(80)
    another_snapshot = _sized_snapshot(80)
    system = ExportJobSystem(
        backend=_bounded_backend,
        default_timeout_s=5.0,
        max_pending_jobs=3,
        # raw geometry 80 bytes x (parent + serialization + worker) 3 copies。
        max_retained_bytes=300,
    )
    try:
        system.submit(
            kind=ExportKind.GCODE,
            snapshot=snapshot,
            output_path=tmp_path / "one.gcode",
        )
        # 同じ immutable snapshot の連続 capture は親 geometry 参照を共有する。
        system.submit(
            kind=ExportKind.PNG,
            snapshot=snapshot,
            output_path=tmp_path / "two.png",
        )

        assert system.queue_status.request_count == 2
        assert system.queue_status.retained_bytes == 240
        with pytest.raises(ExportQueueFullError) as exc_info:
            system.submit(
                kind=ExportKind.GCODE,
                snapshot=another_snapshot,
                output_path=tmp_path / "rejected.gcode",
            )

        error = exc_info.value
        assert error.reason == "bytes"
        assert error.retained_bytes == 240
        assert error.requested_bytes == 240
        assert error.byte_limit == 300
        assert "requests=2/4" in str(error)
        assert not (tmp_path / "rejected.gcode").exists()

        assert system.cancel()
        assert system.retained_bytes == 0
        assert system.request_count == 0
    finally:
        system.close()


def test_capture_queue_releases_byte_budget_after_success(tmp_path: Path) -> None:
    first_snapshot = _sized_snapshot(80)
    second_snapshot = _sized_snapshot(80)
    system = ExportJobSystem(
        backend=_success_backend,
        default_timeout_s=5.0,
        max_pending_jobs=0,
        max_retained_bytes=240,
    )
    try:
        first = system.submit(
            kind=ExportKind.GCODE,
            snapshot=first_snapshot,
            output_path=tmp_path / "first.gcode",
        )
        assert system.retained_bytes == 240
        assert _wait_for_job(system, first.job_id).status is ExportJobStatus.SUCCESS
        assert system.retained_bytes == 0
        assert system.request_count == 0

        # 終端 result 後は以前の geometry が budget を占有し続けず、
        # 同じ上限の別 snapshot を受理できる。
        second = system.submit(
            kind=ExportKind.GCODE,
            snapshot=second_snapshot,
            output_path=tmp_path / "second.gcode",
        )
        assert _wait_for_job(system, second.job_id).status is ExportJobStatus.SUCCESS
        assert system.retained_bytes == 0
        assert system.request_count == 0
    finally:
        system.close()


def test_backend_error_is_reported_and_worker_remains_usable(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_conditional_backend)
    try:
        failed = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=tmp_path / "fail.gcode",
        )
        failed_result = _wait_for_job(system, failed.job_id)
        assert failed_result.status is ExportJobStatus.ERROR
        assert "backend failure" in (failed_result.error or "")

        succeeded = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=tmp_path / "ok.gcode",
        )
        assert _wait_for_job(system, succeeded.job_id).status is ExportJobStatus.SUCCESS
    finally:
        system.close()


def test_default_worker_exports_gcode(tmp_path: Path) -> None:
    system = ExportJobSystem()
    try:
        output_path = tmp_path / "frame.gcode"
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=output_path,
        )

        result = _wait_for_job(system, job.job_id)
        assert result.status is ExportJobStatus.SUCCESS
        assert result.paths == (output_path,)
        assert result.manifest_path == capture_manifest_path_for(output_path)
        assert output_path.is_file()
        assert result.manifest_path.is_file()
    finally:
        system.close()


def test_default_worker_uses_parent_gcode_config_recorded_in_manifest(
    tmp_path: Path,
) -> None:
    """spawn worker が独自 config を再探索せず、親 snapshot の設定を使う。"""

    gcode_config = replace(
        runtime_config().gcode,
        z_up=17.0,
        decimals=1,
    )
    effective_config = replace(runtime_config(), gcode=gcode_config)

    def draw(_t: float) -> tuple[object, ...]:
        return ()

    store = ParamStore()
    provenance = CaptureProvenanceBuilder(
        draw,
        config=effective_config,
        parameter_source="code",
        parameter_store_path=None,
        parameter_load_provenance=store.load_provenance,
    ).frame(
        store,
        t=0.0,
        frame_index=0,
        quality="final",
        origin="interactive",
    )
    snapshot = FrameExportSnapshot(
        layers=(),
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        provenance=provenance,
        gcode_config=gcode_config,
    )
    system = ExportJobSystem()
    try:
        output_path = tmp_path / "parent-config.gcode"
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=snapshot,
            output_path=output_path,
        )

        result = _wait_for_job(system, job.job_id)

        assert result.status is ExportJobStatus.SUCCESS
        assert "G1 Z37.0" in output_path.read_text(encoding="utf-8")
        assert result.manifest_path is not None
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["config"]["effective"]["gcode"]["z_up"] == 17.0
        assert manifest["config"]["effective"]["gcode"]["decimals"] == 1
    finally:
        system.close()


def test_default_worker_reports_png_backend_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    system = ExportJobSystem()
    try:
        output_path = tmp_path / "frame.png"
        svg_path = tmp_path / "frame.svg"
        svg_path.write_text("saved-by-s-key", encoding="utf-8")
        job = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=output_path,
            svg_output_path=svg_path,
        )

        result = _wait_for_job(system, job.job_id)
        assert result.status is ExportJobStatus.ERROR
        assert "resvg が見つかりません" in (result.error or "")
        assert svg_path.read_text(encoding="utf-8") == "saved-by-s-key"
        assert not output_path.exists()
    finally:
        system.close()


@pytest.mark.parametrize("raster_succeeds", [True, False])
def test_png_job_uses_private_svg_and_always_cleans_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raster_succeeds: bool,
) -> None:
    public_svg = tmp_path / "frame.svg"
    public_svg.write_text("saved-by-s-key", encoding="utf-8")
    intermediate_paths: list[Path] = []

    def fake_export_svg(*args: object, **kwargs: object) -> Path:
        svg_path = Path(args[1])
        intermediate_paths.append(svg_path)
        svg_path.write_text("png-intermediate", encoding="utf-8")
        return svg_path

    def fake_rasterize(svg_path: Path, png_path: Path, **kwargs: object) -> Path:
        assert Path(svg_path).read_text(encoding="utf-8") == "png-intermediate"
        if not raster_succeeds:
            raise RuntimeError("raster failed")
        Path(png_path).write_bytes(b"png")
        return Path(png_path)

    monkeypatch.setattr(capture_module, "export_svg", fake_export_svg)
    monkeypatch.setattr(capture_module, "rasterize_svg_to_png", fake_rasterize)
    job = ExportJob(
        job_id=1,
        kind=ExportKind.PNG,
        snapshot=_snapshot(),
        output_path=tmp_path / "frame.png",
        timeout_s=1.0,
        svg_output_path=public_svg,
    )

    if raster_succeeds:
        assert export_job_system._execute_export_job(job) == (job.output_path,)
    else:
        with pytest.raises(RuntimeError, match="raster failed"):
            export_job_system._execute_export_job(job)

    assert len(intermediate_paths) == 1
    assert intermediate_paths[0] != public_svg
    assert not intermediate_paths[0].exists()
    assert not intermediate_paths[0].parent.exists()
    assert public_svg.read_text(encoding="utf-8") == "saved-by-s-key"


def test_timeout_cancels_job_and_restarts_worker(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_conditional_backend)
    try:
        timed_out = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=tmp_path / "slow.png",
            timeout_s=0.15,
        )
        timeout_result = _wait_for_job(system, timed_out.job_id)
        assert timeout_result.status is ExportJobStatus.TIMEOUT

        succeeded = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=tmp_path / "ok.png",
        )
        assert _wait_for_job(system, succeeded.job_id).status is ExportJobStatus.SUCCESS
    finally:
        system.close()


def test_cancel_in_flight_dispatches_pending_job(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_conditional_backend, default_timeout_s=5.0)
    try:
        slow = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=tmp_path / "slow.png",
        )
        pending = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=tmp_path / "ok.gcode",
        )

        assert system.cancel(slow.job_id)
        results = system.poll()
        cancelled = next(result for result in results if result.job_id == slow.job_id)
        assert cancelled.status is ExportJobStatus.CANCELLED
        assert (
            _wait_for_job(system, pending.job_id, collected=results).status
            is ExportJobStatus.SUCCESS
        )
    finally:
        system.close()


def test_worker_death_is_reported_and_recovered(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_conditional_backend)
    try:
        died = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=tmp_path / "die.gcode",
        )
        death_result = _wait_for_job(system, died.job_id)
        assert death_result.status is ExportJobStatus.WORKER_DIED
        assert death_result.worker_exitcode == 7
        assert death_result.worker_pid is not None

        succeeded = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=tmp_path / "ok.gcode",
        )
        assert _wait_for_job(system, succeeded.job_id).status is ExportJobStatus.SUCCESS
    finally:
        system.close()


def test_close_cancels_jobs_reaps_worker_and_is_idempotent(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_conditional_backend, default_timeout_s=5.0)
    in_flight = system.submit(
        kind=ExportKind.PNG,
        snapshot=_snapshot(),
        output_path=tmp_path / "slow.png",
    )
    pending = system.submit(
        kind=ExportKind.GCODE,
        snapshot=_snapshot(),
        output_path=tmp_path / "pending.gcode",
    )
    proc = system._proc
    proc_pid = None if proc is None else proc.pid

    system.close()
    system.close()

    results = system.poll()
    assert {result.job_id for result in results if result.status is ExportJobStatus.CANCELLED} == {
        in_flight.job_id,
        pending.job_id,
    }
    assert proc_pid is not None
    assert proc_pid not in {child.pid for child in mp.active_children()}
    with pytest.raises(RuntimeError, match="close 済み"):
        system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=tmp_path / "after_close.png",
        )


def test_close_cleans_staging_even_when_queue_teardown_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = ExportJobSystem()
    real_close_queues = system._close_queues
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    (staging_dir / "partial.gcode").write_text("partial", encoding="utf-8")
    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE,
        snapshot=_snapshot(),
        output_path=tmp_path / "capture.gcode",
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    system._in_flight = job
    teardown_error = RuntimeError("queue teardown failed")

    def fail_queue_teardown(*, cancel_pending: bool) -> None:
        assert cancel_pending is True
        raise teardown_error

    monkeypatch.setattr(system, "_close_queues", fail_queue_teardown)
    try:
        with pytest.raises(RuntimeError, match="queue teardown failed") as exc_info:
            system.close()

        assert exc_info.value is teardown_error
        assert not staging_dir.exists()
        # close は既に terminal 状態のため、二回目は例外を再送出しない。
        system.close()
    finally:
        # fault injection で閉じなかった実 Queue は test 側で回収する。
        real_close_queues(cancel_pending=True)


def test_cancel_cleans_staging_even_when_worker_replacement_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = ExportJobSystem()
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    (staging_dir / "partial.gcode").write_text("partial", encoding="utf-8")
    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE,
        snapshot=_snapshot(),
        output_path=tmp_path / "capture.gcode",
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    system._in_flight = job
    replacement_error = RuntimeError("worker replacement failed")

    monkeypatch.setattr(system, "_service", lambda: None)

    def fail_worker_replacement() -> None:
        raise replacement_error

    monkeypatch.setattr(system, "_replace_worker", fail_worker_replacement)
    try:
        with pytest.raises(RuntimeError, match="worker replacement failed") as exc_info:
            system.cancel(job.job_id)

        assert exc_info.value is replacement_error
        assert not staging_dir.exists()
    finally:
        system._closed = True
        system._close_queues(cancel_pending=True)
