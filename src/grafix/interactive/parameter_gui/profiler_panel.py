"""Bounded profiler snapshot を Inspector に表示する。"""

from __future__ import annotations

from typing import Any

from grafix.interactive.telemetry import PerfSnapshot, PerfTiming


def _timing_line(index: int, timing: PerfTiming) -> str:
    calls = f"{timing.calls_per_frame:.1f}x/frame"
    return (
        f"  {index}. {timing.name} · {timing.per_frame_ms:.2f} ms/frame"
        f" · {calls}"
    )


def profiler_lines(snapshot: PerfSnapshot) -> tuple[str, ...]:
    """Inspector 向けに slowest operation/layer と pressure を整形する。"""

    lines: list[str] = [
        (
            f"Full loop · avg {snapshot.frame_ms:.2f} ms"
            f" · p50 {snapshot.frame_p50_ms:.2f}"
            f" · p95 {snapshot.frame_p95_ms:.2f}"
            f" · p99 {snapshot.frame_p99_ms:.2f}"
            f" · max {snapshot.frame_max_ms:.2f}"
            f" · {snapshot.frame_tail_samples}/{snapshot.frame_count} tail sampled"
        )
    ]
    if snapshot.frame_deadline_misses > 0:
        lines.append(
            "Deadline · "
            f"{snapshot.frame_deadline_misses} misses"
            " · "
            f"{snapshot.frame_max_consecutive_deadline_misses} consecutive max"
        )
    if snapshot.duration_timing:
        lines.append("Window tails")
        lines.extend(
            (
                f"  {timing.name} · p50 {timing.p50_ms:.2f} ms"
                f" · p95 {timing.p95_ms:.2f}"
                f" · p99 {timing.p99_ms:.2f}"
                f" · max {timing.max_ms:.2f}"
            )
            for timing in snapshot.duration_timing
        )
    if snapshot.input_to_present_samples > 0:
        lines.append(
            "Input to present · "
            f"p50 {snapshot.input_to_present_p50_ms:.2f} ms"
            f" · p95 {snapshot.input_to_present_p95_ms:.2f}"
            f" · p99 {snapshot.input_to_present_p99_ms:.2f}"
            f" · max {snapshot.input_to_present_max_ms:.2f}"
            f" · {snapshot.input_to_present_samples} sampled"
        )
    if (
        snapshot.trace_dropped_events > 0
        or snapshot.trace_dropped_records > 0
        or snapshot.trace_dropped_causal_inputs > 0
        or snapshot.trace_dropped_latency_samples > 0
    ):
        lines.append(
            "Trace pressure · "
            f"{snapshot.trace_dropped_events} causal events dropped"
            " · "
            f"{snapshot.trace_dropped_causal_inputs} pending inputs dropped"
            " · "
            f"{snapshot.trace_dropped_latency_samples} latency samples dropped"
            " · "
            f"{snapshot.trace_dropped_records} writer records dropped"
        )
    if snapshot.operations:
        lines.append("Slow operations")
        lines.extend(
            _timing_line(index, timing)
            for index, timing in enumerate(snapshot.operations, start=1)
        )
    if snapshot.layers:
        lines.append("Slow layers")
        lines.extend(
            _timing_line(index, timing)
            for index, timing in enumerate(snapshot.layers, start=1)
        )

    cache_samples = int(snapshot.cache_hits) + int(snapshot.cache_misses)
    if cache_samples > 0 or snapshot.cache_evictions > 0:
        eviction_label = (
            "eviction" if int(snapshot.cache_evictions) == 1 else "evictions"
        )
        lines.append(
            "Cache · "
            f"{snapshot.cache_hit_rate * 100.0:.0f}% hit"
            f" · {snapshot.cache_hits}/{cache_samples}"
            f" · {snapshot.cache_evictions} {eviction_label}"
        )

    if snapshot.worker_lag_ms is not None:
        max_lag = (
            snapshot.worker_lag_ms
            if snapshot.worker_lag_max_ms is None
            else snapshot.worker_lag_max_ms
        )
        lines.append(
            "Worker lag · "
            f"{snapshot.worker_lag_ms:.1f} ms average"
            f" · {max_lag:.1f} ms peak"
        )
    if snapshot.preview_samples > 0:
        line = (
            "Preview freshness · "
            f"{snapshot.preview_fresh_result_ratio * 100.0:.0f}% fresh"
            " · "
            f"{snapshot.preview_max_consecutive_stale_frames} stale frames max"
        )
        if snapshot.preview_revision_lag is not None:
            max_revision_lag = (
                snapshot.preview_revision_lag
                if snapshot.preview_revision_lag_max is None
                else float(snapshot.preview_revision_lag_max)
            )
            line += (
                f" · {snapshot.preview_revision_lag:.1f} revisions average"
                f" · {max_revision_lag:.0f} max"
            )
        lines.append(line)
    return tuple(lines)


def render_profiler_panel(imgui: Any, snapshot: PerfSnapshot | None) -> None:
    """profile がある場合だけ折り畳み可能な Inspector panel を描画する。"""

    if snapshot is None:
        return
    opened, _visible = imgui.collapsing_header("PROFILER##profiler")
    if not opened:
        return

    for line in profiler_lines(snapshot):
        if line in {"Window tails", "Slow operations", "Slow layers"}:
            imgui.text_disabled(line)
            continue
        imgui.text(line)


__all__ = ["profiler_lines", "render_profiler_panel"]
