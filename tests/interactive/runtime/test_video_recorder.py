from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from grafix.interactive.runtime import video_recorder
from grafix.interactive.runtime.video_recorder import (
    VideoRecorder,
    _ffmpeg_command,
    default_video_output_path,
)


def test_default_video_output_path_uses_data_dir_and_script_stem():
    def draw(t: float) -> None:
        return None

    path = default_video_output_path(draw)
    assert path.parts[0] == "data"
    assert path.parts[1] == "output"
    assert path.parts[2] == "video"
    assert path.name == f"{Path(__file__).stem}.mp4"
    assert path.suffix == ".mp4"


def test_ffmpeg_command_contains_expected_rawvideo_args():
    cmd = _ffmpeg_command(output_path=Path("out.mp4"), size=(320, 240), fps=60.0)

    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd
    assert "rawvideo" in cmd
    assert "-pix_fmt" in cmd
    assert "rgb24" in cmd
    assert "-video_size" in cmd
    assert "320x240" in cmd
    assert "-framerate" in cmd
    assert "60.0" in cmd
    assert "-vf" in cmd
    assert cmd[cmd.index("-vf") + 1] == "vflip,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    assert cmd[-1] == "out.mp4"


def test_close_error_includes_recording_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedProcess:
        stdin = object()
        returncode = 1

        def communicate(self, *, input: bytes) -> tuple[bytes, bytes]:
            assert input == b""
            return b"", b"encoder failed"

    monkeypatch.setattr(video_recorder.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())

    output_path = tmp_path / "failed.mp4"
    recorder = VideoRecorder(output_path=output_path, size=(3, 5), fps=24.0)

    with pytest.raises(RuntimeError) as exc_info:
        recorder.close()

    message = str(exc_info.value)
    assert f"path={output_path}" in message
    assert "input_size=3x5" in message
    assert "fps=24" in message
    assert "encoder failed" in message


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe が必要",
)
def test_video_recorder_encodes_odd_input_size_with_even_padding(tmp_path: Path) -> None:
    output_path = tmp_path / "odd.mp4"
    recorder = VideoRecorder(output_path=output_path, size=(3, 5), fps=1.0)
    # GL readback と同じ bottom-up 行順。vflip 後は明るい最終行が動画の先頭行になる。
    frame = b"".join(bytes([value]) * (3 * 3) for value in (0, 50, 100, 150, 250))
    recorder.write_frame_rgb24(frame)
    recorder.close()

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "4x6"

    decoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output_path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    row_bytes = 4 * 3
    top_drawn = decoded[:row_bytes][: 3 * 3]
    bottom_drawn = decoded[4 * row_bytes : 5 * row_bytes][: 3 * 3]
    assert sum(top_drawn) > sum(bottom_drawn)
