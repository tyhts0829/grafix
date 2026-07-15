from __future__ import annotations

from grafix.core.parameters.view import ParameterRow
from grafix.interactive.parameter_gui.rules import ui_rules_for_row
from grafix.interactive.parameter_gui.table import (
    _render_cc_cell,
    _render_label_cell,
    _snippet_popup_geometry,
)


class LayoutImGui:
    """右端 cell の responsive 配置だけを観測する小さい test double。"""

    def __init__(self, *, cell_width: float) -> None:
        self.cell_width = float(cell_width)
        self.same_line_calls: list[tuple[float, float]] = []
        self.buttons: list[tuple[str, float]] = []
        self.checkboxes: list[str] = []

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


class LabelLayoutImGui:
    def __init__(self, *, cell_width: float) -> None:
        self.cell_width = float(cell_width)
        self.same_line_count = 0
        self.texts: list[str] = []
        self.buttons: list[str] = []

    def table_set_column_index(self, index: int) -> None:
        assert index == 0

    def get_content_region_available_width(self) -> float:
        return self.cell_width

    def calc_text_size(self, text: str) -> tuple[float, float]:
        return float(len(text) * 7), 12.0

    def text(self, value: str) -> None:
        self.texts.append(str(value))

    def same_line(self) -> None:
        self.same_line_count += 1

    def button(self, label: str) -> bool:
        self.buttons.append(str(label))
        return False


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


def _render(imgui: LayoutImGui, row: ParameterRow) -> None:
    changed, cc_key, override = _render_cc_cell(
        imgui,
        row=row,
        rules=ui_rules_for_row(row),
        cc_key=row.cc_key,
        override=row.override,
        cc_key_width=30,
        width_spacer=4,
        midi_learn_state=None,
        midi_last_cc_change=None,
    )
    assert changed is False
    assert cc_key == row.cc_key
    assert override is row.override


def test_scalar_midi_and_use_ui_stack_when_right_cell_is_narrow() -> None:
    imgui = LayoutImGui(cell_width=120.0)
    _render(imgui, _row(kind="float", cc_key=12))

    assert len(imgui.buttons) == 1
    assert imgui.buttons[0][0].startswith("MIDI 12 ×##")
    assert imgui.buttons[0][1] <= imgui.cell_width
    assert imgui.checkboxes == ["Use UI##override"]
    assert imgui.same_line_calls == []


def test_scalar_midi_and_use_ui_stay_inline_when_they_fit() -> None:
    imgui = LayoutImGui(cell_width=200.0)
    _render(imgui, _row(kind="float", cc_key=12))

    assert imgui.same_line_calls == [(0.0, 4.0)]


def test_vec3_midi_controls_wrap_without_exceeding_narrow_cell() -> None:
    imgui = LayoutImGui(cell_width=130.0)
    _render(imgui, _row(kind="vec3", cc_key=(10, 11, 12)))

    assert [label.split("##", 1)[0] for label, _width in imgui.buttons] == [
        "X 10 ×",
        "Y 11 ×",
        "Z 12 ×",
    ]
    assert all(width <= imgui.cell_width for _label, width in imgui.buttons)
    # X/Y と Z/Use UI の 2 段。旧実装のように 4 control を 1 行へ溢れさせない。
    assert imgui.same_line_calls == [(0.0, 4.0), (0.0, 4.0)]


def test_vec3_midi_controls_fully_stack_at_very_narrow_width() -> None:
    imgui = LayoutImGui(cell_width=90.0)
    _render(imgui, _row(kind="vec3", cc_key=(10, 11, 12)))

    assert imgui.same_line_calls == []


def test_long_parameter_label_stacks_to_code_in_narrow_cell() -> None:
    imgui = LabelLayoutImGui(cell_width=180.0)

    clicked = _render_label_cell(
        imgui,
        row_label="partition#1 site_density_base",
        source_badge="UI",
        show_reset_to_code=True,
    )

    assert clicked is False
    assert imgui.texts == ["[UI] partition#1 site_density_base"]
    assert imgui.buttons == ["Code##reset_to_code"]
    assert imgui.same_line_count == 0


def test_parameter_label_keeps_to_code_inline_when_both_fit() -> None:
    imgui = LabelLayoutImGui(cell_width=400.0)

    _render_label_cell(
        imgui,
        row_label="partition#1 site_density_base",
        source_badge="UI",
        show_reset_to_code=True,
    )

    assert imgui.same_line_count == 1


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
