"""
どこで: `src/grafix/interactive/runtime/mp_draw.py`。
何を: `draw(t)` を別プロセスで実行し、結果（Layer/観測レコード）を Queue 経由で受け渡す。
なぜ: draw が支配的なスケッチでも、メイン（イベント処理 + GL）を詰まらせずに描画を継続するため。

メインフロー
------------
1. メインプロセスが `submit()` でタスク（t と snapshot revision）を enqueue する。
   - task queue は有限なので、詰まったら古いタスクを捨てて「最新優先」にする。
   - snapshot 本体は revision 変更時だけ worker 別 control queue へ broadcast する。
2. worker プロセスが revision を照合し、snapshot を固定して `draw(t)` を実行する。
3. worker が `DrawResult` を返し、メインは `poll_latest()` で最も新しい結果だけを採用する。
4. メインは受け取った `layers` を描画パイプライン（例: `realize_scene()`）へ渡して表示/出力する。
   - worker は draw/normalize までで、realize は行わない（mp-draw は realize の並列化ではない）。

設計上のポイント
----------------
- multiprocessing は `"spawn"` を使うため、worker は「空の Python」から起動する。
  そのため `draw` は picklable（通常はモジュールトップレベル定義）である必要がある。
- `draw` の通常例外は traceback 文字列を `DrawResult.error` に載せて返す。
- worker は初期化後に ready message を返す。`SystemExit`、native crash など process 自体の
  異常終了は submit/poll 共通の health check が `MpDrawWorkerError` として通知する。
- parameter 観測（FrameParamRecord/FrameLabelRecord）は worker で収集して返し、
  メイン側で当該フレームの `FrameParamsBuffer` にマージして使う（例: SceneRunner）。
"""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.process as mp_process
import multiprocessing.queues as mp_queues
import os
import queue
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, cast

from grafix.core.layer import Layer
from grafix.core.parameters import FrameLabelRecord, FrameParamRecord
from grafix.core.parameters.context import parameter_context_from_snapshot
from grafix.core.parameters.snapshot_ops import ParamSnapshot
from grafix.core.scene import SceneItem, normalize_scene

_WORKER_READY_TIMEOUT_S = 10.0
_WORKER_JOIN_TIMEOUT_S = 1.0


class MpDrawWorkerError(RuntimeError):
    """mp-draw worker が予期せず終了したことを表す。"""

    def __init__(
        self,
        *,
        worker: str,
        pid: int | None,
        exitcode: int | None,
        detail: str | None = None,
    ) -> None:
        self.worker = str(worker)
        self.pid = None if pid is None else int(pid)
        self.exitcode = None if exitcode is None else int(exitcode)
        self.detail = None if detail is None else str(detail)
        message = (
            "mp-draw worker が予期せず終了しました: "
            f"worker={self.worker!r}, pid={self.pid}, exitcode={self.exitcode}"
        )
        if self.detail is not None:
            message = f"{message} ({self.detail})"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _DrawTask:
    """worker に渡す 1 フレーム分の入力。

    Notes
    -----
    - parameter snapshot 本体は revision が変わったときだけ別 queue で配信する。
      フレーム task は revision だけを持ち、毎フレームの pickle を避ける。
    - `frame_id` はメインプロセス側で単調増加し、結果の新旧判定に使う。
    """

    frame_id: int
    t: float
    snapshot_revision: int
    cc_snapshot: dict[int, float] | None


@dataclass(frozen=True, slots=True)
class _SnapshotUpdate:
    """worker ごとに broadcast する parameter snapshot 更新。"""

    revision: int
    snapshot: ParamSnapshot


@dataclass(frozen=True, slots=True)
class _SnapshotAck:
    """worker が snapshot 更新を処理したことを親へ通知する。"""

    worker: str
    pid: int
    requested_revision: int
    applied_revision: int
    status: str


@dataclass(frozen=True, slots=True)
class _TaskRejected:
    """worker が未知または古い snapshot revision の task を拒否した通知。"""

    frame_id: int
    worker: str
    pid: int
    requested_revision: int
    applied_revision: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class DrawResult:
    """worker からメインへ返す 1 フレーム分の結果。

    Notes
    -----
    - `layers` は `draw(t)` の戻り値を `normalize_scene()` で正規化したもの。
    - `records` / `labels` は draw 実行中に観測した parameter 情報で、メイン側の
      `FrameParamsBuffer` にマージして GUI/記録に使う（メインの ParamStore は触らない）。
    - `error` が非 None の場合、`layers/records/labels` は空で、`error` には
      `traceback.format_exc()` の文字列が入る。
    """

    frame_id: int
    layers: list[Layer]
    records: list[FrameParamRecord]
    labels: list[FrameLabelRecord]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _WorkerReady:
    """worker の初期化完了を親プロセスへ通知するメッセージ。"""

    worker: str
    pid: int


_WorkerMessage = DrawResult | _WorkerReady | _SnapshotAck | _TaskRejected


def _draw_worker_main(
    task_q: mp_queues.Queue[_DrawTask | None],
    control_q: mp_queues.Queue[_SnapshotUpdate],
    result_q: mp_queues.Queue[_WorkerMessage],
    draw: Callable[[float], SceneItem],
) -> None:
    """worker プロセスのエントリポイント。

    `task_q` から `_DrawTask` を受け取り、`draw(t)` を実行して `DrawResult` を `result_q`
    に返す。`task_q` に `None` が入ってきたら終了する。

    Notes
    -----
    worker は別プロセスなので、親プロセスの ParamStore には触れない。
    `parameter_context_from_snapshot()` で snapshot を固定し、観測結果だけを返す。
    """

    current = mp.current_process()
    worker = str(current.name)
    pid = os.getpid()
    result_q.put(_WorkerReady(worker=worker, pid=pid))

    snapshot: ParamSnapshot | None = None
    snapshot_revision: int | None = None

    def apply_snapshot(update: _SnapshotUpdate) -> None:
        """新しい snapshot だけを適用し、処理結果を必ず ack する。"""

        nonlocal snapshot, snapshot_revision
        requested = int(update.revision)
        if snapshot_revision is None or requested > snapshot_revision:
            snapshot = update.snapshot
            snapshot_revision = requested
            status = "applied"
        elif requested == snapshot_revision:
            status = "current"
        else:
            status = "stale"
        assert snapshot_revision is not None
        result_q.put(
            _SnapshotAck(
                worker=worker,
                pid=pid,
                requested_revision=requested,
                applied_revision=int(snapshot_revision),
                status=status,
            )
        )

    def drain_snapshot_updates() -> None:
        while True:
            try:
                update = control_q.get_nowait()
            except queue.Empty:
                return
            apply_snapshot(update)

    try:
        while True:
            drain_snapshot_updates()
            try:
                task = task_q.get(timeout=0.01)
            except queue.Empty:
                continue
            if task is None:
                return
            drain_snapshot_updates()
            requested_revision = int(task.snapshot_revision)
            if snapshot_revision != requested_revision or snapshot is None:
                reason = (
                    "unknown"
                    if snapshot_revision is None or requested_revision > snapshot_revision
                    else "stale"
                )
                result_q.put(
                    _TaskRejected(
                        frame_id=int(task.frame_id),
                        worker=worker,
                        pid=pid,
                        requested_revision=requested_revision,
                        applied_revision=snapshot_revision,
                        reason=reason,
                    )
                )
                continue
            try:
                # snapshot を固定したコンテキスト内で draw を実行することで、
                # GUI の状態（ParamStore）と独立に「このフレームで解決すべき値」を決定できる。
                with parameter_context_from_snapshot(
                    snapshot, cc_snapshot=task.cc_snapshot
                ) as frame_params:
                    scene = draw(float(task.t))
                    layers = normalize_scene(scene)
                result_q.put(
                    DrawResult(
                        frame_id=int(task.frame_id),
                        layers=layers,
                        # frame_params は worker 内で作ったバッファなので、値だけをコピーして返す。
                        records=list(frame_params.records),
                        labels=list(frame_params.labels),
                        error=None,
                    )
                )
            except Exception:
                # 通常の draw 例外は失敗結果として返す。SystemExit 等で process 自体が
                # 終了した場合は、親側の health check が MpDrawWorkerError として検知する。
                result_q.put(
                    DrawResult(
                        frame_id=int(task.frame_id),
                        layers=[],
                        records=[],
                        labels=[],
                        error=traceback.format_exc(),
                    )
                )
    finally:
        # Queue はプロセスごとに feeder thread を持ち得る。正常終了と SystemExit の
        # どちらでも、このプロセスが所有する endpoint を閉じて flush を待つ。
        for raw_queue in (task_q, control_q, result_q):
            worker_queue = cast(mp_queues.Queue[Any], raw_queue)
            try:
                worker_queue.close()
                worker_queue.join_thread()
            except (OSError, ValueError):
                pass


class MpDraw:
    """`draw(t)` を worker プロセスで実行し、最新結果を保持する。

    このクラスは「リアルタイム性（UI を止めない）」を優先するため、
    タスク/結果ともに古いフレームは積極的に捨てる設計になっている。

    - `submit()` はノンブロッキングで、混雑時は古いタスクを捨てて最新を優先する。
    - `poll_latest()` は result queue を drain して最大 `frame_id` の結果のみ採用する。
    - `latest_layers()` は直近の成功結果の `layers` を返す（失敗結果は None 扱い）。
    """

    def __init__(self, draw: Callable[[float], SceneItem], *, n_worker: int) -> None:
        """worker 群を起動して mp-draw を開始する。

        Parameters
        ----------
        draw : Callable[[float], SceneItem]
            スケッチの描画関数。`spawn` で渡すため picklable である必要がある。
        n_worker : int
            worker 数。2 以上。

        Raises
        ------
        ValueError
            `n_worker < 2` の場合。
        MpDrawWorkerError
            ready message より前に worker が終了した場合。
        RuntimeError
            process 自体の起動に失敗した場合。
        """

        if int(n_worker) < 2:
            raise ValueError("n_worker は 2 以上である必要がある")

        # `spawn` は macOS での安全側（fork しない）として選ぶ。
        # 代わりに、worker へ渡す `draw` は picklable である必要がある。
        self._ctx = mp.get_context("spawn")
        # タスクが詰まりすぎるとリアルタイム性が落ちるため、キューは小さく保つ。
        self._task_q: mp.Queue[_DrawTask | None] = self._ctx.Queue(maxsize=int(n_worker))
        # snapshot は全 worker が同じ revision を持つ必要があるため、worker ごとの
        # control queue へ broadcast する。共有 queue では 1 worker しか受け取れない。
        self._control_qs: list[mp.Queue[_SnapshotUpdate]] = [
            self._ctx.Queue(maxsize=1) for _ in range(int(n_worker))
        ]
        self._result_q: mp.Queue[_WorkerMessage] = self._ctx.Queue()
        self._procs: list[mp_process.BaseProcess] = []
        self._ready_worker_pids: set[int] = set()
        self._worker_snapshot_revisions: dict[int, int] = {}
        self._control_index_by_pid: dict[int, int] = {}
        self._pending_snapshot_updates: dict[int, _SnapshotUpdate] = {}
        self._queued_snapshot_revisions: dict[int, int] = {}
        self._closed = False

        self._next_frame_id = 0
        self._latest: DrawResult | None = None
        self._completed_result_count = 0
        self._pending_task: _DrawTask | None = None
        self._snapshot_broadcast_revision: int | None = None
        self._snapshot_broadcast_count = 0
        self._snapshot_ack_count = 0
        self._last_snapshot_ack: _SnapshotAck | None = None
        self._rejected_task_count = 0
        self._last_rejection: _TaskRejected | None = None
        # `poll_latest()` の「同じ結果を二度返さない」ためのブックキーピング。
        self._last_published_frame_id = 0

        try:
            for i, control_q in enumerate(self._control_qs):
                proc = self._ctx.Process(
                    target=_draw_worker_main,
                    args=(self._task_q, control_q, self._result_q, draw),
                    name=f"grafix-mp-draw-{i}",
                )
                proc.start()
                self._procs.append(proc)
                if proc.pid is not None:
                    self._control_index_by_pid[int(proc.pid)] = int(i)
            self._await_workers_ready()
        except MpDrawWorkerError:
            self.close()
            raise
        except Exception as exc:
            # 起動途中で失敗しても worker を残さないように後始末する。
            self.close()
            raise RuntimeError(
                "mp-draw の worker 起動に失敗しました。"
                "draw がモジュールトップレベル定義で picklable か、"
                "スケッチ側が __main__ ガードを持つか確認してください。"
            ) from exc

    def _await_workers_ready(self) -> None:
        """全 worker の初期化完了を待ち、起動直後の異常終了を検知する。"""

        expected = {int(proc.pid) for proc in self._procs if proc.pid is not None}
        deadline = time.monotonic() + _WORKER_READY_TIMEOUT_S

        while self._ready_worker_pids != expected:
            self._check_health()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pending = next(
                    proc
                    for proc in self._procs
                    if proc.pid is None or int(proc.pid) not in self._ready_worker_pids
                )
                error = MpDrawWorkerError(
                    worker=pending.name,
                    pid=pending.pid,
                    exitcode=pending.exitcode,
                    detail="ready message timeout",
                )
                self.close()
                raise error

            try:
                message = self._result_q.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue

            if isinstance(message, _WorkerReady) and message.pid in expected:
                self._ready_worker_pids.add(int(message.pid))

        self._check_health()

    def _check_health(self) -> None:
        """全 worker が稼働中か確認し、異常終了なら残りも閉じて例外を送出する。"""

        if self._closed:
            raise RuntimeError("MpDraw は close 済みです")

        for proc in self._procs:
            exitcode = proc.exitcode
            if exitcode is None:
                continue
            error = MpDrawWorkerError(
                worker=proc.name,
                pid=proc.pid,
                exitcode=exitcode,
            )
            # 1 worker でも失われた時点で処理能力・結果順序の契約が変わるため、
            # 残存 worker への暗黙 fallback は行わず、全体を停止して fail-fast する。
            self.close()
            raise error

    def _drain_result_queue(self) -> None:
        """result/control message を drain し、親側の状態へ反映する。"""

        while True:
            try:
                message = self._result_q.get_nowait()
            except queue.Empty:
                return

            if isinstance(message, _WorkerReady):
                self._ready_worker_pids.add(int(message.pid))
            elif isinstance(message, _SnapshotAck):
                pid = int(message.pid)
                applied = int(message.applied_revision)
                previous = self._worker_snapshot_revisions.get(pid)
                if previous is None or applied > previous:
                    self._worker_snapshot_revisions[pid] = applied
                self._snapshot_ack_count += 1
                self._last_snapshot_ack = message
                control_index = self._control_index_by_pid.get(pid)
                if control_index is not None:
                    queued_revision = self._queued_snapshot_revisions.get(control_index)
                    if queued_revision == int(message.requested_revision):
                        self._queued_snapshot_revisions.pop(control_index, None)
                    pending = self._pending_snapshot_updates.get(control_index)
                    if pending is not None and int(pending.revision) <= applied:
                        self._pending_snapshot_updates.pop(control_index, None)
            elif isinstance(message, _TaskRejected):
                self._rejected_task_count += 1
                self._last_rejection = message
            else:
                self._completed_result_count += 1
                if self._latest is None or int(message.frame_id) > int(
                    self._latest.frame_id
                ):
                    # 複数結果が溜まっていても、保持するのは最新だけ。
                    self._latest = message

    def _broadcast_snapshot(self, *, revision: int, snapshot: ParamSnapshot) -> None:
        """snapshot 本体を各 worker へ 1 回ずつ配信する。"""

        # store snapshot は外側を read-only にしているため、そのままでは spawn Queue で
        # pickle できない。revision 変更時だけ plain dict へ 1 回コピーして配信する。
        update = _SnapshotUpdate(revision=int(revision), snapshot=dict(snapshot))
        # worker ごとに「queue 内 1 件 + 親側 latest 1 件」だけを保持する。
        # 既に古い update が queue にある場合は、それが ack された後に latest を送る。
        for index in range(len(self._control_qs)):
            self._pending_snapshot_updates[index] = update
        self._flush_snapshot_updates()
        self._snapshot_broadcast_revision = int(revision)
        self._snapshot_broadcast_count += 1

    def _flush_snapshot_updates(self) -> None:
        """各 worker の空いた control queue へ pending latest を 1 件だけ送る。"""

        for index, update in tuple(self._pending_snapshot_updates.items()):
            if index in self._queued_snapshot_revisions:
                continue
            try:
                self._control_qs[index].put_nowait(update)
            except queue.Full:
                # feeder/reader 間の短い race。次の submit/poll で再試行する。
                continue
            self._queued_snapshot_revisions[index] = int(update.revision)

    def _workers_have_revision(self, revision: int) -> bool:
        expected = self._ready_worker_pids
        return bool(expected) and all(
            self._worker_snapshot_revisions.get(pid) == int(revision) for pid in expected
        )

    def _enqueue_latest(self, task: _DrawTask) -> None:
        """有限 task queue へ latest-wins で投入する。"""

        try:
            self._task_q.put_nowait(task)
        except queue.Full:
            try:
                _ = self._task_q.get_nowait()
            except queue.Empty:
                return
            try:
                self._task_q.put_nowait(task)
            except queue.Full:
                return

    def _enqueue_pending_if_ready(self) -> None:
        task = self._pending_task
        if task is None or not self._workers_have_revision(task.snapshot_revision):
            return
        self._pending_task = None
        self._enqueue_latest(task)

    def submit(
        self,
        *,
        t: float,
        snapshot_revision: int,
        snapshot: ParamSnapshot,
        cc_snapshot: dict[int, float] | None = None,
    ) -> None:
        """このフレームの draw を worker に依頼する（ノンブロッキング）。

        Notes
        -----
        task queue が満杯のときは、最も古いタスクを 1 つ捨てて再投入する。
        それでも入らなければ、このフレームは諦める（UI を止めないことを優先）。

        Raises
        ------
        MpDrawWorkerError
            worker が予期せず終了していた場合。
        RuntimeError
            close 後に呼び出した場合。
        """

        self._check_health()
        try:
            # 前フレームまでの ack を先に反映し、この submit の最新 task だけを残す。
            self._drain_result_queue()
            self._flush_snapshot_updates()
            self._next_frame_id += 1
            task = _DrawTask(
                frame_id=self._next_frame_id,
                t=float(t),
                snapshot_revision=int(snapshot_revision),
                cc_snapshot=cc_snapshot,
            )
            if self._snapshot_broadcast_revision != int(snapshot_revision):
                self._broadcast_snapshot(
                    revision=int(snapshot_revision),
                    snapshot=snapshot,
                )

            if self._workers_have_revision(int(snapshot_revision)):
                self._pending_task = None
                self._enqueue_latest(task)
            else:
                # ack 待ちの間に複数 submit されても、実行するのは最新だけ。
                self._pending_task = task
        finally:
            # enqueue 中に worker が落ちても次の frame まで空画面で待たない。
            self._check_health()

    def poll_latest(self) -> DrawResult | None:
        """worker から届いた結果を回収し、最新フレームの結果があれば返す。

        Returns
        -------
        DrawResult | None
            前回呼び出し以降に「より新しい frame_id の結果」が届いていればそれを返す。
            何も届いていない場合や、届いたが既に返した frame_id の場合は None。

        Notes
        -----
        result queue を drain して最大 `frame_id` の結果だけを採用するため、
        中間フレームの結果は捨てられる（リアルタイム性優先）。

        Raises
        ------
        MpDrawWorkerError
            worker が予期せず終了していた場合。
        RuntimeError
            close 後に呼び出した場合。
        """

        self._check_health()

        self._drain_result_queue()
        self._flush_snapshot_updates()
        self._enqueue_pending_if_ready()

        # drain 中に process が終了した場合も、その場で明示的に失敗させる。
        self._check_health()

        if self._latest is None or int(self._latest.frame_id) <= int(
            self._last_published_frame_id
        ):
            return None

        self._last_published_frame_id = int(self._latest.frame_id)
        return self._latest

    @property
    def snapshot_broadcast_count(self) -> int:
        """snapshot 本体を broadcast した revision 数を返す。"""

        return int(self._snapshot_broadcast_count)

    @property
    def snapshot_ack_count(self) -> int:
        """worker から受信した snapshot ack 数を返す。"""

        return int(self._snapshot_ack_count)

    @property
    def worker_snapshot_revisions(self) -> dict[int, int]:
        """worker pid ごとの適用済み snapshot revision を返す。"""

        return dict(self._worker_snapshot_revisions)

    @property
    def last_snapshot_ack(self) -> tuple[int, int, str] | None:
        """直近 ack の (requested, applied, status) を返す。"""

        ack = self._last_snapshot_ack
        if ack is None:
            return None
        return int(ack.requested_revision), int(ack.applied_revision), str(ack.status)

    @property
    def rejected_task_count(self) -> int:
        """未知または古い snapshot revision で拒否された task 数を返す。"""

        return int(self._rejected_task_count)

    @property
    def completed_result_count(self) -> int:
        """親が回収済みの DrawResult 総数を返す。"""

        return int(self._completed_result_count)

    @property
    def pending_snapshot_update_count(self) -> int:
        """親側で保持する worker 別 latest update 数を返す。"""

        return len(self._pending_snapshot_updates)

    @property
    def queued_snapshot_update_count(self) -> int:
        """control queue へ投入済みで ack 待ちの update 数を返す。"""

        return len(self._queued_snapshot_revisions)

    @property
    def last_rejection(self) -> tuple[int, int | None, str] | None:
        """直近拒否の (requested, applied, reason) を返す。"""

        rejection = self._last_rejection
        if rejection is None:
            return None
        return (
            int(rejection.requested_revision),
            rejection.applied_revision,
            str(rejection.reason),
        )

    def latest_layers(self) -> list[Layer] | None:
        """直近の成功結果の layers を返す（失敗/未到着なら None）。"""

        if self._latest is None or self._latest.error is not None:
            return None
        return self._latest.layers

    def _send_stop_tokens(self, count: int) -> None:
        """待機中の古い task を捨てながら、通常終了用 sentinel を送る。"""

        sent = 0
        deadline = time.monotonic() + 0.5
        while sent < int(count) and time.monotonic() < deadline:
            try:
                self._task_q.put(None, timeout=0.05)
                sent += 1
            except queue.Full:
                try:
                    _ = self._task_q.get_nowait()
                except queue.Empty:
                    pass
            except (OSError, ValueError):
                return

    @staticmethod
    def _join_processes(procs: list[mp_process.BaseProcess], *, timeout: float) -> None:
        """複数 process を合計 `timeout` 秒まで待つ。"""

        deadline = time.monotonic() + float(timeout)
        for proc in procs:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                proc.join(timeout=remaining)
            except (AssertionError, OSError, ValueError):
                pass

    @staticmethod
    def _close_queue(worker_queue: mp_queues.Queue[Any], *, cancel_pending: bool = False) -> None:
        """Queue endpoint と feeder thread を閉じる。"""

        if cancel_pending:
            # 読み手が異常終了した task queue は feeder が pipe write で詰まり得る。
            # 未処理 task は破棄対象なので、join を cancel して close を有界に保つ。
            try:
                worker_queue.cancel_join_thread()
            except (AttributeError, OSError, ValueError):
                pass
        try:
            worker_queue.close()
        except (OSError, ValueError):
            pass
        try:
            worker_queue.join_thread()
        except (AssertionError, OSError, ValueError):
            pass

    def close(self) -> None:
        """worker と Queue を終了する（複数回呼んでもよい）。"""

        if self._closed:
            return
        # health check より先に正常終了状態へ遷移し、sentinel による exitcode=0 を
        # 「予期せぬ worker death」と誤認しないようにする。
        self._closed = True

        procs = list(self._procs)
        self._send_stop_tokens(sum(proc.is_alive() for proc in procs))
        self._join_processes(procs, timeout=_WORKER_JOIN_TIMEOUT_S)

        # draw が停止しない worker だけを強制終了する。
        for proc in procs:
            if proc.is_alive():
                try:
                    proc.terminate()
                except (AttributeError, OSError, ValueError):
                    pass
        self._join_processes(procs, timeout=_WORKER_JOIN_TIMEOUT_S)

        # terminate にも反応しない場合を残さない。kill 後は timeout 無し join を避け、
        # close 自体が UI thread を永久に止めないようにする。
        for proc in procs:
            if proc.is_alive():
                try:
                    proc.kill()
                except (AttributeError, OSError, ValueError):
                    pass
        self._join_processes(procs, timeout=_WORKER_JOIN_TIMEOUT_S)

        clean_shutdown = all(proc.exitcode == 0 for proc in procs)
        self._procs.clear()
        self._close_queue(self._task_q, cancel_pending=not clean_shutdown)
        for control_q in self._control_qs:
            self._close_queue(control_q, cancel_pending=not clean_shutdown)
        self._control_qs.clear()
        self._pending_snapshot_updates.clear()
        self._queued_snapshot_revisions.clear()
        self._control_index_by_pid.clear()
        self._close_queue(self._result_q)


__all__ = ["DrawResult", "MpDraw", "MpDrawWorkerError"]
