from __future__ import annotations

import os
from pathlib import Path

import pytest

from grafix.export.capture_publish import capture_manifest_path_for
from grafix.export.capture_staging import (
    CaptureStaging,
    allocate_capture_generation_path,
    capture_staging_work_path,
    cleanup_capture_staging,
    publish_with_late_collision_retry,
    validate_capture_staged_outputs,
)
from grafix.export.output_paths import VersionedPathAllocator


def test_capture_staging_cleans_normal_exception_and_repeated_close(
    tmp_path: Path,
) -> None:
    normal = CaptureStaging.create(tmp_path / "frame.svg", purpose="capture")
    normal.work_path.write_bytes(b"complete")
    directory = normal.directory
    normal.close()
    normal.close()
    assert not directory.exists()

    exceptional_directory: Path | None = None
    with pytest.raises(RuntimeError, match="encode failed"):
        with CaptureStaging.create(
            tmp_path / "failed.svg", purpose="capture"
        ) as exceptional:
            exceptional_directory = exceptional.directory
            exceptional.work_path.write_bytes(b"partial")
            raise RuntimeError("encode failed")
    assert exceptional_directory is not None
    assert not exceptional_directory.exists()


def test_cleanup_capture_staging_is_idempotent(tmp_path: Path) -> None:
    directory = tmp_path / ".frame.export-1-test"
    directory.mkdir()
    (directory / "partial").write_bytes(b"partial")

    cleanup_capture_staging(directory)
    cleanup_capture_staging(directory)

    assert not directory.exists()


def test_staging_owner_creates_work_path_and_rejects_escape(tmp_path: Path) -> None:
    directory = tmp_path / ".frame.export-1-test"
    work_path = capture_staging_work_path(directory, tmp_path / "frame.png")
    work_path.write_bytes(b"complete")

    assert validate_capture_staged_outputs(directory, (work_path,)) == (work_path,)
    with pytest.raises(ValueError, match="staging directory"):
        validate_capture_staged_outputs(directory, (tmp_path / "outside.png",))
    with pytest.raises(ValueError, match="staging directory"):
        validate_capture_staged_outputs(directory, (directory,))


@pytest.mark.parametrize("collision", ["artifact", "manifest"])
def test_generation_allocation_treats_broken_symlink_as_occupied(
    tmp_path: Path,
    collision: str,
) -> None:
    base = tmp_path / "frame.svg"
    occupied = base if collision == "artifact" else capture_manifest_path_for(base)
    os.symlink(tmp_path / "missing-target", occupied)

    allocated = allocate_capture_generation_path(VersionedPathAllocator(), base)

    assert allocated == tmp_path / "frame_001.svg"
    assert os.path.lexists(occupied)


def test_generation_allocation_checks_complete_artifact_family(
    tmp_path: Path,
) -> None:
    base = tmp_path / "drawing.gcode"

    def family(candidate: Path) -> tuple[Path, Path]:
        return (
            candidate.with_name(f"{candidate.stem}_layer001.gcode"),
            candidate.with_name(f"{candidate.stem}_layer002.gcode"),
        )

    family(base)[1].write_bytes(b"external layer")

    allocated = allocate_capture_generation_path(
        VersionedPathAllocator(),
        base,
        artifact_paths_for=family,
    )

    assert allocated == tmp_path / "drawing_001.gcode"
    assert family(base)[1].read_bytes() == b"external layer"


def test_late_collision_retry_reuses_completed_staging_callback(
    tmp_path: Path,
) -> None:
    base = tmp_path / "frame.svg"
    staging = tmp_path / ".frame.capture-test.svg"
    staging.write_bytes(b"encoded-once")
    attempts: list[tuple[Path, bytes]] = []

    def publish(candidate: Path) -> Path:
        attempts.append((candidate, staging.read_bytes()))
        if len(attempts) < 3:
            candidate.write_bytes(f"external-{len(attempts)}".encode())
            raise FileExistsError(candidate)
        candidate.write_bytes(staging.read_bytes())
        return candidate

    result = publish_with_late_collision_retry(
        allocator=VersionedPathAllocator(),
        base_path=base,
        publish=publish,
        max_retries=3,
    )

    assert [candidate for candidate, _payload in attempts] == [
        base,
        tmp_path / "frame_001.svg",
        tmp_path / "frame_002.svg",
    ]
    assert {payload for _candidate, payload in attempts} == {b"encoded-once"}
    assert result.output_path == tmp_path / "frame_002.svg"
    assert result.value == result.output_path


def test_late_collision_retry_reports_bounded_exhaustion(tmp_path: Path) -> None:
    attempts: list[Path] = []

    def always_collide(candidate: Path) -> None:
        attempts.append(candidate)
        raise FileExistsError(candidate)

    with pytest.raises(FileExistsError, match="retries=2"):
        publish_with_late_collision_retry(
            allocator=VersionedPathAllocator(),
            base_path=tmp_path / "frame.svg",
            publish=always_collide,
            max_retries=2,
        )

    assert attempts == [
        tmp_path / "frame.svg",
        tmp_path / "frame_001.svg",
    ]
