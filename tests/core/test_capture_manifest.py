from __future__ import annotations

import json
from pathlib import Path

import pytest

from grafix.core.capture_manifest import (
    CAPTURE_MANIFEST_SCHEMA_VERSION,
    CaptureManifest,
    capture_manifest_path_for,
    publish_capture_generation,
    write_capture_manifest,
)


def test_capture_manifest_normalizes_and_serializes_minimum_provenance() -> None:
    manifest = CaptureManifest(
        t=1.25,
        canvas_size=(800, 600),
        format=".PNG",
        artifact_paths=(Path("output/capture.png"),),
    )

    assert manifest.as_dict() == {
        "schema_version": CAPTURE_MANIFEST_SCHEMA_VERSION,
        "t": 1.25,
        "canvas_size": {"width": 800, "height": 600},
        "format": "png",
        "artifact_paths": ["output/capture.png"],
    }


def test_capture_manifest_supports_multiple_layer_artifacts(tmp_path: Path) -> None:
    artifacts = (
        tmp_path / "capture_layer001.gcode",
        tmp_path / "capture_layer002.gcode",
    )
    manifest = CaptureManifest(
        t=0.0,
        canvas_size=(210, 297),
        format="gcode_layers",
        artifact_paths=artifacts,
    )
    path = tmp_path / "capture.gcode.capture.json"

    assert write_capture_manifest(path, manifest) == path
    assert json.loads(path.read_text(encoding="utf-8")) == manifest.as_dict()
    assert path.read_bytes().endswith(b"\n")


def test_capture_manifest_write_never_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "capture.svg.capture.json"
    path.write_text("previous\n", encoding="utf-8")
    manifest = CaptureManifest(
        t=2.0,
        canvas_size=(100, 100),
        format="svg",
        artifact_paths=(tmp_path / "capture.svg",),
    )

    with pytest.raises(FileExistsError):
        write_capture_manifest(path, manifest)

    assert path.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.iterdir()) == [path]


def test_capture_manifest_path_keeps_artifact_extension() -> None:
    assert capture_manifest_path_for(Path("output/capture_002.png")) == Path(
        "output/capture_002.png.capture.json"
    )


def test_capture_generation_rolls_back_artifact_when_manifest_late_collides(
    tmp_path: Path,
) -> None:
    staged = tmp_path / ".staged.svg"
    staged.write_bytes(b"new artifact")
    artifact = tmp_path / "capture.svg"
    manifest_path = capture_manifest_path_for(artifact)
    manifest_path.write_bytes(b"external manifest")
    manifest = CaptureManifest(
        t=1.5,
        canvas_size=(100, 80),
        format="svg",
        artifact_paths=(artifact,),
    )

    with pytest.raises(FileExistsError):
        publish_capture_generation(
            staged_artifact_paths=(staged,),
            artifact_paths=(artifact,),
            manifest_path=manifest_path,
            manifest=manifest,
        )

    assert not artifact.exists()
    assert manifest_path.read_bytes() == b"external manifest"
    assert staged.read_bytes() == b"new artifact"


def test_capture_generation_publishes_all_artifacts_and_manifest(tmp_path: Path) -> None:
    staged = (tmp_path / ".layer1", tmp_path / ".layer2")
    for index, path in enumerate(staged, start=1):
        path.write_bytes(f"layer {index}".encode())
    artifacts = (
        tmp_path / "capture_layer001.gcode",
        tmp_path / "capture_layer002.gcode",
    )
    manifest_path = tmp_path / "capture.gcode.capture.json"
    manifest = CaptureManifest(
        t=2.25,
        canvas_size=(210, 297),
        format="gcode_layers",
        artifact_paths=artifacts,
    )

    published = publish_capture_generation(
        staged_artifact_paths=staged,
        artifact_paths=artifacts,
        manifest_path=manifest_path,
        manifest=manifest,
    )

    assert published.artifact_paths == artifacts
    assert published.manifest_path == manifest_path
    assert [path.read_bytes() for path in artifacts] == [b"layer 1", b"layer 2"]
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest.as_dict()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"t": float("nan")}, "t"),
        ({"canvas_size": (0, 100)}, "canvas_size"),
        ({"format": "."}, "format"),
        ({"artifact_paths": ()}, "artifact_paths"),
    ],
)
def test_capture_manifest_validates_fields(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "t": 0.0,
        "canvas_size": (100, 100),
        "format": "svg",
        "artifact_paths": (Path("capture.svg"),),
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        CaptureManifest(**values)  # type: ignore[arg-type]
