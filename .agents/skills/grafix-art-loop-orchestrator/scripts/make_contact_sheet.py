#!/usr/bin/env python3
"""Art loop の contact sheet を生成する補助 CLI。

仕様:
- `iter` モード: `iter_XX/vYY/out.png` を収集して `iter_XX/contact_sheet.png` を生成
- `final` モード: `run_dir/iter_XX/contact_sheet.png` を収集して
  `run_summary/final_contact_sheet_8k.png` を生成
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError as exc:
    raise SystemExit("error: Pillow is required (`pip install pillow`).") from exc

TARGET_LONG_EDGE = 7690
OUTER_PADDING = 40
GRID_GAP = 24
LABEL_HEIGHT = 44
BG_COLOR = (246, 244, 239)
LABEL_COLOR = (32, 32, 32)


@dataclass(frozen=True)
class TileSource:
    label: str
    path: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate contact sheet images for grafix art loop.")
    parser.add_argument("--mode", choices=("iter", "final"), required=True)
    parser.add_argument("--iter-dir", type=Path, help="Path to iter_XX directory.")
    parser.add_argument("--run-dir", type=Path, help="Path to run_<...> directory.")
    parser.add_argument("--out", type=Path, help="Output png path. If omitted, mode-specific default is used.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print ordered inputs and output path without generating images.",
    )
    return parser.parse_args()


def _numeric_sort_key(text: str, pattern: re.Pattern[str]) -> int | None:
    matched = pattern.match(text)
    if not matched:
        return None
    return int(matched.group(1))


def collect_iter_sources(iter_dir: Path) -> list[TileSource]:
    if not iter_dir.is_dir():
        raise ValueError(f"iter directory not found: {iter_dir}")
    variant_pattern = re.compile(r"^v(\d+)$")
    collected: list[tuple[int, TileSource]] = []
    for path in iter_dir.glob("v*/out.png"):
        num = _numeric_sort_key(path.parent.name, variant_pattern)
        if num is None:
            continue
        collected.append((num, TileSource(label=path.parent.name, path=path)))
    collected.sort(key=lambda item: item[0])
    return [item[1] for item in collected]


def collect_final_sources(run_dir: Path) -> list[TileSource]:
    if not run_dir.is_dir():
        raise ValueError(f"run directory not found: {run_dir}")
    iter_pattern = re.compile(r"^iter_(\d+)$")
    collected: list[tuple[int, TileSource]] = []
    for path in run_dir.glob("iter_*/contact_sheet.png"):
        num = _numeric_sort_key(path.parent.name, iter_pattern)
        if num is None:
            continue
        collected.append((num, TileSource(label=path.parent.name, path=path)))
    collected.sort(key=lambda item: item[0])
    return [item[1] for item in collected]


def choose_grid(n_tiles: int) -> tuple[int, int]:
    if n_tiles <= 0:
        raise ValueError("n_tiles must be positive")

    target_ratio = 16 / 9
    best_cols = 1
    best_rows = n_tiles
    best_score = float("inf")
    for cols in range(1, n_tiles + 1):
        rows = math.ceil(n_tiles / cols)
        empty = (cols * rows) - n_tiles
        ratio = cols / rows
        score = (empty * 3.0) + abs(math.log(max(ratio, 1e-9) / target_ratio))
        if score < best_score:
            best_score = score
            best_cols = cols
            best_rows = rows
    return best_cols, best_rows


def _fitted_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    scale = min(max_width / width, max_height / height)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return new_w, new_h


def render_sheet(sources: list[TileSource]) -> Image.Image:
    if not sources:
        raise ValueError("no input png found")

    sizes: list[tuple[int, int]] = []
    for src in sources:
        with Image.open(src.path) as image:
            sizes.append((image.width, image.height))
    cell_width = max(width for width, _ in sizes)
    cell_height = max(height for _, height in sizes)

    cols, rows = choose_grid(len(sources))
    tile_height = LABEL_HEIGHT + cell_height
    canvas_width = (OUTER_PADDING * 2) + (cols * cell_width) + ((cols - 1) * GRID_GAP)
    canvas_height = (OUTER_PADDING * 2) + (rows * tile_height) + ((rows - 1) * GRID_GAP)

    canvas = Image.new("RGB", (canvas_width, canvas_height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for idx, src in enumerate(sources):
        row = idx // cols
        col = idx % cols
        base_x = OUTER_PADDING + col * (cell_width + GRID_GAP)
        base_y = OUTER_PADDING + row * (tile_height + GRID_GAP)

        draw.text((base_x + 8, base_y + 10), src.label, fill=LABEL_COLOR, font=font)

        with Image.open(src.path) as loaded:
            rgba = loaded.convert("RGBA")
            new_w, new_h = _fitted_size(rgba.width, rgba.height, cell_width, cell_height)
            resized = rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
        paste_x = base_x + ((cell_width - new_w) // 2)
        paste_y = base_y + LABEL_HEIGHT + ((cell_height - new_h) // 2)
        canvas.paste(resized, (paste_x, paste_y), resized)

    return canvas


def ensure_long_edge(image: Image.Image, min_long_edge: int) -> Image.Image:
    width, height = image.size
    long_edge = max(width, height)
    if long_edge >= min_long_edge:
        return image
    scale = min_long_edge / long_edge
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def default_output(mode: str, iter_dir: Path | None, run_dir: Path | None) -> Path:
    if mode == "iter":
        if iter_dir is None:
            raise ValueError("--iter-dir is required in iter mode")
        return iter_dir / "contact_sheet.png"
    if run_dir is None:
        raise ValueError("--run-dir is required in final mode")
    return run_dir / "run_summary" / "final_contact_sheet_8k.png"


def validate_mode_args(args: argparse.Namespace) -> None:
    if args.mode == "iter" and args.iter_dir is None:
        raise ValueError("--iter-dir is required for --mode iter")
    if args.mode == "final" and args.run_dir is None:
        raise ValueError("--run-dir is required for --mode final")


def main() -> int:
    args = _parse_args()
    try:
        validate_mode_args(args)
        if args.mode == "iter":
            sources = collect_iter_sources(args.iter_dir)
        else:
            sources = collect_final_sources(args.run_dir)

        if not sources:
            raise ValueError(f"no input png found for mode={args.mode}")

        out_path = args.out if args.out is not None else default_output(args.mode, args.iter_dir, args.run_dir)
        print(f"mode={args.mode} sources={len(sources)} out={out_path}")
        for idx, src in enumerate(sources, start=1):
            print(f"{idx:02d} {src.label} {src.path}")

        if args.dry_run:
            return 0

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet = render_sheet(sources)
        if args.mode == "final":
            sheet = ensure_long_edge(sheet, TARGET_LONG_EDGE)
        sheet.save(out_path)
        print(f"saved={out_path} size={sheet.width}x{sheet.height}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
