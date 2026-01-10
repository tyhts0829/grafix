# どこで: `src/grafix/core/output_paths.py`。
# 何を: draw 定義元（例: sketch/）に基づき、出力ファイルの保存先パスを決める。
# なぜ: `output/{kind}/` 配下で、ユーザースクリプトのディレクトリ構造をミラーして整理するため。

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from pathlib import Path

from grafix.core.runtime_config import output_root_dir, runtime_config


def _sanitize_run_id(run_id: str) -> str:
    """run_id をファイル名の一部として使える形に正規化して返す。"""

    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(run_id))


def _run_id_suffix(run_id: str | None) -> str:
    """run_id の接尾辞（例: `_v1`）を返す。未指定なら空文字を返す。"""

    if run_id is None:
        return ""
    s = str(run_id).strip()
    if not s:
        return ""
    sanitized = _sanitize_run_id(s)
    if not sanitized:
        return ""
    return f"_{sanitized}"


def _fmt_canvas_dim_for_filename(value: float | int) -> str:
    """canvas の寸法をファイル名に埋め込むための短い表現にして返す。"""

    v = float(value)
    if v <= 0:
        raise ValueError("canvas_size は正の値である必要がある")
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))

    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _canvas_size_suffix(canvas_size: tuple[float | int, float | int] | None) -> str:
    """canvas_size の接尾辞（例: `_800x800`）を返す。未指定なら空文字を返す。"""

    if canvas_size is None:
        return ""
    w, h = canvas_size
    return f"_{_fmt_canvas_dim_for_filename(w)}x{_fmt_canvas_dim_for_filename(h)}"


def _is_pseudo_filename(text: str) -> bool:
    """`<stdin>` などの疑似ファイル名なら True を返す。"""

    s = str(text).strip()
    return bool(s) and s.startswith("<") and s.endswith(">")


def _draw_source_path(draw: Callable[[float], object]) -> Path | None:
    """draw の定義元ファイルパスを推定して返す。推定できなければ None を返す。"""

    code = getattr(draw, "__code__", None)
    filename = getattr(code, "co_filename", None) if code is not None else None
    if filename and not _is_pseudo_filename(str(filename)):
        return Path(str(filename))

    try:
        found = inspect.getsourcefile(draw) or inspect.getfile(draw)
    except Exception:
        found = None

    if found and not _is_pseudo_filename(str(found)):
        return Path(str(found))

    return None


def output_path_for_draw(
    *,
    kind: str,
    ext: str,
    draw: Callable[[float], object],
    run_id: str | None = None,
    canvas_size: tuple[float | int, float | int] | None = None,
) -> Path:
    """draw の定義元（sketch_dir）に基づき、出力ファイルの保存先パスを返す。

    Notes
    -----
    - `paths.sketch_dir` が設定され、かつ draw の定義元ファイルがその配下にある場合:
      `output_root/{kind}/<sketch 相対 dir>/<stem>[_WxH][_run_id].{ext}`
    - それ以外の場合（フォールバック）:
      `output_root/{kind}/misc/<stem>[_WxH][_run_id].{ext}`
    - `canvas_size` が指定されている場合は `_800x800` のような接尾辞をファイル名へ付与する。
    """

    ext_norm = str(ext).lstrip(".").strip()
    if not ext_norm:
        raise ValueError("ext は空でない必要がある")

    cfg = runtime_config()
    base_dir = output_root_dir() / str(kind)
    suffix = _run_id_suffix(run_id)

    source_path = _draw_source_path(draw)
    stem = source_path.stem if source_path is not None else "unknown"

    rel_parent: Path | None = None
    sketch_dir = cfg.sketch_dir
    if sketch_dir is not None and source_path is not None:
        try:
            rel = source_path.resolve(strict=False).relative_to(
                Path(sketch_dir).resolve(strict=False)
            )
            rel_parent = rel.parent
            stem = rel.stem or stem
        except Exception:
            rel_parent = None

    filename = f"{stem}{_canvas_size_suffix(canvas_size)}{suffix}.{ext_norm}"
    if rel_parent is None:
        return base_dir / "misc" / filename
    if rel_parent == Path("."):
        return base_dir / filename
    return base_dir / rel_parent / filename


__all__ = ["output_path_for_draw"]
