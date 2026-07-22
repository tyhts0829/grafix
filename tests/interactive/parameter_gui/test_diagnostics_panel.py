from __future__ import annotations

from grafix.interactive.parameter_gui.diagnostics_panel import render_diagnostics_panel
from grafix.interactive.diagnostics import (
    DiagnosticAction,
    DiagnosticCenter,
    DiagnosticEvent,
)


class _Imgui:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.clipboard: str | None = None
        self.clicked: set[str] = set()

    def collapsing_header(self, label: str) -> tuple[bool, None]:
        self.lines.append(label)
        return True, None

    def text(self, value: object) -> None:
        self.lines.append(str(value))

    def text_disabled(self, value: object) -> None:
        self.lines.append(str(value))

    def text_wrapped(self, value: object) -> None:
        self.lines.append(str(value))

    def button(self, label: str) -> bool:
        return any(label.startswith(prefix) for prefix in self.clicked)

    def same_line(self) -> None:
        return None

    def separator(self) -> None:
        return None

    def set_clipboard_text(self, value: str) -> None:
        self.clipboard = value


def _event() -> DiagnosticEvent:
    return DiagnosticEvent(
        category="scene",
        severity="error",
        summary="draw failed",
        details="Traceback line 10",
        source="sketch.py:10",
        actions=(DiagnosticAction("copy", "Copy details"),),
        count=2,
    )


def test_panel_renders_details_count_source_and_copy_action() -> None:
    imgui = _Imgui()
    imgui.clicked.add("Copy details")

    render_diagnostics_panel(imgui, [_event()])

    assert "DIAGNOSTICS (1)##diagnostics" in imgui.lines
    assert "ERROR · scene ×2" in imgui.lines
    assert "draw failed" in imgui.lines
    assert "Traceback line 10" in imgui.lines
    assert "sketch.py:10" in imgui.lines
    assert imgui.clipboard == "Traceback line 10"


def test_panel_dismisses_event_from_center() -> None:
    center = DiagnosticCenter()
    event = center.publish(_event())
    imgui = _Imgui()
    imgui.clicked.add("Dismiss")

    render_diagnostics_panel(imgui, center.snapshot(), center=center)

    assert center.snapshot() == ()
    assert event.count == 2


def test_panel_dispatches_non_clipboard_action_through_center() -> None:
    center = DiagnosticCenter()
    action = DiagnosticAction("open", "Open source")
    event = center.publish(
        DiagnosticEvent(
            category="scene",
            severity="error",
            summary="draw failed",
            source="sketch.py:10",
            actions=(action,),
        )
    )
    handled: list[DiagnosticEvent] = []
    center.register_action("open", handled.append)
    imgui = _Imgui()
    imgui.clicked.add("Open source")

    render_diagnostics_panel(imgui, center.snapshot(), center=center)

    assert handled == [event]


def test_panel_omits_empty_diagnostics() -> None:
    imgui = _Imgui()

    render_diagnostics_panel(imgui, ())

    assert imgui.lines == []
