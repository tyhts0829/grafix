import pytest

from grafix.interactive.parameter_gui.theme import (
    PARAMETER_GUI_PALETTE,
    apply_parameter_gui_theme,
    contrast_ratio,
)


def test_palette_is_valid_and_keeps_normal_text_readable() -> None:
    assert all(
        0.0 <= component <= 1.0 for color in PARAMETER_GUI_PALETTE.values() for component in color
    )
    background = PARAMETER_GUI_PALETTE["background"]
    assert contrast_ratio(PARAMETER_GUI_PALETTE["text"], background) >= 7.0
    assert contrast_ratio(PARAMETER_GUI_PALETTE["text_muted"], background) >= 4.5


def test_theme_uses_logical_spacing_and_neutral_buttons() -> None:
    imgui = pytest.importorskip("imgui")
    context = imgui.create_context()
    try:
        apply_parameter_gui_theme(imgui)
        style = imgui.get_style()
        assert style.window_padding == (16.0, 12.0)
        assert style.frame_padding == (8.0, 6.0)
        assert style.cell_padding == (8.0, 5.0)
        assert style.frame_rounding == 4.0
        assert tuple(style.colors[imgui.COLOR_BUTTON]) == pytest.approx(
            PARAMETER_GUI_PALETTE["surface_raised"]
        )
        assert tuple(style.colors[imgui.COLOR_SLIDER_GRAB]) == pytest.approx(
            PARAMETER_GUI_PALETTE["accent"]
        )
    finally:
        imgui.destroy_context(context)


def test_theme_scales_spacing_and_minimum_targets_with_ui_scale() -> None:
    imgui = pytest.importorskip("imgui")
    context = imgui.create_context()
    try:
        apply_parameter_gui_theme(imgui, ui_scale=1.5)
        style = imgui.get_style()
        assert style.window_padding == (24.0, 18.0)
        assert style.frame_padding == (12.0, 9.0)
        assert style.cell_padding == (12.0, 7.5)
        assert style.scrollbar_size == 18.0
        assert style.grab_min_size == 18.0
    finally:
        imgui.destroy_context(context)
