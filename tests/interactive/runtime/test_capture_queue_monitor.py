from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from grafix.interactive.parameter_gui.monitor_bar import (
    monitor_alert_lines,
    monitor_status_lines,
    render_monitor_alerts,
    render_monitor_status,
)
from grafix.interactive.runtime.monitor import MonitorSnapshot, RuntimeMonitor


class _Imgui:
    COLOR_TEXT = 0

    def __init__(self) -> None:
        self.lines: list[str] = []

    def text(self, value: object) -> None:
        self.lines.append(str(value))

    def text_disabled(self, value: object) -> None:
        self.lines.append(str(value))

    def text_wrapped(self, value: object) -> None:
        self.lines.append(str(value))

    def push_style_color(self, *_args: object) -> None:
        pass

    def pop_style_color(self) -> None:
        pass

    def separator(self) -> None:
        return None


def test_capture_queue_pressure_and_rejection_are_visible_in_monitor() -> None:
    monitor = RuntimeMonitor()
    monitor.set_capture_queue(
        request_count=3,
        request_limit=17,
        retained_bytes=12 * 1024 * 1024,
        byte_limit=256 * 1024 * 1024,
        notice="Capture rejected: PNG; reason=bytes",
    )
    snapshot = monitor.snapshot()
    status_imgui = _Imgui()
    alerts_imgui = _Imgui()

    render_monitor_status(
        imgui=status_imgui,
        snapshot=snapshot,
        midi_status=None,
    )
    render_monitor_alerts(imgui=alerts_imgui, snapshot=snapshot)

    assert "CAPTURE NOTICE" in status_imgui.lines
    assert (
        "CAPTURE QUEUE (estimated process-wide): 3/17 · 12.0/256.0 MiB"
        in alerts_imgui.lines
    )
    assert "Capture rejected: PNG; reason=bytes" in alerts_imgui.lines


def test_transport_waiting_shows_rendered_and_target_times() -> None:
    monitor = RuntimeMonitor()
    monitor.set_transport(
        t=2.5,
        requested_t=0.0,
        waiting=True,
        speed=1.0,
    )
    imgui = _Imgui()

    render_monitor_alerts(imgui=imgui, snapshot=monitor.snapshot())

    assert any(
        "WAIT — rendered 2.500s" in line and "target 0.000s" in line
        for line in imgui.lines
    )


def test_normal_monitor_omits_empty_queue_and_disconnected_midi_noise() -> None:
    monitor = RuntimeMonitor()
    status_imgui = _Imgui()
    alerts_imgui = _Imgui()

    render_monitor_status(
        imgui=status_imgui,
        snapshot=monitor.snapshot(),
        midi_status=None,
    )
    render_monitor_alerts(imgui=alerts_imgui, snapshot=monitor.snapshot())

    assert len(status_imgui.lines) == 2
    assert "FPS" in status_imgui.lines[0]
    assert all("MIDI" not in line for line in status_imgui.lines)
    assert alerts_imgui.lines == []


def test_compact_status_is_one_line_and_spells_out_wait_state() -> None:
    monitor = RuntimeMonitor()
    monitor.set_transport(
        t=1.25,
        requested_t=2.0,
        waiting=True,
        speed=0.5,
    )

    lines = monitor_status_lines(
        monitor.snapshot(),
        midi_status=None,
        compact=True,
    )

    assert len(lines) == 1
    assert "FPS" in lines[0].text
    assert "WAIT" in lines[0].text
    assert lines[0].token == "warning"


def test_long_frame_error_lives_in_full_width_alert_not_status_column() -> None:
    monitor = RuntimeMonitor()
    monitor.set_frame_error("renderer failed with a deliberately long diagnostic")
    snapshot = monitor.snapshot()

    status = monitor_status_lines(snapshot, midi_status=None, compact=False)
    alerts = monitor_alert_lines(snapshot)

    assert status[-1].text == "FRAME ERROR"
    assert all("renderer failed" not in line.text for line in status)
    assert any("renderer failed" in line.text for line in alerts)


def test_monitor_wraps_actionable_notices_when_backend_supports_it() -> None:
    class WrappedImgui(_Imgui):
        def text_wrapped(self, value: object) -> None:
            self.lines.append(f"wrapped:{value}")

    monitor = RuntimeMonitor()
    monitor.set_capture_queue(
        request_count=0,
        request_limit=17,
        retained_bytes=0,
        byte_limit=256 * 1024 * 1024,
        notice="Capture rejected: queue is full",
    )
    imgui = WrappedImgui()

    render_monitor_alerts(imgui=imgui, snapshot=monitor.snapshot())

    assert "wrapped:Capture rejected: queue is full" in imgui.lines


def test_autosave_failure_is_visible_in_status_alert_and_diagnostics() -> None:
    monitor = RuntimeMonitor()
    monitor.set_autosave(status="failed", error="OSError: disk full")
    monitor.set_autosave(status="failed", error="OSError: disk full")
    snapshot = monitor.snapshot()

    status = monitor_status_lines(snapshot, midi_status=None, compact=False)
    alerts = monitor_alert_lines(snapshot)

    assert status[-1].text == "SAVE FAILED"
    assert any("OSError: disk full" in line.text for line in alerts)
    assert snapshot.diagnostics[-1].category == "save"
    assert snapshot.diagnostics[-1].count == 1


def test_recovered_session_remains_visible_in_status() -> None:
    monitor = RuntimeMonitor()
    monitor.set_recovered_session(True)
    monitor.set_autosave(status="dirty")

    status = monitor_status_lines(
        monitor.snapshot(),
        midi_status=None,
        compact=False,
    )

    assert status[-1].text == "RECOVERED SESSION  ·  UNSAVED"
    assert status[-1].token == "warning"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpu_mem_sample_interval_s": "0.5"},
        {"fps_sample_interval_s": True},
        {"diagnostic_center": object()},
    ],
)
def test_runtime_monitor_rejects_noncanonical_constructor_values(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        RuntimeMonitor(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpu_mem_sample_interval_s": 0.0},
        {"fps_sample_interval_s": float("inf")},
    ],
)
def test_runtime_monitor_rejects_invalid_sample_intervals(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        RuntimeMonitor(**kwargs)  # type: ignore[arg-type]


def test_runtime_monitor_rejects_implicit_setter_coercion() -> None:
    monitor = RuntimeMonitor()

    with pytest.raises(TypeError, match="vertices"):
        monitor.set_draw_counts(vertices="1", lines=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="message"):
        monitor.set_frame_error(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="t"):
        monitor.set_transport(t="0", speed=1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="waiting"):
        monitor.set_transport(t=0.0, waiting=1, speed=1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="request_count"):
        monitor.set_capture_queue(
            request_count=1.0,  # type: ignore[arg-type]
            request_limit=1,
            retained_bytes=0,
            byte_limit=1,
        )
    with pytest.raises(TypeError, match="status"):
        monitor.set_autosave(status=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="active"):
        monitor.set_recovered_session(1)  # type: ignore[arg-type]


def test_runtime_monitor_rejects_negative_counts_instead_of_clamping() -> None:
    monitor = RuntimeMonitor()

    with pytest.raises(ValueError, match="request_count"):
        monitor.set_capture_queue(
            request_count=-1,
            request_limit=1,
            retained_bytes=0,
            byte_limit=1,
        )
    with pytest.raises(ValueError, match="vertices"):
        monitor.set_draw_counts(vertices=-1, lines=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fps": "60.0"},
        {"vertices": True},
        {"transport_waiting": 0},
        {"transport_speed": 0.0},
        {"diagnostics": []},
        {"autosave_status": "unknown"},
        {"profiler": object()},
    ],
)
def test_monitor_snapshot_validates_direct_construction(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "fps": 60.0,
        "cpu_percent": 10.0,
        "rss_mb": 50.0,
        "vertices": 3,
        "lines": 1,
    }
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        MonitorSnapshot(**values)  # type: ignore[arg-type]


class _ProcessMetrics:
    def __init__(
        self,
        *,
        user: float = 1.0,
        system: float = 2.0,
        rss: int = 10,
        children: tuple[object, ...] = (),
    ) -> None:
        self._times = SimpleNamespace(user=user, system=system)
        self._rss = rss
        self._children = children

    def cpu_times(self) -> object:
        return self._times

    def memory_info(self) -> object:
        return SimpleNamespace(rss=self._rss)

    def children(self, *, recursive: bool) -> list[object]:
        assert recursive is True
        return list(self._children)


class _VanishedProcess:
    def cpu_times(self) -> object:
        raise psutil.NoSuchProcess(12345)

    def memory_info(self) -> object:
        raise psutil.NoSuchProcess(12345)


def test_runtime_monitor_skips_only_known_child_process_races() -> None:
    child = _ProcessMetrics(user=0.25, system=0.75, rss=7)
    parent = _ProcessMetrics(children=(child, _VanishedProcess()))
    monitor = RuntimeMonitor()
    monitor._process = parent  # type: ignore[assignment]

    assert monitor._cpu_total_s() == pytest.approx(4.0)
    assert monitor._rss_bytes() == 17


def test_runtime_monitor_tolerates_known_child_enumeration_race() -> None:
    class ChildEnumerationUnavailable(_ProcessMetrics):
        def children(self, *, recursive: bool) -> list[object]:
            assert recursive is True
            raise psutil.AccessDenied(12345)

    monitor = RuntimeMonitor()
    monitor._process = ChildEnumerationUnavailable()  # type: ignore[assignment]

    assert monitor._cpu_total_s() == pytest.approx(3.0)
    assert monitor._rss_bytes() == 10


def test_runtime_monitor_does_not_hide_psutil_api_mismatch() -> None:
    class IncompleteProcess(_ProcessMetrics):
        def cpu_times(self) -> object:
            return SimpleNamespace(user=1.0)

    monitor = RuntimeMonitor()
    monitor._process = IncompleteProcess()  # type: ignore[assignment]

    with pytest.raises(AttributeError, match="system"):
        monitor._cpu_total_s()


def test_runtime_monitor_does_not_hide_unexpected_child_error() -> None:
    class BrokenChild(_ProcessMetrics):
        def cpu_times(self) -> object:
            raise RuntimeError("broken psutil adapter")

    monitor = RuntimeMonitor()
    monitor._process = _ProcessMetrics(children=(BrokenChild(),))  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="broken psutil adapter"):
        monitor._cpu_total_s()
