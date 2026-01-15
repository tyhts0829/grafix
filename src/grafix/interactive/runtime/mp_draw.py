"""
どこで: `src/grafix/interactive/runtime/mp_draw.py`。
何を: `draw(t)` を別プロセスで実行し、結果（Layer/観測レコード）を Queue 経由で受け渡す。
なぜ: draw が支配的なスケッチでも、メイン（イベント処理 + GL）を詰まらせずに描画を継続するため。

メインフロー
------------
1. メインプロセスが `submit()` でタスク（t と parameter snapshot）を enqueue する。
   - task queue は有限なので、詰まったら古いタスクを捨てて「最新優先」にする。
2. worker プロセスが task を取り出し、snapshot を固定して `draw(t)` を実行する。
3. worker が `DrawResult` を返し、メインは `poll_latest()` で最も新しい結果だけを採用する。

設計上のポイント
----------------
- multiprocessing は `"spawn"` を使うため、worker は「空の Python」から起動する。
  そのため `draw` は picklable（通常はモジュールトップレベル定義）である必要がある。
- worker 内の例外は握りつぶさず、traceback 文字列を `DrawResult.error` に載せて返す。
- parameter 観測（FrameParamRecord/FrameLabelRecord）は worker で収集して返し、
  メイン側で当該フレームの `FrameParamsBuffer` にマージして使う（例: SceneRunner）。
"""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.process as mp_process
import multiprocessing.queues as mp_queues
import queue
import traceback
from dataclasses import dataclass
from typing import Callable

from grafix.core.layer import Layer
from grafix.core.parameters import FrameLabelRecord, FrameParamRecord
from grafix.core.parameters.context import parameter_context_from_snapshot
from grafix.core.scene import SceneItem, normalize_scene


@dataclass(frozen=True, slots=True)
class _DrawTask:
    """worker に渡す 1 フレーム分の入力。

    Notes
    -----
    - `snapshot` は draw 実行中の param 解決を決定的にするための値で、worker 側では
      `parameter_context_from_snapshot()` によって contextvars に固定される。
    - `frame_id` はメインプロセス側で単調増加し、結果の新旧判定に使う。
    """

    frame_id: int
    t: float
    snapshot: dict
    cc_snapshot: dict[int, float] | None


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


def _draw_worker_main(
    task_q: mp_queues.Queue[_DrawTask | None],
    result_q: mp_queues.Queue[DrawResult],
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

    # built-in op の登録（registry）を確実に行う。
    # draw 側が `from grafix.api import G/E` を行っていないケースでも動くようにする。
    # `spawn` では worker が新規プロセスになるため、親プロセスで済んでいる import の
    # 副作用（登録）を期待せず、ここで明示的に初期化しておく。
    import grafix.api.effects  # noqa: F401
    import grafix.api.primitives  # noqa: F401

    while True:
        task = task_q.get()
        if task is None:
            return
        try:
            # snapshot を固定したコンテキスト内で draw を実行することで、
            # GUI の状態（ParamStore）と独立に「このフレームで解決すべき値」を決定できる。
            with parameter_context_from_snapshot(
                task.snapshot, cc_snapshot=task.cc_snapshot
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
            # draw の例外は worker を落とさず、メインへ「失敗したフレーム」として返す。
            result_q.put(
                DrawResult(
                    frame_id=int(task.frame_id),
                    layers=[],
                    records=[],
                    labels=[],
                    error=traceback.format_exc(),
                )
            )


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
        RuntimeError
            worker の起動に失敗した場合。
        """

        if int(n_worker) < 2:
            raise ValueError("n_worker は 2 以上である必要がある")

        # `spawn` は macOS での安全側（fork しない）として選ぶ。
        # 代わりに、worker へ渡す `draw` は picklable である必要がある。
        self._ctx = mp.get_context("spawn")
        # タスクが詰まりすぎるとリアルタイム性が落ちるため、キューは小さく保つ。
        self._task_q: mp.Queue[_DrawTask | None] = self._ctx.Queue(maxsize=int(n_worker))
        self._result_q: mp.Queue[DrawResult] = self._ctx.Queue()
        self._procs: list[mp_process.BaseProcess] = []

        self._next_frame_id = 0
        self._latest: DrawResult | None = None
        # `poll_latest()` の「同じ結果を二度返さない」ためのブックキーピング。
        self._last_published_frame_id = 0

        try:
            for i in range(int(n_worker)):
                proc = self._ctx.Process(
                    target=_draw_worker_main,
                    args=(self._task_q, self._result_q, draw),
                    name=f"grafix-mp-draw-{i}",
                )
                proc.start()
                self._procs.append(proc)
        except Exception as exc:
            # 起動途中で失敗しても worker を残さないように後始末する。
            self.close()
            raise RuntimeError(
                "mp-draw の worker 起動に失敗しました。"
                "draw がモジュールトップレベル定義で picklable か、"
                "スケッチ側が __main__ ガードを持つか確認してください。"
            ) from exc

    def submit(
        self, *, t: float, snapshot: dict, cc_snapshot: dict[int, float] | None = None
    ) -> None:
        """このフレームの draw を worker に依頼する（ノンブロッキング）。

        Notes
        -----
        task queue が満杯のときは、最も古いタスクを 1 つ捨てて再投入する。
        それでも入らなければ、このフレームは諦める（UI を止めないことを優先）。
        """

        self._next_frame_id += 1
        task = _DrawTask(
            frame_id=self._next_frame_id,
            t=float(t),
            snapshot=snapshot,
            cc_snapshot=cc_snapshot,
        )
        try:
            self._task_q.put_nowait(task)
        except queue.Full:
            # 混雑時は「最新を優先」するため、古い task を 1 つ捨てて入れ直す。
            try:
                _ = self._task_q.get_nowait()
            except queue.Empty:
                return
            try:
                self._task_q.put_nowait(task)
            except queue.Full:
                return

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
        """

        best: DrawResult | None = None
        while True:
            try:
                res = self._result_q.get_nowait()
            except queue.Empty:
                break
            # 複数の結果が溜まっていても「最新だけ」を採用する。
            if best is None or int(res.frame_id) > int(best.frame_id):
                best = res

        if best is None:
            return None

        if self._latest is None or int(best.frame_id) > int(self._latest.frame_id):
            self._latest = best

        if int(self._latest.frame_id) <= int(self._last_published_frame_id):
            return None

        self._last_published_frame_id = int(self._latest.frame_id)
        return self._latest

    def latest_layers(self) -> list[Layer] | None:
        """直近の成功結果の layers を返す（失敗/未到着なら None）。"""

        if self._latest is None or self._latest.error is not None:
            return None
        return self._latest.layers

    def close(self) -> None:
        """worker を終了する（best-effort / 複数回呼んでもよい）。"""

        if not self._procs:
            return

        for _ in self._procs:
            try:
                # sentinel を送って通常終了を促す。
                self._task_q.put_nowait(None)
            except Exception:
                pass

        for proc in self._procs:
            try:
                # まずは短い timeout で join し、終わらない場合は terminate へ進む。
                proc.join(timeout=1.0)
            except Exception:
                pass

        for proc in self._procs:
            if proc.is_alive():
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.join(timeout=1.0)
                except Exception:
                    pass

        self._procs.clear()
