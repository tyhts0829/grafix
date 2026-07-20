from __future__ import annotations

import pytest

from grafix.core.parameters.view import ParameterRow
from grafix.core.parameters.source import ValueSource
from grafix.interactive.parameter_gui.rules import RowUiRules, ui_rules_for_row
from grafix.interactive.parameter_gui.table import (
    PARAMETER_TABLE_MIDI_COLUMN_WIDTH_PX,
    PARAMETER_TABLE_RANGE_COLUMN_WIDTH_PX,
    PARAMETER_TABLE_SOURCE_COLUMN_WIDTH_PX,
    SOURCE_SELECTOR_TOTAL_WIDTH_PX,
    _render_cc_cell,
    _render_label_cell,
    _setup_parameter_table_columns,
    _source_segment_style,
    _source_selector_tooltip,
    _snippet_popup_geometry,
)


class LayoutImGui:
    """右端 cell の responsive 配置だけを観測する小さい test double。"""

    COLOR_BUTTON = 0
    COLOR_BUTTON_HOVERED = 1
    COLOR_BUTTON_ACTIVE = 2
    COLOR_TEXT = 3

    def __init__(self, *, cell_width: float) -> None:
        self.cell_width = float(cell_width)
        self.same_line_calls: list[tuple[float, float]] = []
        self.buttons: list[tuple[str, float]] = []
        self.checkboxes: list[str] = []
        self.style_colors: list[tuple[int, tuple[float, ...]]] = []

    def table_set_column_index(self, index: int) -> None:
        assert index == 3

    def get_content_region_available_width(self) -> float:
        return self.cell_width

    def calc_text_size(self, text: str) -> tuple[float, float]:
        return (float(len(text) * 7), 12.0)

    def get_frame_height(self) -> float:
        return 20.0

    def same_line(self, position: float, spacing: float) -> None:
        self.same_line_calls.append((float(position), float(spacing)))

    def button(self, label: str, width: float) -> bool:
        self.buttons.append((str(label), float(width)))
        return False

    def checkbox(self, label: str, value: bool) -> tuple[bool, bool]:
        self.checkboxes.append(str(label))
        return False, bool(value)

    def push_style_color(self, index: int, *color: float) -> None:
        self.style_colors.append((int(index), tuple(float(value) for value in color)))

    def pop_style_color(self, _count: int) -> None:
        return None

    def is_item_hovered(self) -> bool:
        return False

    def is_item_focused(self) -> bool:
        return False

    def set_tooltip(self, _text: str) -> None:
        return None


class ColumnSetupImGui:
    TABLE_COLUMN_WIDTH_FIXED = 1
    TABLE_COLUMN_WIDTH_STRETCH = 2
    TABLE_COLUMN_NO_RESIZE = 4

    def __init__(self, *, text_height: float) -> None:
        self.text_height = float(text_height)
        self.columns: list[tuple[str, int, float]] = []

    def calc_text_size(self, _text: str) -> tuple[float, float]:
        return 28.0, self.text_height

    def table_setup_column(self, label: str, flags: int, width: float) -> None:
        self.columns.append((str(label), int(flags), float(width)))


class _Popup:
    def __init__(self, *, opened: bool) -> None:
        self.opened = bool(opened)

    def __enter__(self) -> _Popup:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class SourceLayoutImGui:
    SELECTABLE_DISABLED = 8
    COLOR_BUTTON = 0
    COLOR_BUTTON_HOVERED = 1
    COLOR_BUTTON_ACTIVE = 2
    COLOR_TEXT = 3
    STYLE_FRAME_PADDING = 4

    def __init__(
        self,
        *,
        clicked_ids: set[str] | None = None,
        click_reset: bool = False,
        cell_width: float = 500.0,
        text_height: float = 14.0,
    ) -> None:
        self.clicked_ids = set(clicked_ids or set())
        self.click_reset = bool(click_reset)
        self.cell_width = cell_width
        self.text_height = float(text_height)
        self.popup_open = False
        self.same_line_calls: list[tuple[float, float]] = []
        self.texts: list[str] = []
        self.buttons: list[tuple[str, float]] = []
        self.selectables: list[tuple[str, bool, int, float, float]] = []

    def table_set_column_index(self, index: int) -> None:
        assert index == 0

    def get_content_region_available_width(self) -> float:
        return self.cell_width

    def calc_text_size(self, text: str) -> tuple[float, float]:
        scale = self.text_height / 14.0
        return float(len(text) * 7) * scale, self.text_height

    def text(self, value: str) -> None:
        self.texts.append(str(value))

    def same_line(self, position: float, spacing: float) -> None:
        self.same_line_calls.append((float(position), float(spacing)))

    def button(self, label: str, width: float) -> bool:
        self.buttons.append((str(label), float(width)))
        widget_id = str(label).split("##", 1)[-1]
        return widget_id in self.clicked_ids

    def push_style_color(self, *_args: object) -> None:
        return None

    def pop_style_color(self, _count: int = 1) -> None:
        return None

    def get_style(self) -> object:
        return type("_Style", (), {"frame_padding": (4.0, 3.0)})()

    def push_style_var(self, *_args: object) -> None:
        return None

    def pop_style_var(self, _count: int = 1) -> None:
        return None

    def is_item_hovered(self) -> bool:
        return False

    def is_item_focused(self) -> bool:
        return False

    def set_tooltip(self, _text: str) -> None:
        return None

    def open_popup(self, _label: str) -> None:
        self.popup_open = True

    def begin_popup(self, _label: str) -> _Popup:
        return _Popup(opened=self.popup_open)

    def menu_item(
        self,
        _label: str,
        _shortcut: str | None,
        selected: bool,
        enabled: bool,
    ) -> tuple[bool, bool]:
        return bool(self.click_reset and enabled), bool(selected)

    def close_current_popup(self) -> None:
        self.popup_open = False

    def text_disabled(self, _text: str) -> None:
        return None

    def separator(self) -> None:
        return None

    def selectable(
        self,
        label: str,
        selected: bool,
        flags: int,
        width: float,
        height: float,
    ) -> tuple[bool, bool]:
        self.selectables.append((str(label), bool(selected), int(flags), float(width), float(height)))
        return False, bool(selected)


class _Viewport:
    def __init__(self, *, x: float, y: float, width: float, height: float) -> None:
        self.work_pos = (float(x), float(y))
        self.work_size = (float(width), float(height))


class ViewportImGui:
    def __init__(self, *, x: float, y: float, width: float, height: float) -> None:
        self.viewport = _Viewport(x=x, y=y, width=width, height=height)

    def get_main_viewport(self) -> _Viewport:
        return self.viewport


def _row(
    *,
    kind: str,
    cc_key: int | tuple[int | None, int | None, int | None] | None,
) -> ParameterRow:
    return ParameterRow(
        label="1:value",
        op="op",
        site_id="file.py:1:2",
        arg="value",
        kind=kind,
        ui_value=(0.0, 0.0, 0.0) if kind == "vec3" else 0.0,
        ui_min=0.0,
        ui_max=1.0,
        choices=None,
        cc_key=cc_key,
        override=True,
        ordinal=1,
    )


def _render(
    imgui: LayoutImGui,
    row: ParameterRow,
    *,
    last_source: ValueSource | None = None,
) -> None:
    changed, cc_key = _render_cc_cell(
        imgui,
        row=row,
        rules=ui_rules_for_row(row),
        cc_key=row.cc_key,
        width_spacer=4,
        midi_learn_state=None,
        midi_last_cc_change=None,
        last_source=last_source,
    )
    assert changed is False
    assert cc_key == row.cc_key


def test_scalar_midi_is_the_only_control_in_the_right_cell() -> None:
    imgui = LayoutImGui(cell_width=120.0)
    _render(imgui, _row(kind="float", cc_key=12))

    assert len(imgui.buttons) == 1
    assert imgui.buttons[0][0].startswith("V12##")
    assert imgui.buttons[0][1] == imgui.cell_width
    assert imgui.checkboxes == []
    assert imgui.same_line_calls == []


def test_scalar_midi_does_not_reserve_space_for_a_removed_override_checkbox() -> None:
    imgui = LayoutImGui(cell_width=200.0)
    _render(imgui, _row(kind="float", cc_key=12))

    assert imgui.same_line_calls == []
    assert imgui.checkboxes == []


def test_vec3_midi_controls_use_readable_compact_labels_in_a_narrow_cell() -> None:
    imgui = LayoutImGui(cell_width=130.0)
    _render(imgui, _row(kind="vec3", cc_key=(10, 11, 12)))

    assert [label.split("##", 1)[0] for label, _width in imgui.buttons] == [
        "X=",
        "Y=",
        "Z=",
    ]
    assert all(width <= imgui.cell_width for _label, width in imgui.buttons)
    assert imgui.same_line_calls == [(0.0, 4.0), (0.0, 4.0)]


def test_vec3_midi_controls_stay_on_one_row_at_very_narrow_width() -> None:
    imgui = LayoutImGui(cell_width=90.0)
    _render(imgui, _row(kind="vec3", cc_key=(10, 11, 12)))

    assert imgui.same_line_calls == [(0.0, 4.0), (0.0, 4.0)]
    assert all(width <= (90.0 - 8.0) / 3.0 for _label, width in imgui.buttons)


def test_current_midi_input_uses_an_amber_live_chip_with_text() -> None:
    imgui = LayoutImGui(cell_width=120.0)
    _render(imgui, _row(kind="float", cc_key=12), last_source="midi_live")

    assert imgui.buttons[0][0].startswith("V12 LIVE##")
    assert len(imgui.style_colors) == 4


def test_saved_midi_input_is_labeled_frozen_instead_of_live() -> None:
    imgui = LayoutImGui(cell_width=160.0)
    _render(
        imgui,
        _row(kind="float", cc_key=12),
        last_source="midi_frozen",
    )

    assert imgui.buttons[0][0].startswith("V12 FROZEN##")
    assert len(imgui.style_colors) == 4


def test_unassigned_midi_controls_use_one_consistent_component_series() -> None:
    scalar = LayoutImGui(cell_width=165.0)
    _render(scalar, _row(kind="float", cc_key=None))
    assert scalar.buttons == [("V##cc_learn", 165.0)]

    vector = LayoutImGui(cell_width=165.0)
    _render(vector, _row(kind="vec3", cc_key=None))
    assert [label.split("##", 1)[0] for label, _width in vector.buttons] == [
        "X",
        "Y",
        "Z",
    ]
    widths = [width for _label, width in vector.buttons]
    assert widths[0] == pytest.approx(widths[1])
    assert widths[1] == pytest.approx(widths[2])

    rgb = LayoutImGui(cell_width=165.0)
    rgb_row = _row(kind="rgb", cc_key=None)
    changed, cc_key = _render_cc_cell(
        rgb,
        row=rgb_row,
        rules=RowUiRules(minmax="none", cc_key="int3", show_override=True),
        cc_key=rgb_row.cc_key,
        width_spacer=4,
        midi_learn_state=None,
        midi_last_cc_change=None,
    )
    assert (changed, cc_key) == (False, None)
    assert [label.split("##", 1)[0] for label, _width in rgb.buttons] == [
        "R",
        "G",
        "B",
    ]


def _actual_parameter_table_cell_widths(window_width: float) -> tuple[float, ...]:
    imgui = pytest.importorskip("imgui")
    context = imgui.create_context()
    try:
        io = imgui.get_io()
        io.display_size = (float(window_width), 500.0)
        io.fonts.get_tex_data_as_rgba32()
        imgui.new_frame()
        imgui.set_next_window_position(0.0, 0.0)
        imgui.set_next_window_size(float(window_width), 500.0)
        imgui.begin(
            "Column width test",
            flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE,
        )
        table = imgui.begin_table(
            "##column_widths",
            4,
            imgui.TABLE_SIZING_FIXED_FIT,
        )
        assert table.opened
        _setup_parameter_table_columns(imgui)
        imgui.table_next_row()
        widths: list[float] = []
        for index in range(4):
            imgui.table_set_column_index(index)
            widths.append(float(imgui.get_content_region_available_width()))
        imgui.end_table()
        imgui.end()
        imgui.render()
        return tuple(widths)
    finally:
        imgui.destroy_context(context)


def test_only_value_column_receives_additional_window_width() -> None:
    narrow = _actual_parameter_table_cell_widths(1100.0)
    wide = _actual_parameter_table_cell_widths(1400.0)

    assert narrow[0] == pytest.approx(PARAMETER_TABLE_SOURCE_COLUMN_WIDTH_PX)
    assert narrow[2] == pytest.approx(PARAMETER_TABLE_RANGE_COLUMN_WIDTH_PX)
    assert narrow[3] == pytest.approx(PARAMETER_TABLE_MIDI_COLUMN_WIDTH_PX)
    assert wide[0] == pytest.approx(narrow[0])
    assert wide[2] == pytest.approx(narrow[2])
    assert wide[3] == pytest.approx(narrow[3])
    assert wide[1] - narrow[1] == pytest.approx(300.0)


def test_fixed_columns_follow_metric_scale_and_cannot_be_resized() -> None:
    imgui = ColumnSetupImGui(text_height=28.0)
    _setup_parameter_table_columns(imgui)

    fixed_flags = imgui.TABLE_COLUMN_WIDTH_FIXED | imgui.TABLE_COLUMN_NO_RESIZE
    assert imgui.columns == [
        ("  Source / Parameter", fixed_flags, 500.0),
        ("  Value", imgui.TABLE_COLUMN_WIDTH_STRETCH, 1.0),
        ("  Range", fixed_flags, 260.0),
        ("  MIDI", fixed_flags, 330.0),
    ]


def test_fixed_columns_accept_explicit_workspace_scale_below_one() -> None:
    imgui = ColumnSetupImGui(text_height=14.0)
    _setup_parameter_table_columns(imgui, metric_scale=0.75)

    fixed_flags = imgui.TABLE_COLUMN_WIDTH_FIXED | imgui.TABLE_COLUMN_NO_RESIZE
    assert imgui.columns == [
        ("  Source / Parameter", fixed_flags, 187.5),
        ("  Value", imgui.TABLE_COLUMN_WIDTH_STRETCH, 1.0),
        ("  Range", fixed_flags, 97.5),
        ("  MIDI", fixed_flags, 123.75),
    ]


def test_source_segments_switch_only_override_and_keep_midi_mapping() -> None:
    imgui = SourceLayoutImGui(clicked_ids={"source_code"})

    changed, override, reset = _render_label_cell(
        imgui,
        row_label="Site density",
        kind="float",
        override=True,
        cc_key=12,
        last_source="midi_live",
    )

    assert (changed, override, reset) == (True, False, False)
    assert [label for label, _width in imgui.buttons] == [
        "CODE##source_code",
        "UI##source_ui",
        "v##source_actions",
    ]
    assert SOURCE_SELECTOR_TOTAL_WIDTH_PX == 80.0
    assert imgui.same_line_calls == [(0.0, 1.0), (0.0, 1.0), (0.0, 6.0)]
    assert imgui.texts == ["Site density"]


def test_clicking_the_active_source_is_a_noop() -> None:
    imgui = SourceLayoutImGui(clicked_ids={"source_code"})

    changed, override, reset = _render_label_cell(
        imgui,
        row_label="Site density",
        kind="float",
        override=False,
        cc_key=12,
    )

    assert (changed, override, reset) == (False, False, False)


def test_source_selector_shortens_to_c_u_at_minimum_width_on_retina() -> None:
    # logical 120px 相当の cell が Retina backing座標では240px。font metricも
    # 2倍なので同じ breakpoint と52 logical pxのselectorになる。
    imgui = SourceLayoutImGui(cell_width=240.0, text_height=28.0)

    _changed, _override, _reset = _render_label_cell(
        imgui,
        row_label="Site density",
        kind="float",
        override=False,
        cc_key=None,
    )

    assert [label for label, _width in imgui.buttons] == [
        "C##source_code",
        "U##source_ui",
        "v##source_actions",
    ]
    assert [width for _label, width in imgui.buttons] == [36.0, 36.0, 28.0]


def test_visible_source_menu_keeps_explicit_reset_to_code_reachable() -> None:
    imgui = SourceLayoutImGui(clicked_ids={"source_actions"}, click_reset=True)

    changed, override, reset = _render_label_cell(
        imgui,
        row_label="Site density",
        kind="float",
        override=True,
        cc_key=12,
    )

    assert (changed, override, reset) == (False, True, True)
    assert imgui.popup_open is False


def test_bool_uses_the_same_code_ui_selector_as_other_parameters() -> None:
    imgui = SourceLayoutImGui()

    changed, override, reset = _render_label_cell(
        imgui,
        row_label="Visible",
        kind="bool",
        override=False,
        cc_key=None,
    )

    assert (changed, override, reset) == (False, False, False)
    assert [label for label, _width in imgui.buttons] == [
        "CODE##source_code",
        "UI##source_ui",
        "v##source_actions",
    ]
    assert imgui.selectables == []
    assert imgui.texts == ["Visible"]


def test_midi_mapping_tooltip_explains_that_source_is_a_fallback() -> None:
    tooltip = _source_selector_tooltip(
        source="UI",
        kind="vec3",
        cc_key=(10, None, 12),
        last_source="midi_live",
    )

    assert "X:CC 10" in tooltip
    assert "Z:CC 12" in tooltip
    assert "UI is the fallback" in tooltip
    assert "keeps the MIDI mapping" in tooltip

    frozen_tooltip = _source_selector_tooltip(
        source="CODE",
        kind="float",
        cc_key=10,
        last_source="midi_frozen",
    )
    assert "frozen saved MIDI value" in frozen_tooltip


def test_active_source_segment_has_a_distinct_filled_style() -> None:
    active_button, _active_hover, _active_pressed, active_text = _source_segment_style(
        "UI", active=True
    )
    inactive_button, _inactive_hover, _inactive_pressed, inactive_text = _source_segment_style(
        "UI", active=False
    )

    assert active_button != inactive_button
    assert active_text != inactive_text


def test_code_popup_keeps_margin_inside_600px_viewport() -> None:
    imgui = ViewportImGui(x=0.0, y=0.0, width=600.0, height=900.0)

    center_x, center_y, width, height = _snippet_popup_geometry(imgui)

    assert (center_x, center_y) == (300.0, 450.0)
    assert (width, height) == (552.0, 720.0)
    assert center_x - width / 2.0 == 24.0
    assert center_x + width / 2.0 == 576.0


def test_code_popup_retains_preferred_size_in_large_viewport() -> None:
    imgui = ViewportImGui(x=100.0, y=50.0, width=1600.0, height=1200.0)

    center_x, center_y, width, height = _snippet_popup_geometry(imgui)

    assert (center_x, center_y) == (900.0, 650.0)
    assert (width, height) == (960.0, 720.0)
