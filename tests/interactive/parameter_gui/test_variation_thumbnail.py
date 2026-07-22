from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from grafix.interactive.parameter_gui.variation_thumbnail import (
    draw_variation_thumbnail_status,
    variation_thumbnail_output_path,
    variation_thumbnail_size,
)


def test_variation_thumbnail_path_size_and_missing_status(tmp_path: Path) -> None:
    base = tmp_path / "sketch_800x400.png"
    assert variation_thumbnail_output_path(base, "  A/B candidate  ") == (
        tmp_path / "sketch_800x400_A_B_candidate.png"
    )
    assert variation_thumbnail_size((800, 400)) == (320, 160)

    messages: list[str] = []
    imgui = SimpleNamespace(text_disabled=messages.append)
    missing = tmp_path / "missing.png"
    draw_variation_thumbnail_status(imgui, missing)
    missing.write_bytes(b"png")
    draw_variation_thumbnail_status(imgui, missing)

    assert messages == [
        f"Thumbnail unavailable (missing): {missing}",
        "Thumbnail: missing.png",
    ]
