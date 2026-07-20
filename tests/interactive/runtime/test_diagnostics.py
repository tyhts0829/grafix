from __future__ import annotations

import pytest

from grafix.interactive.runtime.diagnostics import (
    DiagnosticAction,
    DiagnosticCenter,
    DiagnosticEvent,
)
from grafix.interactive.runtime.monitor import RuntimeMonitor


def _event(summary: str, *, key: str | None = None) -> DiagnosticEvent:
    return DiagnosticEvent(
        category="scene",
        severity="error",
        summary=summary,
        details=f"details: {summary}",
        source="sketch.py:10",
        actions=(DiagnosticAction("copy", "Copy details"),),
        dedupe_key=key,
    )


def test_center_deduplicates_and_counts_latest_event() -> None:
    center = DiagnosticCenter(max_events=3)

    first = center.publish(_event("first", key="draw-error"))
    second = center.publish(
        DiagnosticEvent(
            category="scene",
            severity="error",
            summary="updated summary",
            details="new traceback",
            dedupe_key="draw-error",
        )
    )

    assert first.count == 1
    assert second.count == 2
    assert center.snapshot() == (second,)


def test_center_evicts_oldest_distinct_event() -> None:
    center = DiagnosticCenter(max_events=2)
    center.publish(_event("one"))
    center.publish(_event("two"))
    center.publish(_event("three"))

    assert [event.summary for event in center.snapshot()] == ["two", "three"]


def test_center_dismiss_and_clear_category() -> None:
    center = DiagnosticCenter()
    scene = center.publish(_event("scene"))
    center.publish(
        DiagnosticEvent(category="export", severity="warning", summary="export")
    )

    assert center.dismiss(scene) is True
    assert center.dismiss(scene) is False
    center.clear(category="export")
    assert center.snapshot() == ()


def test_event_validation_rejects_invalid_payloads() -> None:
    with pytest.raises(ValueError, match="category"):
        DiagnosticEvent(category="", severity="error", summary="x")
    with pytest.raises(ValueError, match="severity"):
        DiagnosticEvent(category="scene", severity="fatal", summary="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="summary"):
        DiagnosticEvent(category="scene", severity="error", summary="")
    with pytest.raises(ValueError, match="count"):
        DiagnosticEvent(category="scene", severity="error", summary="x", count=0)


def test_action_validation_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="action_id"):
        DiagnosticAction("", "Copy")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="label"):
        DiagnosticAction("copy", "")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": object()},
        {"severity": 1},
        {"summary": object()},
        {"details": object()},
        {"actions": [DiagnosticAction("copy", "Copy")]},
        {"count": 1.0},
    ],
)
def test_event_validation_rejects_implicit_conversion(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "category": "scene",
        "severity": "error",
        "summary": "failed",
    }
    values.update(kwargs)

    with pytest.raises(TypeError):
        DiagnosticEvent(**values)  # type: ignore[arg-type]


def test_action_and_center_reject_implicit_conversion() -> None:
    with pytest.raises(TypeError):
        DiagnosticAction("copy", object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        DiagnosticCenter(max_events=1.0)  # type: ignore[arg-type]


def test_center_dispatches_registered_typed_action() -> None:
    center = DiagnosticCenter()
    action = DiagnosticAction("retry", "Retry")
    event = center.publish(
        DiagnosticEvent(
            category="save",
            severity="error",
            summary="save failed",
            actions=(action,),
        )
    )
    handled: list[DiagnosticEvent] = []
    center.register_action("retry", handled.append)

    assert center.dispatch_action(event, action) is True
    assert handled == [event]


def test_unregistered_action_is_published_as_diagnostic() -> None:
    center = DiagnosticCenter()
    action = DiagnosticAction("open", "Open source")
    event = center.publish(
        DiagnosticEvent(
            category="scene",
            severity="error",
            summary="draw failed",
            actions=(action,),
        )
    )

    assert center.dispatch_action(event, action) is False
    diagnostic = center.snapshot()[-1]
    assert diagnostic.category == "diagnostic"
    assert diagnostic.severity == "warning"
    assert diagnostic.summary == "Action is unavailable: Open source"


def test_failed_action_publishes_traceback_to_same_center() -> None:
    center = DiagnosticCenter()
    action = DiagnosticAction("retry", "Retry")
    event = center.publish(
        DiagnosticEvent(
            category="save",
            severity="error",
            summary="save failed",
            source="params.json",
            actions=(action,),
        )
    )

    def fail(_event: DiagnosticEvent) -> None:
        raise OSError("disk full")

    center.register_action("retry", fail)

    assert center.dispatch_action(event, action) is False
    diagnostic = center.snapshot()[-1]
    assert diagnostic.category == "save"
    assert diagnostic.summary == "Action failed: Retry"
    assert "OSError: disk full" in diagnostic.details
    assert diagnostic.source == "params.json"
    assert diagnostic.actions == (DiagnosticAction("copy", "Copy details"),)


def test_category_scoped_handler_does_not_receive_other_retry_actions() -> None:
    center = DiagnosticCenter()
    handled: list[DiagnosticEvent] = []
    center.register_action("retry", handled.append, category="save")
    action = DiagnosticAction("retry", "Retry")
    event = center.publish(
        DiagnosticEvent(
            category="export",
            severity="error",
            summary="export failed",
            actions=(action,),
        )
    )

    assert center.dispatch_action(event, action) is False
    assert handled == []
    assert center.snapshot()[-1].category == "diagnostic"


def test_runtime_monitor_exposes_deduplicated_diagnostics() -> None:
    monitor = RuntimeMonitor()

    monitor.set_frame_error(
        "draw failed",
        details="Traceback: line 10",
        source="sketch.py:10",
    )
    monitor.set_frame_error(None)
    monitor.set_frame_error(
        "draw failed",
        details="Traceback: line 10",
        source="sketch.py:10",
    )
    monitor.set_capture_queue(
        request_count=0,
        request_limit=1,
        retained_bytes=0,
        byte_limit=1024,
        notice="Capture rejected",
    )

    diagnostics = monitor.snapshot().diagnostics
    assert len(diagnostics) == 2
    assert diagnostics[0].category == "scene"
    assert diagnostics[0].count == 2
    assert diagnostics[0].details == "Traceback: line 10"
    assert tuple(action.action_id for action in diagnostics[0].actions) == (
        "copy",
        "open",
    )
    assert diagnostics[1].category == "export"
