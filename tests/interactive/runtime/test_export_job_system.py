from __future__ import annotations

import multiprocessing as mp
import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from grafix.interactive.runtime.export_job_system import (
    ExportJob,
    ExportJobResult,
    ExportJobStatus,
    ExportJobSystem,
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


def test_repeated_submit_keeps_only_in_flight_and_latest_pending(tmp_path: Path) -> None:
    system = ExportJobSystem(backend=_bounded_backend, default_timeout_s=5.0)
    jobs: list[ExportJob] = []
    collected: list[ExportJobResult] = []
    try:
        for index in range(200):
            job = system.submit(
                kind=ExportKind.PNG,
                snapshot=_snapshot(),
                output_path=tmp_path / f"frame_{index}.png",
            )
            jobs.append(job)
            assert system.in_flight_job is not None
            assert system.pending_job is None or system.pending_job.job_id == job.job_id

        assert len(system._completed) == 64
        collected.extend(system.poll())
        first_result = _wait_for_job(system, jobs[0].job_id, collected=collected)
        last_result = _wait_for_job(system, jobs[-1].job_id, collected=collected)

        assert first_result.status is ExportJobStatus.SUCCESS
        assert last_result.status is ExportJobStatus.SUCCESS
        assert {
            result.job_id for result in collected if result.status is ExportJobStatus.SUCCESS
        } == {jobs[0].job_id, jobs[-1].job_id}
        assert all(
            result.status is ExportJobStatus.CANCELLED
            for result in collected
            if jobs[0].job_id < result.job_id < jobs[-1].job_id
        )
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
        assert output_path.is_file()
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
        job = system.submit(
            kind=ExportKind.PNG,
            snapshot=_snapshot(),
            output_path=output_path,
            svg_output_path=svg_path,
        )

        result = _wait_for_job(system, job.job_id)
        assert result.status is ExportJobStatus.ERROR
        assert "resvg が見つかりません" in (result.error or "")
        assert svg_path.is_file()
        assert not output_path.exists()
    finally:
        system.close()


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
