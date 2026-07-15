import time

import pytest

from grafix.interactive.runtime.frame_clock import (
    RealTimeClock,
    RecordingClock,
    TransportClock,
    TransportSnapshot,
)


class FakeTime:
    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return float(self.value)

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def test_recording_clock_advances_by_fixed_fps():
    clock = RecordingClock(t0=1.0, fps=60.0)
    assert clock.fps == 60.0
    assert clock.frame_index == 0
    assert clock.t() == pytest.approx(1.0)

    clock.tick()
    assert clock.frame_index == 1
    assert clock.t() == pytest.approx(1.0 + 1.0 / 60.0)

    for _ in range(59):
        clock.tick()
    assert clock.frame_index == 60
    assert clock.t() == pytest.approx(2.0)


def test_real_time_clock_returns_elapsed_seconds():
    start_time = time.perf_counter() - 1.0
    clock = RealTimeClock(start_time=start_time)
    assert 0.5 < clock.t() < 1.5


def test_transport_pause_keeps_time_fixed_and_play_resumes_without_jump():
    now = FakeTime(10.0)
    clock = TransportClock(start_time=now.value, time_source=now)
    now.advance(2.0)
    assert clock.t() == pytest.approx(2.0)

    clock.pause()
    assert not clock.is_playing
    now.advance(100.0)
    assert clock.t() == pytest.approx(2.0)

    clock.play()
    assert clock.is_playing
    assert clock.t() == pytest.approx(2.0)
    now.advance(0.5)
    assert clock.t() == pytest.approx(2.5)


def test_transport_toggle_reports_resulting_state():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    assert clock.toggle() is False
    assert clock.toggle() is True


def test_transport_seek_and_reset_are_deterministic_while_playing_or_paused():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    now.advance(4.0)
    clock.seek(12.5)
    assert clock.is_playing
    assert clock.t() == pytest.approx(12.5)
    now.advance(1.0)
    assert clock.t() == pytest.approx(13.5)

    clock.pause()
    clock.seek(-2.0)
    now.advance(30.0)
    assert clock.t() == pytest.approx(-2.0)
    clock.reset()
    assert not clock.is_playing
    assert clock.t() == pytest.approx(0.0)


def test_transport_step_frame_pauses_and_supports_backward_steps():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    now.advance(1.0)

    assert clock.step_frame(fps=20.0) == pytest.approx(1.05)
    assert not clock.is_playing
    now.advance(10.0)
    assert clock.t() == pytest.approx(1.05)
    assert clock.step_frame(fps=20.0, frames=-2) == pytest.approx(0.95)


def test_transport_speed_change_is_continuous():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    now.advance(2.0)

    clock.set_speed(0.5)
    assert clock.t() == pytest.approx(2.0)
    assert clock.speed == pytest.approx(0.5)
    now.advance(4.0)
    assert clock.t() == pytest.approx(4.0)

    clock.pause()
    clock.set_speed(2.0)
    assert clock.t() == pytest.approx(4.0)
    clock.play()
    now.advance(0.25)
    assert clock.t() == pytest.approx(4.5)


def test_transport_snapshot_is_immutable_value_object():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now, speed=2.0)
    now.advance(0.25)
    snapshot = clock.snapshot()
    assert snapshot.t == pytest.approx(0.5)
    assert snapshot.is_playing is True
    assert snapshot.speed == pytest.approx(2.0)
    assert snapshot.epoch == 0


def test_transport_epoch_changes_only_at_discontinuities():
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)

    assert clock.epoch == 0
    clock.pause()
    clock.play()
    clock.set_speed(2.0)
    assert clock.epoch == 0

    clock.synchronize(2.5)
    assert clock.t() == pytest.approx(2.5)
    assert clock.epoch == 0

    clock.seek(3.0)
    assert clock.epoch == 1
    clock.reset()
    assert clock.epoch == 2
    clock.step_frame(fps=20.0, frames=-1)
    assert clock.epoch == 3
    assert clock.mark_discontinuity() == 4
    assert clock.snapshot().epoch == 4


def test_transport_snapshot_keeps_legacy_three_positional_arguments():
    snapshot = TransportSnapshot(1.5, False, 0.5)
    assert snapshot.t == pytest.approx(1.5)
    assert snapshot.is_playing is False
    assert snapshot.speed == pytest.approx(0.5)
    assert snapshot.epoch == 0


def test_transport_clamps_a_regressing_time_source():
    now = FakeTime(10.0)
    clock = TransportClock(start_time=now.value, time_source=now)
    now.advance(2.0)
    assert clock.t() == pytest.approx(2.0)
    now.value = 9.0
    assert clock.t() == pytest.approx(2.0)


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_transport_rejects_invalid_speed(value: float):
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    with pytest.raises(ValueError):
        clock.set_speed(value)


@pytest.mark.parametrize("fps", [0.0, -1.0, float("inf"), float("nan")])
def test_transport_rejects_invalid_step_fps(fps: float):
    now = FakeTime()
    clock = TransportClock(start_time=now.value, time_source=now)
    with pytest.raises(ValueError):
        clock.step_frame(fps=fps)


def test_real_time_clock_keeps_legacy_name_and_supports_transport_controls():
    now = FakeTime(5.0)
    clock = RealTimeClock(start_time=now.value, time_source=now)
    clock.pause()
    clock.seek(3.0)
    assert clock.t() == pytest.approx(3.0)
