from __future__ import annotations

from grafix.interactive.parameter_gui.monitor_bar import (
    monitor_alert_lines,
    monitor_status_lines,
    render_monitor_bar,
)
from grafix.interactive.runtime.monitor import RuntimeMonitor


class _Imgui:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def text(self, value: object) -> None:
        self.lines.append(str(value))

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
    imgui = _Imgui()

    render_monitor_bar(
        imgui=imgui,
        snapshot=snapshot,
        midi_status=None,
    )

    assert "CAPTURE QUEUE (estimated process-wide): 3/17 · 12.0/256.0 MiB" in imgui.lines
    assert "Capture rejected: PNG; reason=bytes" in imgui.lines
    assert "CAPTURE NOTICE" in imgui.lines


def test_transport_waiting_shows_rendered_and_target_times() -> None:
    monitor = RuntimeMonitor()
    monitor.set_transport(
        t=2.5,
        requested_t=0.0,
        waiting=True,
        playing=False,
        speed=1.0,
    )
    imgui = _Imgui()

    render_monitor_bar(
        imgui=imgui,
        snapshot=monitor.snapshot(),
        midi_status=None,
    )

    assert any(
        "WAIT — rendered 2.500s" in line and "target 0.000s" in line
        for line in imgui.lines
    )


def test_normal_monitor_omits_empty_queue_and_disconnected_midi_noise() -> None:
    monitor = RuntimeMonitor()
    imgui = _Imgui()

    render_monitor_bar(
        imgui=imgui,
        snapshot=monitor.snapshot(),
        midi_status=None,
    )

    assert len(imgui.lines) == 2
    assert "FPS" in imgui.lines[0]
    assert all("CAPTURE QUEUE" not in line for line in imgui.lines)
    assert all("MIDI" not in line for line in imgui.lines)


def test_compact_status_is_one_line_and_spells_out_wait_state() -> None:
    monitor = RuntimeMonitor()
    monitor.set_transport(
        t=1.25,
        requested_t=2.0,
        waiting=True,
        playing=False,
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

    render_monitor_bar(
        imgui=imgui,
        snapshot=monitor.snapshot(),
        midi_status=None,
    )

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
