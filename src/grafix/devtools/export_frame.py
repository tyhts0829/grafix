"""
どこで: `src/grafix/devtools/export_frame.py`。
何を: `python -m grafix export ...` で `draw(t)` を headless で PNG に書き出す。
なぜ: 対話ウィンドウ無しで複数候補画像を生成し、比較→改良のループを回せるようにするため。
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafix.api import Export
from grafix.core.runtime_config import set_config_path
from grafix.export.image import default_png_output_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m grafix export")
    p.add_argument(
        "--callable",
        required=True,
        help="module:attr 形式（例: sketch.main:draw）",
    )
    p.add_argument(
        "--t",
        nargs="+",
        type=float,
        default=None,
        help="draw(t) に渡す時刻（複数指定可、既定: 0.0）",
    )
    p.add_argument(
        "--canvas",
        nargs=2,
        type=int,
        default=(800, 800),
        metavar=("W", "H"),
        help="canvas_size (width height)。既定: 800 800",
    )
    p.add_argument(
        "--out",
        default=None,
        help="出力 PNG パス（--t が 1 つのときのみ）",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="出力ディレクトリ（省略時: 既定の出力先）",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="既定出力パスの run_id（ファイル名 suffix）",
    )
    p.add_argument(
        "--config",
        default=None,
        help="config.yaml のパス（指定した場合は探索より優先）",
    )

    args = p.parse_args(argv)

    ts = [0.0] if args.t is None else list(args.t)
    if args.out is not None and args.out_dir is not None:
        p.error("--out と --out-dir は同時に指定できません")
    if args.out is not None and len(ts) != 1:
        p.error("--out は --t が 1 つのときだけ指定できます（複数枚は --out-dir を使ってください）")

    return args


def _resolve_callable(spec: str) -> Callable[[float], Any]:
    module_name, sep, attr_path = str(spec).partition(":")
    if not sep:
        raise ValueError("--callable は module:attr 形式で指定してください")
    if not module_name.strip() or not attr_path.strip():
        raise ValueError("--callable は module:attr 形式で指定してください")

    mod = importlib.import_module(module_name)
    out: Any = mod
    for part in attr_path.split("."):
        out = getattr(out, part)
    if not callable(out):
        raise TypeError(f"指定された callable が呼び出し可能ではありません: {spec!r}")
    return out


def _frame_output_paths(base_path: Path, *, n_frames: int) -> list[Path]:
    n = int(n_frames)
    if n <= 0:
        return []
    if n == 1:
        return [base_path]

    width = max(3, len(str(n)))
    return [
        base_path.with_name(f"{base_path.stem}_f{i:0{int(width)}d}{base_path.suffix}")
        for i in range(1, n + 1)
    ]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)

    config_path = args.config
    if config_path is not None:
        set_config_path(config_path)

    draw = _resolve_callable(args.callable)
    ts = [0.0] if args.t is None else [float(t) for t in args.t]
    canvas_w, canvas_h = args.canvas
    canvas_size = (int(canvas_w), int(canvas_h))

    out_path = None if args.out is None else Path(str(args.out))
    if out_path is not None:
        t0 = float(ts[0])
        Export(draw, t=t0, fmt="png", path=out_path, canvas_size=canvas_size)
        print(f"Saved PNG: {out_path} (t={t0})")
        return 0

    base_path = default_png_output_path(draw, run_id=args.run_id, canvas_size=canvas_size)
    out_dir = None if args.out_dir is None else Path(str(args.out_dir))
    if out_dir is not None:
        base_path = out_dir / base_path.name

    paths = _frame_output_paths(base_path, n_frames=len(ts))
    for t, path in zip(ts, paths, strict=True):
        Export(draw, t=float(t), fmt="png", path=path, canvas_size=canvas_size)
        print(f"Saved PNG: {path} (t={float(t)})")

    return 0


__all__ = ["main"]

