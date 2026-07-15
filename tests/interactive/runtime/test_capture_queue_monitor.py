from __future__ import annotations

from grafix.interactive.parameter_gui.monitor_bar import render_monitor_bar
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
        midi_port_name=None,
    )

    assert "CAPTURE QUEUE (estimated process-wide): 3/17 | 12.0/256.0 MiB" in imgui.lines
    assert "Capture rejected: PNG; reason=bytes" in imgui.lines


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
        midi_port_name=None,
    )

    assert any("WAIT t=2.500s" in line and "target=0.000s" in line for line in imgui.lines)


def test_normal_monitor_omits_empty_queue_and_disconnected_midi_noise() -> None:
    monitor = RuntimeMonitor()
    imgui = _Imgui()

    render_monitor_bar(
        imgui=imgui,
        snapshot=monitor.snapshot(),
        midi_port_name=None,
    )

    assert len(imgui.lines) == 1
    assert imgui.lines[0].startswith("FPS ")
    assert "CAPTURE QUEUE" not in imgui.lines[0]
    assert "MIDI:" not in imgui.lines[0]


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
        midi_port_name=None,
    )

    assert "wrapped:Capture rejected: queue is full" in imgui.lines
