from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grafix.export import image
from grafix.core.runtime_config import runtime_config, set_config_path


# `grafix.export.image`（SVG→PNG / resvg）をテストする。


@pytest.fixture(autouse=True)
def _reset_runtime_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_config_path(None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    set_config_path(None)
    yield
    set_config_path(None)


def test_default_png_output_path_uses_data_dir_and_script_stem():
    def draw(t: float) -> None:
        return None

    path = image.default_png_output_path(draw)
    assert path.parts[0] == "data"
    assert path.parts[1] == "output"
    assert path.parts[2] == "png"
    assert path.name == f"{Path(__file__).stem}.png"
    assert path.suffix == ".png"


def test_default_png_output_path_includes_output_size_when_given():
    def draw(t: float) -> None:
        return None

    path = image.default_png_output_path(draw, canvas_size=(800, 600))
    assert path.name == f"{Path(__file__).stem}_6400x4800.png"


def test_png_output_size_scales_canvas_by_png_scale():
    scale = float(runtime_config().png_scale)
    expected = (int(300 * scale), int(300 * scale))
    assert image.png_output_size((300, 300)) == expected


def test_export_image_png_uses_private_temporary_svg_without_touching_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_png = tmp_path / "art.png"
    sibling_svg = out_png.with_suffix(".svg")
    sibling_svg.write_text("existing artwork\n", encoding="utf-8")
    observed_svg_path: Path | None = None

    def fake_rasterize(
        svg_path,
        png_path,
        *,
        output_size,
        background_color_rgb01,
    ) -> Path:
        nonlocal observed_svg_path
        observed_svg_path = Path(svg_path)
        assert observed_svg_path != sibling_svg
        assert observed_svg_path.parent != out_png.parent
        assert observed_svg_path.read_text(encoding="utf-8").startswith("<?xml")
        assert Path(png_path) == out_png
        assert output_size == image.png_output_size((20, 10))
        assert background_color_rgb01 == (0.1, 0.2, 0.3)
        return out_png

    monkeypatch.setattr(image, "rasterize_svg_to_png", fake_rasterize)

    result = image.export_image(
        [],
        out_png,
        canvas_size=(20, 10),
        background_color=(0.1, 0.2, 0.3),
    )

    assert result == out_png
    assert sibling_svg.read_text(encoding="utf-8") == "existing artwork\n"
    assert observed_svg_path is not None
    assert not observed_svg_path.exists()
    assert not observed_svg_path.parent.exists()


def test_export_image_png_cleans_up_temporary_svg_after_rasterizer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_png = tmp_path / "art.png"
    observed_svg_path: Path | None = None

    def fail_rasterize(svg_path, png_path, **kwargs) -> Path:
        nonlocal observed_svg_path
        observed_svg_path = Path(svg_path)
        assert observed_svg_path.exists()
        raise RuntimeError("rasterizer failed")

    monkeypatch.setattr(image, "rasterize_svg_to_png", fail_rasterize)

    with pytest.raises(RuntimeError, match="rasterizer failed"):
        image.export_image([], out_png, canvas_size=(20, 10))

    assert observed_svg_path is not None
    assert not observed_svg_path.exists()
    assert not observed_svg_path.parent.exists()


def test_export_image_svg_still_exports_directly_to_requested_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_svg = tmp_path / "art.svg"
    observed: tuple[object, Path, tuple[int, int]] | None = None

    def fake_export_svg(layers, path, *, canvas_size) -> Path:
        nonlocal observed
        observed = (layers, Path(path), canvas_size)
        return Path(path)

    monkeypatch.setattr(image, "export_svg", fake_export_svg)

    layers: list[object] = []
    result = image.export_image(layers, out_svg, canvas_size=(20, 10))

    assert result == out_svg
    assert observed == (layers, out_svg, (20, 10))


def test_rasterize_svg_to_png_invokes_resvg_with_resized_svg(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    src_svg = tmp_path / "in.svg"
    src_svg.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="300" height="300">',
                '  <path d="M 0 0 L 1 1" fill="none" stroke="#000000" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" />',
                "</svg>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_png = tmp_path / "out.png"

    def fake_run(cmd, *, capture_output: bool, text: bool, check: bool, timeout: float):
        assert capture_output is True
        assert text is True
        assert check is False
        assert timeout == 30.0
        assert cmd[0] == "resvg"

        assert "--width" in cmd
        assert cmd[cmd.index("--width") + 1] == "1200"
        assert "--height" in cmd
        assert cmd[cmd.index("--height") + 1] == "1200"
        assert "--background" in cmd
        assert cmd[cmd.index("--background") + 1] == "#FFFFFF"

        temp_svg = Path(cmd[-2])
        assert temp_svg == src_svg
        temp_png = Path(cmd[-1])
        assert temp_png != out_png
        assert temp_png.parent == out_png.parent
        assert temp_png.suffix == ".png"
        temp_png.write_bytes(b"png")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(image.subprocess, "run", fake_run)

    path = image.rasterize_svg_to_png(src_svg, out_png, output_size=(1200, 1200))
    assert path == out_png
    assert out_png.read_bytes() == b"png"


def test_rasterize_svg_to_png_raises_when_resvg_is_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    src_svg = tmp_path / "in.svg"
    src_svg.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">',
                "</svg>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_png = tmp_path / "out.png"

    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(image.subprocess, "run", missing)

    with pytest.raises(RuntimeError, match="resvg が見つかりません"):
        image.rasterize_svg_to_png(src_svg, out_png, output_size=(10, 10))


def test_rasterize_svg_to_png_times_out_resvg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_svg = tmp_path / "in.svg"
    src_svg.write_text("<svg></svg>\n", encoding="utf-8")
    out_png = tmp_path / "out.png"
    out_png.write_bytes(b"original")

    def timeout_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(image.subprocess, "run", timeout_run)

    with pytest.raises(TimeoutError, match="0.25 秒以内"):
        image.rasterize_svg_to_png(
            src_svg,
            out_png,
            output_size=(10, 10),
            timeout_s=0.25,
        )

    assert out_png.read_bytes() == b"original"
    assert list(tmp_path.glob(".out.*.tmp.png")) == []
