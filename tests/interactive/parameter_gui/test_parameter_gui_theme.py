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
        assert style.window_padding == (14.0, 10.0)
        assert style.frame_padding == (7.0, 4.0)
        assert style.cell_padding == (7.0, 3.0)
        assert style.child_rounding == 3.0
        assert style.frame_rounding == 2.0
        assert style.popup_rounding == 4.0
        assert style.scrollbar_rounding == 3.0
        assert style.grab_rounding == 2.0
        assert style.tab_rounding == 2.0
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
        assert style.window_padding == (21.0, 15.0)
        assert style.frame_padding == (10.5, 6.0)
        assert style.cell_padding == (10.5, 4.5)
        assert style.scrollbar_size == 16.5
        assert style.grab_min_size == 16.5
    finally:
        imgui.destroy_context(context)
