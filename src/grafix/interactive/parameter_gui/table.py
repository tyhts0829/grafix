# どこで: `src/grafix/interactive/parameter_gui/table.py`。
# 何を: ParameterRow を 4 列テーブルとして描画し、更新後の行モデルを返す。
# なぜ: テーブルの UI レイアウトを 1 箇所に閉じ込め、store 反映や backend と分離するため。

from __future__ import annotations

import math
from collections.abc import Mapping

from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.view import ParameterRow
from grafix.core.preset_registry import preset_registry
from grafix.core.runtime_config import runtime_config

from .group_blocks import GroupBlock, group_blocks_from_rows
from .labeling import format_contextual_row_label, humanize_identifier
from .midi_learn import MidiLearnState
from .rules import ui_rules_for_row
from .snippet import snippet_for_block
from .theme import PARAMETER_GUI_PALETTE, source_badge_color
from .widgets import render_value_widget

SNIPPET_POPUP_WINDOW_SIZE_PX = (960.0, 720.0)
SNIPPET_POPUP_VIEWPORT_MARGIN_PX = 24.0

GROUP_HEADER_BASE_COLORS_RGBA: dict[str, tuple[int, int, int, int]] = {
    "style": (104, 164, 255, 94),
    "primitive": (229, 138, 125, 94),
    "preset": (170, 140, 255, 94),
    "effect": (107, 203, 149, 94),
}


def _clamp01(x: float) -> float:
    """0..1 に clamp した値を返す。"""

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return float(x)


def _rgba01_from_rgba255(
    rgba: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    """0..255 の RGBA を 0..1 の RGBA に変換して返す。"""

    r, g, b, a = rgba
    return (
        _clamp01(float(r) / 255.0),
        _clamp01(float(g) / 255.0),
        _clamp01(float(b) / 255.0),
        _clamp01(float(a) / 255.0),
    )


def _derive_header_colors(
    base: tuple[float, float, float, float],
) -> tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]:
    """(normal, hovered, active) のヘッダ色を base から作る。"""

    normal = base

    def _tint_towards_white(
        rgba: tuple[float, float, float, float],
        *,
        t: float,
        alpha_add: float,
    ) -> tuple[float, float, float, float]:
        t = _clamp01(float(t))
        r, g, b, a = rgba
        return (
            _clamp01(r * (1.0 - t) + 1.0 * t),
            _clamp01(g * (1.0 - t) + 1.0 * t),
            _clamp01(b * (1.0 - t) + 1.0 * t),
            _clamp01(a + float(alpha_add)),
        )

    # hover/active の色は base から自動導出する（白方向へ補間 + alpha を少し増やす）。
    hovered = _tint_towards_white(base, t=0.12, alpha_add=0.08)
    active = _tint_towards_white(base, t=0.22, alpha_add=0.14)
    return normal, hovered, active


def _header_kind_for_group_id(group_id: tuple[str, object]) -> str | None:
    """GroupBlock.group_id からヘッダ種別（style/preset/primitive/effect）を返す。"""

    group_type = str(group_id[0])
    if group_type == "effect_chain":
        return "effect"
    if group_type in {"style", "preset", "primitive"}:
        return group_type
    return None


def _collapse_key_for_block(block: GroupBlock) -> str | None:
    """ブロックの折りたたみ永続キーを返す。"""

    group_type = str(block.group_id[0])
    if group_type == "style":
        return "style:global"
    if group_type == "effect_chain":
        chain_id = str(block.group_id[1])
        return f"effect_chain:{chain_id}"
    if group_type == "preset":
        if not block.items:
            return None
        row0 = block.items[0].row
        return f"preset:{row0.op}:{row0.site_id}"
    if group_type == "primitive":
        if not block.items:
            return None
        row0 = block.items[0].row
        return f"primitive:{row0.op}:{row0.site_id}"
    return None


def _row_visible_label(row: ParameterRow) -> str:
    """行の表示ラベル（`op#ordinal arg`）を返す。"""

    op = str(row.op)
    if op in preset_registry:
        op = preset_registry.get_display_op(op)
    return format_contextual_row_label(op, int(row.ordinal), row.arg)


def _row_id(row: ParameterRow) -> str:
    """ImGui の `push_id()` 用に、行の安定 ID を返す。"""

    return f"{row.op}#{row.ordinal}:{row.arg}"


def source_badge_for_row(row: ParameterRow, last_source: str | None) -> str:
    """行の現在の有効値ソースを、製品 UI 用の短い表記で返す。"""

    # last_source は直近に実現した frame の観測値。Undo/Redo や
    # Snapshot Load の直後は row だけが新状態に進んでいるため、
    # 現在の control 状態と両立する観測値だけを使う。
    cc_can_be_source = (isinstance(row.cc_key, int) and row.kind in {"float", "int", "choice"}) or (
        isinstance(row.cc_key, tuple)
        and row.kind == "vec3"
        and any(cc is not None for cc in row.cc_key)
    )
    if last_source == "cc" and cc_can_be_source:
        return "MIDI"
    if last_source == "gui" and (row.kind == "bool" or row.override):
        return "UI"
    if last_source == "base" and row.kind != "bool" and not row.override:
        return "CODE"
    if row.kind == "bool" or row.override:
        return "UI"
    return "CODE"


def _render_label_cell(
    imgui,
    *,
    row_label: str,
    source_badge: str,
    show_reset_to_code: bool = False,
) -> bool:
    """label 列を描画し、明示的な source reset が押されたら True を返す。"""

    imgui.table_set_column_index(0)
    cell_width = _content_region_available_width(imgui)
    label_text = f"[{source_badge}] {row_label}"
    text_colored = getattr(imgui, "text_colored", None)
    if callable(text_colored):
        text_colored(str(source_badge), *source_badge_color(source_badge))
        imgui.same_line(0.0, 6.0)
        imgui.text(str(row_label))
    else:
        imgui.text(label_text)
    if not show_reset_to_code:
        return False

    inline = True
    calc_text_size = getattr(imgui, "calc_text_size", None)
    if cell_width is not None and callable(calc_text_size):
        try:
            label_width = float(calc_text_size(label_text)[0])
        except (IndexError, TypeError, ValueError):
            pass
        else:
            button_width = _button_width_for_cell(
                imgui,
                "Code##reset_to_code",
                minimum=1.0,
                cell_width=None,
            )
            if math.isfinite(label_width):
                # same_line() の既定 item spacing を保守的に 8px と見積もる。
                inline = label_width + 8.0 + button_width <= cell_width

    if inline:
        # 幅取得 API を持たない従来 backend/test double では旧配置を維持する。
        imgui.same_line()
    clicked = bool(imgui.button("Code##reset_to_code"))
    is_item_hovered = getattr(imgui, "is_item_hovered", None)
    set_tooltip = getattr(imgui, "set_tooltip", None)
    if callable(is_item_hovered) and callable(set_tooltip) and is_item_hovered():
        set_tooltip("Reset this parameter to the value defined in code")
    return clicked


def _render_control_cell(imgui, row: ParameterRow) -> tuple[bool, object]:
    """control 列を描画し、(changed, ui_value) を返す。"""

    imgui.table_set_column_index(1)
    imgui.set_next_item_width(-1)  # 残り幅いっぱい
    return render_value_widget(row)


def _render_effect_step_heading(imgui, label: str) -> None:
    """Effect chain 内で operation が切り替わる位置に小見出しを描く。"""

    imgui.table_next_row()
    imgui.table_set_column_index(0)
    text_colored = getattr(imgui, "text_colored", None)
    if callable(text_colored):
        text_colored(str(label), *PARAMETER_GUI_PALETTE["success"])
    else:
        imgui.text(str(label))


def _effect_step_heading_by_site(block: GroupBlock) -> dict[str, str]:
    """Effect block の各 site_id に、短く一意な小見出しを割り当てる。"""

    sites_by_op: dict[str, list[str]] = {}
    for item in block.items:
        op = str(item.row.op)
        site_id = str(item.row.site_id)
        op_sites = sites_by_op.setdefault(op, [])
        if site_id not in op_sites:
            op_sites.append(site_id)

    out: dict[str, str] = {}
    for op, sites in sites_by_op.items():
        op_label = humanize_identifier(op)
        for ordinal, site_id in enumerate(sites, start=1):
            out[site_id] = op_label if len(sites) == 1 else f"{op_label} {int(ordinal)}"
    return out


def _should_auto_enable_override(
    row: ParameterRow,
    *,
    before_ui_value: object,
    after_ui_value: object,
) -> bool:
    """GUI の値編集に応じて override を自動で有効化するか判定する。

    Notes
    -----
    - override は「GUI 値を採用するか」を決めるトグル。
    - parameter_gui では `override=False` の行でも、値を触った瞬間に反映されるのが直感的。
      そのため「値が編集されたら override=True」を基本とする。
    - ただし `kind=bool` は override を持たない（常に GUI 値を採用する）ため対象外。
    - `kind=choice` は choices の変化などで ui_value が自動丸めされる場合がある。
      そのケースでは override を自動で立てず、base 優先を維持する。
    """

    if row.kind == "bool":
        return False

    if row.kind == "choice":
        choices = list(row.choices) if row.choices is not None else []
        if choices:
            before_s = str(before_ui_value)
            if before_s not in choices:
                # choices 外の値は widget 側で先頭へ丸められる。
                # この「自動丸め」だけでは override を立てない。
                return str(after_ui_value) != str(choices[0])

    return True


def _render_minmax_cell(
    imgui,
    *,
    rules,
    ui_min: float | int | None,
    ui_max: float | int | None,
) -> tuple[bool, float | int | None, float | int | None]:
    """min-max 列を描画し、(changed, ui_min, ui_max) を返す。"""

    imgui.table_set_column_index(2)

    if rules.minmax == "float_range":
        min_display = -1.0 if ui_min is None else float(ui_min)
        max_display = 1.0 if ui_max is None else float(ui_max)
        imgui.set_next_item_width(-1)
        changed, min_display, max_display = imgui.drag_float_range2(
            "##ui_range",
            float(min_display),  # current_min
            float(max_display),  # current_max
            0.1,  # speed
            0.0,  # min_value
            0.0,  # max_value
            "%.1f",  # format
            None,
        )
        if not changed:
            return False, ui_min, ui_max
        return True, float(min_display), float(max_display)

    if rules.minmax == "int_range":
        min_display_i = -10 if ui_min is None else int(ui_min)
        max_display_i = 10 if ui_max is None else int(ui_max)
        imgui.set_next_item_width(-1)
        changed, min_display_i, max_display_i = imgui.drag_int_range2(
            "##ui_range",
            int(min_display_i),  # current_min
            int(max_display_i),  # current_max
            0.1,  # speed
            0,  # min_value
            0,  # max_value
        )
        if not changed:
            return False, ui_min, ui_max
        return True, int(min_display_i), int(max_display_i)

    return False, ui_min, ui_max


def _content_region_available_width(imgui) -> float | None:
    """現在の table cell で利用可能な幅を返す。

    古い pyimgui backend や unit-test double に幅取得 API がない場合は
    ``None`` を返し、従来どおり 1 行配置を使う。通常の pyimgui では table
    column の work rect が反映されるため、右端 cell の実幅を取得できる。
    """

    getter = getattr(imgui, "get_content_region_available_width", None)
    if callable(getter):
        try:
            width = float(getter())
        except (TypeError, ValueError):
            return None
        if math.isfinite(width) and width > 0.0:
            return width

    getter_vec = getattr(imgui, "get_content_region_available", None)
    if callable(getter_vec):
        try:
            available = getter_vec()
            width = float(available[0])
        except (IndexError, TypeError, ValueError):
            return None
        if math.isfinite(width) and width > 0.0:
            return width
    return None


def _visible_widget_text(label: str) -> str:
    """ImGui の ``##id`` より前にある可視ラベルだけを返す。"""

    return str(label).split("##", 1)[0]


def _button_width_for_cell(
    imgui,
    label: str,
    *,
    minimum: float,
    cell_width: float | None,
) -> float:
    """ラベルが読める button 幅を求め、狭い cell の外へはみ出させない。"""

    width = max(1.0, float(minimum))
    calc_text_size = getattr(imgui, "calc_text_size", None)
    if callable(calc_text_size):
        try:
            text_width = float(calc_text_size(_visible_widget_text(label))[0])
        except (IndexError, TypeError, ValueError):
            pass
        else:
            # ImGui 既定 frame padding（左右各 8px）相当。font scale は
            # calc_text_size 側で追従する。
            if math.isfinite(text_width):
                width = max(width, text_width + 16.0)
    if cell_width is not None:
        width = min(width, max(1.0, float(cell_width)))
    return width


def _checkbox_width(imgui, label: str) -> float:
    """checkbox を同行配置できるか判断するための保守的な推定幅。"""

    text_width = 36.0
    calc_text_size = getattr(imgui, "calc_text_size", None)
    if callable(calc_text_size):
        try:
            measured = float(calc_text_size(_visible_widget_text(label))[0])
        except (IndexError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(measured):
                text_width = max(0.0, measured)

    frame_height = 20.0
    get_frame_height = getattr(imgui, "get_frame_height", None)
    if callable(get_frame_height):
        try:
            measured_height = float(get_frame_height())
        except (TypeError, ValueError):
            pass
        else:
            if math.isfinite(measured_height) and measured_height > 0.0:
                frame_height = measured_height

    # checkbox square + item-inner spacing（4px）+ label。
    return frame_height + 4.0 + text_width


def _place_responsive_item(
    imgui,
    *,
    cell_width: float | None,
    used_width: float,
    item_width: float,
    spacing: float,
) -> float:
    """item を収まる場合だけ同行へ置き、現在行の使用幅を返す。"""

    item_width = max(1.0, float(item_width))
    if used_width <= 0.0:
        return item_width

    next_width = float(used_width) + float(spacing) + item_width
    if cell_width is None or next_width <= float(cell_width):
        imgui.same_line(0.0, float(spacing))
        return next_width

    # same_line を呼ばなければ、次の item は次行の先頭に置かれる。
    return item_width


def _snippet_popup_geometry(
    imgui,
    *,
    preferred_size: tuple[float, float] = SNIPPET_POPUP_WINDOW_SIZE_PX,
    margin: float = SNIPPET_POPUP_VIEWPORT_MARGIN_PX,
) -> tuple[float, float, float, float]:
    """Code popup の中心座標と viewport 内に収まるサイズを返す。"""

    viewport_x = 0.0
    viewport_y = 0.0
    viewport_width = 0.0
    viewport_height = 0.0

    get_main_viewport = getattr(imgui, "get_main_viewport", None)
    if callable(get_main_viewport):
        try:
            viewport = get_main_viewport()
            work_pos = viewport.work_pos
            work_size = viewport.work_size
            viewport_x = float(work_pos[0])
            viewport_y = float(work_pos[1])
            viewport_width = float(work_size[0])
            viewport_height = float(work_size[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            viewport_width = 0.0
            viewport_height = 0.0

    if (
        not math.isfinite(viewport_width)
        or not math.isfinite(viewport_height)
        or viewport_width <= 0.0
        or viewport_height <= 0.0
    ):
        # pyimgui 2.0 では frame 開始前の main viewport が 0x0 の場合がある。
        # GUI backend が毎 frame 同期する io.display_size を fallback にする。
        try:
            display_size = imgui.get_io().display_size
            viewport_x = 0.0
            viewport_y = 0.0
            viewport_width = float(display_size[0])
            viewport_height = float(display_size[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            fallback_margin = max(0.0, float(margin)) * 2.0
            viewport_width = float(preferred_size[0]) + fallback_margin
            viewport_height = float(preferred_size[1]) + fallback_margin

    preferred_width = max(1.0, float(preferred_size[0]))
    preferred_height = max(1.0, float(preferred_size[1]))
    inset = max(0.0, float(margin))
    available_width = max(1.0, viewport_width - inset * 2.0)
    available_height = max(1.0, viewport_height - inset * 2.0)
    popup_width = min(preferred_width, available_width)
    popup_height = min(preferred_height, available_height)
    center_x = viewport_x + viewport_width * 0.5
    center_y = viewport_y + viewport_height * 0.5
    return center_x, center_y, popup_width, popup_height


def _render_cc_cell(
    imgui,
    *,
    row: ParameterRow,
    rules,
    cc_key: int | tuple[int | None, int | None, int | None] | None,
    override: bool,
    cc_key_width: int,
    width_spacer: int,
    midi_learn_state: MidiLearnState | None,
    midi_last_cc_change: tuple[int, int] | None,
) -> tuple[bool, int | tuple[int | None, int | None, int | None] | None, bool]:
    """cc/override 列を描画し、(changed, cc_key, override) を返す。"""

    imgui.table_set_column_index(3)

    changed_any = False
    cell_width = _content_region_available_width(imgui)
    used_width = 0.0

    if rules.cc_key == "none":
        clicked_override = False
        if rules.show_override:
            clicked_override, override = imgui.checkbox("Use UI##override", bool(override))
            if clicked_override:
                changed_any = True
        return changed_any, cc_key, bool(override)

    def _set_scalar(current: object, value: int | None) -> int | None:
        if value is None:
            return None
        return int(value)

    def _set_component(
        current: object, *, index: int, value: int | None
    ) -> tuple[int | None, int | None, int | None] | None:
        if isinstance(current, tuple):
            a, b, c = current
        else:
            a, b, c = None, None, None
        items = [a, b, c]
        items[int(index)] = None if value is None else int(value)
        out = (items[0], items[1], items[2])
        return None if out == (None, None, None) else out

    def _key_for_row(target_row: ParameterRow) -> ParameterKey:
        return ParameterKey(
            op=target_row.op,
            site_id=target_row.site_id,
            arg=target_row.arg,
        )

    def _is_active(*, key: ParameterKey, component: int | None) -> bool:
        state = midi_learn_state
        if state is None:
            return False
        return state.active_target == key and state.active_component == component

    def _enter_learn(*, key: ParameterKey, component: int | None) -> None:
        state = midi_learn_state
        if state is None:
            return
        state.active_target = key
        state.active_component = component
        state.last_seen_cc_seq = 0 if midi_last_cc_change is None else int(midi_last_cc_change[0])

    def _cancel_learn() -> None:
        state = midi_learn_state
        if state is None:
            return
        state.active_target = None
        state.active_component = None

    key = _key_for_row(row)

    if rules.cc_key == "int3":
        current_tuple = cc_key if isinstance(cc_key, tuple) else (None, None, None)
        for i in range(3):
            component_cc = current_tuple[i]
            active = _is_active(key=key, component=int(i))

            if active and midi_learn_state is not None and midi_last_cc_change is not None:
                seq, learned_cc = midi_last_cc_change
                if int(seq) > int(midi_learn_state.last_seen_cc_seq):
                    cc_key = _set_component(cc_key, index=int(i), value=int(learned_cc))
                    midi_learn_state.last_seen_cc_seq = int(seq)
                    _cancel_learn()
                    changed_any = True
                    current_tuple = cc_key if isinstance(cc_key, tuple) else (None, None, None)
                    component_cc = current_tuple[i]
                    active = False

            if active:
                label_text = f"{chr(88 + i)} ..."
            elif component_cc is None:
                label_text = f"{chr(88 + i)} +"
            else:
                label_text = f"{chr(88 + i)} {int(component_cc)} ×"

            button_label = f"{label_text}##cc_learn_{i}"
            button_width = _button_width_for_cell(
                imgui,
                button_label,
                minimum=float(cc_key_width * 1.6),
                cell_width=cell_width,
            )
            used_width = _place_responsive_item(
                imgui,
                cell_width=cell_width,
                used_width=used_width,
                item_width=button_width,
                spacing=float(width_spacer),
            )
            clicked = imgui.button(button_label, button_width)
            if clicked:
                # 新規操作で learn は 1 件に限定する（別ターゲットがあればキャンセル）。
                if (
                    midi_learn_state is not None
                    and midi_learn_state.active_target is not None
                    and not active
                ):
                    _cancel_learn()

                if active:
                    _cancel_learn()
                elif component_cc is not None:
                    cc_key = _set_component(cc_key, index=int(i), value=None)
                    changed_any = True
                else:
                    _enter_learn(key=key, component=int(i))

    else:
        current_cc = cc_key if isinstance(cc_key, int) else None
        active = _is_active(key=key, component=None)

        if active and midi_learn_state is not None and midi_last_cc_change is not None:
            seq, learned_cc = midi_last_cc_change
            if int(seq) > int(midi_learn_state.last_seen_cc_seq):
                cc_key = _set_scalar(cc_key, int(learned_cc))
                midi_learn_state.last_seen_cc_seq = int(seq)
                _cancel_learn()
                changed_any = True
                current_cc = cc_key if isinstance(cc_key, int) else None
                active = False

        if active:
            label_text = "MIDI..."
        elif current_cc is None:
            label_text = "MIDI +"
        else:
            label_text = f"MIDI {int(current_cc)} ×"

        button_label = f"{label_text}##cc_learn"
        button_width = _button_width_for_cell(
            imgui,
            button_label,
            minimum=float(cc_key_width * 1.8) * 0.88,
            cell_width=cell_width,
        )
        used_width = _place_responsive_item(
            imgui,
            cell_width=cell_width,
            used_width=used_width,
            item_width=button_width,
            spacing=float(width_spacer),
        )
        clicked = imgui.button(button_label, button_width)
        if clicked:
            if (
                midi_learn_state is not None
                and midi_learn_state.active_target is not None
                and not active
            ):
                _cancel_learn()

            if active:
                _cancel_learn()
            elif current_cc is not None:
                cc_key = None
                changed_any = True
            else:
                _enter_learn(key=key, component=None)

    clicked_override = False
    if rules.show_override:
        used_width = _place_responsive_item(
            imgui,
            cell_width=cell_width,
            used_width=used_width,
            item_width=_checkbox_width(imgui, "Use UI##override"),
            spacing=float(width_spacer),
        )
        clicked_override, override = imgui.checkbox("Use UI##override", bool(override))
        if clicked_override:
            changed_any = True

    return changed_any, cc_key, bool(override)


def render_parameter_row_4cols(
    row: ParameterRow,
    *,
    visible_label: str | None = None,
    midi_learn_state: MidiLearnState | None = None,
    midi_last_cc_change: tuple[int, int] | None = None,
    last_source: str | None = None,
) -> tuple[bool, ParameterRow]:
    """1 行（1 key）を 4 列テーブルとして描画し、更新後の row を返す。

    Columns
    -------
    1. label : op#ordinal
    2. control : kind に応じたウィジェット
    3. min-max : ui_min/ui_max
    4. cc override : cc_key/override

    Returns
    -------
    changed : bool
        いずれかの UI 値が変更された場合 True。
    row : ParameterRow
        変更を反映した新しい行モデル。
    """

    import imgui  # type: ignore[import-untyped]

    row_label = _row_visible_label(row) if visible_label is None else str(visible_label)

    # この 1 行（= 1 key）で何かが変更されたかの集計フラグ。
    changed_any = False

    # ParameterRow は immutable（frozen）なので、まずは更新候補をローカル変数として持つ。
    ui_value = row.ui_value
    ui_min = row.ui_min
    ui_max = row.ui_max
    cc_key = row.cc_key
    override = row.override

    cc_key_width = 30
    width_spacer = 4

    rules = ui_rules_for_row(row)

    # テーブル内のウィジェット ID が行ごとに衝突しないよう、push_id でスコープを切る。
    # ここで `row.arg` まで含めているのは、同じ op#ordinal でも arg が異なる可能性があるため。
    imgui.push_id(_row_id(row))
    try:
        # 以降の描画は「この行」に対して行う。
        imgui.table_next_row()

        # --- Column 1: label（op#ordinal のみ表示）---
        reset_to_code = _render_label_cell(
            imgui,
            row_label=row_label,
            source_badge=source_badge_for_row(row, last_source),
            show_reset_to_code=(row.kind != "bool" and (cc_key is not None or bool(override))),
        )
        if reset_to_code:
            cc_key = None
            override = False
            changed_any = True
            target = ParameterKey(op=row.op, site_id=row.site_id, arg=row.arg)
            if midi_learn_state is not None and midi_learn_state.active_target == target:
                midi_learn_state.active_target = None
                midi_learn_state.active_component = None

        # --- Column 2: control（kind に応じたウィジェット）---
        # slider の visible label はテーブルの label 列で代替するため、
        # ウィジェット側は "##value" を使って非表示にしている。
        changed, value = _render_control_cell(imgui, row)
        if changed:
            changed_any = True
            before_ui_value = ui_value
            ui_value = value
            if (
                rules.show_override
                and not bool(override)
                and _should_auto_enable_override(
                    row,
                    before_ui_value=before_ui_value,
                    after_ui_value=ui_value,
                )
            ):
                override = True

        # --- Column 3: min-max（ui_min/ui_max）---
        changed_range, ui_min, ui_max = _render_minmax_cell(
            imgui,
            rules=rules,
            ui_min=ui_min,
            ui_max=ui_max,
        )
        if changed_range:
            changed_any = True

        # --- Column 4: cc override（cc_key/override）---
        changed_cc, cc_key, override = _render_cc_cell(
            imgui,
            row=row,
            rules=rules,
            cc_key=cc_key,
            override=bool(override),
            cc_key_width=cc_key_width,
            width_spacer=width_spacer,
            midi_learn_state=midi_learn_state,
            midi_last_cc_change=midi_last_cc_change,
        )
        if changed_cc:
            changed_any = True
    finally:
        # push_id と必ず対になるよう finally で pop_id する。
        imgui.pop_id()

    # ローカル変数へ反映した結果を、新しい ParameterRow として返す。
    updated = ParameterRow(
        label=row.label,
        op=row.op,
        site_id=row.site_id,
        arg=row.arg,
        kind=row.kind,
        ui_value=ui_value,
        ui_min=ui_min,
        ui_max=ui_max,
        choices=row.choices,
        cc_key=cc_key,
        override=override,
        ordinal=row.ordinal,
        reset_to_code=bool(reset_to_code),
    )

    return changed_any, updated


def render_parameter_table(
    rows: list[ParameterRow],
    *,
    column_weights: tuple[float, float, float, float] | None = None,
    primitive_header_by_group: Mapping[tuple[str, int], str] | None = None,
    layer_style_name_by_site_id: Mapping[str, str] | None = None,
    effect_chain_header_by_id: Mapping[str, str] | None = None,
    step_info_by_site: Mapping[tuple[str, str], tuple[str, int]] | None = None,
    effect_step_ordinal_by_site: Mapping[tuple[str, str], int] | None = None,
    last_effective_by_key: Mapping[ParameterKey, object] | None = None,
    last_source_by_key: Mapping[ParameterKey, str] | None = None,
    raw_label_by_site: Mapping[tuple[str, str], str] | None = None,
    midi_learn_state: MidiLearnState | None = None,
    midi_last_cc_change: tuple[int, int] | None = None,
    collapsed_headers: set[str] | None = None,
) -> tuple[bool, list[ParameterRow]]:
    """ParameterRow の列を 4 列テーブルとして描画し、更新後の rows を返す。"""

    import imgui  # type: ignore[import-untyped]

    if column_weights is None:
        column_weights = runtime_config().parameter_gui_table_column_weights

    # 列幅は stretch 比率として使う（負/ゼロは imgui 的にも意味が無いのでエラーにする）。
    label_weight, control_weight, range_weight, meta_weight = column_weights
    if label_weight <= 0.0 or control_weight <= 0.0 or range_weight <= 0.0 or meta_weight <= 0.0:
        raise ValueError(f"column_weights must be > 0: {column_weights}")

    # このテーブル（rows 全体）で変更があったかの集計。
    changed_any = False
    # 返り値として「更新後の row 群」を返すため、描画しながら新しい row を貯める。
    # 注: グループを折りたたんで行を描画しない場合でも、`rows_before` と 1:1 で揃える必要がある。
    #     （store_bridge が `zip(rows_before, rows_after, strict=True)` で差分適用するため）
    updated_rows: list[ParameterRow] = []

    # rows を “連続する group” ごとにブロック化する。
    # `collapsing_header` をテーブル外へ出すことで、ヘッダを全幅で表示できる。
    blocks = group_blocks_from_rows(
        rows,
        primitive_header_by_group=primitive_header_by_group,
        layer_style_name_by_site_id=layer_style_name_by_site_id,
        effect_chain_header_by_id=effect_chain_header_by_id,
        step_info_by_site=step_info_by_site,
        effect_step_ordinal_by_site=effect_step_ordinal_by_site,
    )

    # --- Code（ポップアップ出力）---
    # “トリガ（ボタン）” と “表示（ポップアップ）” を分離し、コピペ用途に寄せる。
    global _SNIPPET_POPUP_TEXT, _SNIPPET_POPUP_FOCUS_NEXT
    want_open_snippet_popup = False
    snippet_popup_text_new: str | None = None

    # 列ヘッダ（label/control/min-max/cc）は繰り返すとノイズになるので、
    # 最初に開いたグループのテーブルで 1 回だけ描画する。
    drew_column_headers = False

    for block_index, block in enumerate(blocks):
        if block_index > 0 and block.header:
            spacing = getattr(imgui, "spacing", None)
            if callable(spacing):
                spacing()
        # 折りたたみ状態の永続化と ID 衝突回避のため、group 固有 ID で push_id する。
        # - collapsing_header の state（open/close）
        # - begin_table の内部 ID
        # の両方をブロック単位で分離できる。
        imgui.push_id(block.header_id)
        try:
            # collapsing_header は (expanded, visible) を返す。
            # visible=None なので close ボタン無しで常に表示する。
            group_open = True
            if block.header:
                collapse_key = None if collapsed_headers is None else _collapse_key_for_block(block)
                if collapsed_headers is not None and collapse_key is not None:
                    want_open = collapse_key not in collapsed_headers
                    set_next_item_open = getattr(imgui, "set_next_item_open", None)
                    if callable(set_next_item_open):
                        cond_always = getattr(imgui, "ALWAYS", None)
                        try:
                            if cond_always is None:
                                set_next_item_open(bool(want_open))
                            else:
                                set_next_item_open(bool(want_open), cond_always)
                        except TypeError:
                            set_next_item_open(bool(want_open))

                color_count = 0
                header_kind = _header_kind_for_group_id(block.group_id)
                if header_kind is not None:
                    base_rgba255 = GROUP_HEADER_BASE_COLORS_RGBA.get(header_kind)
                    if base_rgba255 is not None:
                        base = _rgba01_from_rgba255(base_rgba255)
                        normal, hovered, active = _derive_header_colors(base)
                        imgui.push_style_color(imgui.COLOR_HEADER, *normal)
                        imgui.push_style_color(imgui.COLOR_HEADER_HOVERED, *hovered)
                        imgui.push_style_color(imgui.COLOR_HEADER_ACTIVE, *active)
                        color_count = 3
                try:
                    allow_overlap_flag = getattr(imgui, "TREE_NODE_ALLOW_ITEM_OVERLAP", 0)
                    group_open, _visible = imgui.collapsing_header(
                        f"{humanize_identifier(block.header)}##group_header",
                        None,
                        flags=imgui.TREE_NODE_DEFAULT_OPEN | allow_overlap_flag,
                    )
                    set_item_allow_overlap = getattr(imgui, "set_item_allow_overlap", None)
                    if callable(set_item_allow_overlap):
                        set_item_allow_overlap()
                finally:
                    if color_count:
                        imgui.pop_style_color(color_count)

                # ヘッダ行の右側に件数と Code ボタンを置く。
                # collapsing_header は幅いっぱいを使うため、same_line(position=...) で明示配置する。
                button_label = "Code"
                text_w, _text_h = imgui.calc_text_size(button_label)
                button_w = float(text_w) + 24.0
                count_label = f"{len(block.items)} parameters"
                count_w, _count_h = imgui.calc_text_size(count_label)
                cluster_w = float(count_w) + 12.0 + float(button_w)
                pos_x = float(imgui.get_window_width()) - cluster_w - 16.0
                if pos_x > 0.0:
                    imgui.same_line(position=pos_x)
                else:
                    imgui.same_line()
                imgui.text_disabled(count_label)
                imgui.same_line()
                if imgui.small_button(button_label):
                    snippet_popup_text_new = snippet_for_block(
                        block,
                        last_effective_by_key=last_effective_by_key,
                        layer_style_name_by_site_id=layer_style_name_by_site_id,
                        step_info_by_site=step_info_by_site,
                        raw_label_by_site=raw_label_by_site,
                    )
                    want_open_snippet_popup = True

                if collapsed_headers is not None and collapse_key is not None:
                    if group_open:
                        collapsed_headers.discard(collapse_key)
                    else:
                        collapsed_headers.add(collapse_key)

            if not group_open:
                # 折りたたみ中は描画しないが、rows_after の長さを揃えるため “変更なし” として返す。
                for item in block.items:
                    updated_rows.append(item.row)
                continue

            # --- open のときだけ、当該グループの行を 4 列テーブルとして描く ---
            #
            # `begin_table` は pyimgui のバージョン/バックエンドで返り値が揺れるため、
            # `.opened` 属性があればそれを使い、無ければ返り値自体を bool として扱う。
            table_flags = (
                imgui.TABLE_SIZING_STRETCH_PROP
                | getattr(imgui, "TABLE_ROW_BACKGROUND", 0)
                | getattr(imgui, "TABLE_BORDERS_INNER_VERTICAL", 0)
                | getattr(imgui, "TABLE_RESIZABLE", 0)
            )
            table = imgui.begin_table("##parameters", 4, table_flags)
            opened = getattr(table, "opened", table)
            if not opened:
                for item in block.items:
                    updated_rows.append(item.row)
                continue

            try:
                # 4 列: label / control / min-max / cc
                # それぞれ「残り幅に対する比率」で伸縮させる。
                imgui.table_setup_column(
                    "  Parameter",
                    imgui.TABLE_COLUMN_WIDTH_STRETCH,
                    float(label_weight),
                )
                imgui.table_setup_column(
                    "  Value",
                    imgui.TABLE_COLUMN_WIDTH_STRETCH,
                    float(control_weight),
                )
                imgui.table_setup_column(
                    "  Range",
                    imgui.TABLE_COLUMN_WIDTH_STRETCH,
                    float(range_weight),
                )
                imgui.table_setup_column(
                    "  MIDI / UI",
                    imgui.TABLE_COLUMN_WIDTH_STRETCH,
                    float(meta_weight),
                )
                if not drew_column_headers:
                    # カラム名（label/control/min-max/cc）をヘッダ行として描画する（1回だけ）。
                    imgui.table_headers_row()
                    drew_column_headers = True

                effect_heading_by_site = (
                    _effect_step_heading_by_site(block)
                    if str(block.group_id[0]) == "effect_chain"
                    else {}
                )
                previous_effect_site: str | None = None
                for item in block.items:
                    item_site = str(item.row.site_id)
                    if effect_heading_by_site and item_site != previous_effect_site:
                        _render_effect_step_heading(
                            imgui,
                            effect_heading_by_site[item_site],
                        )
                        previous_effect_site = item_site
                    row_key = ParameterKey(
                        op=item.row.op,
                        site_id=item.row.site_id,
                        arg=item.row.arg,
                    )
                    row_changed, updated = render_parameter_row_4cols(
                        item.row,
                        visible_label=item.visible_label,
                        midi_learn_state=midi_learn_state,
                        midi_last_cc_change=midi_last_cc_change,
                        last_source=(
                            None if last_source_by_key is None else last_source_by_key.get(row_key)
                        ),
                    )
                    changed_any = changed_any or row_changed
                    updated_rows.append(updated)
            finally:
                imgui.end_table()
        finally:
            imgui.pop_id()

    # --- Code popup ---
    #
    # open_popup と begin_popup_modal は “同じ ID スタック” が必要なので、push_id の外で扱う。
    if want_open_snippet_popup and snippet_popup_text_new is not None:
        _SNIPPET_POPUP_TEXT = str(snippet_popup_text_new)
        _SNIPPET_POPUP_FOCUS_NEXT = True
        imgui.open_popup("Code##snippet_popup")

    popup_x, popup_y, popup_width, popup_height = _snippet_popup_geometry(imgui)
    # 親 window が 600px 程度でも modal を viewport 内へ収める。ALWAYS にして
    # popup を開いたまま OS window が resize された場合にも追従させる。
    imgui.set_next_window_position(
        popup_x,
        popup_y,
        condition=imgui.ALWAYS,
        pivot_x=0.5,
        pivot_y=0.5,
    )
    imgui.set_next_window_size(
        popup_width,
        popup_height,
        condition=imgui.ALWAYS,
    )
    with imgui.begin_popup_modal("Code##snippet_popup") as popup:
        if popup.opened:
            if imgui.button("Close"):
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Copy"):
                imgui.set_clipboard_text(str(_SNIPPET_POPUP_TEXT))
                imgui.close_current_popup()
                _SNIPPET_POPUP_FOCUS_NEXT = False
            imgui.same_line()
            imgui.text_disabled("macOS Cmd+A→Cmd+C / Win/Linux Ctrl+A→Ctrl+C")

            if _SNIPPET_POPUP_FOCUS_NEXT:
                imgui.set_keyboard_focus_here()
                _SNIPPET_POPUP_FOCUS_NEXT = False

            avail_w, avail_h = imgui.get_content_region_available()
            editor_width = max(1.0, float(avail_w))
            editor_height = max(1.0, float(avail_h) - 8.0)
            _changed, _text_out = imgui.input_text_multiline(
                "##snippet_text",
                str(_SNIPPET_POPUP_TEXT),
                -1,
                editor_width,
                editor_height,
                flags=imgui.INPUT_TEXT_READ_ONLY | imgui.INPUT_TEXT_AUTO_SELECT_ALL,
            )
            if imgui.is_item_focused() or imgui.is_item_active():
                io = imgui.get_io()
                if (io.key_ctrl or io.key_super) and imgui.is_key_pressed(imgui.KEY_C, False):
                    imgui.set_clipboard_text(str(_SNIPPET_POPUP_TEXT))

    # changed_any は「UI のどこかが変わったか」。
    # updated_rows は store へ差分適用するための “更新後” 行モデル列（rows と同じ長さ）。
    return changed_any, updated_rows


# Code popup の一時状態（永続化しない）。
_SNIPPET_POPUP_TEXT = ""
_SNIPPET_POPUP_FOCUS_NEXT = False
