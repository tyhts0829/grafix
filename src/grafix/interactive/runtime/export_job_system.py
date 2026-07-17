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
import shutil
import tempfile
import time
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any

from grafix.core.capture_provenance import CaptureProvenance
from grafix.core.pipeline import RealizedLayer
from grafix.core.resource_budget import DEFAULT_RESOURCE_BUDGET
from grafix.core.runtime_config import GCodeExportConfig
from grafix.core.runtime_limits import RuntimeLimits
from grafix.export.capture import CaptureService

_WORKER_JOIN_TIMEOUT_S = 0.5
_PARENT_TIMEOUT_GRACE_S = 0.25
_COMPLETED_RESULT_LIMIT = 64
_DEFAULT_PENDING_JOB_LIMIT = 16
_DEFAULT_MAX_RETAINED_BYTES = int(DEFAULT_RESOURCE_BUDGET.max_output_bytes)
# 1つのin-flight snapshotは、親のimmutable geometry、multiprocessing Queueの
# serialization buffer、workerでunpickleしたgeometryの最大3世代を同時に持ち得る。
# pending jobにも同じ係数を保守的に課し、queue全体がprocessをまたいでbudget内に
# 収まる契約にする（Python objectの小さなoverheadは従来どおり推定外）。
_SNAPSHOT_PROCESS_COPY_FACTOR = 3

# 親 process と spawn worker はそれぞれ独立した service instance を持つ。
_CAPTURE_SERVICE = CaptureService()


class ExportQueueFullError(RuntimeError):
    """明示 capture が件数または aggregate byte budget で拒否された。"""

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str = "unknown",
        request_count: int = 0,
        request_limit: int = 0,
        retained_bytes: int = 0,
        requested_bytes: int = 0,
        byte_limit: int = 0,
    ) -> None:
        self.reason = str(reason)
        self.request_count = int(request_count)
        self.request_limit = int(request_limit)
        self.retained_bytes = int(retained_bytes)
        self.requested_bytes = int(requested_bytes)
        self.byte_limit = int(byte_limit)
        projected = self.retained_bytes + self.requested_bytes
        detail = (
            "capture queue が満杯のため rejected: "
            f"reason={self.reason}, requests={self.request_count}/{self.request_limit}, "
            f"estimated-retained={self.retained_bytes / (1024 * 1024):.1f} MiB, "
            f"estimated-request={self.requested_bytes / (1024 * 1024):.1f} MiB, "
            f"projected={projected / (1024 * 1024):.1f} MiB, "
            f"limit={self.byte_limit / (1024 * 1024):.1f} MiB"
        )
        super().__init__(detail if message is None else str(message))


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
    t: float = 0.0
    provenance: CaptureProvenance | None = None
    gcode_config: GCodeExportConfig | None = None

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
        capture_t = float(self.t)
        if not isfinite(capture_t):
            raise ValueError("t は有限値である必要がある")
        object.__setattr__(self, "t", capture_t)
        if self.provenance is not None and float(self.provenance.frame.t) != capture_t:
            raise ValueError("provenance.frame.t は snapshot.t と一致する必要があります")
        if self.gcode_config is not None and not isinstance(
            self.gcode_config, GCodeExportConfig
        ):
            raise TypeError("gcode_config は GCodeExportConfig または None である必要があります")

    @property
    def retained_bytes(self) -> int:
        """親 process が保持する immutable geometry array の推定 byte 数。"""

        return estimate_snapshot_retained_bytes(self)


def estimate_snapshot_retained_bytes(snapshot: FrameExportSnapshot) -> int:
    """snapshot が参照する geometry array の重複を除いた byte 数を返す。

    ``RealizedGeometry`` は immutable なので、同じ array を複数 layer が共有する場合は
    物理メモリも共有される。配列 identity ごとに一度だけ数え、Python object の小さな
    overhead は含めない。test double / 旧実装で配列が見えない layer は 0 bytes とする。
    """

    seen_arrays: set[int] = set()
    total = 0
    for layer in snapshot.layers:
        realized = getattr(layer, "realized", None)
        if realized is None:
            continue
        found_array = False
        for name in ("coords", "offsets"):
            array = getattr(realized, name, None)
            nbytes = getattr(array, "nbytes", None)
            if array is None or nbytes is None:
                continue
            found_array = True
            identity = id(array)
            if identity in seen_arrays:
                continue
            seen_arrays.add(identity)
            total += max(0, int(nbytes))
        if not found_array:
            # RealizedGeometry 互換 object が array を公開せず byte_size だけを持つ場合。
            byte_size = getattr(realized, "byte_size", 0)
            total += max(0, int(byte_size))
    return int(total)


def _estimate_snapshot_process_bytes(snapshot: FrameExportSnapshot) -> int:
    """queue輸送中にprocessをまたいで同時保持し得るbyte数を保守的に返す。"""

    return int(estimate_snapshot_retained_bytes(snapshot)) * int(
        _SNAPSHOT_PROCESS_COPY_FACTOR
    )


@dataclass(frozen=True, slots=True)
class ExportQueueStatus:
    """capture admission の現在値。GUI と拒否診断で同じ契約を共有する。"""

    request_count: int
    request_limit: int
    retained_bytes: int
    byte_limit: int


@dataclass(frozen=True, slots=True)
class ExportJob:
    """worker へ渡す不変 export request。"""

    job_id: int
    kind: ExportKind
    snapshot: FrameExportSnapshot
    output_path: Path
    timeout_s: float
    # 後方互換のため request には残すが、PNG の中間 SVG 保存先としては使用しない。
    svg_output_path: Path | None = None
    output_size: tuple[int, int] | None = None
    deadline_monotonic: float | None = field(default=None, compare=False, repr=False)
    # 既定 backend の非同期実行時だけ親 process が sibling staging dir を設定する。
    # None の場合は `_execute_export_job()` を直接呼ぶ従来 semantics（output_path へ保存）。
    staging_dir: Path | None = field(default=None, compare=False, repr=False)

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
        if self.staging_dir is not None:
            object.__setattr__(self, "staging_dir", Path(self.staging_dir))


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
    # 既存 positional field の意味を変えないよう、新 metadata は末尾へ追加する。
    manifest_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", int(self.job_id))
        object.__setattr__(self, "kind", ExportKind(self.kind))
        object.__setattr__(self, "status", ExportJobStatus(self.status))
        object.__setattr__(self, "output_path", Path(self.output_path))
        object.__setattr__(self, "paths", tuple(Path(path) for path in self.paths))
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        if self.worker_pid is not None:
            object.__setattr__(self, "worker_pid", int(self.worker_pid))
        if self.worker_exitcode is not None:
            object.__setattr__(self, "worker_exitcode", int(self.worker_exitcode))


@dataclass(frozen=True, slots=True)
class _WorkerReady:
    pid: int


_WorkerMessage = _WorkerReady | ExportJobResult
ExportBackend = Callable[[ExportJob], Sequence[Path]]


def _job_work_output_path(job: ExportJob) -> Path:
    """worker が書く path を返す。非同期既定 backend では staging 内へ隔離する。"""

    staging_dir = job.staging_dir
    if staging_dir is None:
        return job.output_path
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir / job.output_path.name


def _cleanup_job_staging(job: ExportJob) -> None:
    """job-private staging directory を best-effort で削除する。"""

    staging_dir = job.staging_dir
    if staging_dir is not None:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _commit_staged_outputs(
    job: ExportJob,
    staged_paths: Sequence[Path],
) -> tuple[tuple[Path, ...], Path | None]:
    """成果物と manifest を上書きなしの一世代として親側で公開する。"""

    staging_dir = job.staging_dir
    if staging_dir is None:
        return tuple(Path(path) for path in staged_paths), None

    published = _CAPTURE_SERVICE.publish_staged(
        job.snapshot,
        job.output_path,
        staged_paths,
        mode=job.kind.value,
        output_size=job.output_size,
    )
    if published is None:
        return (), None
    return published.artifact_paths, published.manifest_path


def _finalize_default_backend_result(
    job: ExportJob,
    result: ExportJobResult,
) -> ExportJobResult:
    """worker result を親側で commit し、staging を必ず掃除する。"""

    try:
        if result.status is not ExportJobStatus.SUCCESS:
            return result
        committed_paths, manifest_path = _commit_staged_outputs(job, result.paths)
        return replace(
            result,
            paths=committed_paths,
            manifest_path=manifest_path,
        )
    except Exception:
        return ExportJobResult(
            job_id=result.job_id,
            kind=result.kind,
            status=ExportJobStatus.ERROR,
            output_path=result.output_path,
            error="parent-side export commit failed:\n" + traceback.format_exc(),
            worker_pid=result.worker_pid,
            worker_exitcode=result.worker_exitcode,
        )
    finally:
        _cleanup_job_staging(job)


def _execute_export_job(job: ExportJob) -> tuple[Path, ...]:
    """既定 backend として PNG/G-code job を同期実行する。"""

    work_output_path = _job_work_output_path(job)
    gcode_config = (
        job.snapshot.gcode_config
        if job.kind in {ExportKind.GCODE, ExportKind.GCODE_LAYERS}
        else None
    )
    return _CAPTURE_SERVICE.encode(
        job.snapshot,
        work_output_path,
        mode=job.kind.value,
        output_size=job.output_size,
        timeout_s=job.timeout_s,
        deadline_monotonic=job.deadline_monotonic,
        gcode_config=gcode_config,
    )


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
            try:
                result_q.put(result)
            finally:
                # 次のtask_q.get()で待機している間に直前の巨大snapshotをworkerが
                # 保持し続けない。Queue feederが必要なのはsnapshotを含まないresultだけ。
                del result
                del job
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
    - worker へ渡す in-flight job は 1 件、親の pending FIFO は bounded。
    - 明示した保存操作は置換せず順番に実行し、満杯なら明示的に拒否する。
    - worker death/timeout/cancel 後は Queue ごと交換し、古い job の再実行を防ぐ。
    """

    def __init__(
        self,
        *,
        backend: ExportBackend = _execute_export_job,
        default_timeout_s: float = 30.0,
        max_pending_jobs: int = _DEFAULT_PENDING_JOB_LIMIT,
        max_retained_bytes: int = _DEFAULT_MAX_RETAINED_BYTES,
        runtime_limits: RuntimeLimits | None = None,
    ) -> None:
        if runtime_limits is not None:
            if not isinstance(runtime_limits, RuntimeLimits):
                raise TypeError("runtime_limits は RuntimeLimits である必要があります")
            max_pending_jobs = int(runtime_limits.capture_queue_pending_jobs)
            max_retained_bytes = int(runtime_limits.capture_queue_bytes)
        timeout_s = float(default_timeout_s)
        if not isfinite(timeout_s) or timeout_s <= 0.0:
            raise ValueError("default_timeout_s は正である必要がある")
        if int(max_pending_jobs) < 0:
            raise ValueError("max_pending_jobs は 0 以上である必要がある")
        if isinstance(max_retained_bytes, bool) or int(max_retained_bytes) < 0:
            raise ValueError("max_retained_bytes は 0 以上の整数である必要がある")

        self._ctx = mp.get_context("spawn")
        self._backend = backend
        self._uses_parent_commit = backend is _execute_export_job
        self._default_timeout_s = timeout_s
        self._max_pending_jobs = int(max_pending_jobs)
        self._max_retained_bytes = int(max_retained_bytes)
        self._task_q: mp.Queue[ExportJob | None]
        self._result_q: mp.Queue[_WorkerMessage]
        self._proc: mp_process.BaseProcess | None = None
        self._worker_generation = 0
        self._ready_pid: int | None = None
        self._closed = False
        self._next_job_id = 0
        self._in_flight: ExportJob | None = None
        self._pending: deque[ExportJob] = deque()
        self._completed: deque[ExportJobResult] = deque(maxlen=_COMPLETED_RESULT_LIMIT)
        # 同じ immutable snapshot を pause 中に連続保存する場合、親 process の
        # geometry 参照は共有する。job ごとの refcount だけを増やし、親参照 +
        # Queue serialization + worker copy の保守的な推定bytesを一度だけ数える。
        self._retained_snapshots: dict[
            int, tuple[FrameExportSnapshot, int, int]
        ] = {}
        self._retained_job_ids: set[int] = set()
        self._retained_bytes = 0

        self._create_queues()

    @property
    def in_flight_job(self) -> ExportJob | None:
        """現在 worker へ渡している job を返す。"""

        return self._in_flight

    @property
    def pending_job(self) -> ExportJob | None:
        """次に実行する pending job を返す。"""

        return self._pending[0] if self._pending else None

    @property
    def pending_job_count(self) -> int:
        """親 process で待機中の job 数を返す。"""

        return len(self._pending)

    @property
    def request_count(self) -> int:
        """in-flight と pending を合わせた accepted request 件数。"""

        return (1 if self._in_flight is not None else 0) + len(self._pending)

    @property
    def request_limit(self) -> int:
        """同時に accepted として保持する最大 request 件数。"""

        return self._max_pending_jobs + 1

    @property
    def retained_bytes(self) -> int:
        """accepted snapshotのprocess横断・同時保持byte数の保守的推定。"""

        return int(self._retained_bytes)

    @property
    def max_retained_bytes(self) -> int:
        """aggregate process-wide snapshot byte 推定の上限。"""

        return int(self._max_retained_bytes)

    @property
    def queue_status(self) -> ExportQueueStatus:
        """GUI/診断用の同一 backpressure 状態を返す。"""

        return ExportQueueStatus(
            request_count=self.request_count,
            request_limit=self.request_limit,
            retained_bytes=self.retained_bytes,
            byte_limit=self.max_retained_bytes,
        )

    @property
    def can_submit(self) -> bool:
        """件数上、新しい job を受理できるなら True（byte 判定には snapshot が必要）。"""

        if self._closed:
            return False
        return self.request_count < self.request_limit

    def _incremental_snapshot_bytes(self, snapshot: FrameExportSnapshot) -> int:
        if id(snapshot) in self._retained_snapshots:
            return 0
        return _estimate_snapshot_process_bytes(snapshot)

    def _admission_error(
        self, snapshot: FrameExportSnapshot
    ) -> ExportQueueFullError | None:
        requested_bytes = self._incremental_snapshot_bytes(snapshot)
        def error(reason: str) -> ExportQueueFullError:
            return ExportQueueFullError(
                reason=reason,
                request_count=self.request_count,
                request_limit=self.request_limit,
                retained_bytes=self.retained_bytes,
                requested_bytes=requested_bytes,
                byte_limit=self.max_retained_bytes,
            )

        if self.request_count >= self.request_limit:
            return error("count")
        if self.retained_bytes + requested_bytes > self.max_retained_bytes:
            return error("bytes")
        return None

    def ensure_can_submit(self, snapshot: FrameExportSnapshot) -> None:
        """同じ submit 契約で事前検査し、拒否理由を path 予約前に返す。"""

        if self._closed:
            raise RuntimeError("ExportJobSystem は close 済みです")
        self._service()
        error = self._admission_error(snapshot)
        if error is not None:
            raise error

    def can_submit_snapshot(self, snapshot: FrameExportSnapshot) -> bool:
        """件数と aggregate bytes の両方で snapshot を受理できるなら True。"""

        try:
            self.ensure_can_submit(snapshot)
        except (ExportQueueFullError, RuntimeError):
            return False
        return True

    def _retain_job(self, job: ExportJob) -> None:
        if job.job_id in self._retained_job_ids:
            return
        snapshot_id = id(job.snapshot)
        current = self._retained_snapshots.get(snapshot_id)
        if current is None:
            byte_size = _estimate_snapshot_process_bytes(job.snapshot)
            self._retained_snapshots[snapshot_id] = (job.snapshot, 1, byte_size)
            self._retained_bytes += byte_size
        else:
            snapshot, refcount, byte_size = current
            self._retained_snapshots[snapshot_id] = (
                snapshot,
                refcount + 1,
                byte_size,
            )
        self._retained_job_ids.add(job.job_id)

    def _release_job(self, job: ExportJob) -> None:
        if job.job_id not in self._retained_job_ids:
            return
        self._retained_job_ids.remove(job.job_id)
        snapshot_id = id(job.snapshot)
        snapshot, refcount, byte_size = self._retained_snapshots[snapshot_id]
        if refcount <= 1:
            del self._retained_snapshots[snapshot_id]
            self._retained_bytes -= byte_size
        else:
            self._retained_snapshots[snapshot_id] = (
                snapshot,
                refcount - 1,
                byte_size,
            )

    @property
    def has_work(self) -> bool:
        """worker 実行中または pending の job が残っているなら True。"""

        return self._in_flight is not None or bool(self._pending)

    def _create_queues(self) -> None:
        task_q: mp.Queue[ExportJob | None] | None = None
        try:
            task_q = self._ctx.Queue(maxsize=1)
            result_q: mp.Queue[_WorkerMessage] = self._ctx.Queue(maxsize=2)
        except BaseException:
            # 2本目のQueue構築失敗時も、1本目のfeeder/thread descriptorを残さない。
            if task_q is not None:
                try:
                    self._close_queue(task_q, cancel=True)
                except BaseException:
                    pass
            raise
        self._task_q = task_q
        self._result_q = result_q

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
        first_error: BaseException | None = None

        def attempt(action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        def is_alive() -> bool:
            nonlocal first_error
            try:
                return bool(proc.is_alive())
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                # 生存状態を確認できない場合も、後続の terminate/kill は試す。
                return True

        attempt(lambda: proc.join(timeout=_WORKER_JOIN_TIMEOUT_S))
        if is_alive():
            attempt(proc.terminate)
            attempt(lambda: proc.join(timeout=_WORKER_JOIN_TIMEOUT_S))
        if is_alive():
            attempt(proc.kill)
            attempt(lambda: proc.join(timeout=_WORKER_JOIN_TIMEOUT_S))
        if not is_alive():
            attempt(proc.close)

        if first_error is not None:
            raise first_error

    @staticmethod
    def _close_queue(worker_queue: mp_queues.Queue[Any], *, cancel: bool) -> None:
        first_error: BaseException | None = None

        def attempt(action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if cancel:
            attempt(worker_queue.cancel_join_thread)
        attempt(worker_queue.close)
        attempt(worker_queue.join_thread)

        if first_error is not None:
            raise first_error

    def _close_queues(self, *, cancel_pending: bool) -> None:
        first_error: BaseException | None = None
        for worker_queue, cancel in (
            (self._task_q, cancel_pending),
            (self._result_q, False),
        ):
            try:
                self._close_queue(worker_queue, cancel=cancel)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error

    def _replace_worker(self) -> None:
        first_error: BaseException | None = None
        proc = self._proc
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.terminate()
            except BaseException as exc:
                first_error = exc
            try:
                self._join_process(proc)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        self._proc = None
        try:
            self._close_queues(cancel_pending=True)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        try:
            self._create_queues()
        except BaseException as exc:
            if first_error is None:
                first_error = exc

        if first_error is not None:
            raise first_error

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
            if self._uses_parent_commit:
                output_parent = job.output_path.parent
                output_parent.mkdir(parents=True, exist_ok=True)
                staging_dir = Path(
                    tempfile.mkdtemp(
                        prefix=f".{job.output_path.stem}.export-{job.job_id}-",
                        dir=output_parent,
                    )
                )
                dispatched = replace(dispatched, staging_dir=staging_dir)
            if self._proc is None:
                self._start_worker()
            self._task_q.put_nowait(dispatched)
        except Exception:
            _cleanup_job_staging(dispatched)
            self._completed.append(
                self._terminal_result(
                    job,
                    ExportJobStatus.ERROR,
                    error=traceback.format_exc(),
                )
            )
            self._release_job(job)
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
            if self._uses_parent_commit:
                message = _finalize_default_backend_result(current, message)
            self._completed.append(message)
            self._in_flight = None
            self._release_job(current)

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
            self._release_job(current)
        try:
            self._replace_worker()
        finally:
            if current is not None:
                _cleanup_job_staging(current)

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
        self._release_job(current)
        try:
            self._replace_worker()
        finally:
            _cleanup_job_staging(current)

    def _service(self) -> None:
        self._drain_worker_messages()
        self._recover_dead_worker()
        self._expire_timed_out_job()
        if self._in_flight is None and self._pending:
            self._dispatch(self._pending.popleft())

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
        """job を bounded FIFO へ投入する。満杯なら明示的に拒否する。"""

        if self._closed:
            raise RuntimeError("ExportJobSystem は close 済みです")
        self._service()

        error = self._admission_error(snapshot)
        if error is not None:
            raise error

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

        self._retain_job(job)

        if self._in_flight is None:
            self._dispatch(job)
            return job
        self._pending.append(job)
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

        kept: deque[ExportJob] = deque()
        for pending in self._pending:
            if job_id is None or pending.job_id == int(job_id):
                self._completed.append(
                    self._terminal_result(
                        pending,
                        ExportJobStatus.CANCELLED,
                        error="cancelled",
                    )
                )
                self._release_job(pending)
                cancelled = True
            else:
                kept.append(pending)
        self._pending = kept

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
            self._release_job(current)
            cancelled = True
            try:
                self._replace_worker()
            finally:
                _cleanup_job_staging(current)

        if self._in_flight is None and self._pending:
            self._dispatch(self._pending.popleft())
        return cancelled

    def close(self) -> None:
        """実行中・pending job を取消し、worker/Queue を冪等に閉じる。"""

        if self._closed:
            return
        self._closed = True

        current = self._in_flight
        jobs_to_cancel = (() if current is None else (current,)) + tuple(self._pending)
        for job in jobs_to_cancel:
            if job is not None:
                self._completed.append(
                    self._terminal_result(
                        job,
                        ExportJobStatus.CANCELLED,
                        error="ExportJobSystem.close()",
                    )
                )
                self._release_job(job)
        had_in_flight = self._in_flight is not None
        self._in_flight = None
        self._pending.clear()

        first_error: BaseException | None = None
        proc = self._proc
        if proc is not None and not had_in_flight:
            try:
                if proc.is_alive():
                    self._task_q.put_nowait(None)
            except queue.Full:
                had_in_flight = True
            except BaseException as exc:
                first_error = exc
                had_in_flight = True
        if proc is not None:
            try:
                self._join_process(proc)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        self._proc = None
        try:
            self._close_queues(cancel_pending=had_in_flight)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        finally:
            if current is not None:
                _cleanup_job_staging(current)

        if first_error is not None:
            raise first_error


__all__ = [
    "ExportJob",
    "ExportJobResult",
    "ExportJobStatus",
    "ExportJobSystem",
    "ExportQueueStatus",
    "ExportQueueFullError",
    "ExportKind",
    "FrameExportSnapshot",
    "estimate_snapshot_retained_bytes",
]
