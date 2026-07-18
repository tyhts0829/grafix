from __future__ import annotations

from grafix.interactive.parameter_gui.profiler_panel import (
    profiler_lines,
    render_profiler_panel,
)
from grafix.interactive.runtime.monitor import RuntimeMonitor
from grafix.interactive.runtime.perf import PerfCollector


class _Imgui:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def collapsing_header(self, label: str) -> bool:
        self.lines.append(label)
        return True

    def text(self, value: object) -> None:
        self.lines.append(str(value))

    def text_disabled(self, value: object) -> None:
        self.lines.append(str(value))


def _profiled_monitor() -> RuntimeMonitor:
    monitor = RuntimeMonitor()
    perf = PerfCollector(enabled=True, console_output=False)
    with perf.frame():
        perf.record_event(
            "parameter_revision_created",
            revision=12,
            timestamp_ns=1_000_000,
        )
        perf.record_operation("slow-effect", 8_000_000)
        perf.record_operation("fast-effect", 1_000_000)
        perf.record_layer("Foreground", 12_000_000)
        perf.record_cache(hits=7, misses=3, evictions=1)
        perf.record_worker_lag(15.0)
        perf.record_duration("preview_draw_flip", 5_000_000)
        perf.record_duration("parameter_gui_draw_flip", 3_000_000)
        perf.record_duration("full_loop", 9_000_000)
        perf.record_preview_result(
            requested_revision=12,
            presented_revision=10,
            fresh=False,
        )
        perf.record_event(
            "preview_presented",
            revision=12,
            timestamp_ns=21_000_000,
        )
    monitor.set_profiler(perf.snapshot())
    return monitor


def test_runtime_monitor_exposes_profiler_snapshot() -> None:
    snapshot = _profiled_monitor().snapshot()

    assert snapshot.profiler is not None
    assert snapshot.profiler.operations[0].name == "slow-effect"
    assert snapshot.profiler.layers[0].name == "Foreground"


def test_profiler_lines_show_actionable_slowest_items_and_runtime_pressure() -> None:
    snapshot = _profiled_monitor().snapshot().profiler
    assert snapshot is not None

    lines = profiler_lines(snapshot)

    assert any("slow-effect" in line for line in lines)
    assert any("Foreground" in line for line in lines)
    assert any("Cache" in line and "70% hit" in line and "1 eviction" in line for line in lines)
    assert any("Worker lag" in line and "15.0 ms" in line for line in lines)
    assert any(
        "Input to present" in line and "20.00 ms" in line
        for line in lines
    )
    assert any(
        "preview_draw_flip" in line and "p95 5.00" in line
        for line in lines
    )
    assert any(
        "Preview freshness" in line
        and "0% fresh" in line
        and "2.0 revisions" in line
        for line in lines
    )


def test_profiler_panel_renders_inside_inspector() -> None:
    snapshot = _profiled_monitor().snapshot().profiler
    assert snapshot is not None
    imgui = _Imgui()

    render_profiler_panel(imgui, snapshot)

    assert imgui.lines[0].startswith("PROFILER")
    assert any("Slow operations" in line for line in imgui.lines)
    assert any("Slow layers" in line for line in imgui.lines)
