"""interactive 描画向けの bounded performance collector。"""

from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import sys
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

_OTHER_SERIES = "<other>"
_FRAME_SAMPLE_LIMIT = 256
_EVENT_LIMIT = 4096
_TRACE_QUEUE_LIMIT = 128
_TRACE_CLOSE_TIMEOUT_S = 2.0


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return None
    return Path(str(value)).expanduser()


def _percentile(values: tuple[int, ...], fraction: float) -> float | None:
    """小さな bounded sample 列の線形補間 percentile を返す。"""

    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    weight = position - lower
    return float(ordered[lower]) * (1.0 - weight) + float(ordered[upper]) * weight


class _TraceWriter:
    """render thread を I/O から分離する bounded JSONL writer。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._queue: queue.Queue[str | None] = queue.Queue(
            maxsize=_TRACE_QUEUE_LIMIT
        )
        self._dropped = 0
        self._error: BaseException | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="grafix-performance-trace",
            daemon=True,
        )
        self._thread.start()

    @property
    def dropped(self) -> int:
        return int(self._dropped)

    def submit(self, line: str) -> None:
        if self._closed:
            return
        if self._error is not None or not self._thread.is_alive():
            self._dropped += 1
            return
        try:
            self._queue.put_nowait(str(line))
        except queue.Full:
            self._dropped += 1

    def close(self, *, footer: str | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread.is_alive():
            if footer is not None:
                try:
                    self._queue.put(
                        str(footer),
                        timeout=_TRACE_CLOSE_TIMEOUT_S,
                    )
                except queue.Full:
                    self._dropped += 1
            try:
                self._queue.put(
                    None,
                    timeout=_TRACE_CLOSE_TIMEOUT_S,
                )
            except queue.Full:
                self._dropped += 1
        self._thread.join(timeout=_TRACE_CLOSE_TIMEOUT_S)
        if self._thread.is_alive():
            raise RuntimeError(
                f"performance trace の終了が timeout しました: {self._path}"
            )
        if self._error is not None:
            raise RuntimeError(
                f"performance trace の書き込みに失敗しました: {self._path}"
            ) from self._error

    def _run(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                while True:
                    line = self._queue.get()
                    if line is None:
                        stream.flush()
                        return
                    stream.write(line)
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            # close() が sentinel 投入で永久に待たないよう、残件を捨てる。
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    return


@dataclass(frozen=True, slots=True)
class PerfTiming:
    """1 区間名の bounded 集計値。"""

    name: str
    total_ms: float
    mean_ms: float
    per_frame_ms: float
    calls: int
    calls_per_frame: float

    def as_dict(self) -> dict[str, object]:
        """structured trace 用の JSON 互換値を返す。"""

        return {
            "name": self.name,
            "total_ms": self.total_ms,
            "mean_ms": self.mean_ms,
            "per_frame_ms": self.per_frame_ms,
            "calls": self.calls,
            "calls_per_frame": self.calls_per_frame,
        }


@dataclass(frozen=True, slots=True)
class PerfEvent:
    """parameter revision と描画段階を結ぶ bounded causal event。"""

    name: str
    timestamp_ns: int
    frame_id: int | None = None
    revision: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "timestamp_ns": self.timestamp_ns,
            "frame_id": self.frame_id,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class PerfDurationDistribution:
    """draw+flip / full loop など frame 外区間の bounded tail。"""

    name: str
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "count": self.count,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
        }


@dataclass(frozen=True, slots=True)
class PerfSnapshot:
    """Inspector と trace 出力で共有する小さな immutable snapshot。"""

    frame_index: int = 0
    frame_count: int = 0
    frame_ms: float = 0.0
    frame_p50_ms: float = 0.0
    frame_p95_ms: float = 0.0
    frame_p99_ms: float = 0.0
    frame_max_ms: float = 0.0
    frame_tail_samples: int = 0
    frame_deadline_misses: int = 0
    frame_max_consecutive_deadline_misses: int = 0
    sections: tuple[PerfTiming, ...] = ()
    duration_timing: tuple[PerfDurationDistribution, ...] = ()
    operations: tuple[PerfTiming, ...] = ()
    layers: tuple[PerfTiming, ...] = ()
    events: tuple[PerfEvent, ...] = ()
    trace_dropped_records: int = 0
    trace_dropped_events: int = 0
    trace_dropped_causal_inputs: int = 0
    trace_dropped_latency_samples: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_evictions: int = 0
    worker_lag_samples: int = 0
    worker_lag_ms: float | None = None
    worker_lag_max_ms: float | None = None
    preview_samples: int = 0
    preview_fresh_results: int = 0
    preview_max_consecutive_stale_frames: int = 0
    preview_revision_lag_samples: int = 0
    preview_revision_lag: float | None = None
    preview_revision_lag_max: int | None = None
    input_to_present_samples: int = 0
    input_to_present_p50_ms: float | None = None
    input_to_present_p95_ms: float | None = None
    input_to_present_p99_ms: float | None = None
    input_to_present_max_ms: float | None = None

    @property
    def cache_hit_rate(self) -> float:
        """hit/miss の観測総数に対する hit 比率を返す。"""

        total = int(self.cache_hits) + int(self.cache_misses)
        return 0.0 if total <= 0 else float(self.cache_hits) / float(total)

    @property
    def preview_fresh_result_ratio(self) -> float:
        """preview 観測 frame に対する fresh result の比率を返す。"""

        samples = int(self.preview_samples)
        return (
            0.0
            if samples <= 0
            else float(self.preview_fresh_results) / float(samples)
        )

    def as_dict(self) -> dict[str, object]:
        """JSON Lines trace の 1 record に変換する。"""

        return {
            "schema": "grafix.performance.trace.v2",
            "frame_index": self.frame_index,
            "frame_count": self.frame_count,
            "frame_ms": self.frame_ms,
            "frame_timing": {
                "p50_ms": self.frame_p50_ms,
                "p95_ms": self.frame_p95_ms,
                "p99_ms": self.frame_p99_ms,
                "max_ms": self.frame_max_ms,
                "sample_count": self.frame_tail_samples,
                "deadline_misses": self.frame_deadline_misses,
                "max_consecutive_deadline_misses": (
                    self.frame_max_consecutive_deadline_misses
                ),
            },
            "sections": [item.as_dict() for item in self.sections],
            "duration_timing": [
                item.as_dict() for item in self.duration_timing
            ],
            "operations": [item.as_dict() for item in self.operations],
            "layers": [item.as_dict() for item in self.layers],
            "events": [item.as_dict() for item in self.events],
            "trace": {
                "dropped_records": self.trace_dropped_records,
                "dropped_events": self.trace_dropped_events,
                "dropped_causal_inputs": self.trace_dropped_causal_inputs,
                "dropped_latency_samples": (
                    self.trace_dropped_latency_samples
                ),
            },
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "evictions": self.cache_evictions,
                "hit_rate": self.cache_hit_rate,
            },
            "worker": {
                "samples": self.worker_lag_samples,
                "average_lag_ms": self.worker_lag_ms,
                "max_lag_ms": self.worker_lag_max_ms,
            },
            "preview": {
                "samples": self.preview_samples,
                "fresh_results": self.preview_fresh_results,
                "fresh_result_ratio": self.preview_fresh_result_ratio,
                "max_consecutive_stale_frames": (
                    self.preview_max_consecutive_stale_frames
                ),
                "revision_lag_samples": self.preview_revision_lag_samples,
                "average_revision_lag": self.preview_revision_lag,
                "max_revision_lag": self.preview_revision_lag_max,
            },
            "input_to_present": {
                "samples": self.input_to_present_samples,
                "p50_ms": self.input_to_present_p50_ms,
                "p95_ms": self.input_to_present_p95_ms,
                "p99_ms": self.input_to_present_p99_ms,
                "max_ms": self.input_to_present_max_ms,
            },
        }


class _PerfSection:
    def __init__(self, perf: PerfCollector, name: str) -> None:
        self._perf = perf
        self._name = str(name)
        self._t0_ns = 0

    def __enter__(self) -> None:
        self._t0_ns = time.perf_counter_ns()

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        dt = time.perf_counter_ns() - self._t0_ns
        self._perf._add_section(self._name, int(dt))


class PerfCollector:
    """フレーム性能を bounded 集計し、Inspector/JSON trace へ渡す。

    Parameters
    ----------
    enabled : bool
        False の場合は計測処理を軽量な no-op にする。
    print_every : int, optional
        集計 window のフレーム数。console/JSON trace の出力周期でもある。
    gpu_finish : bool, optional
        呼び出し側が GPU 同期計測を行うかを示す既存フラグ。
    top_n : int, optional
        snapshot に残す section/operation/layer の最大件数。
    max_series : int, optional
        1 window 内で集計する動的な名前の最大件数。
    console_output : bool or None, optional
        既存の ``[grafix-perf]`` 出力を行うか。None は ``enabled`` と同値。
    trace_path : pathlib.Path or str or None, optional
        structured JSON Lines trace の保存先。
    snapshot_callback : Callable or None, optional
        フレーム境界で最新 snapshot を受け取る callback。

    Notes
    -----
    動的な operation/layer 名は ``max_series`` で、公開 snapshot は ``top_n`` で
    制限する。trace はディスクへ逐次追記し、履歴をメモリに保持しない。
    """

    def __init__(
        self,
        *,
        enabled: bool,
        print_every: int = 60,
        gpu_finish: bool = False,
        top_n: int = 5,
        max_series: int = 64,
        console_output: bool | None = None,
        trace_path: str | Path | None = None,
        snapshot_callback: Callable[[PerfSnapshot], None] | None = None,
        frame_deadline_ms: float = 1000.0 / 60.0,
        defer_frame_finalize: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.print_every = int(print_every) if int(print_every) > 0 else 60
        self.gpu_finish = bool(gpu_finish)
        self._top_n = max(1, int(top_n))
        self._max_series = max(2, int(max_series))
        self._console_output = (
            self.enabled if console_output is None else bool(console_output)
        )
        self._trace_path = (
            None if trace_path is None else Path(trace_path).expanduser()
        )
        deadline = float(frame_deadline_ms)
        self._frame_deadline_ns = (
            0
            if not math.isfinite(deadline) or deadline <= 0.0
            else int(deadline * 1_000_000.0)
        )
        self._snapshot_callback = snapshot_callback
        self._defer_frame_finalize = bool(defer_frame_finalize)
        self._trace_writer = (
            None if self._trace_path is None else _TraceWriter(self._trace_path)
        )
        self._trace_records_emitted = 0
        self._closed = False
        writer = self._trace_writer
        if writer is not None:
            writer.submit(
                json.dumps(
                    {
                        "schema": "grafix.performance.trace.v2",
                        "record_type": "header",
                        "timestamp_ns": time.monotonic_ns(),
                        "process": {
                            "pid": os.getpid(),
                            "python": sys.version.split()[0],
                        },
                        "config": {
                            "frame_deadline_ms": deadline,
                            "print_every": self.print_every,
                            "sample_limit": _FRAME_SAMPLE_LIMIT,
                            "event_limit": _EVENT_LIMIT,
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

        self._frame_index = 0
        self._window_frames = 0
        self._pending_frame_elapsed_ns: deque[int] = deque()
        self._frame_samples_ns: deque[int] = deque(maxlen=_FRAME_SAMPLE_LIMIT)
        self._frame_deadline_misses = 0
        self._frame_consecutive_deadline_misses = 0
        self._frame_max_consecutive_deadline_misses = 0
        self._events: deque[PerfEvent] = deque(maxlen=_EVENT_LIMIT)
        self._event_drop_count = 0
        self._causal_input_drop_count = 0
        self._latency_sample_drop_count = 0
        self._duration_samples_ns: dict[str, deque[int]] = {}
        self._input_created_ns: OrderedDict[int, int] = OrderedDict()
        self._style_input_created_ns: OrderedDict[int, int] = OrderedDict()
        self._input_to_present_ns: deque[int] = deque(
            maxlen=_FRAME_SAMPLE_LIMIT
        )
        self._sum_ns: dict[str, int] = {}
        self._calls: dict[str, int] = {}
        self._operation_sum_ns: dict[str, int] = {}
        self._operation_calls: dict[str, int] = {}
        self._layer_sum_ns: dict[str, int] = {}
        self._layer_calls: dict[str, int] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0
        self._worker_lag_sum_ms = 0.0
        self._worker_lag_max_ms = 0.0
        self._worker_lag_samples = 0
        self._preview_samples = 0
        self._preview_fresh_results = 0
        self._preview_consecutive_stale_frames = 0
        self._preview_max_consecutive_stale_frames = 0
        self._preview_revision_lag_sum = 0
        self._preview_revision_lag_max = 0
        self._preview_revision_lag_samples = 0
        self._snapshot = PerfSnapshot()

    @classmethod
    def from_env(
        cls,
        *,
        enabled_by_default: bool = False,
        snapshot_callback: Callable[[PerfSnapshot], None] | None = None,
        defer_frame_finalize: bool = False,
    ) -> PerfCollector:
        """環境変数から設定して作成する。

        ``GRAFIX_PERF=1`` は console 集計、``GRAFIX_PERF_TRACE=/path`` は
        GUI の有無に依存しない JSON Lines trace を有効にする。
        """

        console_output = _env_flag("GRAFIX_PERF")
        trace_path = _env_path("GRAFIX_PERF_TRACE")
        return cls(
            enabled=bool(enabled_by_default or console_output or trace_path is not None),
            print_every=_env_int("GRAFIX_PERF_EVERY", 60),
            gpu_finish=_env_flag("GRAFIX_PERF_GPU_FINISH"),
            console_output=console_output,
            trace_path=trace_path,
            snapshot_callback=snapshot_callback,
            defer_frame_finalize=defer_frame_finalize,
        )

    def section(self, name: str) -> contextlib.AbstractContextManager[None]:
        """``with`` で囲った汎用区間の時間を加算する。"""

        if not self.enabled:
            return contextlib.nullcontext()
        return _PerfSection(self, str(name))

    @contextlib.contextmanager
    def frame(self) -> Iterator[None]:
        """1 フレーム全体を計測し、bounded snapshot を更新する。"""

        if not self.enabled:
            yield
            return

        t0 = time.perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ns = int(time.perf_counter_ns() - t0)
            # production の Frame tail/deadline は full multi-window loop で
            # 統一する。preview core は独立した tail として保持する。
            self.record_duration("preview_core", elapsed_ns)
            self._pending_frame_elapsed_ns.append(elapsed_ns)
            if not self._defer_frame_finalize:
                self.finish_frame()

    def finish_frame(self, *, deadline_elapsed_ns: int | None = None) -> None:
        """flip/full-loop 後に 1 frame の snapshot と trace window を確定する。"""

        if not self.enabled or not self._pending_frame_elapsed_ns:
            return
        core_elapsed_ns = self._pending_frame_elapsed_ns.popleft()
        deadline_sample_ns = (
            core_elapsed_ns
            if deadline_elapsed_ns is None
            else max(0, int(deadline_elapsed_ns))
        )
        self._add_section("frame", deadline_sample_ns)
        self._frame_samples_ns.append(deadline_sample_ns)
        deadline_ns = int(self._frame_deadline_ns)
        if deadline_ns > 0 and deadline_sample_ns > deadline_ns:
            self._frame_deadline_misses += 1
            self._frame_consecutive_deadline_misses += 1
            self._frame_max_consecutive_deadline_misses = max(
                self._frame_max_consecutive_deadline_misses,
                self._frame_consecutive_deadline_misses,
            )
        else:
            self._frame_consecutive_deadline_misses = 0
        self._window_frames += 1
        self._frame_index += 1
        emit_window = self._window_frames >= self.print_every
        self._refresh_snapshot(include_events=emit_window)
        callback = self._snapshot_callback
        if callback is not None:
            callback(self._snapshot)
        if emit_window:
            self._emit_window()
            self._reset_window()

    def record_event(
        self,
        name: str,
        *,
        frame_id: int | None = None,
        revision: int | None = None,
        timestamp_ns: int | None = None,
    ) -> None:
        """frame/revision と結び付く causal event を bounded に記録する。"""

        if not self.enabled:
            return
        event_name = str(name)
        event_timestamp_ns = (
            time.monotonic_ns()
            if timestamp_ns is None
            else max(0, int(timestamp_ns))
        )
        normalized_revision = None if revision is None else int(revision)
        if len(self._events) == self._events.maxlen:
            self._event_drop_count += 1
        self._events.append(
            PerfEvent(
                name=event_name,
                timestamp_ns=event_timestamp_ns,
                frame_id=None if frame_id is None else int(frame_id),
                revision=normalized_revision,
            )
        )
        if normalized_revision is None:
            return
        if event_name == "parameter_revision_created":
            self._remember_input_revision(
                self._input_created_ns,
                normalized_revision,
                event_timestamp_ns,
            )
        elif event_name == "parameter_style_revision_created":
            self._remember_input_revision(
                self._style_input_created_ns,
                normalized_revision,
                event_timestamp_ns,
            )
        elif event_name == "preview_presented":
            self._match_presented_inputs(
                self._input_created_ns,
                normalized_revision,
                event_timestamp_ns,
            )
        elif event_name == "preview_style_presented":
            self._match_presented_inputs(
                self._style_input_created_ns,
                normalized_revision,
                event_timestamp_ns,
            )

    def _remember_input_revision(
        self,
        pending: OrderedDict[int, int],
        revision: int,
        timestamp_ns: int,
    ) -> None:
        pending[int(revision)] = int(timestamp_ns)
        pending.move_to_end(int(revision))
        while len(pending) > _EVENT_LIMIT:
            pending.popitem(last=False)
            self._causal_input_drop_count += 1

    def _match_presented_inputs(
        self,
        pending: OrderedDict[int, int],
        revision: int,
        timestamp_ns: int,
    ) -> None:
        for created_revision, created_ns in tuple(pending.items()):
            if created_revision > int(revision):
                continue
            if len(self._input_to_present_ns) == self._input_to_present_ns.maxlen:
                self._latency_sample_drop_count += 1
            self._input_to_present_ns.append(
                max(0, int(timestamp_ns) - created_ns)
            )
            del pending[created_revision]

    def close(self) -> None:
        """trace writer の残件を flush して終了する。"""

        if self._closed:
            return
        self._closed = True
        while self._pending_frame_elapsed_ns:
            self.finish_frame()
        writer = self._trace_writer
        if writer is not None:
            if (
                self._window_frames > 0
                or self._events
                or self._duration_samples_ns
                or self._input_to_present_ns
            ):
                self._refresh_snapshot(include_events=True)
                self._emit_window()
            footer = (
                json.dumps(
                    {
                        "schema": "grafix.performance.trace.v2",
                        "record_type": "footer",
                        "timestamp_ns": time.monotonic_ns(),
                        "frame_index": int(self._frame_index),
                        "records": int(self._trace_records_emitted),
                        "dropped_records": int(writer.dropped),
                        "unflushed_records": 0,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self._trace_writer = None
            writer.close(footer=footer)

    def record_operation(self, name: str, elapsed_ns: int) -> None:
        """1 operation evaluator の実行時間を記録する。"""

        if self.enabled:
            self._add_named(
                self._operation_sum_ns,
                self._operation_calls,
                name,
                elapsed_ns,
            )

    def record_duration(self, name: str, elapsed_ns: int) -> None:
        """frame 外で完了する flip / full-loop 区間を section に加える。"""

        if self.enabled:
            key = str(name).strip() or "<unnamed>"
            value = max(0, int(elapsed_ns))
            self._add_section(key, value)
            samples = self._duration_samples_ns.get(key)
            if samples is None:
                if len(self._duration_samples_ns) >= self._max_series:
                    key = _OTHER_SERIES
                    samples = self._duration_samples_ns.get(key)
                if samples is None:
                    samples = deque(maxlen=_FRAME_SAMPLE_LIMIT)
                    self._duration_samples_ns[key] = samples
            samples.append(value)

    def record_layer(self, name: str, elapsed_ns: int) -> None:
        """1 layer の resolve/realize 時間を記録する。"""

        if self.enabled:
            self._add_named(
                self._layer_sum_ns,
                self._layer_calls,
                name,
                elapsed_ns,
            )

    def record_cache(
        self,
        *,
        hits: int = 0,
        misses: int = 0,
        evictions: int = 0,
    ) -> None:
        """CPU realize cache の hit/miss/eviction 差分を記録する。"""

        if not self.enabled:
            return
        self._cache_hits += max(0, int(hits))
        self._cache_misses += max(0, int(misses))
        self._cache_evictions += max(0, int(evictions))

    def record_worker_lag(self, lag_ms: float) -> None:
        """worker task の submit から result 到着までの遅延を記録する。"""

        if not self.enabled:
            return
        value = float(lag_ms)
        if not math.isfinite(value) or value < 0.0:
            return
        self._worker_lag_sum_ms += value
        self._worker_lag_max_ms = max(self._worker_lag_max_ms, value)
        self._worker_lag_samples += 1

    def record_preview_result(
        self,
        *,
        requested_revision: int,
        presented_revision: int | None,
        fresh: bool,
    ) -> None:
        """preview の freshness と parameter revision 遅延を記録する。"""

        if not self.enabled:
            return
        requested = max(0, int(requested_revision))
        self._preview_samples += 1
        if bool(fresh):
            self._preview_fresh_results += 1
            self._preview_consecutive_stale_frames = 0
        else:
            self._preview_consecutive_stale_frames += 1
            self._preview_max_consecutive_stale_frames = max(
                self._preview_max_consecutive_stale_frames,
                self._preview_consecutive_stale_frames,
            )

        if presented_revision is None:
            return
        lag = max(0, requested - int(presented_revision))
        self._preview_revision_lag_sum += lag
        self._preview_revision_lag_max = max(
            self._preview_revision_lag_max,
            lag,
        )
        self._preview_revision_lag_samples += 1

    def snapshot(self) -> PerfSnapshot:
        """直近フレーム境界の immutable snapshot を返す。"""

        return self._snapshot

    def _add_section(self, name: str, dt_ns: int) -> None:
        self._add_named(self._sum_ns, self._calls, name, dt_ns)

    def _add_named(
        self,
        sums: dict[str, int],
        calls: dict[str, int],
        name: str,
        dt_ns: int,
    ) -> None:
        key = str(name).strip() or "<unnamed>"
        # 1 slot を overflow 集計用に予約し、動的名が memory を増やし続けないようにする。
        if key not in sums and len(sums) >= self._max_series - 1:
            key = _OTHER_SERIES
        sums[key] = int(sums.get(key, 0)) + max(0, int(dt_ns))
        calls[key] = int(calls.get(key, 0)) + 1

    def _timings(
        self,
        sums: dict[str, int],
        calls: dict[str, int],
        *,
        include_frame: bool = True,
    ) -> tuple[PerfTiming, ...]:
        frames = max(1, int(self._window_frames))
        names = (
            name
            for name in sums
            if name != _OTHER_SERIES and (include_frame or name != "frame")
        )
        ordered = sorted(names, key=lambda name: (-int(sums[name]), name))[
            : self._top_n
        ]
        result: list[PerfTiming] = []
        for name in ordered:
            total_ns = int(sums[name])
            count = max(1, int(calls.get(name, 0)))
            total_ms = float(total_ns) / 1_000_000.0
            result.append(
                PerfTiming(
                    name=name,
                    total_ms=total_ms,
                    mean_ms=total_ms / float(count),
                    per_frame_ms=total_ms / float(frames),
                    calls=count,
                    calls_per_frame=float(count) / float(frames),
                )
            )
        return tuple(result)

    def _refresh_snapshot(self, *, include_events: bool = False) -> None:
        frames = max(1, int(self._window_frames))
        frame_ms = (
            float(self._sum_ns.get("frame", 0)) / float(frames) / 1_000_000.0
        )
        frame_samples = tuple(self._frame_samples_ns)
        p50_ns = _percentile(frame_samples, 0.50)
        p95_ns = _percentile(frame_samples, 0.95)
        p99_ns = _percentile(frame_samples, 0.99)
        max_ns = None if not frame_samples else max(frame_samples)
        input_samples = tuple(self._input_to_present_ns)
        input_p50_ns = _percentile(input_samples, 0.50)
        input_p95_ns = _percentile(input_samples, 0.95)
        input_p99_ns = _percentile(input_samples, 0.99)
        input_max_ns = None if not input_samples else max(input_samples)
        writer = self._trace_writer
        lag_samples = int(self._worker_lag_samples)
        revision_lag_samples = int(self._preview_revision_lag_samples)
        self._snapshot = PerfSnapshot(
            frame_index=int(self._frame_index),
            frame_count=int(self._window_frames),
            frame_ms=frame_ms,
            frame_p50_ms=0.0 if p50_ns is None else p50_ns / 1_000_000.0,
            frame_p95_ms=0.0 if p95_ns is None else p95_ns / 1_000_000.0,
            frame_p99_ms=0.0 if p99_ns is None else p99_ns / 1_000_000.0,
            frame_max_ms=0.0 if max_ns is None else max_ns / 1_000_000.0,
            frame_tail_samples=len(frame_samples),
            frame_deadline_misses=int(self._frame_deadline_misses),
            frame_max_consecutive_deadline_misses=int(
                self._frame_max_consecutive_deadline_misses
            ),
            sections=self._timings(
                self._sum_ns,
                self._calls,
                include_frame=False,
            ),
            duration_timing=self._duration_distributions(),
            operations=self._timings(
                self._operation_sum_ns,
                self._operation_calls,
            ),
            layers=self._timings(self._layer_sum_ns, self._layer_calls),
            events=tuple(self._events) if include_events else (),
            trace_dropped_records=(
                0 if writer is None else int(writer.dropped)
            ),
            trace_dropped_events=int(self._event_drop_count),
            trace_dropped_causal_inputs=int(self._causal_input_drop_count),
            trace_dropped_latency_samples=int(
                self._latency_sample_drop_count
            ),
            cache_hits=int(self._cache_hits),
            cache_misses=int(self._cache_misses),
            cache_evictions=int(self._cache_evictions),
            worker_lag_samples=lag_samples,
            worker_lag_ms=(
                None
                if lag_samples <= 0
                else float(self._worker_lag_sum_ms) / float(lag_samples)
            ),
            worker_lag_max_ms=(
                None if lag_samples <= 0 else float(self._worker_lag_max_ms)
            ),
            preview_samples=int(self._preview_samples),
            preview_fresh_results=int(self._preview_fresh_results),
            preview_max_consecutive_stale_frames=int(
                self._preview_max_consecutive_stale_frames
            ),
            preview_revision_lag_samples=revision_lag_samples,
            preview_revision_lag=(
                None
                if revision_lag_samples <= 0
                else float(self._preview_revision_lag_sum)
                / float(revision_lag_samples)
            ),
            preview_revision_lag_max=(
                None
                if revision_lag_samples <= 0
                else int(self._preview_revision_lag_max)
            ),
            input_to_present_samples=len(input_samples),
            input_to_present_p50_ms=(
                None
                if input_p50_ns is None
                else input_p50_ns / 1_000_000.0
            ),
            input_to_present_p95_ms=(
                None
                if input_p95_ns is None
                else input_p95_ns / 1_000_000.0
            ),
            input_to_present_p99_ms=(
                None
                if input_p99_ns is None
                else input_p99_ns / 1_000_000.0
            ),
            input_to_present_max_ms=(
                None
                if input_max_ns is None
                else input_max_ns / 1_000_000.0
            ),
        )

    def _duration_distributions(
        self,
    ) -> tuple[PerfDurationDistribution, ...]:
        """frame 外の固定 section を tail の大きい順で返す。"""

        result: list[PerfDurationDistribution] = []
        for name, values in self._duration_samples_ns.items():
            samples = tuple(values)
            if not samples:
                continue
            p50_ns = _percentile(samples, 0.50)
            p95_ns = _percentile(samples, 0.95)
            p99_ns = _percentile(samples, 0.99)
            assert p50_ns is not None
            assert p95_ns is not None
            assert p99_ns is not None
            result.append(
                PerfDurationDistribution(
                    name=name,
                    count=len(samples),
                    p50_ms=p50_ns / 1_000_000.0,
                    p95_ms=p95_ns / 1_000_000.0,
                    p99_ms=p99_ns / 1_000_000.0,
                    max_ms=max(samples) / 1_000_000.0,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (-item.p95_ms, item.name),
            )[: self._top_n]
        )

    def _emit_window(self) -> None:
        snapshot = self._snapshot
        if self._console_output:
            parts = [
                f"frame={snapshot.frame_ms:.3f}ms",
                f"p95={snapshot.frame_p95_ms:.3f}ms",
                f"max={snapshot.frame_max_ms:.3f}ms",
            ]
            for timing in snapshot.sections:
                suffix = (
                    f" ({timing.calls_per_frame:.1f}x)"
                    if timing.calls_per_frame >= 1.5
                    else ""
                )
                parts.append(f"{timing.name}={timing.per_frame_ms:.3f}ms{suffix}")
            if snapshot.operations:
                parts.append(
                    "slow-op="
                    f"{snapshot.operations[0].name}:"
                    f"{snapshot.operations[0].per_frame_ms:.3f}ms"
                )
            if snapshot.layers:
                parts.append(
                    "slow-layer="
                    f"{snapshot.layers[0].name}:"
                    f"{snapshot.layers[0].per_frame_ms:.3f}ms"
                )
            if snapshot.preview_samples:
                parts.append(
                    "fresh="
                    f"{snapshot.preview_fresh_result_ratio * 100.0:.0f}%"
                    f" stale-max={snapshot.preview_max_consecutive_stale_frames}"
                )
            print("[grafix-perf]", " ".join(parts))

        writer = self._trace_writer
        if writer is not None:
            writer.submit(
                json.dumps(
                    snapshot.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self._trace_records_emitted += 1

    def _reset_window(self) -> None:
        self._window_frames = 0
        self._frame_samples_ns.clear()
        self._frame_deadline_misses = 0
        self._frame_consecutive_deadline_misses = 0
        self._frame_max_consecutive_deadline_misses = 0
        self._events.clear()
        self._event_drop_count = 0
        self._causal_input_drop_count = 0
        self._latency_sample_drop_count = 0
        self._duration_samples_ns.clear()
        self._input_to_present_ns.clear()
        self._sum_ns.clear()
        self._calls.clear()
        self._operation_sum_ns.clear()
        self._operation_calls.clear()
        self._layer_sum_ns.clear()
        self._layer_calls.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0
        self._worker_lag_sum_ms = 0.0
        self._worker_lag_max_ms = 0.0
        self._worker_lag_samples = 0
        self._preview_samples = 0
        self._preview_fresh_results = 0
        self._preview_consecutive_stale_frames = 0
        self._preview_max_consecutive_stale_frames = 0
        self._preview_revision_lag_sum = 0
        self._preview_revision_lag_max = 0
        self._preview_revision_lag_samples = 0


__all__ = [
    "PerfCollector",
    "PerfDurationDistribution",
    "PerfEvent",
    "PerfSnapshot",
    "PerfTiming",
]
