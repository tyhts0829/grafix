"""interactive previewとfinal outputで共有する評価品質context。"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from typing import Literal

PreviewQuality = Literal["draft", "final"]

_preview_quality_var: contextvars.ContextVar[PreviewQuality] = contextvars.ContextVar(
    "preview_quality",
    default="final",
)


def current_preview_quality() -> PreviewQuality:
    """現在evaluationの品質を返す。context外のheadless処理はfinal。"""

    return _preview_quality_var.get()


@contextlib.contextmanager
def preview_quality_context(quality: PreviewQuality) -> Iterator[None]:
    """evaluation中だけdraft/final品質を設定し、終了時に復元する。"""

    if quality not in {"draft", "final"}:
        raise ValueError(f"unknown preview quality: {quality!r}")
    token = _preview_quality_var.set(quality)
    try:
        yield
    finally:
        _preview_quality_var.reset(token)


__all__ = [
    "PreviewQuality",
    "current_preview_quality",
    "preview_quality_context",
]
