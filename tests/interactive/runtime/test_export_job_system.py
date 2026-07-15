from __future__ import annotations

import multiprocessing as mp
import os
import time
import weakref
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.core.capture_manifest import capture_manifest_path_for
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

    monkeypatch.setattr(export_job_system, "export_svg", fake_export_svg)
    monkeypatch.setattr(export_job_system, "rasterize_svg_to_png", fake_rasterize)
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
