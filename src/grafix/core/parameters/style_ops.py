# どこで: `src/grafix/core/parameters/style_ops.py`。
# 何を: ParamStore の Style エントリ（__style__/__global__）を作成する手続きを提供する。
# なぜ: 更新経路を ops に固定し、snapshot の純粋性（副作用なし）を保つため。

from __future__ import annotations

from typing import Any

from .meta import ParamMeta
from .store import ParamStore
from .style import (
    STYLE_BACKGROUND_COLOR,
    STYLE_GLOBAL_LINE_COLOR,
    STYLE_GLOBAL_THICKNESS,
    rgb01_to_rgb255,
    style_key,
)


def ensure_style_entries(
    store: ParamStore,
    *,
    background_color_rgb01: tuple[float, float, float],
    global_thickness: float,
    global_line_color_rgb01: tuple[float, float, float],
) -> None:
    """Style 行を ParamStore に作成し、meta/state を初期化する。"""

    bg255 = rgb01_to_rgb255(background_color_rgb01)
    line255 = rgb01_to_rgb255(global_line_color_rgb01)
    thickness = float(global_thickness)

    # RGB は 0..255 int を正とする（GUI は COLOR_EDIT_UINT8 前提）。
    items: list[tuple[str, Any, ParamMeta]] = [
        (
            STYLE_BACKGROUND_COLOR,
            bg255,
            ParamMeta(
                kind="rgb",
                ui_min=0,
                ui_max=255,
                description="キャンバス全体の背景色を RGB で指定する。",
            ),
        ),
        (
            STYLE_GLOBAL_THICKNESS,
            thickness,
            ParamMeta(
                kind="float",
                ui_min=1e-6,
                ui_max=0.01,
                description="個別指定がない線に適用する既定の線幅を指定する。",
            ),
        ),
        (
            STYLE_GLOBAL_LINE_COLOR,
            line255,
            ParamMeta(
                kind="rgb",
                ui_min=0,
                ui_max=255,
                description="個別指定がない線に適用する既定色を RGB で指定する。",
            ),
        ),
    ]

    ordinals = store._ordinals_ref()
    for arg, base_value, meta in items:
        key = style_key(arg)
        store._set_meta(key, meta)
        store._ensure_state(key, base_value=base_value, initial_override=True)
        ordinals.get_or_assign(key.op, key.site_id)


__all__ = ["ensure_style_entries"]
