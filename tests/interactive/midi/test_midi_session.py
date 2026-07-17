"""MIDI live/frozen session lifecycle のテスト。"""

from __future__ import annotations

from typing import Any, cast

import pytest

from grafix.interactive.midi import MidiSession
from grafix.interactive.runtime.diagnostics import DiagnosticCenter


class _Controller:
    def __init__(
        self,
        *,
        values: dict[int, float] | None = None,
        poll_error: Exception | None = None,
    ) -> None:
        self.port_name = "Test Port"
        self.values = dict(values or {})
        self.poll_error = poll_error
        self.last_cc_change: tuple[int, int] | None = None
        self.closed = 0
        self.saved = 0

    def poll_pending(self) -> int:
        if self.poll_error is not None:
            raise self.poll_error
        return 0

    def snapshot(self) -> dict[int, float]:
        return dict(self.values)

    def save(self) -> None:
        self.saved += 1

    def close(self) -> None:
        self.closed += 1


def _controller(**kwargs: object) -> Any:
    return cast(Any, _Controller(**kwargs))


def test_no_port_distinguishes_disabled_from_empty_frozen_state() -> None:
    disabled = MidiSession(controller=None, frozen_values=None)
    frozen = MidiSession(controller=None, frozen_values={})

    assert disabled.state == "disabled"
    assert disabled.status_label == "MIDI OFF"
    assert disabled.frame_snapshot() is None

    frozen_snapshot = frozen.frame_snapshot()
    assert frozen.state == "frozen"
    assert frozen.status_label == "MIDI FROZEN"
    assert frozen_snapshot is not None
    assert frozen_snapshot.source == "midi_frozen"
    assert dict(frozen_snapshot) == {}


def test_poll_error_transitions_to_frozen_and_publishes_diagnostic() -> None:
    center = DiagnosticCenter()
    controller = _controller(values={7: 0.75}, poll_error=OSError("device lost"))
    session = MidiSession(
        controller=controller,
        frozen_values={7: 0.25},
        diagnostics=center,
    )

    snapshot = session.frame_snapshot()

    assert snapshot is not None
    assert snapshot.source == "midi_frozen"
    assert snapshot[7] == pytest.approx(0.75)
    assert session.state == "frozen"
    assert controller.closed == 1
    event = center.snapshot()[-1]
    assert event.category == "midi"
    assert "disconnected" in event.summary
    assert [action.action_id for action in event.actions] == ["retry", "discard"]


def test_reconnect_success_and_failure_are_explicit() -> None:
    center = DiagnosticCenter()
    live = _controller(values={1: 0.5})
    session = MidiSession(
        controller=None,
        frozen_values={1: 0.25},
        reconnect=lambda: live,
        diagnostics=center,
    )

    assert session.reconnect() is True
    assert session.controller is live
    assert session.state == "live"
    snapshot = session.frame_snapshot()
    assert snapshot is not None
    assert snapshot.source == "midi_live"
    assert snapshot[1] == pytest.approx(0.5)

    failed = MidiSession(
        controller=None,
        frozen_values={},
        reconnect=lambda: None,
        diagnostics=center,
    )
    assert failed.reconnect() is False
    assert failed.state == "frozen"
    assert center.snapshot()[-1].summary == "MIDI reconnect failed"


def test_clear_frozen_and_close_own_the_session_resources() -> None:
    cleared: list[bool] = []
    frozen = MidiSession(
        controller=None,
        frozen_values={2: 1.0},
        clear_frozen=lambda: cleared.append(True),
    )
    frozen.clear_frozen_snapshot()
    snapshot = frozen.frame_snapshot()
    assert snapshot is None
    assert frozen.state == "disabled"
    assert cleared == [True]

    controller = _controller(values={2: 1.0})
    live = MidiSession(controller=controller, frozen_values=None)
    live.close()
    live.close()
    assert controller.saved == 1
    assert controller.closed == 1
