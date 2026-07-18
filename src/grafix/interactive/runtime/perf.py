"""interactive 描画向けの bounded performance collector。"""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

_OTHER_SERIES = "<other>"


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
class PerfSnapshot:
    """Inspector と trace 出力で共有する小さな immutable snapshot。"""

    frame_index: int = 0
    frame_count: int = 0
    frame_ms: float = 0.0
    sections: tuple[PerfTiming, ...] = ()
    operations: tuple[PerfTiming, ...] = ()
    layers: tuple[PerfTiming, ...] = ()
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
            "schema": "grafix.performance.trace.v1",
            "frame_index": self.frame_index,
            "frame_count": self.frame_count,
            "frame_ms": self.frame_ms,
            "sections": [item.as_dict() for item in self.sections],
            "operations": [item.as_dict() for item in self.operations],
            "layers": [item.as_dict() for item in self.layers],
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
        self._snapshot_callback = snapshot_callback

        self._frame_index = 0
        self._window_frames = 0
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
            self._add_section("frame", int(time.perf_counter_ns() - t0))
            self._window_frames += 1
            self._frame_index += 1
            self._refresh_snapshot()
            callback = self._snapshot_callback
            if callback is not None:
                callback(self._snapshot)
            if self._window_frames >= self.print_every:
                self._emit_window()
                self._reset_window()

    def record_operation(self, name: str, elapsed_ns: int) -> None:
        """1 operation evaluator の実行時間を記録する。"""

        if self.enabled:
            self._add_named(
                self._operation_sum_ns,
                self._operation_calls,
                name,
                elapsed_ns,
            )

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

    def _refresh_snapshot(self) -> None:
        frames = max(1, int(self._window_frames))
        frame_ms = (
            float(self._sum_ns.get("frame", 0)) / float(frames) / 1_000_000.0
        )
        lag_samples = int(self._worker_lag_samples)
        revision_lag_samples = int(self._preview_revision_lag_samples)
        self._snapshot = PerfSnapshot(
            frame_index=int(self._frame_index),
            frame_count=int(self._window_frames),
            frame_ms=frame_ms,
            sections=self._timings(
                self._sum_ns,
                self._calls,
                include_frame=False,
            ),
            operations=self._timings(
                self._operation_sum_ns,
                self._operation_calls,
            ),
            layers=self._timings(self._layer_sum_ns, self._layer_calls),
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
        )

    def _emit_window(self) -> None:
        snapshot = self._snapshot
        if self._console_output:
            parts = [f"frame={snapshot.frame_ms:.3f}ms"]
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

        trace_path = self._trace_path
        if trace_path is not None:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with trace_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        snapshot.as_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

    def _reset_window(self) -> None:
        self._window_frames = 0
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


__all__ = ["PerfCollector", "PerfSnapshot", "PerfTiming"]
