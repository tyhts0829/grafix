from __future__ import annotations

import pytest

from grafix.interactive.runtime.window_layout import (
    WindowPairLayout,
    WindowRect,
    layout_window_pair,
)


def _assert_inside(rect: WindowRect, bounds: WindowRect) -> None:
    assert rect.x >= bounds.x
    assert rect.y >= bounds.y
    assert rect.right <= bounds.right
    assert rect.bottom <= bounds.bottom


def _assert_non_overlapping(layout: WindowPairLayout) -> None:
    preview = layout.preview
    gui = layout.parameter_gui
    assert (
        preview.right <= gui.x
        or gui.right <= preview.x
        or preview.bottom <= gui.y
        or gui.bottom <= preview.y
    )


def test_layout_keeps_natural_sizes_when_side_by_side_fits() -> None:
    bounds = WindowRect(0, 0, 2200, 1200)

    layout = layout_window_pair(
        preview_size=(900, 900),
        parameter_gui_size=(800, 1000),
        usable_bounds=bounds,
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert layout.orientation == "side_by_side"
    assert (layout.preview.width, layout.preview.height) == (900, 900)
    assert (layout.parameter_gui.width, layout.parameter_gui.height) == (800, 1000)
    assert layout.parameter_gui.x - layout.preview.right == 16
    _assert_inside(layout.preview, bounds)
    _assert_inside(layout.parameter_gui, bounds)
    _assert_non_overlapping(layout)


def test_layout_shrinks_both_windows_on_1440_by_900_screen() -> None:
    # menu bar / Dock を除いた 1440x875 の usable bounds を想定する。
    bounds = WindowRect(0, 25, 1440, 875)

    layout = layout_window_pair(
        preview_size=(900, 900),
        parameter_gui_size=(800, 1000),
        usable_bounds=bounds,
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert layout.orientation == "side_by_side"
    assert 480 <= layout.preview.width < 900
    assert layout.preview.width == layout.preview.height
    assert 560 <= layout.parameter_gui.width < 800
    assert layout.parameter_gui.height < 1000
    assert layout.parameter_gui.x - layout.preview.right == 16
    _assert_inside(layout.preview, bounds)
    _assert_inside(layout.parameter_gui, bounds)
    _assert_non_overlapping(layout)


def test_layout_falls_back_to_stacked_on_narrow_tall_screen() -> None:
    bounds = WindowRect(0, 0, 900, 1400)

    layout = layout_window_pair(
        preview_size=(900, 900),
        parameter_gui_size=(800, 1000),
        usable_bounds=bounds,
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert layout.orientation == "stacked"
    assert layout.parameter_gui.y - layout.preview.bottom == 16
    _assert_inside(layout.preview, bounds)
    _assert_inside(layout.parameter_gui, bounds)
    _assert_non_overlapping(layout)


def test_layout_compresses_below_recommended_minimum_only_when_unavoidable() -> None:
    bounds = WindowRect(0, 0, 800, 600)

    layout = layout_window_pair(
        preview_size=(900, 900),
        parameter_gui_size=(800, 1000),
        usable_bounds=bounds,
    )

    assert layout.orientation == "stacked"
    assert layout.preview.height < 480
    assert layout.parameter_gui.height < 560
    _assert_inside(layout.preview, bounds)
    _assert_inside(layout.parameter_gui, bounds)
    _assert_non_overlapping(layout)


def test_layout_clamps_out_of_range_preferences_in_offset_bounds() -> None:
    bounds = WindowRect(-1920, 50, 1920, 1080)

    layout = layout_window_pair(
        preview_size=(900, 900),
        parameter_gui_size=(800, 1000),
        usable_bounds=bounds,
        preferred_preview_position=(5000, -100),
        preferred_parameter_gui_position=(5000, -100),
    )

    _assert_inside(layout.preview, bounds)
    _assert_inside(layout.parameter_gui, bounds)
    _assert_non_overlapping(layout)


def test_layout_does_not_enlarge_small_natural_windows() -> None:
    layout = layout_window_pair(
        preview_size=(300, 200),
        parameter_gui_size=(500, 400),
        usable_bounds=WindowRect(0, 0, 1920, 1080),
    )

    assert (layout.preview.width, layout.preview.height) == (300, 200)
    assert (layout.parameter_gui.width, layout.parameter_gui.height) == (500, 400)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"preview_size": (0, 900)}, "preview_size"),
        ({"parameter_gui_size": (800, -1)}, "parameter_gui_size"),
        ({"usable_bounds": WindowRect(0, 0, 1, 900)}, "usable_bounds"),
        ({"gap": -1}, "gap"),
        ({"margin": -1}, "margin"),
    ],
)
def test_layout_rejects_invalid_inputs(
    kwargs: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "preview_size": (900, 900),
        "parameter_gui_size": (800, 1000),
        "usable_bounds": WindowRect(0, 0, 1440, 900),
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError, match=message):
        layout_window_pair(**arguments)  # type: ignore[arg-type]
