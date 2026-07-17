from pathlib import Path

import grafix.interactive.runtime.recording_system as recording_module
import grafix.interactive.runtime.video_recorder as video_recorder_module
import pytest
from grafix.interactive.runtime.recording_system import VideoRecordingSystem
from grafix.interactive.runtime.video_recorder import VideoPublishError


class _FakeRecorder:
    last_created: "_FakeRecorder | None" = None

    def __init__(
        self,
        *,
        output_path: Path,
        size: tuple[int, int],
        fps: float,
        no_clobber: bool = False,
    ) -> None:
        self.path = Path(output_path)
        self.size = size
        self.fps = fps
        self.no_clobber = no_clobber
        self.closed = False
        self.aborted = False
        self.close_timeout_s: float | None = None
        self.frames: list[bytes] = []
        _FakeRecorder.last_created = self

    def write_frame_rgb24(self, frame: bytes) -> None:
        self.frames.append(frame)

    def close(self, *, timeout_s: float) -> None:
        self.closed = True
        self.close_timeout_s = float(timeout_s)

    def close_to_staging(self, *, timeout_s: float) -> Path:
        self.closed = True
        self.close_timeout_s = float(timeout_s)
        staging = self.path.with_name(f".{self.path.name}.staged")
        staging.write_bytes(b"video")
        return staging

    def abort(self) -> None:
        self.aborted = True


def test_recording_can_choose_a_versioned_path_at_start(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)
    capture_path = tmp_path / "base_001.mp4"

    system.start(framebuffer_size=(100, 80), t0=1.5, output_path=capture_path)
    recorder = _FakeRecorder.last_created
    assert recorder is not None
    assert recorder.path == capture_path
    assert recorder.no_clobber is True
    assert system.t() == 1.5

    saved = system.stop(timeout_s=2.5)

    assert saved == capture_path
    assert recorder.closed is True
    assert recorder.close_timeout_s == 2.5
    assert system.is_recording is False


def test_recording_can_transfer_completed_video_to_generation_transaction(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)
    capture_path = tmp_path / "base_001.mp4"
    system.start(framebuffer_size=(100, 80), t0=1.5, output_path=capture_path)

    staged = system.stop_to_staging(timeout_s=1.25)

    assert staged is not None
    assert staged.output_path == capture_path
    assert staged.staging_path.read_bytes() == b"video"
    assert not capture_path.exists()
    assert _FakeRecorder.last_created is not None
    assert _FakeRecorder.last_created.close_timeout_s == 1.25
    assert system.is_recording is False


def test_pause_policy_drops_error_frame_without_advancing_clock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Screen:
        def read(self, **_kwargs: object) -> bytes:
            return b"rgb"

    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=20.0)
    system.start(framebuffer_size=(100, 80), t0=1.5)

    system.write_frame(Screen())
    assert system.t() == pytest.approx(1.55)
    system.pause_frame("ValueError: broken scene")
    assert system.t() == pytest.approx(1.55)
    assert system.frame_index == 1

    staged = system.stop_to_staging(stop_reason="user_stop")

    assert staged is not None
    assert staged.framebuffer_size == (100, 80)
    assert staged.recording.as_dict() == {
        "fps": 20.0,
        "frame_count": 1,
        "dropped_frame_count": 1,
        "duplicated_frame_count": 0,
        "error_count": 1,
        "error_policy": "pause",
        "stop_reason": "user_stop",
        "abort_reason": None,
        "last_error": "ValueError: broken scene",
    }
    recorder = _FakeRecorder.last_created
    assert recorder is not None
    assert recorder.frames == [b"rgb"]


def test_direct_stop_surfaces_recovery_path_after_late_publish_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class SuccessfulProcess:
        stdin = object()
        returncode = 0

        def communicate(
            self, *, input: bytes, timeout: float
        ) -> tuple[bytes, bytes]:
            assert input == b""
            # 呼び出し側deadlineの一部はtimeout後のkill/reap用に予約する。
            assert timeout == pytest.approx(0.375)
            return b"", b""

    capture_path = tmp_path / "base_001.mp4"

    def fake_popen(cmd: list[str], **_kwargs: object) -> SuccessfulProcess:
        Path(cmd[-1]).write_bytes(b"completed-video")
        return SuccessfulProcess()

    monkeypatch.setattr(video_recorder_module.subprocess, "Popen", fake_popen)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)
    system.start(
        framebuffer_size=(100, 80),
        t0=1.5,
        output_path=capture_path,
    )
    capture_path.write_bytes(b"late-external-video")

    with pytest.raises(VideoPublishError, match="recovery=") as exc_info:
        system.stop(timeout_s=0.75)

    assert system.is_recording is False
    assert capture_path.read_bytes() == b"late-external-video"
    assert exc_info.value.recovery_path.read_bytes() == b"completed-video"
    exc_info.value.recovery_path.unlink()


@pytest.mark.parametrize("t0", [float("nan"), float("inf"), float("-inf")])
def test_invalid_start_time_is_rejected_before_encoder_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    t0: float,
) -> None:
    created: list[str] = []

    class UnexpectedRecorder:
        def __init__(self, **_kwargs: object) -> None:
            created.append("recorder")

    monkeypatch.setattr(recording_module, "VideoRecorder", UnexpectedRecorder)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)

    with pytest.raises(ValueError, match="t0 は有限値"):
        system.start(framebuffer_size=(100, 80), t0=t0)

    assert created == []
    assert system.is_recording is False


def test_clock_initialization_failure_happens_before_encoder_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class FailedClock:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("clock")
            raise RuntimeError("clock failed")

    class UnexpectedRecorder:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("recorder")

    monkeypatch.setattr(recording_module, "RecordingClock", FailedClock)
    monkeypatch.setattr(recording_module, "VideoRecorder", UnexpectedRecorder)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)

    with pytest.raises(RuntimeError, match="clock failed"):
        system.start(framebuffer_size=(100, 80), t0=0.0)

    assert calls == ["clock"]
    assert system.is_recording is False


def test_notification_failure_aborts_encoder_before_committing_recording_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    notification_error = KeyboardInterrupt("stdout interrupted")

    def fail_notification(*_args: object, **_kwargs: object) -> None:
        raise notification_error

    monkeypatch.setattr("builtins.print", fail_notification)
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)

    with pytest.raises(KeyboardInterrupt, match="stdout interrupted") as exc_info:
        system.start(framebuffer_size=(100, 80), t0=0.0)

    recorder = _FakeRecorder.last_created
    assert recorder is not None
    assert recorder.aborted is True
    assert exc_info.value is notification_error
    assert system.is_recording is False


def test_stop_closes_recorder_even_if_clock_invariant_is_missing(
    tmp_path: Path,
) -> None:
    recorder = _FakeRecorder(
        output_path=tmp_path / "base.mp4",
        size=(100, 80),
        fps=30.0,
    )
    system = VideoRecordingSystem(output_path=tmp_path / "base.mp4", fps=30.0)
    system._recorder = recorder
    system._clock = None

    saved = system.stop()

    assert saved == tmp_path / "base.mp4"
    assert recorder.closed is True
    assert system.is_recording is False
