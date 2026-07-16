# どこで: `src/grafix/interactive/parameter_gui/gui.py`。
# 何を: ParamStore を pyimgui で編集するための最小 GUI（初期化/1フレーム描画/破棄）を提供する。
# なぜ: 依存の重いライフサイクル管理を 1 箇所に閉じ込め、他モジュールを純粋に保つため。

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from grafix.core.font_resolver import default_font_path, resolve_font_path
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.history import (
    ParamSnapshotSlots,
    ParamStoreHistory,
    SnapshotSlot,
)
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_ops import set_meta
from grafix.core.parameters.snapshot_ops import store_snapshot, store_snapshot_for_gui
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.style import STYLE_OP
from grafix.core.runtime_config import runtime_config
from grafix.interactive.midi import MidiController
from grafix.interactive.runtime.frame_clock import TransportClock

from .midi_learn import MidiLearnState
from .monitor_bar import render_monitor_alerts, render_monitor_status
from .pyglet_backend import (
    _create_imgui_pyglet_renderer,
    _install_imgui_clipboard_callbacks,
    _sync_imgui_io_for_window,
)
from .range_edit import RangeEditMode, apply_range_shift
from .store_bridge import clear_all_midi_assignments, render_store_parameter_table
from .theme import PARAMETER_GUI_PALETTE, apply_parameter_gui_theme


@dataclass(frozen=True, slots=True)
class ToolbarLayout:
    """上部 Controls / Status surface の純粋な幅計算結果。"""

    stacked: bool
    controls_width: float
    status_width: float
    gap: float
    surface_height: float
    coordinate_scale: float


@dataclass(frozen=True, slots=True)
class TransportToolbarGeometry:
    """TIME行の幅契約。reserved はcaption/buttons/spacingの合計。"""

    available_width: float
    reserved_width: float
    timeline_width: float

    @property
    def required_width(self) -> float:
        return self.reserved_width + self.timeline_width

    @property
    def fits(self) -> bool:
        return self.required_width <= self.available_width + 0.01


def compute_transport_toolbar_geometry(
    controls_width: float,
    *,
    coordinate_scale: float = 1.0,
) -> TransportToolbarGeometry:
    """標準Inspectorでtimelineを160px以上確保する純粋なgeometry計算。"""

    width = max(0.0, float(controls_width))
    scale = max(1.0, float(coordinate_scale))
    # TIME caption、明示幅button 6個、speed label、item spacing 8個。
    reserved_width = 358.0 * scale
    timeline_width = max(160.0 * scale, min(220.0 * scale, width - reserved_width))
    return TransportToolbarGeometry(
        available_width=width,
        reserved_width=reserved_width,
        timeline_width=timeline_width,
    )


def compute_toolbar_layout(
    content_width: float,
    *,
    coordinate_scale: float = 1.0,
) -> ToolbarLayout:
    """通常幅は約 65:35、760px 未満は compact status を下へ積む。"""

    width = max(0.0, float(content_width))
    scale = max(1.0, float(coordinate_scale))
    if width >= 760.0 * scale:
        gap = 12.0 * scale
        # 固定 50:50 にせず、制作操作と160px以上のtimelineを優先する。
        # 標準768px contentではControls 68.4% / Status 30%（残りはgap）。
        status_width = min(300.0 * scale, max(228.0 * scale, width * 0.30))
        controls_width = max(0.0, width - gap - status_width)
        return ToolbarLayout(
            stacked=False,
            controls_width=controls_width,
            status_width=status_width,
            gap=gap,
            surface_height=72.0 * scale,
            coordinate_scale=scale,
        )
    return ToolbarLayout(
        stacked=True,
        controls_width=width,
        status_width=width,
        gap=6.0 * scale,
        # Compact status is rendered separately below, so two control rows do
        # not need the extra height reserved for the three-line desktop status.
        surface_height=60.0 * scale,
        coordinate_scale=scale,
    )


def _window_content_coordinate_scale(window: Any) -> float:
    """ImGui座標がrequested logical sizeの何倍かを返す。"""

    requested_size = getattr(window, "get_requested_size", None)
    if not callable(requested_size):
        return 1.0
    try:
        requested_width = float(requested_size()[0])
        public_width = float(window.width)
    except (AttributeError, TypeError, ValueError):
        return 1.0
    if requested_width <= 0.0 or public_width <= 0.0:
        return 1.0
    return max(1.0, public_width / requested_width)


def _available_content_width(imgui: Any) -> float | None:
    """現在の content 幅を返し、古い backend/test double では None にする。"""

    getter = getattr(imgui, "get_content_region_available_width", None)
    if not callable(getter):
        return None
    try:
        width = float(getter())
    except (TypeError, ValueError):
        return None
    return width if width > 0.0 else None


def _same_line_with_spacing(imgui: Any, spacing: float) -> None:
    """pyimgui2 と単純な test double の両方で明示的な group gap を作る。"""

    try:
        imgui.same_line(spacing=float(spacing))
    except TypeError:
        imgui.same_line()


def _button_with_width(imgui: Any, label: str, width: float) -> bool:
    """明示幅を使い、古いtest doubleでは通常buttonへfallbackする。"""

    try:
        return bool(imgui.button(str(label), float(width), 0.0))
    except TypeError:
        return bool(imgui.button(str(label)))


def _item_tooltip(imgui: Any, text: str) -> None:
    """hover tooltipを利用可能なbackendでだけ表示する。"""

    hovered = getattr(imgui, "is_item_hovered", None)
    tooltip = getattr(imgui, "set_tooltip", None)
    if callable(hovered) and callable(tooltip) and bool(hovered()):
        tooltip(str(text))


def _begin_toolbar_surface(imgui: Any, label: str, width: float, height: float) -> bool:
    """弱い surface 色を適用して child を開始し、色を push したか返す。"""

    push = getattr(imgui, "push_style_color", None)
    color_child = getattr(imgui, "COLOR_CHILD_BACKGROUND", None)
    pushed = False
    if callable(push) and color_child is not None:
        push(color_child, *PARAMETER_GUI_PALETTE["surface"])
        pushed = True
    imgui.begin_child(str(label), float(width), float(height), border=False)
    return pushed


def _end_toolbar_surface(imgui: Any, *, color_pushed: bool) -> None:
    imgui.end_child()
    if color_pushed:
        imgui.pop_style_color()


def _midi_assignment_count(store: ParamStore) -> int:
    """visible/inactive を問わず、割り当て済み CC component 数を返す。"""

    count = 0
    for _key, (_meta, state, _ordinal, _label) in store_snapshot(store).items():
        cc_key = state.cc_key
        if isinstance(cc_key, int):
            count += 1
        elif cc_key is not None:
            count += sum(1 for cc in cc_key if cc is not None)
    return count


def _section_separator(imgui: Any) -> None:
    """上部 toolbar と parameter table の境界を描く。"""

    separator = getattr(imgui, "separator", None)
    if callable(separator):
        separator()


def _default_gui_font_path() -> Path | None:
    try:
        return default_font_path()
    except Exception:
        return None


_DEFAULT_GUI_FONT_PATH = _default_gui_font_path()


def _gui_fallback_font_path_for_japanese() -> Path | None:
    """parameter_gui の日本語表示用フォールバックフォントを解決して返す。"""

    try:
        cfg = runtime_config()
        specified = cfg.parameter_gui_fallback_font_japanese
    except Exception:
        specified = None

    if specified:
        try:
            return resolve_font_path(str(specified))
        except Exception:
            return None

    for font in ("Hiragino Sans GB.ttc", "NotoSansJP-VariableFont_wght.ttf"):
        try:
            return resolve_font_path(str(font))
        except Exception:
            continue
    return None


def _compute_window_backing_scale(gui_window: Any) -> float:
    """ウィンドウの backing scale（DPI 倍率）を返す。"""

    scale = getattr(gui_window, "scale", None)
    if scale is not None:
        return float(max(float(scale), 1.0))

    get_pixel_ratio = getattr(gui_window, "get_pixel_ratio", None)
    if callable(get_pixel_ratio):
        return float(max(float(get_pixel_ratio()), 1.0))  # type: ignore[call-arg]

    return 1.0


class ParameterGUI:
    """pyimgui で ParamStore を編集するための最小 GUI。

    `draw_frame()` を呼ぶことで 1 フレーム分の UI を描画する。
    """

    def __init__(
        self,
        gui_window: Any,
        *,
        store: ParamStore,
        midi_controller: MidiController | None = None,
        monitor: Any | None = None,
        transport: TransportClock | None = None,
        transport_fps: float = 60.0,
        history: ParamStoreHistory | None = None,
        snapshot_slots: ParamSnapshotSlots | None = None,
        is_recording: Callable[[], bool] | None = None,
        title: str = "Parameters",
        column_weights: tuple[float, float, float, float] | None = None,
    ) -> None:
        """GUIをtransactionalに初期化し、途中失敗時も取得済みresourceを解放する。"""

        # `_initialize` が import/context/renderer/font の途中で失敗しても、
        # constructor は部分 object を caller へ返さない。close() は getattr
        # ベースなので、作成済みのものだけを安全に逆順 cleanup できる。
        self._window = gui_window
        self._closed = False
        try:
            self._initialize(
                gui_window,
                store=store,
                midi_controller=midi_controller,
                monitor=monitor,
                transport=transport,
                transport_fps=transport_fps,
                history=history,
                snapshot_slots=snapshot_slots,
                is_recording=is_recording,
                title=title,
                column_weights=column_weights,
            )
        except BaseException:
            try:
                self.close()
            except BaseException:
                # 初期化の根本例外を優先する。close() は全stepを既に試している。
                pass
            raise

    def _initialize(
        self,
        gui_window: Any,
        *,
        store: ParamStore,
        midi_controller: MidiController | None = None,
        monitor: Any | None = None,
        transport: TransportClock | None = None,
        transport_fps: float = 60.0,
        history: ParamStoreHistory | None = None,
        snapshot_slots: ParamSnapshotSlots | None = None,
        is_recording: Callable[[], bool] | None = None,
        title: str = "Parameters",
        column_weights: tuple[float, float, float, float] | None = None,
    ) -> None:
        """GUI の初期化本体（ImGui コンテキスト / renderer 作成）。"""

        import imgui  # type: ignore[import-untyped]

        # imgui の pyglet backend は環境によって import 経路が揺れるため、明示的にここで解決する。
        try:
            from imgui.integrations import (
                pyglet as imgui_pyglet,  # type: ignore[import-untyped]
            )
        except Exception as exc:
            raise RuntimeError(f"imgui.integrations.pyglet を import できない: {exc}")

        # GUI の描画対象となるウィンドウと、編集対象の ParamStore を保持する。
        self._window = gui_window
        self._store = store
        self._midi_controller = midi_controller
        self._monitor = monitor
        self._transport = transport
        self._transport_fps = float(transport_fps) if float(transport_fps) > 0.0 else 60.0
        self._history = history
        self._snapshot_slots = snapshot_slots
        self._is_recording = is_recording
        self._midi_learn_state = MidiLearnState()
        self._range_edit_last_seen_cc_seq = 0
        self._range_edit_prev_value_by_cc: dict[int, float] = {}
        self._range_edit_r_down = False
        self._range_edit_e_down = False
        self._range_edit_t_down = False
        self._range_edit_key_r = 0
        self._range_edit_key_e = 0
        self._range_edit_key_t = 0
        self._transport_key_space = 0
        self._transport_key_home = 0
        self._transport_key_left = 0
        self._transport_key_right = 0
        self._transport_key_slower = 0
        self._transport_key_faster = 0
        self._history_key_z = 0
        self._history_key_y = 0
        self._shortcut_modifier_mask = 0
        self._shortcut_shift_mask = 0
        self._show_inactive_params = False
        self._midi_clear_notice: str | None = None
        self._midi_clear_notice_token: tuple[int, int] | None = None
        self._title = str(title)
        cfg = runtime_config()
        self._font_size_base_px = float(cfg.parameter_gui_font_size_base_px)
        self._column_weights = (
            cfg.parameter_gui_table_column_weights if column_weights is None else column_weights
        )

        # ImGui は「グローバルな current context」を前提にするため、自前コンテキストを作って切り替えながら使う。
        self._imgui = imgui
        self._context = imgui.create_context()
        imgui.style_colors_dark()
        apply_parameter_gui_theme(imgui)
        imgui.set_current_context(self._context)
        _install_imgui_clipboard_callbacks(imgui)

        # pyglet は環境によって「座標系が backing pixel」になり得る。
        # その場合、Retina では物理サイズが小さく見えるため、フォント生成 px を DPI で補正する。
        imgui.get_io().font_global_scale = 1.0

        # ImGui の draw_data を実際に OpenGL へ流す renderer を作る。
        # ここで作られた renderer は内部に GL リソースを保持する。
        self._renderer = _create_imgui_pyglet_renderer(imgui_pyglet, gui_window)

        from pyglet.window import key as pyglet_key

        self._range_edit_key_r = int(pyglet_key.R)
        self._range_edit_key_e = int(pyglet_key.E)
        self._range_edit_key_t = int(pyglet_key.T)
        self._transport_key_space = int(pyglet_key.SPACE)
        self._transport_key_home = int(pyglet_key.HOME)
        self._transport_key_left = int(pyglet_key.LEFT)
        self._transport_key_right = int(pyglet_key.RIGHT)
        self._transport_key_slower = int(pyglet_key.BRACKETLEFT)
        self._transport_key_faster = int(pyglet_key.BRACKETRIGHT)
        self._history_key_z = int(pyglet_key.Z)
        self._history_key_y = int(pyglet_key.Y)
        self._shortcut_modifier_mask = int(pyglet_key.MOD_CTRL) | int(pyglet_key.MOD_COMMAND)
        self._shortcut_shift_mask = int(pyglet_key.MOD_SHIFT)
        self._window.push_handlers(
            on_key_press=self._on_key_press,
            on_key_release=self._on_key_release,
            on_deactivate=self._on_deactivate,
        )

        self._custom_font_path = _DEFAULT_GUI_FONT_PATH
        self._font_backing_scale: float | None = None
        self._font_fallback_path_for_japanese: Path | None = None
        self._font_sync_key: tuple[object, ...] | None = None
        self._sync_font_for_window()

        import time

        # ImGui に渡す delta_time 用の前回時刻。
        self._prev_time = time.monotonic()
        self._closed = False

    def _render_transport_toolbar(
        self,
        *,
        timeline_width: float | None = None,
        coordinate_scale: float = 1.0,
    ) -> None:
        """時間を止めて同じ frame を調整する transport 操作を描画する。"""

        transport = self._transport
        if transport is None:
            return

        imgui = self._imgui
        scale = max(1.0, float(coordinate_scale))
        snapshot = transport.snapshot()
        is_recording = getattr(self, "_is_recording", None)
        if is_recording is not None and is_recording():
            imgui.text_disabled(f"Transport locked  ·  {snapshot.t:.3f}s  ·  fixed 1x")
            return

        play_label = "Pause##transport_play" if snapshot.is_playing else "Play##transport_play"
        if _button_with_width(imgui, play_label, 54.0 * scale):
            transport.toggle()
        imgui.same_line()
        if _button_with_width(imgui, "Reset##transport_reset", 54.0 * scale):
            transport.reset()
        imgui.same_line()
        if _button_with_width(imgui, "-1f##transport_back", 39.0 * scale):
            transport.step_frame(fps=self._transport_fps, frames=-1)
        imgui.same_line()
        if _button_with_width(imgui, "+1f##transport_forward", 39.0 * scale):
            transport.step_frame(fps=self._transport_fps, frames=1)

        imgui.same_line()
        if _button_with_width(imgui, "-##transport_slower", 26.0 * scale):
            transport.set_speed(max(0.125, transport.speed / 2.0))
        _item_tooltip(imgui, "Slower · halve playback speed")
        imgui.same_line()
        imgui.text_disabled(f"{transport.speed:g}x")
        imgui.same_line()
        if _button_with_width(imgui, "+##transport_faster", 26.0 * scale):
            transport.set_speed(min(8.0, transport.speed * 2.0))
        _item_tooltip(imgui, "Faster · double playback speed")

        imgui.same_line()
        timeline_width_px = 160.0 * scale if timeline_width is None else float(timeline_width)
        imgui.set_next_item_width(float(timeline_width_px))
        changed_t, next_t = imgui.drag_float(
            "##transport_time",
            float(snapshot.t),
            0.01,
            0.0,
            0.0,
            "%.3f s",
        )
        if changed_t:
            transport.pause()
            transport.seek(float(next_t))

    def _render_history_toolbar(self) -> bool:
        """Undo/Redo と Snapshot A/B を描画し、store が変われば True を返す。"""

        history = getattr(self, "_history", None)
        slots = self._snapshot_slots
        if history is None or slots is None:
            return False

        imgui = self._imgui
        changed = False
        if imgui.button("Undo##param_undo"):
            changed = history.undo() or changed
        imgui.same_line()
        if imgui.button("Redo##param_redo"):
            changed = history.redo() or changed
        imgui.same_line()
        imgui.text_disabled(f"{history.undo_depth} / {history.redo_depth}")
        imgui.same_line()

        snapshot_slots: tuple[SnapshotSlot, SnapshotSlot] = ("A", "B")
        for index, slot in enumerate(snapshot_slots):
            if index > 0:
                imgui.same_line()
            if imgui.button(f"Save {slot}##snapshot_set_{slot}"):
                slots.capture(slot)
            imgui.same_line()
            slot_available = slots.has(slot)
            load_clicked = imgui.button(f"Load {slot}##snapshot_load_{slot}")
            if load_clicked and slot_available:
                with history.transaction(source=("snapshot", slot)):
                    changed = slots.restore(slot) or changed
        return changed

    def _render_controls_surface(
        self,
        *,
        controls_width: float,
        coordinate_scale: float,
    ) -> bool:
        """制作操作を TIME と HISTORY の2行へ意味的にまとめる。"""

        imgui = self._imgui
        changed = False
        if self._transport is not None:
            imgui.text_disabled("TIME")
            imgui.same_line()
            geometry = compute_transport_toolbar_geometry(
                float(controls_width),
                coordinate_scale=float(coordinate_scale),
            )
            self._render_transport_toolbar(
                timeline_width=geometry.timeline_width,
                coordinate_scale=float(coordinate_scale),
            )
        if self._history is not None and self._snapshot_slots is not None:
            imgui.text_disabled("HISTORY")
            imgui.same_line()
            changed = self._render_history_toolbar() or changed
        return changed

    def _render_toolbar_area(self, *, content_width: float, monitor_snapshot: Any | None) -> bool:
        """通常幅は Controls / Status 2列、狭幅は compact status を下へ積む。"""

        imgui = self._imgui
        coordinate_scale = _window_content_coordinate_scale(getattr(self, "_window", None))
        layout = compute_toolbar_layout(
            float(content_width),
            coordinate_scale=coordinate_scale,
        )
        changed = False

        controls_color = _begin_toolbar_surface(
            imgui,
            "##toolbar_controls_surface",
            layout.controls_width,
            layout.surface_height,
        )
        try:
            changed = (
                self._render_controls_surface(
                    controls_width=layout.controls_width,
                    coordinate_scale=layout.coordinate_scale,
                )
                or changed
            )
        finally:
            _end_toolbar_surface(imgui, color_pushed=controls_color)

        if not layout.stacked:
            _same_line_with_spacing(imgui, layout.gap)

        status_height = (
            32.0 * layout.coordinate_scale if layout.stacked else layout.surface_height
        )
        status_color = _begin_toolbar_surface(
            imgui,
            "##toolbar_status_surface",
            layout.status_width,
            status_height,
        )
        try:
            imgui.text_disabled("STATUS")
            if layout.stacked:
                imgui.same_line()
            if monitor_snapshot is not None:
                midi = self._midi_controller
                render_monitor_status(
                    imgui,
                    monitor_snapshot,
                    midi_port_name=None if midi is None else str(midi.port_name),
                    compact=layout.stacked,
                )
            else:
                imgui.text_disabled("No telemetry")
        finally:
            _end_toolbar_surface(imgui, color_pushed=status_color)
        return changed

    def _render_midi_clear_notice(self) -> bool:
        """全mapping解除後に、明示的な Undo 導線を全幅で表示する。"""

        notice = getattr(self, "_midi_clear_notice", None)
        if notice is None:
            return False

        imgui = self._imgui
        history = getattr(self, "_history", None)
        notice_token = getattr(self, "_midi_clear_notice_token", None)
        if history is not None and notice_token is not None:
            current_token = (int(history.undo_depth), int(self._store.revision))
            if current_token != notice_token:
                # Clear後に別編集が入った場合、そのUndoをClearのUndoと偽装しない。
                self._midi_clear_notice = None
                self._midi_clear_notice_token = None
                return False

        push = getattr(imgui, "push_style_color", None)
        pop = getattr(imgui, "pop_style_color", None)
        color_text = getattr(imgui, "COLOR_TEXT", None)
        colored = False
        if callable(push) and callable(pop) and color_text is not None:
            push(color_text, *PARAMETER_GUI_PALETTE["warning"])
            colored = True
        try:
            imgui.text(str(notice))
        finally:
            if colored and callable(pop):
                pop()

        if history is None or not history.can_undo:
            return False
        imgui.same_line()
        if not imgui.button("Undo##midi_clear_notice_undo"):
            return False
        changed = history.undo()
        self._midi_clear_notice = None
        self._midi_clear_notice_token = None
        return bool(changed)

    def _render_parameter_table_toolbar(self) -> bool:
        """Table固有のfilterとMIDI global commandをtable直上へ配置する。"""

        imgui = self._imgui
        imgui.text_disabled("PARAMETERS")
        imgui.same_line()
        _clicked, self._show_inactive_params = imgui.checkbox(
            "Show inactive##show_inactive_params",
            bool(self._show_inactive_params),
        )

        # MIDI は status へ混ぜず、assignment文脈の popup に閉じ込める。
        imgui.same_line()
        available_width = _available_content_width(imgui)
        get_cursor_x = getattr(imgui, "get_cursor_pos_x", None)
        set_cursor_x = getattr(imgui, "set_cursor_pos_x", None)
        if (
            available_width is not None
            and callable(get_cursor_x)
            and callable(set_cursor_x)
        ):
            coordinate_scale = _window_content_coordinate_scale(getattr(self, "_window", None))
            set_cursor_x(
                float(get_cursor_x())
                + max(0.0, available_width - 56.0 * coordinate_scale)
            )

        if imgui.button("MIDI##midi_menu"):
            open_popup = getattr(imgui, "open_popup", None)
            if callable(open_popup):
                open_popup("MIDI mappings##midi_menu_popup")

        begin_popup = getattr(imgui, "begin_popup", None)
        menu_item = getattr(imgui, "menu_item", None)
        if not callable(begin_popup) or not callable(menu_item):
            return False

        changed = False
        with begin_popup("MIDI mappings##midi_menu_popup") as popup:
            if not bool(getattr(popup, "opened", popup)):
                return False
            assignment_count = _midi_assignment_count(self._store)
            imgui.text_disabled(f"{assignment_count} mappings")
            separator = getattr(imgui, "separator", None)
            if callable(separator):
                separator()
            clear_clicked, _selected = menu_item(
                "Clear all mappings##clear_midi_assigns",
                enabled=assignment_count > 0,
            )
            if clear_clicked and assignment_count > 0:
                self._midi_learn_state.active_target = None
                self._midi_learn_state.active_component = None
                history = getattr(self, "_history", None)
                transaction = (
                    history.transaction(source="clear_all_midi")
                    if history is not None
                    else nullcontext()
                )
                with transaction:
                    changed = bool(clear_all_midi_assignments(self._store))
                if changed:
                    self._midi_clear_notice = "MIDI mappings cleared"
                    self._midi_clear_notice_token = (
                        None
                        if history is None
                        else (int(history.undo_depth), int(self._store.revision))
                    )
        return changed

    def _on_key_press(self, symbol: int | None, modifiers: int) -> None:
        if symbol is None:
            return
        symbol_i = int(symbol)

        try:
            io = self._imgui.get_io()
            if bool(io.want_text_input) or bool(io.want_capture_keyboard):
                return
        except Exception:
            pass

        # ImGui が text/control 入力を所有する間は R/E/T をテキスト
        # として扱う。capture 判定より前にこの flag を立てると、
        # focused input への入力が MIDI range edit も同時に起動してしまう。
        if symbol_i == int(self._range_edit_key_r):
            self._range_edit_r_down = True
        if symbol_i == int(self._range_edit_key_e):
            self._range_edit_e_down = True
        if symbol_i == int(self._range_edit_key_t):
            self._range_edit_t_down = True

        modifier_i = int(modifiers)
        shortcut_mask = int(getattr(self, "_shortcut_modifier_mask", 0))
        if shortcut_mask and modifier_i & shortcut_mask:
            history = getattr(self, "_history", None)
            if history is not None:
                if symbol_i == int(getattr(self, "_history_key_z", 0)):
                    if modifier_i & int(getattr(self, "_shortcut_shift_mask", 0)):
                        history.redo()
                    else:
                        history.undo()
                elif symbol_i == int(getattr(self, "_history_key_y", 0)):
                    history.redo()
            # Cmd/Ctrl を伴う OS/editor shortcut を transport として解釈しない。
            return

        transport = getattr(self, "_transport", None)
        if transport is None:
            return
        is_recording = getattr(self, "_is_recording", None)
        if is_recording is not None and is_recording():
            return
        if symbol_i == int(self._transport_key_space):
            transport.toggle()
        elif symbol_i == int(self._transport_key_home):
            transport.reset()
        elif symbol_i == int(self._transport_key_left):
            transport.step_frame(fps=self._transport_fps, frames=-1)
        elif symbol_i == int(self._transport_key_right):
            transport.step_frame(fps=self._transport_fps, frames=1)
        elif symbol_i == int(self._transport_key_slower):
            transport.set_speed(max(0.125, transport.speed / 2.0))
        elif symbol_i == int(self._transport_key_faster):
            transport.set_speed(min(8.0, transport.speed * 2.0))

    def _on_key_release(self, symbol: int | None, _modifiers: int) -> None:
        if symbol is None:
            return
        symbol_i = int(symbol)
        if symbol_i == int(self._range_edit_key_r):
            self._range_edit_r_down = False
        if symbol_i == int(self._range_edit_key_e):
            self._range_edit_e_down = False
        if symbol_i == int(self._range_edit_key_t):
            self._range_edit_t_down = False

    def _on_deactivate(self) -> None:
        self._range_edit_r_down = False
        self._range_edit_e_down = False
        self._range_edit_t_down = False

    def _maybe_apply_range_edit_by_midi(self) -> bool:
        """R キー + CC 入力で ui_min/ui_max を更新したら True を返す。"""

        midi = self._midi_controller
        if midi is None:
            return False

        last = midi.last_cc_change
        if last is None:
            return False

        seq, cc = last
        seq_i = int(seq)
        cc_i = int(cc)
        if seq_i <= int(self._range_edit_last_seen_cc_seq):
            return False
        self._range_edit_last_seen_cc_seq = int(seq_i)

        current = midi.cc.get(int(cc_i))
        if current is None:
            return False

        prev = float(self._range_edit_prev_value_by_cc.get(int(cc_i), float(current)))
        current_f = float(current)
        self._range_edit_prev_value_by_cc[int(cc_i)] = float(current_f)
        delta = float(current_f - prev)
        if delta == 0.0:
            return False

        if self._midi_learn_state.active_target is not None:
            return False

        mode: RangeEditMode
        if self._range_edit_e_down:
            mode = "min"
        elif self._range_edit_t_down:
            mode = "max"
        elif self._range_edit_r_down:
            mode = "shift"
        else:
            return False

        updated_any = False

        disable_keys = {
            (STYLE_OP, "global_thickness"),
            (LAYER_STYLE_OP, "line_thickness"),
        }

        snapshot = store_snapshot_for_gui(self._store)
        for key, (meta, state, _ordinal, _label) in snapshot.items():
            cc_key = state.cc_key
            if cc_key is None:
                continue
            if isinstance(cc_key, int):
                if int(cc_key) != int(cc_i):
                    continue
            else:
                if int(cc_i) not in {int(v) for v in cc_key if v is not None}:
                    continue

            if (str(key.op), str(key.arg)) in disable_keys:
                continue

            kind = str(meta.kind)
            if kind not in {"float", "int", "vec3"}:
                continue

            if meta.ui_min is None or meta.ui_max is None:
                continue

            ui_min_new, ui_max_new = apply_range_shift(
                kind=kind,
                ui_min=meta.ui_min,
                ui_max=meta.ui_max,
                delta=float(delta),
                mode=mode,
                sensitivity=1.0,
            )
            if ui_min_new == meta.ui_min and ui_max_new == meta.ui_max:
                continue

            set_meta(
                self._store,
                key,
                ParamMeta(
                    kind=str(meta.kind),
                    ui_min=ui_min_new,
                    ui_max=ui_max_new,
                    choices=meta.choices,
                ),
            )
            updated_any = True

        return bool(updated_any)

    def _sync_font_for_window(self) -> None:
        """ウィンドウの backing scale に合わせてフォントを同期する。"""

        if self._custom_font_path is None:
            return

        backing_scale = _compute_window_backing_scale(self._window)
        try:
            cfg = runtime_config()
            config_key: tuple[object, ...] = (
                id(cfg),
                cfg.config_path,
                cfg.parameter_gui_fallback_font_japanese,
                tuple(cfg.font_dirs),
            )
        except Exception:
            config_key = (None,)
        sync_key: tuple[object, ...] = (
            float(backing_scale),
            self._custom_font_path,
            float(self._font_size_base_px),
            config_key,
        )
        # フォント探索/resolve はディスクアクセスを含み得る。安定フレームでは行わず、
        # backing scale または runtime config が変わったときだけ再同期する。
        if getattr(self, "_font_sync_key", None) == sync_key:
            return
        fallback = _gui_fallback_font_path_for_japanese()

        io = self._imgui.get_io()
        io.fonts.clear()
        font_px = float(self._font_size_base_px * backing_scale)
        io.fonts.add_font_from_file_ttf(
            str(self._custom_font_path),
            float(font_px),
            glyph_ranges=io.fonts.get_glyph_ranges_default(),
        )

        if fallback is not None and fallback.is_file():
            try:
                if fallback.resolve() != self._custom_font_path.resolve():
                    cfg = self._imgui.core.FontConfig(merge_mode=True)
                    io.fonts.add_font_from_file_ttf(
                        str(fallback),
                        float(font_px),
                        font_config=cfg,
                        glyph_ranges=io.fonts.get_glyph_ranges_japanese(),
                    )
            except Exception:
                pass

        refresh_font = getattr(self._renderer, "refresh_font_texture", None)
        if callable(refresh_font):
            refresh_font()

        self._font_backing_scale = backing_scale
        self._font_fallback_path_for_japanese = fallback
        self._font_sync_key = sync_key

    def draw_frame(self) -> bool:
        """1 フレーム分の GUI を描画し、変更があれば store に反映する。

        `flip()` は呼ばない。呼び出し側が `window.flip()` を担当する。
        """

        # close() 済みなら何もしない。
        if self._closed:
            return False

        import time

        # 前フレームからの経過秒（ImGui の IO に渡す）。
        now = time.monotonic()
        dt = now - self._prev_time
        self._prev_time = now

        imgui = self._imgui

        # 以降の ImGui 呼び出しはこのインスタンスの context を対象にする。
        imgui.set_current_context(self._context)
        self._sync_font_for_window()

        # 注: 呼び出し側（pyglet.window.Window.draw）が事前に `self._window.switch_to()` 済みである前提。
        # ここで switch_to() を呼ぶと責務が分散し、点滅の原因（複数箇所での画面更新）になりやすい。

        # 注: imgui.integrations.pyglet の process_inputs() は内部で pyglet.clock.tick() を呼ぶ。
        # `pyglet.app.run()` 駆動時にこれを呼ぶと clock が二重に進みやすいので、ここでは呼ばない。
        # 入力イベント自体は pyglet のイベント配送で io に反映される前提。

        # Parameter GUI のスクロール方向を反転する。
        # pyglet backend は `io.mouse_wheel = scroll` をそのまま入れるため、
        # ここで「このフレームのホイールΔ」だけ符号反転して扱う。
        io = imgui.get_io()
        wheel = float(-float(io.mouse_wheel))
        wheel = max(-0.5, min(0.5, wheel))
        io.mouse_wheel = float(wheel)

        # --- ImGui フレーム開始 ---
        imgui.new_frame()

        # Δt / Retina スケール / サイズなどをウィンドウ状態に同期する。
        _sync_imgui_io_for_window(imgui, self._window, dt=dt)

        # GUI は 1 ウィンドウで全面表示する（位置/サイズ固定）。
        imgui.set_next_window_position(0, 0)
        imgui.set_next_window_size(self._window.width, self._window.height)
        imgui.begin(
            self._title,
            flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_TITLE_BAR,
        )

        monitor = self._monitor
        monitor_snapshot = None if monitor is None else monitor.snapshot()
        content_width = _available_content_width(imgui)
        if content_width is None:
            # Window padding は theme で左右16px。古い backend/test double でも
            # breakpoint と幅比率だけは同じ logical unit で保つ。
            content_width = max(0.0, float(self._window.width) - 32.0)
        changed_any = self._render_toolbar_area(
            content_width=float(content_width),
            monitor_snapshot=monitor_snapshot,
        )
        changed_any = self._render_midi_clear_notice() or changed_any
        if monitor_snapshot is not None:
            render_monitor_alerts(imgui, monitor_snapshot)

        # MIDI global command は独立した履歴単位にし、通常のparameter editと
        # coalesceさせない。filter自体はstoreを変更しない。
        changed_any = self._render_parameter_table_toolbar() or changed_any
        history = self._history
        transaction = (
            history.transaction(source="parameter_gui") if history is not None else nullcontext()
        )
        with transaction:
            changed_any = self._maybe_apply_range_edit_by_midi() or changed_any
            _section_separator(imgui)

            # ParamStore の表だけをスクロール領域に閉じ込め、監視バーは常に見えるようにする。
            imgui.begin_child("##parameter_table_scroll", 0, 0, border=False)
            try:
                # ParamStore をテーブルとして描画し、編集結果を store に反映する。
                changed_any = (
                    bool(
                        render_store_parameter_table(
                            self._store,
                            column_weights=self._column_weights,
                            show_inactive_params=bool(self._show_inactive_params),
                            midi_learn_state=self._midi_learn_state,
                            midi_last_cc_change=(
                                None
                                if self._midi_controller is None
                                else self._midi_controller.last_cc_change
                            ),
                        )
                    )
                    or changed_any
                )
            finally:
                imgui.end_child()
        if history is not None and not imgui.is_any_item_active():
            history.break_coalescing()
        imgui.end()

        # --- ImGui フレーム終了（draw_data 構築）---
        imgui.render()

        import pyglet

        # 背景をダークグレーでクリアし、その上に ImGui の draw_data を描く。
        pyglet.gl.glClearColor(0.12, 0.12, 0.12, 1.0)
        self._window.clear()
        self._renderer.render(imgui.get_draw_data())
        # `flip()` は MultiWindowLoop が担当する（ここでは呼ばない）。
        return bool(changed_any)

    def close(self) -> None:
        """GUI を終了し、コンテキストとウィンドウを破棄する。"""

        # 二重 close を許容する（呼び出し側の finally から安全に呼べるようにする）。
        if getattr(self, "_closed", False):
            return
        self._closed = True

        first_error: BaseException | None = None

        def _attempt(step: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                step()
            except BaseException as exc:
                # 1 つの teardown 失敗で後続 resource をリークさせない。
                if first_error is None:
                    first_error = exc

        window = getattr(self, "_window", None)
        switch_to = getattr(window, "switch_to", None)
        if callable(switch_to):
            # renderer.shutdown() が解放する GL resource の所有 context を
            # 必ず current にしてから backend を破棄する。
            _attempt(switch_to)

        renderer = getattr(self, "_renderer", None)
        shutdown = getattr(renderer, "shutdown", None)
        if callable(shutdown):
            _attempt(shutdown)

        imgui = getattr(self, "_imgui", None)
        context = getattr(self, "_context", None)
        destroy_context = getattr(imgui, "destroy_context", None)
        if callable(destroy_context) and context is not None:
            _attempt(lambda: destroy_context(context))

        close_window = getattr(window, "close", None)
        if callable(close_window):
            _attempt(close_window)

        if first_error is not None:
            raise first_error
