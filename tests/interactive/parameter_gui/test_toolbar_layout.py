from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.core.parameters import ParamStore
from grafix.interactive.parameter_gui.gui import (
    ParameterGUI,
    _window_ui_coordinate_scale,
    compute_bottom_drawer_geometry,
    compute_toolbar_layout,
    compute_transport_toolbar_geometry,
)


def test_standard_toolbar_prioritizes_controls_over_read_only_status() -> None:
    layout = compute_toolbar_layout(768.0)

    assert layout.stacked is False
    assert layout.gap == 12.0
    assert layout.controls_width + layout.gap + layout.status_width == pytest.approx(768.0)
    assert layout.controls_width / 768.0 == pytest.approx(0.684, abs=0.01)
    assert layout.status_width / 768.0 == pytest.approx(0.30, abs=0.01)


def test_standard_time_row_has_at_least_160px_timeline_without_clip() -> None:
    layout = compute_toolbar_layout(768.0)
    geometry = compute_transport_toolbar_geometry(layout.controls_width)

    assert geometry.timeline_width >= 160.0
    assert geometry.fits is True
    assert geometry.required_width <= layout.controls_width


def test_retina_backing_coordinates_preserve_logical_ratio_and_timeline() -> None:
    layout = compute_toolbar_layout(1_536.0, coordinate_scale=2.0)
    geometry = compute_transport_toolbar_geometry(
        layout.controls_width,
        coordinate_scale=2.0,
    )

    assert layout.stacked is False
    assert layout.gap == 24.0
    assert layout.status_width / 2.0 == pytest.approx(230.4)
    assert layout.controls_width / 2.0 == pytest.approx(525.6)
    assert geometry.timeline_width / 2.0 >= 160.0
    assert geometry.fits is True


def test_toolbar_does_not_use_fixed_half_width_on_wide_content() -> None:
    layout = compute_toolbar_layout(1_200.0)

    assert layout.stacked is False
    assert layout.status_width == 300.0
    assert layout.controls_width > layout.status_width


@pytest.mark.parametrize("width", [0.0, 560.0, 759.9])
def test_narrow_toolbar_stacks_full_width_compact_status(width: float) -> None:
    layout = compute_toolbar_layout(width)

    assert layout.stacked is True
    assert layout.controls_width == max(0.0, width)
    assert layout.status_width == max(0.0, width)
    assert layout.gap == 6.0
    assert layout.surface_height == 56.0


def test_breakpoint_switches_to_two_columns_at_760() -> None:
    assert compute_toolbar_layout(759.9).stacked is True
    layout = compute_toolbar_layout(760.0)
    geometry = compute_transport_toolbar_geometry(layout.controls_width)
    assert layout.stacked is False
    assert geometry.timeline_width >= 160.0
    assert geometry.fits is True


def test_horizontal_resize_does_not_change_ui_coordinate_scale() -> None:
    window = SimpleNamespace(width=1_600, scale=2.0)

    before = _window_ui_coordinate_scale(window)
    window.width = 2_400
    after = _window_ui_coordinate_scale(window)

    assert before == 2.0
    assert after == 2.0
    assert compute_toolbar_layout(1_536.0, coordinate_scale=before).surface_height == 132.0
    assert compute_toolbar_layout(2_336.0, coordinate_scale=after).surface_height == 132.0


def test_bottom_drawer_height_is_fixed_while_only_pane_widths_grow() -> None:
    narrow = compute_bottom_drawer_geometry(768.0, coordinate_scale=2.0)
    wide = compute_bottom_drawer_geometry(1_200.0, coordinate_scale=2.0)

    assert narrow.height == wide.height == 352.0
    assert narrow.gap == wide.gap == 20.0
    assert wide.help_width > narrow.help_width
    assert wide.runtime_width > narrow.runtime_width


def test_toolbar_and_drawer_allow_workspace_ui_scale_below_one() -> None:
    toolbar = compute_toolbar_layout(900.0, coordinate_scale=0.75)
    drawer = compute_bottom_drawer_geometry(900.0, coordinate_scale=0.75)

    assert toolbar.surface_height == 49.5
    assert drawer.height == 132.0
    assert drawer.gap == 7.5


def test_real_pyimgui_can_render_toolbar_children_and_closed_midi_popup(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    imgui = pytest.importorskip("imgui")
    gui = cast(Any, initialized_parameter_gui)
    context = gui._context
    imgui.set_current_context(context)
    try:
        io = imgui.get_io()
        io.display_size = (800.0, 1000.0)
        io.delta_time = 1.0 / 60.0
        io.fonts.get_tex_data_as_rgba32()
        imgui.new_frame()
        imgui.begin("toolbar smoke")

        gui._imgui = imgui
        gui._transport = None
        gui._history = None
        gui._snapshot_slots = None
        gui._midi_session = None
        gui._store = ParamStore()
        gui._show_inactive_params = False
        gui._midi_learn_state = SimpleNamespace(active_target=None, active_component=None)

        assert gui._render_toolbar_area(content_width=768.0, monitor_snapshot=None) is False
        assert gui._render_parameter_table_toolbar() is False

        imgui.end()
        imgui.render()
        assert imgui.get_draw_data() is not None
    finally:
        imgui.set_current_context(context)
