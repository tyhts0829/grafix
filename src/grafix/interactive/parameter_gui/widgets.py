# どこで: `src/grafix/interactive/parameter_gui/widgets.py`。
# 何を: ParameterRow.kind を pyimgui の値ウィジェットへ対応付けて描画する。
# なぜ: kind ごとの UI 実装を閉じ込め、テーブル描画から分離するため。

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from grafix.core.operation_selector import selector_kind
from grafix.core.font_resolver import list_font_choices
from grafix.core.parameters.view import ParameterRow

WidgetFn = Callable[[ParameterRow], tuple[bool, Any]]

_FONT_FILTER_BY_KEY: dict[tuple[str, str, str], str] = {}
_CHOICE_FILTER_BY_KEY: dict[tuple[str, str, str], str] = {}

_MAX_INLINE_CHOICE_COUNT = 4
_SEARCHABLE_CHOICE_COUNT = 8


def _query_tokens_and(query: str) -> tuple[str, ...]:
    """フィルタークエリを AND 用トークン列へ正規化して返す。"""
    tokens = [t for t in str(query).casefold().split() if t]
    return tuple(tokens)


def _filter_choices_by_query_and(
    choices: tuple[tuple[str, str, bool, str], ...], *, query: str
) -> list[tuple[str, str, bool, str]]:
    """AND クエリで choices を絞り込んで返す（純粋関数）。"""
    tokens = _query_tokens_and(query)
    if not tokens:
        return list(choices)
    out: list[tuple[str, str, bool, str]] = []
    for item in choices:
        _stem, _rel, _is_ttc, search_key = item
        if all(t in str(search_key).casefold() for t in tokens):
            out.append(item)
    return out


def _filter_choice_labels(
    choices: Sequence[str],
    *,
    query: str,
) -> list[str]:
    """choice label を case-insensitive AND query で絞り込む。"""

    tokens = _query_tokens_and(query)
    if not tokens:
        return [str(choice) for choice in choices]
    return [
        str(choice)
        for choice in choices
        if all(token in str(choice).casefold() for token in tokens)
    ]


def _content_region_available_width(imgui: Any) -> float | None:
    """現在の control cell で利用できる幅を backend 互換で返す。"""

    getter = getattr(imgui, "get_content_region_available_width", None)
    if callable(getter):
        try:
            width = float(getter())
        except (TypeError, ValueError):
            width = math.nan
        if math.isfinite(width):
            return max(0.0, width)

    getter_vec = getattr(imgui, "get_content_region_available", None)
    if callable(getter_vec):
        try:
            width = float(getter_vec()[0])
        except (IndexError, TypeError, ValueError):
            return None
        if math.isfinite(width):
            return max(0.0, width)
    return None


def _style_spacing_x(imgui: Any, name: str, default: float) -> float:
    """ImGui style の Vec2 field から正の x 成分を返す。"""

    get_style = getattr(imgui, "get_style", None)
    if not callable(get_style):
        return float(default)
    try:
        value = getattr(get_style(), name)
        x_value = getattr(value, "x", None)
        if x_value is None:
            x_value = value[0]
        x = float(x_value)
    except (AttributeError, IndexError, TypeError, ValueError):
        return float(default)
    return x if math.isfinite(x) and x >= 0.0 else float(default)


def _choice_radio_layout(
    imgui: Any,
    choices: Sequence[str],
) -> tuple[float, float] | None:
    """radio 群の推定必要幅と item 間隔を返す。"""

    calc_text_size = getattr(imgui, "calc_text_size", None)
    get_frame_height = getattr(imgui, "get_frame_height", None)
    if not callable(calc_text_size) or not callable(get_frame_height):
        return None
    try:
        frame_height = float(get_frame_height())
        text_widths = [float(calc_text_size(str(choice))[0]) for choice in choices]
    except (IndexError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(frame_height)
        or frame_height <= 0.0
        or any(not math.isfinite(width) or width < 0.0 for width in text_widths)
    ):
        return None

    inner_spacing = _style_spacing_x(
        imgui,
        "item_inner_spacing",
        max(1.0, frame_height * 0.25),
    )
    item_spacing = _style_spacing_x(
        imgui,
        "item_spacing",
        max(1.0, frame_height * 0.35),
    )
    item_widths = [
        frame_height + inner_spacing + text_width for text_width in text_widths
    ]
    required = sum(item_widths) + item_spacing * max(0, len(item_widths) - 1)
    return float(required), float(item_spacing)


def _choice_uses_radio(
    imgui: Any,
    choices: Sequence[str],
    *,
    force_combo: bool,
) -> bool:
    """候補数と実 cell 幅から inline radio を使うか決める。"""

    if not callable(getattr(imgui, "begin_combo", None)):
        return True
    if force_combo or len(choices) > _MAX_INLINE_CHOICE_COUNT:
        return False

    available_width = _content_region_available_width(imgui)
    layout = _choice_radio_layout(imgui, choices)
    if available_width is None or layout is None:
        return True
    required_width, _item_spacing = layout
    return required_width <= available_width


def _render_choice_radio(
    imgui: Any,
    *,
    choices: Sequence[str],
    current_value: str,
    changed: bool,
) -> tuple[bool, str]:
    """choice を inline radio として描画する。"""

    try:
        selected_index = list(choices).index(current_value)
    except ValueError:
        selected_index = -1

    layout = _choice_radio_layout(imgui, choices)
    item_spacing = 6.0 if layout is None else float(layout[1])
    for index, choice in enumerate(choices):
        clicked = imgui.radio_button(
            f"{choice}##{index}",
            index == selected_index,
        )
        if clicked:
            selected_index = int(index)
            changed = True
        if index != len(choices) - 1:
            imgui.same_line(0.0, float(item_spacing))

    if selected_index < 0:
        return bool(changed), str(current_value)
    return bool(changed), str(choices[int(selected_index)])


def _begin_choice_combo(
    imgui: Any,
    *,
    preview: str,
) -> bool:
    """flags 対応差を吸収して choice combo を開始する。"""

    flags = int(getattr(imgui, "COMBO_HEIGHT_LARGE", 0))
    try:
        return bool(imgui.begin_combo("##value", str(preview), flags=flags))
    except TypeError:
        return bool(imgui.begin_combo("##value", str(preview)))


def _render_choice_filter(
    imgui: Any,
    *,
    key: tuple[str, str, str],
) -> str:
    """開いている choice popup の一時 filter を描画して返す。"""

    filter_text = _CHOICE_FILTER_BY_KEY.get(key, "")
    set_width = getattr(imgui, "set_next_item_width", None)
    if callable(set_width):
        set_width(-1)

    input_with_hint = getattr(imgui, "input_text_with_hint", None)
    if callable(input_with_hint):
        changed, value = input_with_hint(
            "##choice_filter",
            "Filter choices",
            str(filter_text),
        )
    else:
        input_text = getattr(imgui, "input_text", None)
        if not callable(input_text):
            return str(filter_text)
        changed, value = input_text(
            "Filter##choice_filter",
            str(filter_text),
        )
    if changed:
        filter_text = str(value)
        _CHOICE_FILTER_BY_KEY[key] = filter_text
    return str(filter_text)


def _render_choice_combo(
    imgui: Any,
    *,
    row: ParameterRow,
    choices: Sequence[str],
    current_value: str,
    changed: bool,
    preserve_unavailable: bool,
) -> tuple[bool, str]:
    """choice を必要に応じて検索可能な combo として描画する。"""

    unavailable = current_value not in choices
    preview = (
        f"{current_value} (unavailable)"
        if unavailable and preserve_unavailable
        else current_value
    )
    value_out = str(current_value)
    if not _begin_choice_combo(imgui, preview=preview):
        return bool(changed), value_out

    key = (str(row.op), str(row.site_id), str(row.arg))
    searchable = len(choices) >= _SEARCHABLE_CHOICE_COUNT
    try:
        filter_text = (
            _render_choice_filter(imgui, key=key)
            if searchable
            else ""
        )
        filtered = _filter_choice_labels(choices, query=filter_text)
        if not filtered:
            text = getattr(imgui, "text_disabled", None)
            (text if callable(text) else imgui.text)("No match")
        else:
            for index, choice in enumerate(filtered):
                selected = choice == current_value
                clicked, _selected_now = imgui.selectable(
                    f"{choice}##{index}",
                    selected,
                )
                if clicked:
                    value_out = str(choice)
                    changed = True
                    _CHOICE_FILTER_BY_KEY.pop(key, None)
                if selected:
                    set_default_focus = getattr(
                        imgui,
                        "set_item_default_focus",
                        None,
                    )
                    if callable(set_default_focus):
                        set_default_focus()
    finally:
        imgui.end_combo()
    return bool(changed), value_out


def _float_slider_range(row: ParameterRow) -> tuple[float, float]:
    """float スライダーのレンジ (min, max) を返す。

    ui_min/ui_max が None の場合は -1.0..1.0 にフォールバックする。
    """

    min_value = -1.0 if row.ui_min is None else float(row.ui_min)
    max_value = 1.0 if row.ui_max is None else float(row.ui_max)
    return min_value, max_value


def _int_slider_range(row: ParameterRow) -> tuple[int, int]:
    """int スライダーのレンジ (min, max) を返す。

    ui_min/ui_max が None の場合は -10..10 にフォールバックする。
    """

    min_value = -10 if row.ui_min is None else int(row.ui_min)
    max_value = 10 if row.ui_max is None else int(row.ui_max)

    # ImGui の slider_int は min/max が int32 の “半分レンジ” 以内であることを要求する。
    # （範囲外だと assertion error でクラッシュする）
    # 参照: imgui-cpp/imgui_widgets.cpp の slider_int 実装。
    min_value = max(-1_073_741_824, min(1_073_741_823, min_value))
    max_value = max(-1_073_741_824, min(1_073_741_823, max_value))
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    return min_value, max_value


def _as_float3(value: Any) -> tuple[float, float, float]:
    """値を長さ 3 の float タプル `(x, y, z)` に変換して返す。"""

    try:
        x, y, z = value  # type: ignore[misc]
    except Exception as exc:
        raise ValueError(
            f"vec3 ui_value must be a length-3 sequence: {value!r}"
        ) from exc
    return float(x), float(y), float(z)


def _as_rgb255(value: Any) -> tuple[int, int, int]:
    """値を長さ 3 の int タプル `(r, g, b)`（0..255）に変換して返す。"""

    try:
        r, g, b = value  # type: ignore[misc]
    except Exception as exc:
        raise ValueError(f"rgb ui_value must be a length-3 sequence: {value!r}") from exc

    out: list[int] = []
    for v in (r, g, b):
        iv = int(v)
        iv = max(0, min(255, iv))
        out.append(iv)
    return int(out[0]), int(out[1]), int(out[2])


def widget_float_slider(row: ParameterRow) -> tuple[bool, float]:
    """kind=float のスライダーを描画し、(changed, value) を返す。

    Parameters
    ----------
    row : ParameterRow
        kind=float の行モデル。

    Returns
    -------
    changed : bool
        値が変更された場合 True。
    value : float
        変更後の値。
    """

    import imgui  # type: ignore[import-untyped]

    value = float(row.ui_value)
    min_value, max_value = _float_slider_range(row)
    if str(row.arg).endswith("thickness"):
        return imgui.slider_float(
            "##value",
            float(value),
            float(min_value),
            float(max_value),
            format="%.6f",
            flags=imgui.SLIDER_FLAGS_ALWAYS_CLAMP,
        )
    return imgui.slider_float("##value", float(value), float(min_value), float(max_value))


def widget_int_slider(row: ParameterRow) -> tuple[bool, int]:
    """kind=int のスライダーを描画し、(changed, value) を返す。"""

    import imgui  # type: ignore[import-untyped]

    value = int(row.ui_value)
    min_value, max_value = _int_slider_range(row)
    return imgui.slider_int("##value", int(value), int(min_value), int(max_value))


def widget_vec3_slider(row: ParameterRow) -> tuple[bool, tuple[float, float, float]]:
    """kind=vec3 のスライダーを描画し、(changed, value) を返す。"""

    import imgui  # type: ignore[import-untyped]

    value0, value1, value2 = _as_float3(row.ui_value)
    min_value, max_value = _float_slider_range(row)
    changed, out = imgui.slider_float3(
        "##value",
        float(value0),
        float(value1),
        float(value2),
        float(min_value),
        float(max_value),
    )
    return changed, _as_float3(out)


def widget_rgb_color_edit3(row: ParameterRow) -> tuple[bool, tuple[int, int, int]]:
    """kind=rgb のカラーピッカーを描画し、(changed, value) を返す。"""

    import imgui  # type: ignore[import-untyped]

    r, g, b = _as_rgb255(row.ui_value)
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    flags = (
        imgui.COLOR_EDIT_UINT8 | imgui.COLOR_EDIT_DISPLAY_RGB | imgui.COLOR_EDIT_INPUT_RGB
    )
    changed, out = imgui.color_edit3("##value", float(rf), float(gf), float(bf), flags=flags)
    if not changed:
        return False, (r, g, b)

    r2, g2, b2 = out
    r_out = int(round(float(r2) * 255.0))
    g_out = int(round(float(g2) * 255.0))
    b_out = int(round(float(b2) * 255.0))
    r_out = max(0, min(255, r_out))
    g_out = max(0, min(255, g_out))
    b_out = max(0, min(255, b_out))
    return True, (r_out, g_out, b_out)


def widget_bool_checkbox(row: ParameterRow) -> tuple[bool, bool]:
    """kind=bool のチェックボックスを描画し、(changed, value) を返す。"""

    import imgui  # type: ignore[import-untyped]

    clicked, state = imgui.checkbox("##value", bool(row.ui_value))
    return clicked, bool(state)


def widget_string_input(row: ParameterRow) -> tuple[bool, str]:
    """kind=str のテキスト入力を描画し、(changed, value) を返す。"""

    import imgui  # type: ignore[import-untyped]

    value = "" if row.ui_value is None else str(row.ui_value)
    line_count = int(value.count("\n")) + 1
    visible_lines = max(3, min(8, line_count))
    height = float(imgui.get_text_line_height()) * float(visible_lines) + 8.0
    return imgui.input_text_multiline("##value", value, -1, 0.0, float(height))


def widget_font_picker(row: ParameterRow) -> tuple[bool, str]:
    """kind=font のフォント選択を描画し、(changed, value) を返す。

    Notes
    -----
    control 列に以下を縦に描画する。
    - フィルター入力（AND: スペース区切り）
    - フィルター結果のプルダウン（表示は stem のみ）
    """

    import imgui  # type: ignore[import-untyped]

    key = (str(row.op), str(row.site_id), str(row.arg))
    filter_text = _FONT_FILTER_BY_KEY.get(key, "")

    # --- filter input ---
    imgui.set_next_item_width(-1)
    changed_filter, new_filter = imgui.input_text("##font_filter", str(filter_text))
    if changed_filter:
        _FONT_FILTER_BY_KEY[key] = str(new_filter)
        filter_text = str(new_filter)

    # --- dropdown ---
    choices = list_font_choices()
    filtered = _filter_choices_by_query_and(choices, query=str(filter_text))

    current_value = "" if row.ui_value is None else str(row.ui_value)
    preview = Path(current_value).stem if current_value else ""
    if not preview:
        preview = "(default)"

    imgui.set_next_item_width(-1)

    changed_value = False
    value_out = current_value

    if imgui.begin_combo("##font_combo", str(preview)):
        try:
            if not filtered:
                imgui.text("No match")
            else:
                for stem, rel, _is_ttc, _search_key in filtered:
                    selected = str(rel) == str(current_value)
                    label = f"{stem}##{rel}"
                    clicked, _selected_now = imgui.selectable(label, selected)
                    if clicked:
                        value_out = str(rel)
                        changed_value = True
                    if selected:
                        imgui.set_item_default_focus()
        finally:
            imgui.end_combo()

    return changed_value, str(value_out)


def widget_choice_radio(row: ParameterRow) -> tuple[bool, str]:
    """kind=choice を利用可能幅に応じた radio/combo で描画する。"""

    import imgui  # type: ignore[import-untyped]

    if row.choices is None or not list(row.choices):
        raise ValueError("choice requires non-empty choices")

    choices = [str(x) for x in row.choices]
    current_value = str(row.ui_value)
    preserve_unavailable = (
        selector_kind(row.op) is not None and str(row.arg) == "target"
    )
    changed = False
    if current_value not in choices and not preserve_unavailable:
        # 通常 choice は従来どおり先頭へ丸める。table 側はこの自動丸め
        # だけでは override を有効化しない。
        current_value = choices[0]
        changed = True

    if _choice_uses_radio(
        imgui,
        choices,
        force_combo=preserve_unavailable,
    ):
        return _render_choice_radio(
            imgui,
            choices=choices,
            current_value=current_value,
            changed=changed,
        )
    return _render_choice_combo(
        imgui,
        row=row,
        choices=choices,
        current_value=current_value,
        changed=changed,
        preserve_unavailable=preserve_unavailable,
    )


_KIND_TO_WIDGET: dict[str, WidgetFn] = {
    "float": widget_float_slider,
    "int": widget_int_slider,
    "vec3": widget_vec3_slider,
    "rgb": widget_rgb_color_edit3,
    "bool": widget_bool_checkbox,
    "str": widget_string_input,
    "font": widget_font_picker,
    "choice": widget_choice_radio,
}


def render_value_widget(row: ParameterRow) -> tuple[bool, Any]:
    """row.kind に応じたウィジェットを描画し、(changed, value) を返す。

    Parameters
    ----------
    row : ParameterRow
        GUI 行モデル。

    Returns
    -------
    changed : bool
        値が変更された場合 True。
    value : Any
        変更後の値。

    Raises
    ------
    ValueError
        未知 kind の場合。
    """

    fn = _KIND_TO_WIDGET.get(row.kind)
    if fn is None:
        raise ValueError(f"unknown kind: {row.kind}")
    return fn(row)


def widget_registry() -> dict[str, WidgetFn]:
    """kind→widget 関数マップのコピーを返す。"""

    return dict(_KIND_TO_WIDGET)
