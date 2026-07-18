# どこで: `src/grafix/interactive/parameter_gui/theme.py`。
# 何を: Parameter GUI の余白・形・色を一つのテーマとして適用する。
# なぜ: ImGui の既定テーマ由来の強い青と高密度表示を避け、作品制作に集中できる階層を作るため。

from __future__ import annotations

import math
from typing import Any

RGBA = tuple[float, float, float, float]


def _rgba(hex_rgb: str, alpha: float = 1.0) -> RGBA:
    """``#RRGGBB`` を ImGui の 0..1 RGBA に変換する。"""

    value = str(hex_rgb).removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_rgb!r}")
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
        max(0.0, min(1.0, float(alpha))),
    )


# 青は常時塗りつぶす色ではなく、操作中・選択中を示す accent に限定する。
PARAMETER_GUI_PALETTE: dict[str, RGBA] = {
    "background": _rgba("#12151A"),
    "surface": _rgba("#171B21"),
    "surface_raised": _rgba("#1D222A"),
    "frame": _rgba("#222832"),
    "frame_hovered": _rgba("#2A3340"),
    "frame_active": _rgba("#303B4A"),
    "border": _rgba("#303845"),
    "text": _rgba("#F0F3F6"),
    "text_muted": _rgba("#A8B0BC"),
    "text_disabled": _rgba("#737D8A"),
    "accent": _rgba("#68A4FF"),
    "accent_hovered": _rgba("#84B6FF"),
    "accent_active": _rgba("#9AC3FF"),
    "success": _rgba("#69C58F"),
    "warning": _rgba("#E7B564"),
    "error": _rgba("#F07178"),
    "source_code": _rgba("#929CAA"),
    "source_ui": _rgba("#6DC9D8"),
    "source_midi": _rgba("#E7B564"),
    "row_alt": _rgba("#191D24"),
    "selection": _rgba("#68A4FF", 0.34),
    "modal_dim": _rgba("#080A0D", 0.72),
}


def source_badge_color(source: str) -> RGBA:
    """CODE / UI / MIDI badge の文字色を返す。"""

    key = {
        "CODE": "source_code",
        "UI": "source_ui",
        "MIDI": "source_midi",
    }.get(str(source).upper(), "source_code")
    return PARAMETER_GUI_PALETTE[key]


def _set_color(imgui: Any, color_index: int, token: str) -> None:
    imgui.get_style().colors[int(color_index)] = PARAMETER_GUI_PALETTE[token]


def apply_parameter_gui_theme(imgui: Any, *, ui_scale: float = 1.0) -> None:
    """現在の ImGui context に Grafix Inspector のテーマを適用する。

    ここで扱う寸法は logical px。Retina の backing scale はフォント atlas と
    framebuffer 側だけで処理し、style 寸法へ二重に掛けない。
    """

    scale = float(ui_scale)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("ui_scale は finite な正の値である必要がある")

    style = imgui.get_style()
    style.window_padding = (14.0 * scale, 10.0 * scale)
    style.frame_padding = (7.0 * scale, 4.0 * scale)
    style.item_spacing = (7.0 * scale, 4.0 * scale)
    style.item_inner_spacing = (5.0 * scale, 3.0 * scale)
    style.cell_padding = (7.0 * scale, 3.0 * scale)
    style.indent_spacing = 17.0 * scale
    style.scrollbar_size = 11.0 * scale
    style.grab_min_size = 11.0 * scale

    # 全面ウィンドウは角丸にせず、内側の surface と操作も小さい半径に留める。
    style.window_rounding = 0.0
    style.child_rounding = 3.0 * scale
    style.frame_rounding = 2.0 * scale
    style.popup_rounding = 4.0 * scale
    style.scrollbar_rounding = 3.0 * scale
    style.grab_rounding = 2.0 * scale
    style.tab_rounding = 2.0 * scale

    style.window_border_size = 0.0
    style.child_border_size = 0.0
    style.popup_border_size = 1.0 * scale
    style.frame_border_size = 0.0
    style.tab_border_size = 0.0

    color_tokens = {
        imgui.COLOR_TEXT: "text",
        imgui.COLOR_TEXT_DISABLED: "text_disabled",
        imgui.COLOR_WINDOW_BACKGROUND: "background",
        imgui.COLOR_CHILD_BACKGROUND: "background",
        imgui.COLOR_POPUP_BACKGROUND: "surface",
        imgui.COLOR_BORDER: "border",
        imgui.COLOR_BORDER_SHADOW: "background",
        imgui.COLOR_FRAME_BACKGROUND: "frame",
        imgui.COLOR_FRAME_BACKGROUND_HOVERED: "frame_hovered",
        imgui.COLOR_FRAME_BACKGROUND_ACTIVE: "frame_active",
        imgui.COLOR_TITLE_BACKGROUND: "surface",
        imgui.COLOR_TITLE_BACKGROUND_ACTIVE: "surface_raised",
        imgui.COLOR_TITLE_BACKGROUND_COLLAPSED: "surface",
        imgui.COLOR_MENUBAR_BACKGROUND: "surface",
        imgui.COLOR_SCROLLBAR_BACKGROUND: "background",
        imgui.COLOR_SCROLLBAR_GRAB: "border",
        imgui.COLOR_SCROLLBAR_GRAB_HOVERED: "frame_hovered",
        imgui.COLOR_SCROLLBAR_GRAB_ACTIVE: "frame_active",
        imgui.COLOR_CHECK_MARK: "accent",
        imgui.COLOR_SLIDER_GRAB: "accent",
        imgui.COLOR_SLIDER_GRAB_ACTIVE: "accent_active",
        imgui.COLOR_BUTTON: "surface_raised",
        imgui.COLOR_BUTTON_HOVERED: "frame_hovered",
        imgui.COLOR_BUTTON_ACTIVE: "frame_active",
        imgui.COLOR_HEADER: "surface_raised",
        imgui.COLOR_HEADER_HOVERED: "frame_hovered",
        imgui.COLOR_HEADER_ACTIVE: "frame_active",
        imgui.COLOR_SEPARATOR: "border",
        imgui.COLOR_SEPARATOR_HOVERED: "accent_hovered",
        imgui.COLOR_SEPARATOR_ACTIVE: "accent_active",
        imgui.COLOR_RESIZE_GRIP: "border",
        imgui.COLOR_RESIZE_GRIP_HOVERED: "accent_hovered",
        imgui.COLOR_RESIZE_GRIP_ACTIVE: "accent_active",
        imgui.COLOR_TAB: "surface",
        imgui.COLOR_TAB_HOVERED: "frame_hovered",
        imgui.COLOR_TAB_ACTIVE: "surface_raised",
        imgui.COLOR_TAB_UNFOCUSED: "surface",
        imgui.COLOR_TAB_UNFOCUSED_ACTIVE: "surface_raised",
        imgui.COLOR_PLOT_LINES: "accent",
        imgui.COLOR_PLOT_LINES_HOVERED: "accent_active",
        imgui.COLOR_PLOT_HISTOGRAM: "accent",
        imgui.COLOR_PLOT_HISTOGRAM_HOVERED: "accent_active",
        imgui.COLOR_TABLE_HEADER_BACKGROUND: "surface_raised",
        imgui.COLOR_TABLE_BORDER_STRONG: "border",
        imgui.COLOR_TABLE_BORDER_LIGHT: "border",
        imgui.COLOR_TABLE_ROW_BACKGROUND: "background",
        imgui.COLOR_TABLE_ROW_BACKGROUND_ALT: "row_alt",
        imgui.COLOR_TEXT_SELECTED_BACKGROUND: "selection",
        imgui.COLOR_DRAG_DROP_TARGET: "accent_active",
        imgui.COLOR_NAV_HIGHLIGHT: "accent_hovered",
        imgui.COLOR_NAV_WINDOWING_HIGHLIGHT: "accent_hovered",
        imgui.COLOR_NAV_WINDOWING_DIM_BACKGROUND: "modal_dim",
        imgui.COLOR_MODAL_WINDOW_DIM_BACKGROUND: "modal_dim",
    }
    for color_index, token in color_tokens.items():
        _set_color(imgui, int(color_index), token)


def relative_luminance(color: RGBA) -> float:
    """WCAG 2.x の相対輝度を返す（theme regression test 用）。"""

    def _linear(component: float) -> float:
        return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4

    red, green, blue, _alpha = color
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def contrast_ratio(foreground: RGBA, background: RGBA) -> float:
    """2色の WCAG contrast ratio を返す。"""

    lighter = max(relative_luminance(foreground), relative_luminance(background))
    darker = min(relative_luminance(foreground), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)
