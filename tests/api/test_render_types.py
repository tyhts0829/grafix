from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from grafix import (
    Color,
    ExportFormat,
    ExportResult,
    Frame,
    RenderOptions,
    RenderSession,
    export,
    render,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#09f", (0.0, 0.6, 1.0)),
        ("#FF0080", (1.0, 0.0, 128.0 / 255.0)),
        ("Rebecca Purple", (102.0 / 255.0, 51.0 / 255.0, 153.0 / 255.0)),
        ((255, 0, 128), (1.0, 0.0, 128.0 / 255.0)),
        ((1.0, 0.25, 0.0), (1.0, 0.25, 0.0)),
    ],
)
def test_color_normalizes_supported_inputs(value: object, expected: tuple[float, ...]) -> None:
    assert Color(value).rgb01 == pytest.approx(expected)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        "#12",
        "not-a-color",
        (256, 0, 0),
        (-1, 0, 0),
        (1.1, 0.0, 0.0),
        (float("nan"), 0.0, 0.0),
        (True, 0, 0),
        (0, 0),
    ],
)
def test_color_rejects_ambiguous_or_out_of_range_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        Color(value)  # type: ignore[arg-type]


def test_render_options_normalizes_colors_and_uses_single_thickness_default() -> None:
    options = RenderOptions(
        canvas_size=(120, 80),
        background_color="#fff",
        line_color=(255, 0, 0),
    )

    assert options.background_color.rgb01 == (1.0, 1.0, 1.0)
    assert options.line_color.rgb01 == (1.0, 0.0, 0.0)
    assert options.line_thickness == pytest.approx(0.001)


@pytest.mark.parametrize("thickness", [0.0, -0.1, float("inf"), float("nan")])
def test_render_options_rejects_invalid_thickness(thickness: float) -> None:
    with pytest.raises(ValueError, match="line_thickness"):
        RenderOptions(line_thickness=thickness)


def test_render_options_and_result_are_immutable() -> None:
    options = RenderOptions()
    result = ExportResult(path=Path("art.svg"), format=ExportFormat.SVG)

    with pytest.raises(FrozenInstanceError):
        options.line_thickness = 0.5  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.path = Path("other.svg")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("drawing.svg", ExportFormat.SVG),
        ("drawing.PNG", ExportFormat.PNG),
        ("drawing.gcode", ExportFormat.GCODE),
    ],
)
def test_export_format_is_inferred_from_suffix(path: str, expected: ExportFormat) -> None:
    assert ExportFormat.from_path(path) is expected


def test_export_format_rejects_suffix_mismatch() -> None:
    with pytest.raises(ValueError, match="一致しません"):
        ExportFormat.resolve("drawing.svg", ExportFormat.PNG)
    with pytest.raises(ValueError, match="一致しません"):
        ExportResult(path=Path("drawing.svg"), format=ExportFormat.PNG)


def test_new_render_api_is_exported_from_root() -> None:
    assert Color.__module__ == "grafix.api.render"
    assert Frame.__module__ == "grafix.api.render"
    assert RenderOptions.__module__ == "grafix.api.render"
    assert RenderSession.__module__ == "grafix.api.render"
    assert render.__module__ == "grafix.api.render"
    assert export.__module__ == "grafix.api.export"


def test_side_effect_export_constructor_is_not_public() -> None:
    import grafix
    import grafix.api

    assert not hasattr(grafix, "Export")
    assert not hasattr(grafix.api, "Export")
