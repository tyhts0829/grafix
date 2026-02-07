from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageOps


def create_contact_sheet(
    image_paths: Sequence[Path],
    out_path: Path,
    *,
    columns: int = 3,
    cell_size: int = 512,
    padding: int = 20,
    label_height: int = 24,
    bg_color: tuple[int, int, int] = (244, 244, 244),
) -> Path:
    paths = [Path(path) for path in image_paths if Path(path).exists()]
    if not paths:
        raise ValueError("no valid image paths")

    cols = max(1, int(columns))
    cell = max(64, int(cell_size))
    pad = max(0, int(padding))
    label = max(0, int(label_height))

    rows = (len(paths) + cols - 1) // cols
    tile_h = cell + label
    width = cols * cell + (cols + 1) * pad
    height = rows * tile_h + (rows + 1) * pad

    canvas = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(canvas)

    for index, path in enumerate(paths):
        row = index // cols
        col = index % cols
        x = pad + col * (cell + pad)
        y = pad + row * (tile_h + pad)

        with Image.open(path) as image:
            preview = ImageOps.contain(image.convert("RGB"), (cell, cell))

        px = x + (cell - preview.width) // 2
        py = y + (cell - preview.height) // 2
        canvas.paste(preview, (px, py))
        draw.text((x, y + cell + 4), path.name, fill=(32, 32, 32))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build contact sheet from images.")
    parser.add_argument("images", nargs="+", help="input image paths")
    parser.add_argument("--out", required=True, help="output png path")
    parser.add_argument("--columns", type=int, default=3, help="columns")
    parser.add_argument("--cell-size", type=int, default=512, help="cell size")
    parser.add_argument("--padding", type=int, default=20, help="padding")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    create_contact_sheet(
        [Path(path) for path in args.images],
        Path(args.out),
        columns=args.columns,
        cell_size=args.cell_size,
        padding=args.padding,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
