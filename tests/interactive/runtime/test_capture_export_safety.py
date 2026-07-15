from __future__ import annotations

# ruff: noqa: E402 -- pyglet option must be set before importing DrawWindowSystem.

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pyglet
import pytest

pyglet.options["shadow_window"] = False

from grafix.core.capture_manifest import capture_manifest_path_for
from grafix.core.output_paths import VersionedPathAllocator, gcode_layer_output_path
from grafix.core.pipeline import RealizedLayer
from grafix.interactive.runtime import export_job_system as export_module
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
from grafix.interactive.runtime.export_job_system import (
    ExportJob,
    ExportJobResult,
    ExportJobStatus,
    ExportJobSystem,
    ExportKind,
    FrameExportSnapshot,
)

_WAIT_TIMEOUT_S = 8.0


def _snapshot(*layer_names: str) -> FrameExportSnapshot:
    layers = tuple(
        cast(RealizedLayer, SimpleNamespace(layer=SimpleNamespace(name=name)))
        for name in layer_names
    )
    return FrameExportSnapshot(
        layers=layers,
        canvas_size=(100, 80),
        background_color_rgb01=(1.0, 1.0, 1.0),
        t=1.25,
    )


def _staged_output_path(job: ExportJob) -> Path:
    staging_dir = job.staging_dir
    assert staging_dir is not None
    path = staging_dir / job.output_path.name
    path.write_bytes(b"complete-in-staging")
    return path


def _staging_then_sleep_backend(job: ExportJob) -> tuple[Path, ...]:
    path = _staged_output_path(job)
    time.sleep(2.0)
    return (path,)


def _staging_then_error_backend(job: ExportJob) -> tuple[Path, ...]:
    _staged_output_path(job)
    raise RuntimeError("backend failed after staging")


def _parent_commit_system(
    backend: Any,
    *,
    default_timeout_s: float = 5.0,
) -> ExportJobSystem:
    system = ExportJobSystem(backend=backend, default_timeout_s=default_timeout_s)
    # Custom backend で cancel/timeout の timing を決定的にするための test seam。
    # production では既定 `_execute_export_job` の場合だけ自動で True になる。
    system._uses_parent_commit = True
    return system


def _wait_for_staging_file(output_path: Path) -> None:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    pattern = f".{output_path.stem}.export-*"
    while time.monotonic() < deadline:
        if any(path.is_file() for directory in output_path.parent.glob(pattern) for path in directory.iterdir()):
            return
        time.sleep(0.01)
    pytest.fail(f"staging file timeout: {output_path}")


def _wait_for_result(system: ExportJobSystem, job_id: int) -> ExportJobResult:
    deadline = time.monotonic() + _WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        for result in system.poll():
            if result.job_id == job_id:
                return result
        time.sleep(0.01)
    pytest.fail(f"export result timeout: job_id={job_id}")


def _staging_directories(output_path: Path) -> list[Path]:
    return list(output_path.parent.glob(f".{output_path.stem}.export-*"))


def test_default_backend_commits_success_and_removes_staging(tmp_path: Path) -> None:
    output_path = tmp_path / "complete.gcode"
    system = ExportJobSystem()
    try:
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=output_path,
        )
        result = _wait_for_result(system, job.job_id)

        assert result.status is ExportJobStatus.SUCCESS
        assert result.paths == (output_path,)
        assert output_path.is_file()
        assert _staging_directories(output_path) == []
    finally:
        system.close()


def test_cancel_removes_staged_artifact_without_publishing_final(tmp_path: Path) -> None:
    output_path = tmp_path / "cancelled.gcode"
    system = _parent_commit_system(_staging_then_sleep_backend)
    try:
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=output_path,
        )
        _wait_for_staging_file(output_path)

        assert system.cancel(job.job_id)
        result = next(result for result in system.poll() if result.job_id == job.job_id)

        assert result.status is ExportJobStatus.CANCELLED
        assert not output_path.exists()
        assert _staging_directories(output_path) == []
    finally:
        system.close()


def test_timeout_removes_staged_artifact_without_publishing_final(tmp_path: Path) -> None:
    output_path = tmp_path / "timed-out.gcode"
    system = _parent_commit_system(
        _staging_then_sleep_backend,
        default_timeout_s=0.05,
    )
    try:
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=output_path,
        )
        result = _wait_for_result(system, job.job_id)

        assert result.status is ExportJobStatus.TIMEOUT
        assert not output_path.exists()
        assert _staging_directories(output_path) == []
    finally:
        system.close()


def test_backend_error_removes_staged_artifact_without_publishing_final(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "failed.gcode"
    system = _parent_commit_system(_staging_then_error_backend)
    try:
        job = system.submit(
            kind=ExportKind.GCODE,
            snapshot=_snapshot(),
            output_path=output_path,
        )
        result = _wait_for_result(system, job.job_id)

        assert result.status is ExportJobStatus.ERROR
        assert "backend failed after staging" in (result.error or "")
        assert not output_path.exists()
        assert _staging_directories(output_path) == []
    finally:
        system.close()


def test_parent_commit_never_replaces_a_late_existing_destination(tmp_path: Path) -> None:
    output_path = tmp_path / "capture.gcode"
    output_path.write_bytes(b"created-after-allocation")
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    staged_path = staging_dir / output_path.name
    staged_path.write_bytes(b"new-capture")
    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE,
        snapshot=_snapshot(),
        output_path=output_path,
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    result = ExportJobResult(
        job_id=job.job_id,
        kind=job.kind,
        status=ExportJobStatus.SUCCESS,
        output_path=job.output_path,
        paths=(staged_path,),
    )

    finalized = export_module._finalize_default_backend_result(job, result)

    assert finalized.status is ExportJobStatus.ERROR
    assert "parent-side export commit failed" in (finalized.error or "")
    assert output_path.read_bytes() == b"created-after-allocation"
    assert not staging_dir.exists()


@pytest.mark.parametrize("kind", [ExportKind.PNG, ExportKind.GCODE])
def test_parent_commit_rolls_back_artifact_when_manifest_late_collides(
    tmp_path: Path,
    kind: ExportKind,
) -> None:
    suffix = ".png" if kind is ExportKind.PNG else ".gcode"
    output_path = tmp_path / f"capture{suffix}"
    manifest_path = capture_manifest_path_for(output_path)
    manifest_path.write_bytes(b"external manifest")
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    staged_path = staging_dir / output_path.name
    staged_path.write_bytes(b"new capture")
    job = ExportJob(
        job_id=1,
        kind=kind,
        snapshot=_snapshot(),
        output_path=output_path,
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    result = ExportJobResult(
        job_id=job.job_id,
        kind=job.kind,
        status=ExportJobStatus.SUCCESS,
        output_path=job.output_path,
        paths=(staged_path,),
    )

    finalized = export_module._finalize_default_backend_result(job, result)

    assert finalized.status is ExportJobStatus.ERROR
    assert "parent-side export commit failed" in (finalized.error or "")
    assert not output_path.exists()
    assert manifest_path.read_bytes() == b"external manifest"
    assert not staging_dir.exists()


def test_gcode_layer_commit_failure_rolls_back_already_published_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "capture.gcode"
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    snapshot = _snapshot("ink", "detail")
    final_paths = tuple(
        gcode_layer_output_path(
            output_path,
            layer_index=index,
            n_layers=len(snapshot.layers),
            layer_name=layer.layer.name,
        )
        for index, layer in enumerate(snapshot.layers, start=1)
    )
    staged_paths = tuple(staging_dir / path.name for path in final_paths)
    for index, path in enumerate(staged_paths):
        path.write_bytes(f"layer-{index}".encode())

    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE_LAYERS,
        snapshot=snapshot,
        output_path=output_path,
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    result = ExportJobResult(
        job_id=job.job_id,
        kind=job.kind,
        status=ExportJobStatus.SUCCESS,
        output_path=job.output_path,
        paths=staged_paths,
    )
    real_link = os.link
    call_count = 0

    def fail_second_link(
        source: str | Path,
        destination: str | Path,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("simulated second layer commit failure")
        real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(export_module.os, "link", fail_second_link)

    finalized = export_module._finalize_default_backend_result(job, result)

    assert finalized.status is ExportJobStatus.ERROR
    assert "simulated second layer commit failure" in (finalized.error or "")
    assert all(not path.exists() for path in final_paths)
    assert not staging_dir.exists()


def test_gcode_layer_late_collision_keeps_external_layer_and_rolls_back_ours(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "capture.gcode"
    staging_dir = tmp_path / ".capture.export-1-test"
    staging_dir.mkdir()
    snapshot = _snapshot("ink", "detail")
    final_paths = tuple(
        gcode_layer_output_path(
            output_path,
            layer_index=index,
            n_layers=len(snapshot.layers),
            layer_name=layer.layer.name,
        )
        for index, layer in enumerate(snapshot.layers, start=1)
    )
    staged_paths = tuple(staging_dir / path.name for path in final_paths)
    for index, path in enumerate(staged_paths):
        path.write_bytes(f"new-layer-{index}".encode())
    final_paths[1].write_bytes(b"external layer")
    job = ExportJob(
        job_id=1,
        kind=ExportKind.GCODE_LAYERS,
        snapshot=snapshot,
        output_path=output_path,
        timeout_s=1.0,
        staging_dir=staging_dir,
    )
    result = ExportJobResult(
        job_id=job.job_id,
        kind=job.kind,
        status=ExportJobStatus.SUCCESS,
        output_path=job.output_path,
        paths=staged_paths,
    )

    finalized = export_module._finalize_default_backend_result(job, result)

    assert finalized.status is ExportJobStatus.ERROR
    assert not final_paths[0].exists()
    assert final_paths[1].read_bytes() == b"external layer"
    assert not capture_manifest_path_for(output_path).exists()
    assert not staging_dir.exists()


def test_gcode_layer_family_collision_checks_old_names_and_extra_indices(
    tmp_path: Path,
) -> None:
    stale_path = tmp_path / "piece_layer009_old-name.gcode"
    stale_path.write_text("stale partial capture", encoding="utf-8")
    system = object.__new__(DrawWindowSystem)
    system._capture_paths = VersionedPathAllocator()
    system._gcode_output_path = tmp_path / "piece.gcode"

    allocated = system._allocate_gcode_layers_path(_snapshot("new-name"))

    assert allocated == tmp_path / "piece_001.gcode"
    assert stale_path.read_text(encoding="utf-8") == "stale partial capture"
