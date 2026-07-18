from __future__ import annotations

import json
from pathlib import Path

import pytest

from grafix import G, ExportFormat, Frame, RenderOptions, RenderSession, export, render
from grafix.core.capture_manifest import capture_manifest_path_for
from grafix.core.runtime_config import runtime_config, set_config_path
from grafix.export import capture as capture_module
from grafix.export.capture import CaptureMode, CaptureService
from grafix.export.gcode import export_gcode


@pytest.fixture
def frame() -> Frame:
    geometry = G.line(
        center=(0.0, 0.0, 0.0),
        anchor="left",
        length=10.0,
        angle=0.0,
    )

    def draw(_t: float):
        return geometry

    with RenderSession(draw) as session:
        return session.render(1.25)


def test_export_infers_suffix_versions_existing_and_writes_manifest(
    frame: Frame,
    tmp_path: Path,
) -> None:
    base = tmp_path / "drawing.svg"
    base.write_bytes(b"existing artwork")

    result = export(frame, base)

    assert result.path == tmp_path / "drawing_001.svg"
    assert result.format is ExportFormat.SVG
    assert result.manifest_path == capture_manifest_path_for(result.path)
    assert base.read_bytes() == b"existing artwork"
    assert result.path.is_file()
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["format"] == "svg"
    assert payload["artifact_paths"] == [str(result.path)]
    assert payload["grafix"]["version"]
    assert payload["source"]["available"] is True
    assert payload["source"]["hash"]["algorithm"] == "sha256"
    assert "available" in payload["git"]
    assert payload["config"]["effective"]
    assert payload["parameters"]["source"] == "code"
    assert payload["parameters"]["snapshot_hash"]["algorithm"] == "sha256"
    assert payload["frame"] == {
        "t": 1.25,
        "index": 0,
        "quality": "final",
        "origin": "headless",
    }
    assert payload["output"] == {
        "format": "svg",
        "artifact_paths": [str(result.path)],
        "canvas_size": {"width": 800, "height": 800},
        "size": {"width": 800, "height": 800},
    }
    assert list(tmp_path.glob(".drawing.capture-*")) == []


def test_manifest_only_collision_is_allocated_as_next_version(
    frame: Frame,
    tmp_path: Path,
) -> None:
    base = tmp_path / "drawing.svg"
    old_manifest = capture_manifest_path_for(base)
    old_manifest.write_bytes(b"external manifest")

    result = export(frame, base)

    assert result.path == tmp_path / "drawing_001.svg"
    assert old_manifest.read_bytes() == b"external manifest"


def test_late_collision_retries_without_reencoding_or_overwriting(
    frame: Frame,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CaptureService()
    base = tmp_path / "drawing.svg"
    real_publish = capture_module.publish_capture_generation
    encode_calls = 0
    real_encode = service.encode

    def count_encode(*args, **kwargs):
        nonlocal encode_calls
        encode_calls += 1
        return real_encode(*args, **kwargs)

    publish_calls = 0

    def collide_once(**kwargs):
        nonlocal publish_calls
        publish_calls += 1
        if publish_calls == 1:
            Path(kwargs["artifact_paths"][0]).write_bytes(b"external late capture")
        return real_publish(**kwargs)

    monkeypatch.setattr(service, "encode", count_encode)
    monkeypatch.setattr(capture_module, "publish_capture_generation", collide_once)

    result = service.export(frame, base)

    assert result.path == tmp_path / "drawing_001.svg"
    assert base.read_bytes() == b"external late capture"
    assert encode_calls == 1
    assert publish_calls == 2


def test_encoder_failure_removes_private_staging_and_publishes_nothing(
    frame: Frame,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "broken.svg"

    def fail_svg(_layers, path, *, canvas_size):
        Path(path).write_bytes(b"partial")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr(capture_module, "export_svg", fail_svg)

    with pytest.raises(RuntimeError, match="encoder failed"):
        export(frame, output)

    assert not output.exists()
    assert not capture_manifest_path_for(output).exists()
    assert list(tmp_path.glob(".broken.capture-*")) == []


def test_overwrite_replaces_artifact_and_manifest_as_requested(
    frame: Frame,
    tmp_path: Path,
) -> None:
    output = tmp_path / "drawing.svg"
    output.write_bytes(b"old artifact")
    manifest = capture_manifest_path_for(output)
    manifest.write_bytes(b"old manifest")

    result = export(frame, output, overwrite=True)

    assert result.path == output
    assert output.read_bytes().startswith(b"<?xml")
    assert json.loads(manifest.read_text(encoding="utf-8"))["artifact_paths"] == [
        str(output)
    ]
    assert list(tmp_path.glob(".grafix-capture-backup-*")) == []


def test_png_uses_private_svg_and_effective_background(
    frame: Frame,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intermediate_paths: list[Path] = []
    raster_backgrounds: list[tuple[float, float, float]] = []
    raster_sizes: list[tuple[int, int]] = []

    def fake_svg(_layers, path, *, canvas_size):
        svg_path = Path(path)
        intermediate_paths.append(svg_path)
        svg_path.write_text("svg", encoding="utf-8")
        return svg_path

    def fake_rasterize(
        svg_path,
        png_path,
        *,
        background_color_rgb01,
        output_size,
        **_kwargs,
    ):
        assert Path(svg_path).read_text(encoding="utf-8") == "svg"
        raster_backgrounds.append(background_color_rgb01)
        raster_sizes.append(output_size)
        Path(png_path).write_bytes(b"png")
        return Path(png_path)

    monkeypatch.setattr(capture_module, "export_svg", fake_svg)
    monkeypatch.setattr(capture_module, "rasterize_svg_to_png", fake_rasterize)

    result = CaptureService().export(
        frame,
        tmp_path / "drawing.png",
        output_size=(64, 48),
    )

    assert result.path.read_bytes() == b"png"
    assert raster_backgrounds == [frame.background_color_rgb01]
    assert raster_sizes == [(64, 48)]
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["output"]["size"] == {"width": 64, "height": 48}
    assert len(intermediate_paths) == 1
    assert not intermediate_paths[0].exists()
    assert intermediate_paths[0] != tmp_path / "drawing.svg"


def test_gcode_capture_is_byte_identical_to_existing_encoder(
    frame: Frame,
    tmp_path: Path,
) -> None:
    expected = tmp_path / "expected.gcode"
    export_gcode(frame.layers, expected, canvas_size=frame.canvas_size)

    result = CaptureService().export(frame, tmp_path / "captured.gcode")

    assert result.path.read_bytes() == expected.read_bytes()


def test_gcode_export_uses_closed_render_session_effective_config(
    tmp_path: Path,
) -> None:
    caller_config_path = tmp_path / "caller.yaml"
    caller_config_path.write_text(
        "version: 1\nexport:\n  gcode:\n    z_up: 5.0\n    decimals: 2\n",
        encoding="utf-8",
    )
    render_config_path = tmp_path / "render.yaml"
    render_config_path.write_text(
        "version: 1\nexport:\n  gcode:\n    z_up: 17.0\n    decimals: 1\n",
        encoding="utf-8",
    )

    set_config_path(caller_config_path)
    caller_config = runtime_config()
    try:
        frame = render(lambda _t: (), config_path=render_config_path)
        assert runtime_config() is caller_config

        result = export(frame, tmp_path / "closed-session.gcode")
        direct = CaptureService().export(
            frame,
            tmp_path / "closed-session-direct.gcode",
        )

        assert result.format is ExportFormat.GCODE
        assert "G1 Z37.0" in result.path.read_text(encoding="utf-8")
        assert "G1 Z37.0" in direct.path.read_text(encoding="utf-8")
        assert result.manifest_path is not None
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["config"]["effective"]["gcode"]["z_up"] == 17.0
        assert manifest["config"]["effective"]["gcode"]["decimals"] == 1
    finally:
        set_config_path(None)


def test_png_export_uses_closed_render_session_effective_scale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_config_path = tmp_path / "caller.yaml"
    caller_config_path.write_text(
        "version: 1\nexport:\n  png:\n    scale: 2.0\n",
        encoding="utf-8",
    )
    render_config_path = tmp_path / "render.yaml"
    render_config_path.write_text(
        "version: 1\nexport:\n  png:\n    scale: 3.5\n",
        encoding="utf-8",
    )
    observed_sizes: list[tuple[int, int]] = []

    def fake_rasterize(
        _svg_path: Path,
        png_path: Path,
        *,
        output_size: tuple[int, int],
        **_kwargs: object,
    ) -> Path:
        observed_sizes.append(output_size)
        Path(png_path).write_bytes(b"png")
        return Path(png_path)

    monkeypatch.setattr(capture_module, "rasterize_svg_to_png", fake_rasterize)
    set_config_path(caller_config_path)
    caller_config = runtime_config()
    try:
        frame = render(
            lambda _t: (),
            options=RenderOptions(canvas_size=(10, 8)),
            config_path=render_config_path,
        )
        assert runtime_config() is caller_config

        result = export(frame, tmp_path / "closed-session.png")
        direct = CaptureService().export(
            frame,
            tmp_path / "closed-session-direct.png",
        )

        assert result.format is ExportFormat.PNG
        assert observed_sizes == [(35, 28), (35, 28)]
        assert direct.path.read_bytes() == b"png"
        assert result.manifest_path is not None
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["config"]["effective"]["png_scale"] == 3.5
        assert manifest["output"]["size"] == {"width": 35, "height": 28}
    finally:
        set_config_path(None)


def test_export_rejects_unsupported_suffix_before_creating_parent(
    frame: Frame,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "missing"

    with pytest.raises(ValueError, match="suffix"):
        export(frame, parent / "drawing.jpg")

    assert not parent.exists()


def test_public_export_validates_frame_before_path_suffix(tmp_path: Path) -> None:
    parent = tmp_path / "missing"

    with pytest.raises(TypeError, match="frame は Frame"):
        export(object(), parent / "drawing.jpg")  # type: ignore[arg-type]

    assert not parent.exists()


def test_per_layer_mode_keeps_existing_layer_naming(frame: Frame, tmp_path: Path) -> None:
    service = CaptureService()
    staged = service.encode(
        frame,
        tmp_path / "drawing.gcode",
        mode=CaptureMode.GCODE_LAYERS,
    )

    assert staged == (tmp_path / "drawing_layer001.gcode",)
