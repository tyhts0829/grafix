"""
どこで: `src/grafix/interactive/runtime/export_job_system.py`。
何を: PNG/G-code 書き出しを 1 本の長寿命 worker へ委譲する bounded job system。
なぜ: 重い export 中も描画ループを止めず、連打時の process・snapshot 増殖を防ぐため。
"""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.process as mp_process
import multiprocessing.queues as mp_queues
import os
import queue
import time
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any

from grafix.core.output_paths import gcode_layer_output_path
from grafix.core.pipeline import RealizedLayer
from grafix.export.gcode import export_gcode
from grafix.export.image import png_output_size, rasterize_svg_to_png
from grafix.export.svg import export_svg

_WORKER_JOIN_TIMEOUT_S = 0.5
_PARENT_TIMEOUT_GRACE_S = 0.25
_COMPLETED_RESULT_LIMIT = 64


class ExportKind(StrEnum):
    """非同期 export の種類。"""

    PNG = "png"
    GCODE = "gcode"
    GCODE_LAYERS = "gcode_layers"


class ExportJobStatus(StrEnum):
    """export job の終端状態。"""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    WORKER_DIED = "worker_died"


@dataclass(frozen=True, slots=True)
class FrameExportSnapshot:
    """export 対象となる 1 フレーム分の不変データ。"""

    layers: tuple[RealizedLayer, ...]
    canvas_size: tuple[int, int]
    background_color_rgb01: tuple[float, float, float]

    def __post_init__(self) -> None:
        layers = tuple(self.layers)
        canvas_size = (int(self.canvas_size[0]), int(self.canvas_size[1]))
        if canvas_size[0] <= 0 or canvas_size[1] <= 0:
            raise ValueError("canvas_size は正の (width, height) である必要がある")
        background = tuple(float(value) for value in self.background_color_rgb01)
        if len(background) != 3:
            raise ValueError("background_color_rgb01 は RGB 3 要素である必要がある")
        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "canvas_size", canvas_size)
        object.__setattr__(self, "background_color_rgb01", background)


@dataclass(frozen=True, slots=True)
class ExportJob:
    """worker へ渡す不変 export request。"""

    job_id: int
    kind: ExportKind
    snapshot: FrameExportSnapshot
    output_path: Path
    timeout_s: float
    svg_output_path: Path | None = None
    output_size: tuple[int, int] | None = None
    deadline_monotonic: float | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if int(self.job_id) <= 0:
            raise ValueError("job_id は 1 以上である必要がある")
        timeout_s = float(self.timeout_s)
        if not isfinite(timeout_s) or timeout_s <= 0.0:
            raise ValueError("timeout_s は正である必要がある")
        object.__setattr__(self, "job_id", int(self.job_id))
        object.__setattr__(self, "kind", ExportKind(self.kind))
        object.__setattr__(self, "output_path", Path(self.output_path))
        object.__setattr__(self, "timeout_s", timeout_s)
        if self.svg_output_path is not None:
            object.__setattr__(self, "svg_output_path", Path(self.svg_output_path))
        if self.output_size is not None:
            output_size = (int(self.output_size[0]), int(self.output_size[1]))
            if output_size[0] <= 0 or output_size[1] <= 0:
                raise ValueError("output_size は正の (width, height) である必要がある")
            object.__setattr__(self, "output_size", output_size)
        if self.deadline_monotonic is not None:
            object.__setattr__(
                self,
                "deadline_monotonic",
                float(self.deadline_monotonic),
            )


@dataclass(frozen=True, slots=True)
class ExportJobResult:
    """export job の終端結果。"""

    job_id: int
    kind: ExportKind
    status: ExportJobStatus
    output_path: Path
    paths: tuple[Path, ...] = ()
    error: str | None = None
    worker_pid: int | None = None
    worker_exitcode: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", int(self.job_id))
        object.__setattr__(self, "kind", ExportKind(self.kind))
        object.__setattr__(self, "status", ExportJobStatus(self.status))
        object.__setattr__(self, "output_path", Path(self.output_path))
        object.__setattr__(self, "paths", tuple(Path(path) for path in self.paths))
        if self.worker_pid is not None:
            object.__setattr__(self, "worker_pid", int(self.worker_pid))
        if self.worker_exitcode is not None:
            object.__setattr__(self, "worker_exitcode", int(self.worker_exitcode))


@dataclass(frozen=True, slots=True)
class _WorkerReady:
    pid: int


_WorkerMessage = _WorkerReady | ExportJobResult
ExportBackend = Callable[[ExportJob], Sequence[Path]]


def _execute_export_job(job: ExportJob) -> tuple[Path, ...]:
    """既定 backend として PNG/G-code job を同期実行する。"""

    snapshot = job.snapshot
    if job.kind is ExportKind.PNG:
        svg_path = job.svg_output_path or job.output_path.with_suffix(".svg")
        export_svg(snapshot.layers, svg_path, canvas_size=snapshot.canvas_size)
        remaining = (
            job.timeout_s
            if job.deadline_monotonic is None
            else job.deadline_monotonic - time.monotonic()
        )
        if remaining <= 0.0:
            raise TimeoutError("PNG export deadline exceeded before resvg")
        png_path = rasterize_svg_to_png(
            svg_path,
            job.output_path,
            output_size=job.output_size or png_output_size(snapshot.canvas_size),
            background_color_rgb01=snapshot.background_color_rgb01,
            timeout_s=remaining,
        )
        return (png_path,)

    if job.kind is ExportKind.GCODE:
        path = export_gcode(
            snapshot.layers,
            job.output_path,
            canvas_size=snapshot.canvas_size,
        )
        return (path,)

    paths: list[Path] = []
    for index, layer in enumerate(snapshot.layers, start=1):
        path = gcode_layer_output_path(
            job.output_path,
            layer_index=index,
            n_layers=len(snapshot.layers),
            layer_name=layer.layer.name,
        )
        export_gcode([layer], path, canvas_size=snapshot.canvas_size)
        paths.append(path)
    return tuple(paths)


def _export_worker_main(
    task_q: mp_queues.Queue[ExportJob | None],
    result_q: mp_queues.Queue[_WorkerMessage],
    backend: ExportBackend,
) -> None:
    """長寿命 worker: job を直列実行し、必ず終端結果へ変換する。"""

    result_q.put(_WorkerReady(pid=os.getpid()))
    try:
        while True:
            job = task_q.get()
            if job is None:
                return
            try:
                paths = tuple(Path(path) for path in backend(job))
                result = ExportJobResult(
                    job_id=job.job_id,
                    kind=job.kind,
                    status=ExportJobStatus.SUCCESS,
                    output_path=job.output_path,
                    paths=paths,
                )
            except TimeoutError:
                result = ExportJobResult(
                    job_id=job.job_id,
                    kind=job.kind,
                    status=ExportJobStatus.TIMEOUT,
                    output_path=job.output_path,
                    error=traceback.format_exc(),
                )
            except Exception:
                result = ExportJobResult(
                    job_id=job.job_id,
                    kind=job.kind,
                    status=ExportJobStatus.ERROR,
                    output_path=job.output_path,
                    error=traceback.format_exc(),
                )
            result_q.put(result)
    finally:
        for worker_queue in (task_q, result_q):
            try:
                worker_queue.close()
                worker_queue.join_thread()
            except (OSError, ValueError):
                pass


class ExportJobSystem:
    """PNG/G-code を bounded な 1 worker で非同期実行する。

    Notes
    -----
    - worker は最初の submit で spawn し、その後は job 間で再利用する。
    - worker へ渡す in-flight job と、親が保持する最新 pending job は各 1 件まで。
    - pending 中の再 submit は旧 pending を cancelled にして置換する。
    - worker death/timeout/cancel 後は Queue ごと交換し、古い job の再実行を防ぐ。
    """

    def __init__(
        self,
        *,
        backend: ExportBackend = _execute_export_job,
        default_timeout_s: float = 30.0,
    ) -> None:
        timeout_s = float(default_timeout_s)
        if not isfinite(timeout_s) or timeout_s <= 0.0:
            raise ValueError("default_timeout_s は正である必要がある")

        self._ctx = mp.get_context("spawn")
        self._backend = backend
        self._default_timeout_s = timeout_s
        self._task_q: mp.Queue[ExportJob | None]
        self._result_q: mp.Queue[_WorkerMessage]
        self._proc: mp_process.BaseProcess | None = None
        self._worker_generation = 0
        self._ready_pid: int | None = None
        self._closed = False
        self._next_job_id = 0
        self._in_flight: ExportJob | None = None
        self._pending: ExportJob | None = None
        self._completed: deque[ExportJobResult] = deque(maxlen=_COMPLETED_RESULT_LIMIT)

        self._create_queues()

    @property
    def in_flight_job(self) -> ExportJob | None:
        """現在 worker へ渡している job を返す。"""

        return self._in_flight

    @property
    def pending_job(self) -> ExportJob | None:
        """次に実行する最新 pending job を返す。"""

        return self._pending

    def _create_queues(self) -> None:
        self._task_q = self._ctx.Queue(maxsize=1)
        self._result_q = self._ctx.Queue(maxsize=2)

    def _start_worker(self) -> None:
        self._worker_generation += 1
        proc = self._ctx.Process(
            target=_export_worker_main,
            args=(self._task_q, self._result_q, self._backend),
            name=f"grafix-export-{self._worker_generation}",
        )
        proc.start()
        self._proc = proc
        self._ready_pid = None

    @staticmethod
    def _join_process(proc: mp_process.BaseProcess) -> None:
        proc.join(timeout=_WORKER_JOIN_TIMEOUT_S)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=_WORKER_JOIN_TIMEOUT_S)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=_WORKER_JOIN_TIMEOUT_S)
        if not proc.is_alive():
            proc.close()

    @staticmethod
    def _close_queue(worker_queue: mp_queues.Queue[Any], *, cancel: bool) -> None:
        if cancel:
            worker_queue.cancel_join_thread()
        worker_queue.close()
        worker_queue.join_thread()

    def _close_queues(self, *, cancel_pending: bool) -> None:
        self._close_queue(self._task_q, cancel=cancel_pending)
        self._close_queue(self._result_q, cancel=False)

    def _replace_worker(self) -> None:
        proc = self._proc
        if proc is not None:
            if proc.is_alive():
                proc.terminate()
            self._join_process(proc)
        self._proc = None
        self._close_queues(cancel_pending=True)
        self._create_queues()

    @staticmethod
    def _terminal_result(
        job: ExportJob,
        status: ExportJobStatus,
        *,
        error: str,
        worker_pid: int | None = None,
        worker_exitcode: int | None = None,
    ) -> ExportJobResult:
        return ExportJobResult(
            job_id=job.job_id,
            kind=job.kind,
            status=status,
            output_path=job.output_path,
            error=error,
            worker_pid=worker_pid,
            worker_exitcode=worker_exitcode,
        )

    def _dispatch(self, job: ExportJob) -> None:
        dispatched = replace(
            job,
            deadline_monotonic=time.monotonic() + job.timeout_s,
        )
        try:
            if self._proc is None:
                self._start_worker()
            self._task_q.put_nowait(dispatched)
        except Exception:
            self._completed.append(
                self._terminal_result(
                    job,
                    ExportJobStatus.ERROR,
                    error=traceback.format_exc(),
                )
            )
            return
        self._in_flight = dispatched

    def _drain_worker_messages(self) -> None:
        while True:
            try:
                message = self._result_q.get_nowait()
            except queue.Empty:
                return
            if isinstance(message, _WorkerReady):
                self._ready_pid = message.pid
                continue
            current = self._in_flight
            if current is None or message.job_id != current.job_id:
                continue
            self._completed.append(message)
            self._in_flight = None

    def _recover_dead_worker(self) -> None:
        proc = self._proc
        if proc is None or proc.exitcode is None:
            return

        current = self._in_flight
        if current is not None:
            self._completed.append(
                self._terminal_result(
                    current,
                    ExportJobStatus.WORKER_DIED,
                    error=(
                        "export worker が予期せず終了しました: "
                        f"worker={proc.name!r}, pid={proc.pid}, exitcode={proc.exitcode}"
                    ),
                    worker_pid=proc.pid,
                    worker_exitcode=proc.exitcode,
                )
            )
            self._in_flight = None
        self._replace_worker()

    def _expire_timed_out_job(self) -> None:
        current = self._in_flight
        if current is None:
            return
        deadline = current.deadline_monotonic
        if deadline is None:
            return
        # PNG backend の resvg timeout が subprocess を確実に reap して結果を返す猶予を置く。
        # 猶予後も終わらない Python/G-code backend は worker ごと停止する。
        if time.monotonic() < deadline + _PARENT_TIMEOUT_GRACE_S:
            return

        self._completed.append(
            self._terminal_result(
                current,
                ExportJobStatus.TIMEOUT,
                error=f"export timeout: {current.timeout_s:g}s",
            )
        )
        self._in_flight = None
        self._replace_worker()

    def _service(self) -> None:
        self._drain_worker_messages()
        self._recover_dead_worker()
        self._expire_timed_out_job()
        if self._in_flight is None and self._pending is not None:
            pending = self._pending
            self._pending = None
            self._dispatch(pending)

    def submit(
        self,
        *,
        kind: ExportKind | str,
        snapshot: FrameExportSnapshot,
        output_path: str | Path,
        timeout_s: float | None = None,
        svg_output_path: str | Path | None = None,
        output_size: tuple[int, int] | None = None,
    ) -> ExportJob:
        """job を投入する。実行中なら pending 1 件を最新 job で置換する。"""

        if self._closed:
            raise RuntimeError("ExportJobSystem は close 済みです")
        self._service()

        self._next_job_id += 1
        job = ExportJob(
            job_id=self._next_job_id,
            kind=ExportKind(kind),
            snapshot=snapshot,
            output_path=Path(output_path),
            timeout_s=self._default_timeout_s if timeout_s is None else float(timeout_s),
            svg_output_path=None if svg_output_path is None else Path(svg_output_path),
            output_size=output_size,
        )

        if self._in_flight is None:
            self._dispatch(job)
            return job

        replaced = self._pending
        if replaced is not None:
            self._completed.append(
                self._terminal_result(
                    replaced,
                    ExportJobStatus.CANCELLED,
                    error=f"job {job.job_id} に置き換えられました",
                )
            )
        self._pending = job
        return job

    def poll(self) -> list[ExportJobResult]:
        """新しい終端結果をノンブロッキングで返す。"""

        if not self._closed:
            self._service()
        results = list(self._completed)
        self._completed.clear()
        return results

    def cancel(self, job_id: int | None = None) -> bool:
        """指定 job（None なら全 job）を取消し、終端結果を poll 可能にする。"""

        if self._closed:
            return False
        self._service()
        cancelled = False

        pending = self._pending
        if pending is not None and (job_id is None or pending.job_id == int(job_id)):
            self._completed.append(
                self._terminal_result(
                    pending,
                    ExportJobStatus.CANCELLED,
                    error="cancelled",
                )
            )
            self._pending = None
            cancelled = True

        current = self._in_flight
        if current is not None and (job_id is None or current.job_id == int(job_id)):
            self._completed.append(
                self._terminal_result(
                    current,
                    ExportJobStatus.CANCELLED,
                    error="cancelled",
                )
            )
            self._in_flight = None
            self._replace_worker()
            cancelled = True

        if self._in_flight is None and self._pending is not None:
            pending = self._pending
            self._pending = None
            self._dispatch(pending)
        return cancelled

    def close(self) -> None:
        """実行中・pending job を取消し、worker/Queue を冪等に閉じる。"""

        if self._closed:
            return
        self._closed = True

        for job in (self._in_flight, self._pending):
            if job is not None:
                self._completed.append(
                    self._terminal_result(
                        job,
                        ExportJobStatus.CANCELLED,
                        error="ExportJobSystem.close()",
                    )
                )
        had_in_flight = self._in_flight is not None
        self._in_flight = None
        self._pending = None

        proc = self._proc
        if proc is not None and not had_in_flight and proc.is_alive():
            try:
                self._task_q.put_nowait(None)
            except queue.Full:
                had_in_flight = True
        if proc is not None:
            self._join_process(proc)
        self._proc = None
        self._close_queues(cancel_pending=had_in_flight)


__all__ = [
    "ExportJob",
    "ExportJobResult",
    "ExportJobStatus",
    "ExportJobSystem",
    "ExportKind",
    "FrameExportSnapshot",
]
