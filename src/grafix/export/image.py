"""
どこで: `src/grafix/export/image.py`。
何を: SVG を中間表現として外部ラスタライザ（resvg）で PNG に変換する関数を提供する。
なぜ: ベクター描画と同じ形状を、指定解像度の PNG として安全に保存するため。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from grafix.core.atomic_write import atomic_output_path
from grafix.core.output_paths import output_path_for_draw
from grafix.core.runtime_config import runtime_config
from grafix.core.pipeline import RealizedLayer
from grafix.core.parameters.style import rgb01_to_rgb255
from grafix.export.svg import export_svg

_DEFAULT_RESVG_TIMEOUT_S = 30.0


def export_image(
    layers: Sequence[RealizedLayer],
    path: str | Path,
    *,
    canvas_size: tuple[int, int] | None = None,
    background_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> Path:
    """Layer 列を画像として保存する。

    Notes
    -----
    PNG は private な一時 SVG を resvg でラスタライズして生成する。明示的な SVG
    出力だけが指定パスへ SVG を保存する。
    """
    _path = Path(path)
    suffix = _path.suffix.lower()

    if suffix == ".svg":
        if canvas_size is None:
            raise ValueError("canvas_size=None は未対応（現在は必須）")
        return export_svg(layers, _path, canvas_size=canvas_size)

    if suffix == ".png":
        if canvas_size is None:
            raise ValueError("canvas_size=None は未対応（現在は必須）")
        with TemporaryDirectory(prefix="grafix-png-") as temp_dir:
            svg_path = Path(temp_dir) / "source.svg"
            export_svg(layers, svg_path, canvas_size=canvas_size)
            return rasterize_svg_to_png(
                svg_path,
                _path,
                output_size=png_output_size(canvas_size),
                background_color_rgb01=background_color,
            )

    raise ValueError(f"未対応の画像フォーマット: {suffix!r}")


def default_png_output_path(
    draw: Callable[[float], object],
    *,
    run_id: str | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> Path:
    """draw の定義元に基づく PNG の既定保存パスを返す。

    Notes
    -----
    パスは `output/{kind}/` 配下で sketch_dir のサブディレクトリ構造をミラーする。
    """

    base = output_path_for_draw(kind="png", ext="png", draw=draw, run_id=None)
    run_suffix = ""
    if run_id is not None:
        with_run_id = output_path_for_draw(kind="png", ext="png", draw=draw, run_id=run_id)
        if with_run_id.stem.startswith(base.stem):
            run_suffix = with_run_id.stem[len(base.stem) :]

    size_suffix = ""
    if canvas_size is not None:
        out_w, out_h = png_output_size(canvas_size)
        size_suffix = f"_{int(out_w)}x{int(out_h)}"

    return base.with_name(f"{base.stem}{size_suffix}{run_suffix}{base.suffix}")


def png_output_size(
    canvas_size: tuple[int, int],
    *,
    scale: float | None = None,
) -> tuple[int, int]:
    """canvas_size と明示 scale から PNG 出力ピクセルサイズを返す。

    ``scale=None`` の従来入口だけが process runtime config を参照する。Frame や
    interactive session は、開始時に固定した effective scale を明示して再探索を避ける。
    """

    canvas_w, canvas_h = canvas_size
    if int(canvas_w) <= 0 or int(canvas_h) <= 0:
        raise ValueError("canvas_size は正の (width, height) である必要がある")
    effective_scale = float(runtime_config().png_scale if scale is None else scale)
    if not isfinite(effective_scale) or effective_scale <= 0.0:
        raise ValueError("scale は正の有限値である必要があります")
    return (
        int(int(canvas_w) * effective_scale),
        int(int(canvas_h) * effective_scale),
    )


def _rgb01_to_hex(rgb01: tuple[float, float, float]) -> str:
    r, g, b = rgb01_to_rgb255(rgb01)
    return f"#{r:02X}{g:02X}{b:02X}"


def _resvg_command(
    *,
    input_svg: Path,
    output_png: Path,
    output_size: tuple[int, int],
    background_color_rgb01: tuple[float, float, float],
) -> list[str]:
    out_w, out_h = output_size
    if int(out_w) <= 0 or int(out_h) <= 0:
        raise ValueError("output_size は正の (width, height) である必要がある")
    return [
        "resvg",
        "--width",
        str(int(out_w)),
        "--height",
        str(int(out_h)),
        "--background",
        _rgb01_to_hex(background_color_rgb01),
        str(input_svg),
        str(output_png),
    ]


def rasterize_svg_to_png(
    svg_path: str | Path,
    png_path: str | Path,
    *,
    output_size: tuple[int, int],
    background_color_rgb01: tuple[float, float, float] = (1.0, 1.0, 1.0),
    timeout_s: float = _DEFAULT_RESVG_TIMEOUT_S,
) -> Path:
    """SVG を PNG として保存する。

    Parameters
    ----------
    svg_path : str or Path
        入力 SVG パス。
    png_path : str or Path
        出力 PNG パス。
    output_size : tuple[int, int]
        出力 PNG の (width, height) ピクセルサイズ。
    background_color_rgb01 : tuple[float, float, float]
        背景色 RGB（0..1）。既定は白。
    timeout_s : float
        resvg process の最大実行秒数。

    Returns
    -------
    Path
        出力 PNG パス（正規化済み）。

    Raises
    ------
    RuntimeError
        resvg が見つからない、またはラスタライズに失敗した場合。
    TimeoutError
        resvg が `timeout_s` 秒以内に終了しなかった場合。
    """

    _svg_path = Path(svg_path)
    _png_path = Path(png_path)
    timeout = float(timeout_s)
    if not isfinite(timeout) or timeout <= 0.0:
        raise ValueError("timeout_s は正である必要がある")
    _png_path.parent.mkdir(parents=True, exist_ok=True)

    with atomic_output_path(_png_path) as temp_png_path:
        cmd = _resvg_command(
            input_svg=_svg_path,
            output_png=temp_png_path,
            output_size=output_size,
            background_color_rgb01=background_color_rgb01,
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "resvg が見つかりません（`resvg` をインストールして PATH を通してください）"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"resvg が {timeout:g} 秒以内に終了しませんでした") from e

        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"resvg が失敗しました (code={proc.returncode}). {details}".strip()
            )

    return _png_path
