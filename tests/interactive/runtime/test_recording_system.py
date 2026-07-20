from pathlib import Path

import grafix.interactive.runtime.recording_system as recording_module
import pytest
from grafix.core.capture_manifest import RecordingManifest
from grafix.interactive.runtime.recording_system import (
    StagedVideoCapture,
    VideoRecordingSystem,
)


class _FakeRecorder:
    last_created: "_FakeRecorder | None" = None

    def __init__(
        self,
        *,
        output_path: Path,
        size: tuple[int, int],
        fps: float,
    ) -> None:
        self.path = Path(output_path)
        self.size = size
        self.fps = fps
        self.finished = False
        self.aborted = False
        self.finish_timeout_s: float | None = None
        self.frames: list[bytes] = []
        _FakeRecorder.last_created = self

    def write_frame_rgb24(self, frame: bytes) -> None:
        self.frames.append(frame)

    def finish(self, *, timeout_s: float) -> Path:
        self.finished = True
        self.finish_timeout_s = float(timeout_s)
        staging = self.path.with_name(f".{self.path.name}.staged")
        staging.write_bytes(b"video")
        return staging

    def abort(self) -> None:
        self.aborted = True


def test_recording_can_choose_a_versioned_path_at_start(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(fps=30.0)
    capture_path = tmp_path / "base_001.mp4"

    system.start(framebuffer_size=(100, 80), t0=1.5, output_path=capture_path)
    recorder = _FakeRecorder.last_created
    assert recorder is not None
    assert recorder.path == capture_path
    assert system.t() == 1.5

    staged = system.stop(timeout_s=2.5)

    assert staged is not None
    assert staged.output_path == capture_path
    assert staged.staging_path.read_bytes() == b"video"
    assert not capture_path.exists()
    assert recorder.finished is True
    assert recorder.finish_timeout_s == 2.5
    assert system.is_recording is False


def test_recording_can_transfer_completed_video_to_generation_transaction(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(fps=30.0)
    capture_path = tmp_path / "base_001.mp4"
    system.start(framebuffer_size=(100, 80), t0=1.5, output_path=capture_path)

    staged = system.stop(timeout_s=1.25)

    assert staged is not None
    assert staged.output_path == capture_path
    assert staged.staging_path.read_bytes() == b"video"
    assert not capture_path.exists()
    assert _FakeRecorder.last_created is not None
    assert _FakeRecorder.last_created.finish_timeout_s == 1.25
    assert system.is_recording is False


def test_pause_policy_drops_error_frame_without_advancing_clock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Screen:
        def read(self, **_kwargs: object) -> bytes:
            return b"rgb"

    monkeypatch.setattr(recording_module, "VideoRecorder", _FakeRecorder)
    system = VideoRecordingSystem(fps=20.0)
    system.start(
        framebuffer_size=(100, 80),
        t0=1.5,
        output_path=tmp_path / "base.mp4",
    )

    system.write_frame(Screen())
    assert system.t() == pytest.approx(1.55)
    system.pause_frame("ValueError: broken scene")
    assert system.t() == pytest.approx(1.55)
    assert system.frame_index == 1

    staged = system.stop(stop_reason="user_stop")

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
    system = VideoRecordingSystem(fps=30.0)

    with pytest.raises(ValueError, match="t0"):
        system.start(
            framebuffer_size=(100, 80),
            t0=t0,
            output_path=tmp_path / "base.mp4",
        )

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
    system = VideoRecordingSystem(fps=30.0)

    with pytest.raises(RuntimeError, match="clock failed"):
        system.start(
            framebuffer_size=(100, 80),
            t0=0.0,
            output_path=tmp_path / "base.mp4",
        )

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
    system = VideoRecordingSystem(fps=30.0)

    with pytest.raises(KeyboardInterrupt, match="stdout interrupted") as exc_info:
        system.start(
            framebuffer_size=(100, 80),
            t0=0.0,
            output_path=tmp_path / "base.mp4",
        )

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
    system = VideoRecordingSystem(fps=30.0)
    system._recorder = recorder
    system._clock = None
    system._size = recorder.size

    staged = system.stop()

    assert staged is not None
    assert staged.output_path == tmp_path / "base.mp4"
    assert recorder.finished is True
    assert system.is_recording is False


def test_stop_aborts_untransferred_staging_when_finish_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FailingRecorder(_FakeRecorder):
        def finish(self, *, timeout_s: float) -> Path:
            staging = self.path.with_name(f".{self.path.name}.staged")
            staging.write_bytes(b"partial")
            raise RuntimeError("unexpected finish failure")

        def abort(self) -> None:
            super().abort()
            self.path.with_name(f".{self.path.name}.staged").unlink(missing_ok=True)

    monkeypatch.setattr(recording_module, "VideoRecorder", FailingRecorder)
    system = VideoRecordingSystem(fps=30.0)
    system.start(
        framebuffer_size=(100, 80),
        t0=0.0,
        output_path=tmp_path / "base.mp4",
    )
    recorder = _FakeRecorder.last_created
    assert recorder is not None

    with pytest.raises(RuntimeError, match="unexpected finish failure"):
        system.stop()

    assert recorder.aborted is True
    assert system.is_recording is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("fps", "error"),
    [
        (True, TypeError),
        ("30", TypeError),
        (0.0, ValueError),
        (float("nan"), ValueError),
    ],
)
def test_recording_system_rejects_invalid_fps_at_construction(
    fps: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error, match="fps"):
        VideoRecordingSystem(fps=fps)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"framebuffer_size": [100, 80]}, "framebuffer_size"),
        ({"framebuffer_size": (100.0, 80)}, "framebuffer_size"),
        ({"framebuffer_size": (True, 80)}, "framebuffer_size"),
        ({"t0": "0"}, "t0"),
        ({"t0": True}, "t0"),
        ({"output_path": "movie.mp4"}, "output_path"),
    ],
)
def test_recording_start_rejects_implicit_input_coercion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kwargs: dict[str, object],
    match: str,
) -> None:
    created: list[object] = []

    class UnexpectedRecorder:
        def __init__(self, **values: object) -> None:
            created.append(values)

    monkeypatch.setattr(recording_module, "VideoRecorder", UnexpectedRecorder)
    values: dict[str, object] = {
        "framebuffer_size": (100, 80),
        "t0": 0.0,
        "output_path": tmp_path / "movie.mp4",
    }
    values.update(kwargs)

    system = VideoRecordingSystem(fps=30.0)
    with pytest.raises(TypeError, match=match):
        system.start(**values)  # type: ignore[arg-type]
    assert created == []


def test_recording_control_strings_and_timeout_are_strict() -> None:
    system = VideoRecordingSystem(fps=30.0)

    with pytest.raises(TypeError, match="error"):
        system.pause_frame(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="空"):
        system.pause_frame("")
    with pytest.raises(TypeError, match="timeout_s"):
        system.stop(timeout_s="1")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="stop_reason"):
        system.stop(stop_reason=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="abort_reason"):
        system.stop(abort_reason=1)  # type: ignore[arg-type]


def test_staged_video_capture_validates_direct_construction(tmp_path: Path) -> None:
    recording = RecordingManifest(fps=30.0, frame_count=1)
    values: dict[str, object] = {
        "staging_path": tmp_path / ".movie.mp4",
        "output_path": tmp_path / "movie.mp4",
        "framebuffer_size": (100, 80),
        "recording": recording,
    }
    for field, value in (
        ("staging_path", "staging.mp4"),
        ("output_path", "movie.mp4"),
        ("framebuffer_size", [100, 80]),
        ("recording", object()),
    ):
        invalid = dict(values)
        invalid[field] = value
        with pytest.raises(TypeError):
            StagedVideoCapture(**invalid)  # type: ignore[arg-type]
