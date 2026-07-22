"""MIDI live/frozen session lifecycle のテスト。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from grafix.interactive.midi import MidiSession
from grafix.interactive.midi.midi_controller import (
    CcSnapshotLoadResult,
    MidiConnectionError,
)
from grafix.interactive.diagnostics import DiagnosticCenter, DiagnosticEvent


class _Controller:
    def __init__(
        self,
        *,
        values: dict[int, float] | None = None,
        poll_error: BaseException | None = None,
    ) -> None:
        self.port_name = "Test Port"
        self.values = dict(values or {})
        self.cc = self.values
        self.poll_error = poll_error
        self.last_cc_change: tuple[int, int] | None = None
        self.closed = 0
        self.saved = 0
        self.discarded = 0
        self.snapshot_load_result = CcSnapshotLoadResult(
            values=(),
            status="missing",
            source=Path("snapshot.json"),
        )

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

    def discard_persisted_snapshot(self) -> None:
        self.discarded += 1
        self.snapshot_load_result = CcSnapshotLoadResult(
            values=(),
            status="loaded",
            source=self.snapshot_load_result.source,
        )


def _controller(**kwargs: object) -> Any:
    return cast(Any, _Controller(**kwargs))


def _snapshot(values: dict[int, float]) -> CcSnapshotLoadResult:
    return CcSnapshotLoadResult(
        values=tuple(sorted((cc, float(value)) for cc, value in values.items())),
        status="loaded",
        source=Path("snapshot.json"),
    )


def test_no_port_distinguishes_disabled_from_empty_frozen_state() -> None:
    disabled = MidiSession(controller=None, snapshot_load_result=None)
    frozen = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({}),
        discard_persisted_snapshot=lambda: None,
    )

    assert disabled.state == "disabled"
    assert disabled.status_label == "MIDI OFF"
    assert disabled.frame_snapshot() is None

    frozen_snapshot = frozen.frame_snapshot()
    assert frozen.state == "frozen"
    assert frozen.status_label == "MIDI FROZEN"
    assert frozen_snapshot is not None
    assert frozen_snapshot.source == "midi_frozen"
    assert dict(frozen_snapshot) == {}


def test_session_requires_one_canonical_snapshot_ownership() -> None:
    controller = _controller()

    with pytest.raises(ValueError, match="controller の load result"):
        MidiSession(
            controller=controller,
            snapshot_load_result=_snapshot({}),
        )

    with pytest.raises(ValueError, match="discard_persisted_snapshot"):
        MidiSession(
            controller=None,
            snapshot_load_result=_snapshot({}),
        )


@pytest.mark.parametrize("cc", [True, 1.0, "1", -1, 128])
def test_value_for_cc_rejects_noncanonical_cc(cc: object) -> None:
    controller = _controller(values={1: 0.5})
    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
    )

    with pytest.raises((TypeError, ValueError)):
        session.value_for_cc(cc)  # type: ignore[arg-type]

    assert session.value_for_cc(1) == pytest.approx(0.5)


def test_poll_error_transitions_to_frozen_and_publishes_diagnostic() -> None:
    center = DiagnosticCenter()
    controller = _controller(
        values={7: 0.75},
        poll_error=MidiConnectionError("device lost"),
    )
    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
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


@pytest.mark.parametrize(
    "error",
    [TypeError("invalid MIDI message"), ValueError("invalid MIDI value")],
)
def test_frame_snapshot_does_not_reclassify_strict_validation_error(
    error: Exception,
) -> None:
    center = DiagnosticCenter()
    controller = _controller(values={7: 0.75}, poll_error=error)
    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
        diagnostics=center,
    )

    with pytest.raises(type(error), match=str(error)):
        session.frame_snapshot()

    assert session.state == "live"
    assert session.controller is controller
    assert controller.closed == 0
    assert center.snapshot() == ()


def test_reconnect_success_and_failure_are_explicit() -> None:
    center = DiagnosticCenter()
    live = _controller(values={1: 0.5})
    session = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({1: 0.25}),
        reconnect=lambda: live,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
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
        snapshot_load_result=_snapshot({}),
        reconnect=lambda: None,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )
    assert failed.reconnect() is False
    assert failed.state == "frozen"
    assert center.snapshot()[-1].summary == "MIDI reconnect failed"


@pytest.mark.parametrize(
    "error",
    [ImportError("mido backend failed"), TypeError("invalid reconnect config")],
)
def test_reconnect_does_not_reclassify_factory_errors(error: Exception) -> None:
    center = DiagnosticCenter()

    def fail() -> None:
        raise error

    session = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({1: 0.25}),
        reconnect=fail,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )

    with pytest.raises(type(error), match=str(error)):
        session.reconnect()

    assert session.state == "frozen"
    assert session.last_error is None
    assert center.snapshot() == ()


def test_reconnect_publishes_rejected_snapshot_diagnostic() -> None:
    center = DiagnosticCenter()
    controller = _controller()
    diagnostic = DiagnosticEvent(
        category="midi",
        severity="warning",
        summary="old MIDI snapshot",
    )
    controller.snapshot_load_result = CcSnapshotLoadResult(
        values=(),
        status="old",
        source=Path("snapshot.json"),
        diagnostic=diagnostic,
    )
    session = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({}),
        reconnect=lambda: controller,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )

    assert session.reconnect() is True
    assert center.snapshot() == (diagnostic,)


def test_reconnect_replaces_snapshot_action_identity() -> None:
    center = DiagnosticCenter()
    source = Path("snapshot.json")
    old_diagnostic = DiagnosticEvent(
        category="midi",
        severity="warning",
        summary="old MIDI snapshot",
        dedupe_key="same-snapshot",
    )
    old_result = CcSnapshotLoadResult(
        values=(),
        status="old",
        source=source,
        diagnostic=old_diagnostic,
    )
    replacement = _controller(values={7: 0.75})
    new_diagnostic = DiagnosticEvent(
        category="midi",
        severity="warning",
        summary="old MIDI snapshot",
        dedupe_key="same-snapshot",
    )
    replacement.snapshot_load_result = CcSnapshotLoadResult(
        values=(),
        status="old",
        source=source,
        diagnostic=new_diagnostic,
    )
    session = MidiSession(
        controller=None,
        snapshot_load_result=old_result,
        reconnect=lambda: replacement,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )
    old_event = center.snapshot()[0]

    assert session.reconnect() is True
    assert center.snapshot() == (new_diagnostic,)
    assert session.discard_for_diagnostic(old_event) is False
    assert replacement.discarded == 0
    assert replacement.values == {7: 0.75}

    new_event = center.snapshot()[0]
    assert session.discard_for_diagnostic(new_event) is True
    assert replacement.discarded == 1
    assert replacement.values == {7: 0.75}


def test_reconnect_invalidates_old_disconnect_action() -> None:
    center = DiagnosticCenter()
    disconnected = _controller(
        values={1: 0.25},
        poll_error=MidiConnectionError("device lost"),
    )
    replacement = _controller(values={1: 0.75})
    session = MidiSession(
        controller=disconnected,
        snapshot_load_result=disconnected.snapshot_load_result,
        reconnect=lambda: replacement,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )
    assert session.frame_snapshot() is not None
    disconnect_event = center.snapshot()[-1]

    assert session.reconnect() is True
    assert disconnect_event not in center.snapshot()
    assert session.discard_for_diagnostic(disconnect_event) is False
    assert replacement.discarded == 0
    assert replacement.values == {1: 0.75}


def test_retry_action_requires_current_connection_diagnostic_identity() -> None:
    center = DiagnosticCenter()
    disconnected = _controller(
        values={1: 0.25},
        poll_error=MidiConnectionError("device lost"),
    )
    replacement = _controller(values={1: 0.75})
    attempts = iter([None, replacement])
    calls = 0

    def reconnect() -> Any:
        nonlocal calls
        calls += 1
        return next(attempts)

    session = MidiSession(
        controller=disconnected,
        snapshot_load_result=disconnected.snapshot_load_result,
        reconnect=reconnect,
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )
    assert session.frame_snapshot() is not None
    first_event = center.snapshot()[-1]

    assert session.retry_for_diagnostic(first_event) is False
    current_event = center.snapshot()[-1]
    assert current_event is not first_event
    assert calls == 1
    assert session.retry_for_diagnostic(first_event) is False
    assert calls == 1

    assert session.retry_for_diagnostic(current_event) is True
    assert calls == 2
    assert session.controller is replacement
    assert current_event not in center.snapshot()


def test_reconnect_failure_remains_active_until_success() -> None:
    center = DiagnosticCenter()
    replacement = _controller(values={1: 0.75})
    attempts = iter([None, replacement])
    session = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({1: 0.25}),
        reconnect=lambda: next(attempts),
        diagnostics=center,
        discard_persisted_snapshot=lambda: None,
    )

    assert session.reconnect() is False
    failure_event = center.snapshot()[-1]
    assert failure_event.summary == "MIDI reconnect failed"

    assert session.reconnect() is True
    assert failure_event not in center.snapshot()
    assert session.controller is replacement


def test_reconnect_while_live_fails_before_opening_another_port() -> None:
    controller = _controller(values={1: 0.5})
    reconnect_calls = 0

    def reconnect() -> Any:
        nonlocal reconnect_calls
        reconnect_calls += 1
        return _controller()

    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
        reconnect=reconnect,
    )

    with pytest.raises(RuntimeError, match="live MIDI controller"):
        session.reconnect()

    assert reconnect_calls == 0
    assert session.controller is controller
    assert controller.closed == 0


def test_connection_discard_clears_persistence_and_dismisses_diagnostic() -> None:
    center = DiagnosticCenter()
    controller = _controller(
        values={7: 0.75},
        poll_error=MidiConnectionError("device lost"),
    )
    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
        diagnostics=center,
    )
    assert session.frame_snapshot() is not None
    event = center.snapshot()[-1]

    assert session.discard_for_diagnostic(event) is True
    assert controller.discarded == 1
    assert session.state == "disabled"
    assert event not in center.snapshot()
    assert session.discard_for_diagnostic(event) is False


def test_snapshot_discard_rejects_stale_controller_load_result() -> None:
    center = DiagnosticCenter()
    diagnostic = DiagnosticEvent(
        category="midi",
        severity="warning",
        summary="old MIDI snapshot",
    )
    original = CcSnapshotLoadResult(
        values=(),
        status="old",
        source=Path("snapshot.json"),
        diagnostic=diagnostic,
    )
    controller = _controller(values={7: 0.75})
    controller.snapshot_load_result = original
    session = MidiSession(
        controller=controller,
        snapshot_load_result=original,
        diagnostics=center,
    )
    event = center.snapshot()[0]
    controller.snapshot_load_result = CcSnapshotLoadResult(
        values=(),
        status="loaded",
        source=original.source,
    )

    assert session.discard_for_diagnostic(event) is False
    assert controller.discarded == 0
    assert center.snapshot() == (event,)


def test_disabled_session_cannot_reconnect_or_publish_failure() -> None:
    center = DiagnosticCenter()
    session = MidiSession(
        controller=None,
        snapshot_load_result=None,
        diagnostics=center,
    )

    assert session.can_reconnect is False
    with pytest.raises(RuntimeError, match="構成されていません"):
        session.reconnect()
    assert center.snapshot() == ()


def test_close_catches_base_exception_and_reports_secondary_cleanup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    class CleanupFault(BaseException):
        pass

    save_error = CleanupFault("save failed")

    class Controller(_Controller):
        def save(self) -> None:
            calls.append("save")
            raise save_error

        def close(self) -> None:
            calls.append("close")
            raise RuntimeError("close failed")

    controller = cast(Any, Controller())
    session = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
    )

    with pytest.raises(CleanupFault) as exc_info:
        session.close()

    assert exc_info.value is save_error
    assert calls == ["save", "close"]
    assert any(
        "close MIDI controller" in record.getMessage()
        for record in caplog.records
    )


def test_clear_frozen_and_close_own_the_session_resources() -> None:
    cleared: list[bool] = []
    frozen = MidiSession(
        controller=None,
        snapshot_load_result=_snapshot({2: 1.0}),
        discard_persisted_snapshot=lambda: cleared.append(True),
    )
    frozen.clear_frozen_snapshot()
    snapshot = frozen.frame_snapshot()
    assert snapshot is None
    assert frozen.state == "disabled"
    assert cleared == [True]

    controller = _controller(values={2: 1.0})
    live = MidiSession(
        controller=controller,
        snapshot_load_result=controller.snapshot_load_result,
    )
    with pytest.raises(RuntimeError, match="live MIDI controller"):
        live.clear_frozen_snapshot()
    assert controller.values == {2: 1.0}
    live.close()
    live.close()
    assert controller.discarded == 0
    assert controller.saved == 1
    assert controller.closed == 1
