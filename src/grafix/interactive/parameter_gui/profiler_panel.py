"""Bounded profiler snapshot を Inspector に表示する。"""

from __future__ import annotations

from typing import Any

from grafix.interactive.runtime.perf import PerfSnapshot, PerfTiming


def _timing_line(index: int, timing: PerfTiming) -> str:
    calls = f"{timing.calls_per_frame:.1f}x/frame"
    return (
        f"  {index}. {timing.name} · {timing.per_frame_ms:.2f} ms/frame"
        f" · {calls}"
    )


def profiler_lines(snapshot: PerfSnapshot) -> tuple[str, ...]:
    """Inspector 向けに slowest operation/layer と pressure を整形する。"""

    lines: list[str] = [
        f"Frame · {snapshot.frame_ms:.2f} ms · {snapshot.frame_count} sampled"
    ]
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
    return tuple(lines)


def render_profiler_panel(imgui: Any, snapshot: PerfSnapshot | None) -> None:
    """profile がある場合だけ折り畳み可能な Inspector panel を描画する。"""

    if snapshot is None:
        return
    collapsing_header = getattr(imgui, "collapsing_header", None)
    if not callable(collapsing_header):
        return
    opened = collapsing_header("PROFILER##profiler")
    if isinstance(opened, tuple):
        opened = opened[0]
    if not bool(opened):
        return

    for line in profiler_lines(snapshot):
        if line in {"Slow operations", "Slow layers"}:
            disabled = getattr(imgui, "text_disabled", None)
            if callable(disabled):
                disabled(line)
                continue
        imgui.text(line)


__all__ = ["profiler_lines", "render_profiler_panel"]
