# どこで: `src/grafix/core/parameters/style_resolver.py`。
# 何を: ParamStore の style エントリから、そのフレームの背景色/線色/線幅を確定する。
# なぜ: interactive と headless export で同一規則を共有するため。

from __future__ import annotations

from dataclasses import dataclass

from grafix.core.value_validation import finite_real, rgb01_tuple

from .store import ParamStore
from .style_ops import ensure_style_entries
from .style import (
    coerce_rgb255,
    rgb01_to_rgb255,
    rgb255_to_rgb01,
    style_key,
)


@dataclass(frozen=True, slots=True)
class FrameStyle:
    """1 フレーム分の style 解決結果。"""

    bg_color_rgb01: tuple[float, float, float]
    global_line_color_rgb01: tuple[float, float, float]
    global_thickness: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bg_color_rgb01",
            rgb01_tuple(self.bg_color_rgb01, name="bg_color_rgb01"),
        )
        object.__setattr__(
            self,
            "global_line_color_rgb01",
            rgb01_tuple(
                self.global_line_color_rgb01,
                name="global_line_color_rgb01",
            ),
        )
        object.__setattr__(
            self,
            "global_thickness",
            finite_real(
                self.global_thickness,
                name="global_thickness",
                minimum=0.0,
                minimum_inclusive=False,
            ),
        )


class StyleResolver:
    """ParamStore の style キーから、そのフレームの style を解決する。"""

    def __init__(
        self,
        store: ParamStore,
        *,
        base_background_color_rgb01: tuple[float, float, float],
        base_global_thickness: float,
        base_global_line_color_rgb01: tuple[float, float, float],
    ) -> None:
        if not isinstance(store, ParamStore):
            raise TypeError("store は ParamStore である必要があります")
        background = rgb01_tuple(
            base_background_color_rgb01,
            name="base_background_color_rgb01",
        )
        line_color = rgb01_tuple(
            base_global_line_color_rgb01,
            name="base_global_line_color_rgb01",
        )
        thickness = finite_real(
            base_global_thickness,
            name="base_global_thickness",
            minimum=0.0,
            minimum_inclusive=False,
        )
        ensure_style_entries(
            store,
            background_color_rgb01=background,
            global_thickness=thickness,
            global_line_color_rgb01=line_color,
        )

        self._store = store
        self._key_background = style_key("background_color")
        self._key_thickness = style_key("global_thickness")
        self._key_line_color = style_key("global_line_color")

        self._base_background_rgb255 = rgb01_to_rgb255(background)
        self._base_thickness = thickness
        self._base_line_color_rgb255 = rgb01_to_rgb255(line_color)

    def resolve(self) -> FrameStyle:
        """そのフレームで使う style を返す。"""

        bg_state = self._store.get_state(self._key_background)
        bg255 = (
            self._base_background_rgb255
            if bg_state is None or not bg_state.override
            else coerce_rgb255(bg_state.ui_value)
        )

        line_state = self._store.get_state(self._key_line_color)
        line255 = (
            self._base_line_color_rgb255
            if line_state is None or not line_state.override
            else coerce_rgb255(line_state.ui_value)
        )

        thickness_state = self._store.get_state(self._key_thickness)
        thickness = (
            self._base_thickness
            if thickness_state is None or not thickness_state.override
            else finite_real(
                thickness_state.ui_value,
                name="global_thickness",
                minimum=0.0,
                minimum_inclusive=False,
            )
        )

        return FrameStyle(
            bg_color_rgb01=rgb255_to_rgb01(bg255),
            global_line_color_rgb01=rgb255_to_rgb01(line255),
            global_thickness=thickness,
        )


__all__ = ["FrameStyle", "StyleResolver"]
