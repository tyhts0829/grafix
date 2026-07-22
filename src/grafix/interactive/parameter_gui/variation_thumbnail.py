"""variation thumbnail の保存 policy と GUI callback を組み立てる。"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafix.export.capture import CaptureFrame, CaptureService

from .variation_panel import (
    VariationThumbnailCapture,
    VariationThumbnailPreview,
    make_capture_service_thumbnail_capture,
)


def variation_thumbnail_output_path(base_path: Path, name: str) -> Path:
    """variation 名を安全な path component にした PNG 保存先を返す。"""

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name).strip()).strip("._")
    if not safe_name:
        safe_name = "variation"
    safe_name = safe_name[:64].rstrip("._") or "variation"
    return base_path.with_name(f"{base_path.stem}_{safe_name}{base_path.suffix}")


def variation_thumbnail_size(canvas_size: tuple[int, int]) -> tuple[int, int]:
    """canvas 比率を保つ長辺 320 px の thumbnail 寸法を返す。"""

    width, height = int(canvas_size[0]), int(canvas_size[1])
    scale = 320.0 / float(max(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def draw_variation_thumbnail_status(imgui: Any, path: Path) -> None:
    """texture backend がなくても thumbnail の有無を表示する。"""

    thumbnail_path = Path(path)
    if thumbnail_path.is_file():
        imgui.text_disabled(f"Thumbnail: {thumbnail_path.name}")
    else:
        imgui.text_disabled(f"Thumbnail unavailable (missing): {thumbnail_path}")


def variation_thumbnail_callbacks(
    capture_service: CaptureService,
    *,
    frame_provider: Callable[[], CaptureFrame | None],
    base_path: Path,
    canvas_size: tuple[int, int],
) -> tuple[VariationThumbnailCapture, VariationThumbnailPreview]:
    """capture service から GUI が使う thumbnail callback 一式を作る。"""

    capture = make_capture_service_thumbnail_capture(
        capture_service,
        frame_provider=frame_provider,
        output_path_for_name=lambda name: variation_thumbnail_output_path(
            base_path,
            name,
        ),
        output_size=variation_thumbnail_size(canvas_size),
    )
    return capture, draw_variation_thumbnail_status


__all__ = [
    "draw_variation_thumbnail_status",
    "variation_thumbnail_callbacks",
    "variation_thumbnail_output_path",
    "variation_thumbnail_size",
]
