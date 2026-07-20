# どこで: `src/grafix/interactive/parameter_gui/gui.py`。
# 何を: ParamStore を pyimgui で編集するための最小 GUI（初期化/1フレーム描画/破棄）を提供する。
# なぜ: 依存の重いライフサイクル管理を 1 箇所に閉じ込め、他モジュールを純粋に保つため。

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from grafix.core.font_resolver import default_font_path, resolve_font_path
from grafix.core.lifecycle import CleanupErrors
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.effect_order_ops import (
    move_effect_step,
    reset_effect_order,
)
from grafix.core.parameters.favorites import favorite_parameter_key_set
from grafix.core.parameters.history import (
    ParamSnapshotSlots,
    ParamStoreHistory,
)
from grafix.core.parameters.reconcile_ops import (
    list_reconcile_orphans,
    manual_migrate_orphan,
)
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.variations import (
    create_variation,
    delete_variation,
    duplicate_variation,
    morph_variations,
    randomize_parameters,
    rename_variation,
    restore_variation,
    set_parameters_locked,
)
from grafix.core.parameters.view import ParameterRow
from grafix.core.runtime_config import RuntimeConfig
from grafix.core.value_validation import exact_string, finite_real
from grafix.interactive.midi import MidiSession
from grafix.interactive.runtime.frame_clock import TransportClock
from grafix.interactive.runtime.monitor import MonitorSnapshot, RuntimeMonitor

from .midi_learn import MidiLearnState
from .monitor_bar import monitor_alert_lines, render_monitor_alerts, render_monitor_status
from .diagnostics_panel import render_diagnostics_panel
from .help_pane import render_parameter_help_pane
from .profiler_panel import render_profiler_panel
from .parameter_filter import ParameterActivityFilter, ParameterFilterState
from .pyglet_backend import (
    _install_imgui_clipboard_callbacks,
    _sync_imgui_io_for_window,
    content_region_available_width,
    create_imgui_pyglet_renderer,
)
from .range_edit import (
    RangeEditMode,
    RangeEditSession,
    apply_range_edit_session,
    preview_range_edit,
    range_edit_session_for_store,
)
from .reconcile_panel import (
    ReconcileOrphanPanelModel,
    reconcile_orphan_panel_model,
    render_reconcile_orphan_popup,
)
from .shortcuts import resolve_shortcut_keys, shortcut_help_lines
from .store_bridge import (
    ParameterTableView,
    clear_all_midi_assignments,
    parameter_table_view_for_store,
    render_store_parameter_table,
    set_all_parameter_groups_collapsed,
)
from .table import EffectOrderCommand
from .theme import PARAMETER_GUI_PALETTE, apply_parameter_gui_theme
from .variation_panel import (
    VariationPanelState,
    VariationScopeSummary,
    VariationThumbnailCapture,
    VariationThumbnailPreview,
    normalize_variation_selection,
    variation_panel_model,
    variation_scope_summary,
)


_VARIATION_DELETE_POPUP_ID = "Delete variation##variation_delete_confirmation"
_TOOLBAR_LABEL_WIDTH_PX = 64.0
_BOTTOM_DRAWER_HEIGHT_PX = 176.0
_BOTTOM_DRAWER_GAP_PX = 10.0
_BOTTOM_DRAWER_HELP_RATIO = 0.58


def apply_effect_order_command(
    store: ParamStore,
    command: EffectOrderCommand,
) -> bool:
    """GUI-local commandをcoreのeffect順序operationへ渡す。"""

    if command.kind == "reset":
        return reset_effect_order(store, chain_id=command.chain_id)
    if (
        command.source is None
        or command.target is None
        or command.placement is None
    ):
        raise ValueError("move command requires source, target, and placement")
    return move_effect_step(
        store,
        chain_id=command.chain_id,
        source=command.source,
        target=command.target,
        placement=command.placement,
    )


def _positive_coordinate_scale(value: float) -> float:
    """正の coordinate scale を返し、不正値だけを 1.0 へ戻す。"""

    scale = float(value)
    return scale if scale > 0.0 else 1.0


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


@dataclass(frozen=True, slots=True)
class BottomDrawerGeometry:
    """固定 bottom drawer の高さと左右 pane 幅。"""

    height: float
    gap: float
    help_width: float
    runtime_width: float


def compute_bottom_drawer_geometry(
    content_width: float,
    *,
    coordinate_scale: float = 1.0,
) -> BottomDrawerGeometry:
    """幅変更から独立した drawer 高さと、Help / Runtime の幅を返す。"""

    width = max(0.0, float(content_width))
    scale = _positive_coordinate_scale(coordinate_scale)
    gap = min(width, _BOTTOM_DRAWER_GAP_PX * scale)
    panes_width = max(0.0, width - gap)
    help_width = panes_width * _BOTTOM_DRAWER_HELP_RATIO
    return BottomDrawerGeometry(
        height=_BOTTOM_DRAWER_HEIGHT_PX * scale,
        gap=gap,
        help_width=help_width,
        runtime_width=max(0.0, panes_width - help_width),
    )


def compute_transport_toolbar_geometry(
    controls_width: float,
    *,
    coordinate_scale: float = 1.0,
) -> TransportToolbarGeometry:
    """標準Inspectorでtimelineを160px以上確保する純粋なgeometry計算。"""

    width = max(0.0, float(controls_width))
    scale = _positive_coordinate_scale(coordinate_scale)
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
    scale = _positive_coordinate_scale(coordinate_scale)
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
            surface_height=66.0 * scale,
            coordinate_scale=scale,
        )
    return ToolbarLayout(
        stacked=True,
        controls_width=width,
        status_width=width,
        gap=6.0 * scale,
        # Compact status is rendered separately below, so two control rows do
        # not need the extra height reserved for the three-line desktop status.
        surface_height=56.0 * scale,
        coordinate_scale=scale,
    )


def _window_ui_coordinate_scale(window: Any, *, ui_scale: float = 1.0) -> float:
    """ウィンドウ幅と独立した ImGui 寸法倍率を返す。"""

    return _compute_window_backing_scale(window) * _positive_coordinate_scale(
        ui_scale
    )


def _same_line_with_spacing(imgui: Any, spacing: float) -> None:
    """明示的な group gap を作る。"""

    imgui.same_line(spacing=float(spacing))


def _same_line_at(imgui: Any, position: float) -> None:
    """同一 surface 内の固定 x へ次 item を揃える。"""

    imgui.same_line(position=float(position))


def _vertical_item_spacing(imgui: Any) -> float:
    """現在の style が child 間へ自動挿入する縦 spacing を返す。"""

    return max(0.0, float(imgui.get_style().item_spacing[1]))


def _button_with_width(imgui: Any, label: str, width: float) -> bool:
    """明示幅の button を描画する。"""

    return bool(imgui.button(str(label), float(width), 0.0))


def _item_tooltip(imgui: Any, text: str) -> None:
    """hoverまたはkeyboard focus中のitemへtooltipを表示する。"""

    if imgui.is_item_hovered() or imgui.is_item_focused():
        imgui.set_tooltip(str(text))


def _enable_keyboard_navigation(imgui: Any) -> bool:
    """ImGuiのTab/Enter navigation flagを有効化できたらTrueを返す。"""

    keyboard_nav = int(imgui.CONFIG_NAV_ENABLE_KEYBOARD)
    io = imgui.get_io()
    io.config_flags = int(io.config_flags) | keyboard_nav
    return True


def _begin_toolbar_surface(imgui: Any, label: str, width: float, height: float) -> None:
    """弱い surface 色を適用して child を開始する。"""

    imgui.push_style_color(
        imgui.COLOR_CHILD_BACKGROUND,
        *PARAMETER_GUI_PALETTE["surface"],
    )
    imgui.begin_child(str(label), float(width), float(height), border=False)


def _end_toolbar_surface(imgui: Any) -> None:
    imgui.end_child()
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

    imgui.separator()


def _default_gui_font_path() -> Path | None:
    try:
        return default_font_path()
    except OSError:
        return None


def _gui_fallback_font_path_for_japanese(
    effective_config: RuntimeConfig,
) -> Path | None:
    """parameter_gui の日本語表示用フォールバックフォントを解決して返す。"""

    specified = effective_config.parameter_gui_fallback_font_japanese
    if specified:
        try:
            return resolve_font_path(str(specified))
        except OSError:
            return None

    for font in ("Hiragino Sans GB.ttc", "NotoSansJP-VariableFont_wght.ttf"):
        try:
            return resolve_font_path(str(font))
        except OSError:
            continue
    return None


def _favorite_glyph_font_path() -> Path | None:
    """favorite の星 glyph を必ず持つ同梱フォントを返す。"""

    try:
        return resolve_font_path("NotoSansJP-Regular.ttf")
    except OSError:
        return None


def _compute_window_backing_scale(gui_window: Any) -> float:
    """ウィンドウの backing scale（DPI 倍率）を返す。"""

    return float(max(float(gui_window.scale), 1.0))


class ParameterGUI:
    """pyimgui で ParamStore を編集するための最小 GUI。

    `draw_frame()` を呼ぶことで 1 フレーム分の UI を描画する。
    """

    def __init__(
        self,
        gui_window: Any,
        *,
        effective_config: RuntimeConfig,
        store: ParamStore,
        midi_session: MidiSession | None = None,
        monitor: RuntimeMonitor | None = None,
        transport: TransportClock | None = None,
        transport_fps: float = 60.0,
        history: ParamStoreHistory | None = None,
        snapshot_slots: ParamSnapshotSlots | None = None,
        is_recording: Callable[[], bool] | None = None,
        variation_thumbnail_capture: VariationThumbnailCapture | None = None,
        variation_thumbnail_preview: VariationThumbnailPreview | None = None,
        ui_scale: float = 1.0,
        title: str = "Parameters",
    ) -> None:
        """GUIをtransactionalに初期化し、途中失敗時も取得済みresourceを解放する。"""

        frame_rate = finite_real(
            transport_fps,
            name="transport_fps",
            minimum=0.0,
            minimum_inclusive=False,
        )
        scale = finite_real(
            ui_scale,
            name="ui_scale",
            minimum=0.0,
            minimum_inclusive=False,
        )
        window_title = exact_string(title, name="title")
        if not window_title:
            raise ValueError("title は空にできません")
        # `_initialize` が import/context/renderer/font の途中で失敗しても、
        # constructor は部分 object を caller へ返さない。close() は getattr
        # ベースなので、作成済みのものだけを安全に逆順 cleanup できる。
        self._window = gui_window
        self._closed = False
        try:
            self._initialize(
                gui_window,
                effective_config=effective_config,
                store=store,
                midi_session=midi_session,
                monitor=monitor,
                transport=transport,
                transport_fps=frame_rate,
                history=history,
                snapshot_slots=snapshot_slots,
                is_recording=is_recording,
                variation_thumbnail_capture=variation_thumbnail_capture,
                variation_thumbnail_preview=variation_thumbnail_preview,
                ui_scale=scale,
                title=window_title,
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
        effective_config: RuntimeConfig,
        store: ParamStore,
        midi_session: MidiSession | None = None,
        monitor: RuntimeMonitor | None = None,
        transport: TransportClock | None = None,
        transport_fps: float = 60.0,
        history: ParamStoreHistory | None = None,
        snapshot_slots: ParamSnapshotSlots | None = None,
        is_recording: Callable[[], bool] | None = None,
        variation_thumbnail_capture: VariationThumbnailCapture | None = None,
        variation_thumbnail_preview: VariationThumbnailPreview | None = None,
        ui_scale: float = 1.0,
        title: str = "Parameters",
    ) -> None:
        """GUI の初期化本体（ImGui コンテキスト / renderer 作成）。"""

        import imgui

        # GUI の描画対象となるウィンドウと、編集対象の ParamStore を保持する。
        self._window = gui_window
        self._effective_config = effective_config
        self._store = store
        self._midi_session = midi_session
        self._monitor = monitor
        self._transport = transport
        self._transport_fps = transport_fps
        self._history = history
        self._snapshot_slots = snapshot_slots
        self._is_recording = is_recording
        self._variation_thumbnail_capture = variation_thumbnail_capture
        self._variation_thumbnail_preview = variation_thumbnail_preview
        self._variation_panel_state = VariationPanelState()
        self._midi_learn_state = MidiLearnState()
        self._range_edit_last_seen_cc_seq = 0
        self._range_edit_prev_value_by_cc: dict[int, float] = {}
        self._range_edit_mode: RangeEditMode | None = None
        self._range_edit_session: RangeEditSession | None = None
        self._range_edit_key_r = 0
        self._range_edit_key_e = 0
        self._range_edit_key_t = 0
        self._range_edit_key_escape = 0
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
        self._parameter_filter_state = ParameterFilterState()
        self._parameter_table_view: ParameterTableView | None = None
        self._favorite_parameter_keys = favorite_parameter_key_set(store)
        self._parameter_error_keys: frozenset[ParameterKey] = frozenset()
        self._parameter_help_row: ParameterRow | None = None
        self._parameter_edit_active = False
        self._reconcile_orphan_model: ReconcileOrphanPanelModel = reconcile_orphan_panel_model(
            list_reconcile_orphans(store)
        )
        self._reconcile_error: str | None = None
        self._midi_clear_notice: str | None = None
        self._midi_clear_notice_token: tuple[int, int] | None = None
        self._title = title
        self._ui_scale = ui_scale
        self._font_size_base_px = (
            float(effective_config.parameter_gui_font_size_base_px) * self._ui_scale
        )
        self._shortcut_bindings = effective_config.parameter_gui_shortcuts

        # ImGui は「グローバルな current context」を前提にするため、自前コンテキストを作って切り替えながら使う。
        self._imgui = imgui
        self._context = imgui.create_context()
        imgui.style_colors_dark()
        apply_parameter_gui_theme(imgui, ui_scale=self._ui_scale)
        imgui.set_current_context(self._context)
        _install_imgui_clipboard_callbacks(imgui)

        # pyglet は環境によって「座標系が backing pixel」になり得る。
        # その場合、Retina では物理サイズが小さく見えるため、フォント生成 px を DPI で補正する。
        io = imgui.get_io()
        io.font_global_scale = 1.0
        _enable_keyboard_navigation(imgui)

        # ImGui の draw_data を実際に OpenGL へ流す renderer を作る。
        # ここで作られた renderer は内部に GL リソースを保持する。
        self._renderer = create_imgui_pyglet_renderer(gui_window)

        from pyglet.window import key as pyglet_key

        shortcut_keys = resolve_shortcut_keys(
            self._shortcut_bindings,
            key_namespace=pyglet_key,
        )
        self._range_edit_key_r = shortcut_keys["range_shift"]
        self._range_edit_key_e = shortcut_keys["range_min"]
        self._range_edit_key_t = shortcut_keys["range_max"]
        self._range_edit_key_escape = shortcut_keys["cancel"]
        self._transport_key_space = shortcut_keys["play_pause"]
        self._transport_key_home = shortcut_keys["reset_time"]
        self._transport_key_left = shortcut_keys["step_backward"]
        self._transport_key_right = shortcut_keys["step_forward"]
        self._transport_key_slower = shortcut_keys["slower"]
        self._transport_key_faster = shortcut_keys["faster"]
        self._history_key_z = shortcut_keys["undo"]
        self._history_key_y = shortcut_keys["redo"]
        self._shortcut_modifier_mask = int(pyglet_key.MOD_CTRL) | int(pyglet_key.MOD_COMMAND)
        self._shortcut_shift_mask = int(pyglet_key.MOD_SHIFT)
        self._window.push_handlers(
            on_key_press=self._on_key_press,
            on_deactivate=self._on_deactivate,
        )

        self._custom_font_path = _default_gui_font_path()
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
        is_recording = self._is_recording
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

    def _variation_state(self) -> VariationPanelState:
        return self._variation_panel_state

    def _variation_scope_summary(self) -> VariationScopeSummary:
        """現在の favorite/filter selection から探索 scope を返す。"""

        state = self._variation_state()
        view = parameter_table_view_for_store(
            self._store,
            show_inactive_params=bool(self._show_inactive_params),
            filter_state=self._parameter_filter_state,
            error_keys=self._parameter_error_keys,
            favorite_keys=favorite_parameter_key_set(self._store),
        )
        return variation_scope_summary(self._store, view, state.scope)

    def _save_named_variation(self) -> bool:
        state = self._variation_state()
        name = state.new_name.strip()
        if not name:
            state.notice = "Enter a variation name before saving."
            return False
        if name in variation_panel_model(self._store).names:
            state.notice = f"Variation already exists: {name}."
            return False

        thumbnail_path: str | Path | None = None
        thumbnail_error: str | None = None
        capture = self._variation_thumbnail_capture
        if callable(capture):
            try:
                thumbnail_path = capture(name)
            except Exception as exc:
                # CaptureService boundary の失敗で parameter snapshot 自体を失わない。
                thumbnail_error = str(exc)

        transport = self._transport
        t = None if transport is None else float(transport.snapshot().t)
        try:
            variation = create_variation(
                self._store,
                name,
                note=state.new_note,
                seed=int(state.random_seed) if state.include_seed else None,
                t=t,
                thumbnail_path=thumbnail_path,
            )
        except (KeyError, TypeError, ValueError) as exc:
            state.notice = f"Could not save variation: {exc}"
            return False

        state.selected_name = variation.name
        state.target_name = variation.name
        state.duplicate_name = f"{variation.name} copy"
        state.morph_a = normalize_variation_selection(
            variation_panel_model(self._store).names,
            state.morph_a,
        )
        state.new_name = ""
        state.new_note = ""
        state.notice = (
            f"Saved {variation.name}; thumbnail failed: {thumbnail_error}"
            if thumbnail_error
            else f"Saved {variation.name}."
        )
        return True

    def _load_named_variation(self, name: str) -> bool:
        state = self._variation_state()
        try:
            changed = restore_variation(
                self._store,
                name,
                history=self._history,
            )
        except (KeyError, TypeError, ValueError) as exc:
            state.notice = f"Could not load variation: {exc}"
            return False
        self._parameter_table_view = None
        state.notice = (
            f"Loaded {name}." if changed else f"{name} already matches the current values."
        )
        return changed

    def _rename_selected_variation(self) -> bool:
        state = self._variation_state()
        if state.selected_name is None:
            state.notice = "Select a variation to rename."
            return False
        previous = state.selected_name
        try:
            renamed = rename_variation(self._store, previous, state.target_name)
        except (KeyError, TypeError, ValueError) as exc:
            state.notice = f"Could not rename variation: {exc}"
            return False
        state.selected_name = renamed.name
        state.target_name = renamed.name
        state.duplicate_name = f"{renamed.name} copy"
        if state.morph_a == previous:
            state.morph_a = renamed.name
        if state.morph_b == previous:
            state.morph_b = renamed.name
        state.notice = f"Renamed {previous} to {renamed.name}."
        return renamed.name != previous

    def _duplicate_selected_variation(self) -> bool:
        state = self._variation_state()
        if state.selected_name is None:
            state.notice = "Select a variation to duplicate."
            return False
        try:
            duplicate = duplicate_variation(
                self._store,
                state.selected_name,
                state.duplicate_name,
            )
        except (KeyError, TypeError, ValueError) as exc:
            state.notice = f"Could not duplicate variation: {exc}"
            return False
        state.selected_name = duplicate.name
        state.target_name = duplicate.name
        state.duplicate_name = f"{duplicate.name} copy"
        state.notice = f"Duplicated as {duplicate.name}."
        return True

    def _request_delete_selected_variation(self) -> bool:
        """選択中 variation を確認対象へ固定し、まだ削除は行わない。"""

        state = self._variation_state()
        name = state.selected_name
        if name is None:
            state.notice = "Select a variation to delete."
            return False
        state.pending_delete_name = name
        return True

    def _confirm_delete_pending_variation(self) -> bool:
        """確認 modal が固定した variation だけを削除する。"""

        state = self._variation_state()
        name = state.pending_delete_name
        state.pending_delete_name = None
        if name is None:
            state.notice = "No variation is awaiting deletion."
            return False
        if not delete_variation(self._store, name):
            state.notice = f"Variation no longer exists: {name}."
            return False
        names = variation_panel_model(self._store).names
        state.selected_name = normalize_variation_selection(names, None)
        state.target_name = "" if state.selected_name is None else state.selected_name
        state.duplicate_name = (
            "" if state.selected_name is None else f"{state.selected_name} copy"
        )
        state.morph_a = normalize_variation_selection(names, state.morph_a)
        state.morph_b = normalize_variation_selection(names, state.morph_b)
        state.notice = f"Deleted {name}."
        return True

    def _render_variation_delete_confirmation(self) -> bool:
        """削除対象名と不可逆性を示す modal を描画する。"""

        imgui = self._imgui
        state = self._variation_state()
        changed = False
        with imgui.begin_popup_modal(_VARIATION_DELETE_POPUP_ID) as popup:
            if not popup.opened:
                return False
            name = state.pending_delete_name
            if name is None:
                imgui.text_disabled("The selected variation is no longer available.")
                if imgui.button("Close##variation_delete_missing"):
                    imgui.close_current_popup()
                return False

            imgui.text_wrapped(f'Delete variation "{name}"?')
            imgui.text_disabled("This cannot be undone.")
            if imgui.button("Cancel##variation_delete_cancel"):
                state.pending_delete_name = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Delete permanently##variation_delete_confirm"):
                changed = self._confirm_delete_pending_variation()
                imgui.close_current_popup()
        return changed

    def _randomize_variation_scope(self) -> bool:
        state = self._variation_state()
        scope = self._variation_scope_summary()
        if not scope.keys:
            state.notice = f"No parameters in {scope.scope} scope."
            return False
        if scope.locked_count == scope.parameter_count:
            state.notice = (
                f"All {scope.parameter_count} parameters in {scope.scope} scope are locked; "
                "nothing was randomized."
            )
            return False
        changed = randomize_parameters(
            self._store,
            scope.keys,
            seed=int(state.random_seed),
            history=self._history,
        )
        self._parameter_table_view = None
        if changed:
            state.notice = (
                f"Randomized {len(changed)} / {scope.parameter_count} parameters "
                f"with seed {state.random_seed}."
            )
        else:
            state.notice = (
                f"No eligible unlocked numeric parameters in {scope.scope} scope; "
                "nothing was randomized."
            )
        return bool(changed)

    def _set_variation_scope_locked(self, *, locked: bool) -> bool:
        state = self._variation_state()
        scope = self._variation_scope_summary()
        if not scope.keys:
            state.notice = f"No parameters in {scope.scope} scope."
            return False
        if locked and scope.locked_count == scope.parameter_count:
            state.notice = (
                f"All {scope.parameter_count} parameters in {scope.scope} scope "
                "are already locked."
            )
            return False
        if not locked and scope.locked_count == 0:
            state.notice = f"No parameters in {scope.scope} scope are locked."
            return False
        changed = set_parameters_locked(
            self._store,
            scope.keys,
            locked=bool(locked),
        )
        self._parameter_table_view = None
        if changed:
            state.notice = (
                f"{'Locked' if locked else 'Unlocked'} {len(changed)} parameters "
                f"in {scope.scope} scope."
            )
        else:
            state.notice = f"No lock state changed in {scope.scope} scope."
        return bool(changed)

    def _morph_variation_scope(self) -> bool:
        state = self._variation_state()
        if state.morph_a is None or state.morph_b is None:
            state.notice = "Save and select two variations before morphing."
            return False
        if state.morph_a == state.morph_b:
            state.notice = "Choose two different variations to morph."
            return False
        scope = self._variation_scope_summary()
        if not scope.keys:
            state.notice = f"No parameters in {scope.scope} scope; nothing was morphed."
            return False
        if scope.locked_count == scope.parameter_count:
            state.notice = (
                f"All {scope.parameter_count} parameters in {scope.scope} scope are locked; "
                "nothing was morphed."
            )
            return False
        try:
            changed = morph_variations(
                self._store,
                state.morph_a,
                state.morph_b,
                float(state.morph_amount),
                keys=scope.keys,
                history=self._history,
            )
        except (KeyError, TypeError, ValueError) as exc:
            state.notice = f"Could not morph variations: {exc}"
            return False
        self._parameter_table_view = None
        if changed:
            state.notice = (
                f"Morphed {len(changed)} parameters at {state.morph_amount:.2f}."
            )
        else:
            state.notice = (
                f"No compatible unlocked parameters in {scope.scope} scope; "
                "nothing was morphed."
            )
        return bool(changed)

    def _render_variation_combo(
        self,
        label: str,
        names: tuple[str, ...],
        selected: str | None,
    ) -> str | None:
        imgui = self._imgui
        selection = normalize_variation_selection(names, selected)
        with imgui.begin_combo(label, selection or "(none)") as combo:
            if combo.opened:
                for name in names:
                    clicked, _selected = imgui.selectable(
                        f"{name}##{label}_{name}",
                        name == selection,
                    )
                    if clicked:
                        selection = name
                    if name == selection:
                        imgui.set_item_default_focus()
        return selection

    def _render_variation_popup(self) -> bool:
        """named variation と探索操作を一つの popup に描画する。"""

        imgui = self._imgui
        state = self._variation_state()
        model = variation_panel_model(self._store)
        names = model.names
        previous_selection = state.selected_name
        state.selected_name = normalize_variation_selection(names, state.selected_name)
        if state.selected_name is not None and (
            state.selected_name != previous_selection or not state.target_name
        ):
            state.target_name = state.selected_name
        if state.selected_name is not None and (
            state.selected_name != previous_selection or not state.duplicate_name
        ):
            state.duplicate_name = f"{state.selected_name} copy"
        state.morph_a = normalize_variation_selection(names, state.morph_a)
        state.morph_b = normalize_variation_selection(names, state.morph_b)
        if len(names) > 1 and state.morph_b == state.morph_a:
            state.morph_b = names[1] if names[0] == state.morph_a else names[0]

        changed = False
        imgui.text("Save current variation")
        _name_changed, state.new_name = imgui.input_text(
            "Name##variation_new_name",
            state.new_name,
        )
        _note_changed, state.new_note = imgui.input_text(
            "Note##variation_new_note",
            state.new_note,
        )
        _seed_enabled_changed, state.include_seed = imgui.checkbox(
            "Store seed##variation_include_seed",
            state.include_seed,
        )
        imgui.same_line()
        _seed_changed, state.random_seed = imgui.input_int(
            "Seed##variation_seed",
            int(state.random_seed),
        )
        if imgui.button("Save current##variation_save"):
            changed = self._save_named_variation() or changed

        imgui.separator()
        imgui.text("Explore scope")
        if imgui.button(
            ("[Filtered]" if state.scope == "filtered" else "Filtered")
            + "##variation_scope_filtered"
        ):
            state.scope = "filtered"
        imgui.same_line()
        if imgui.button(
            ("[Favorites]" if state.scope == "favorites" else "Favorites")
            + "##variation_scope_favorites"
        ):
            state.scope = "favorites"
        scope = self._variation_scope_summary()
        imgui.same_line()
        imgui.text_disabled(
            f"{scope.parameter_count} parameters  ·  {scope.locked_count} locked"
        )
        _random_seed_changed, state.random_seed = imgui.input_int(
            "Random seed##variation_random_seed",
            int(state.random_seed),
        )
        if imgui.button("Randomize##variation_randomize"):
            changed = self._randomize_variation_scope() or changed
        imgui.same_line()
        if imgui.button("Lock scope##variation_lock_scope"):
            changed = self._set_variation_scope_locked(locked=True) or changed
        imgui.same_line()
        if imgui.button("Unlock scope##variation_unlock_scope"):
            changed = self._set_variation_scope_locked(locked=False) or changed

        imgui.separator()
        imgui.text("Morph named variations")
        state.morph_a = self._render_variation_combo(
            "A##variation_morph_a",
            names,
            state.morph_a,
        )
        imgui.same_line()
        state.morph_b = self._render_variation_combo(
            "B##variation_morph_b",
            names,
            state.morph_b,
        )
        _amount_changed, state.morph_amount = imgui.slider_float(
            "Amount##variation_morph_amount",
            float(state.morph_amount),
            0.0,
            1.0,
        )
        if imgui.button("Apply morph##variation_morph_apply"):
            changed = self._morph_variation_scope() or changed

        imgui.separator()
        imgui.text(f"Saved variations ({model.count})")
        if not model.items:
            imgui.text_disabled(model.empty_message)
        for index, item in enumerate(model.items):
            selected = item.name == state.selected_name
            if imgui.button(
                f"{'>' if selected else ' '} {item.name}##variation_select_{index}"
            ):
                state.selected_name = item.name
                state.target_name = item.name
                state.duplicate_name = f"{item.name} copy"
            imgui.same_line()
            seed_label = "none" if item.seed is None else str(item.seed)
            imgui.text_disabled(
                f"{item.timestamp}  ·  seed {seed_label}  ·  {item.diff_count} diffs"
            )
            if item.note:
                imgui.text_wrapped(item.note)
            if item.thumbnail_path is not None:
                preview = self._variation_thumbnail_preview
                if callable(preview):
                    try:
                        preview(imgui, item.thumbnail_path)
                    except Exception as exc:
                        imgui.text_disabled(f"Thumbnail unavailable: {exc}")
                else:
                    imgui.text_disabled(f"Thumbnail: {item.thumbnail_path}")

        if state.selected_name is not None:
            imgui.separator()
            imgui.text(f"Selected: {state.selected_name}")
            _target_changed, state.target_name = imgui.input_text(
                "Rename to##variation_target_name",
                state.target_name,
            )
            _duplicate_changed, state.duplicate_name = imgui.input_text(
                "Duplicate as##variation_duplicate_name",
                state.duplicate_name,
            )
            if imgui.button("Load##variation_load"):
                changed = self._load_named_variation(state.selected_name) or changed
            imgui.same_line()
            if imgui.button("Rename##variation_rename"):
                changed = self._rename_selected_variation() or changed
            imgui.same_line()
            if imgui.button("Duplicate##variation_duplicate"):
                changed = self._duplicate_selected_variation() or changed
            imgui.same_line()
            if imgui.button("Delete##variation_delete"):
                if self._request_delete_selected_variation():
                    imgui.open_popup(_VARIATION_DELETE_POPUP_ID)

        changed = self._render_variation_delete_confirmation() or changed

        if state.notice:
            imgui.separator()
            imgui.text_disabled(state.notice)
        return changed

    def _render_history_toolbar(self) -> bool:
        """Undo/Redo と named variation popup を描画する。"""

        history = self._history
        if history is None:
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

        store = self._store
        variation_count = len(store._variations_ref())
        if imgui.button(f"Variations {variation_count}##variation_popup_button"):
            imgui.open_popup("Named variations##variation_popup")
        with imgui.begin_popup("Named variations##variation_popup") as popup:
            if popup.opened:
                changed = self._render_variation_popup() or changed
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
        label_width = _TOOLBAR_LABEL_WIDTH_PX * float(coordinate_scale)
        if self._transport is not None:
            imgui.align_text_to_frame_padding()
            imgui.text_disabled("TIME")
            _same_line_at(imgui, label_width)
            geometry = compute_transport_toolbar_geometry(
                float(controls_width),
                coordinate_scale=float(coordinate_scale),
            )
            self._render_transport_toolbar(
                timeline_width=geometry.timeline_width,
                coordinate_scale=float(coordinate_scale),
            )
        if self._history is not None:
            imgui.align_text_to_frame_padding()
            imgui.text_disabled("HISTORY")
            _same_line_at(imgui, label_width)
            changed = self._render_history_toolbar() or changed
        return changed

    def _render_toolbar_area(
        self,
        *,
        content_width: float,
        monitor_snapshot: MonitorSnapshot | None,
    ) -> bool:
        """通常幅は Controls / Status 2列、狭幅は compact status を下へ積む。"""

        imgui = self._imgui
        coordinate_scale = _window_ui_coordinate_scale(
            self._window,
            ui_scale=float(self._ui_scale),
        )
        layout = compute_toolbar_layout(
            float(content_width),
            coordinate_scale=coordinate_scale,
        )
        changed = False

        _begin_toolbar_surface(
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
            _end_toolbar_surface(imgui)

        if not layout.stacked:
            _same_line_with_spacing(imgui, layout.gap)

        status_height = (
            30.0 * layout.coordinate_scale if layout.stacked else layout.surface_height
        )
        _begin_toolbar_surface(
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
                midi = self._midi_session
                render_monitor_status(
                    imgui,
                    monitor_snapshot,
                    midi_status=None if midi is None else midi.status_label,
                    compact=layout.stacked,
                )
            else:
                imgui.text_disabled("No telemetry")
        finally:
            _end_toolbar_surface(imgui)
        return changed

    def _render_shortcut_help(self) -> None:
        """configから読んだParameter GUI shortcut一覧をpopup表示する。"""

        imgui = self._imgui
        if not imgui.button("Shortcuts##shortcut_help"):
            pass
        else:
            imgui.open_popup("Parameter GUI shortcuts##shortcut_help_popup")
        with imgui.begin_popup("Parameter GUI shortcuts##shortcut_help_popup") as popup:
            if not popup.opened:
                return
            for line in shortcut_help_lines(self._shortcut_bindings):
                imgui.text(str(line))

    def _render_midi_clear_notice(self) -> bool:
        """全mapping解除後に、明示的な Undo 導線を全幅で表示する。"""

        notice = self._midi_clear_notice
        if notice is None:
            return False

        imgui = self._imgui
        history = self._history
        notice_token = self._midi_clear_notice_token
        if history is not None and notice_token is not None:
            current_token = (int(history.undo_depth), int(self._store.revision))
            if current_token != notice_token:
                # Clear後に別編集が入った場合、そのUndoをClearのUndoと偽装しない。
                self._midi_clear_notice = None
                self._midi_clear_notice_token = None
                return False

        imgui.push_style_color(imgui.COLOR_TEXT, *PARAMETER_GUI_PALETTE["warning"])
        try:
            imgui.text(str(notice))
        finally:
            imgui.pop_style_color()

        if history is None or not history.can_undo:
            return False
        imgui.same_line()
        if not imgui.button("Undo##midi_clear_notice_undo"):
            return False
        changed = history.undo()
        self._midi_clear_notice = None
        self._midi_clear_notice_token = None
        return bool(changed)

    def _render_midi_mapping_menu(self) -> bool:
        """主操作行の右端に MIDI assignment menu を描画する。"""

        imgui = self._imgui
        imgui.same_line()
        available_width = content_region_available_width(imgui)
        coordinate_scale = _window_ui_coordinate_scale(
            self._window,
            ui_scale=float(self._ui_scale),
        )
        imgui.set_cursor_pos_x(
            float(imgui.get_cursor_pos_x())
            + max(0.0, available_width - 56.0 * coordinate_scale)
        )

        if imgui.button("MIDI##midi_menu"):
            imgui.open_popup("MIDI mappings##midi_menu_popup")

        changed = False
        with imgui.begin_popup("MIDI mappings##midi_menu_popup") as popup:
            if not popup.opened:
                return False

            assignment_count = _midi_assignment_count(self._store)
            session = self._midi_session
            status = "MIDI OFF" if session is None else session.status_label
            imgui.text_disabled(f"{status}  ·  {assignment_count} mappings")
            imgui.separator()
            reconnect_clicked, _selected = imgui.menu_item(
                "Reconnect##midi_reconnect",
                enabled=session is not None and session.state != "live",
            )
            if reconnect_clicked and session is not None:
                session.reconnect()
            clear_frozen_clicked, _selected = imgui.menu_item(
                "Clear frozen snapshot##midi_clear_frozen",
                enabled=session is not None and session.state == "frozen",
            )
            if clear_frozen_clicked and session is not None:
                session.clear_frozen_snapshot()
            clear_clicked, _selected = imgui.menu_item(
                "Clear all mappings##clear_midi_assigns",
                enabled=assignment_count > 0,
            )
            if clear_clicked and assignment_count > 0:
                self._midi_learn_state.active_target = None
                self._midi_learn_state.active_component = None
                history = self._history
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

    def _render_parameter_table_toolbar(self) -> bool:
        """Table固有のfilterとMIDI global commandをtable直上へ配置する。"""

        imgui = self._imgui
        self._favorite_parameter_keys = favorite_parameter_key_set(self._store)
        state = self._parameter_filter_state
        imgui.align_text_to_frame_padding()
        imgui.text_disabled("PARAMETERS")

        imgui.same_line()
        coordinate_scale = _window_ui_coordinate_scale(
            self._window,
            ui_scale=float(self._ui_scale),
        )
        imgui.set_next_item_width(260.0 * coordinate_scale)
        query_changed, query = imgui.input_text_with_hint(
            "##parameter_search",
            "Search label, op, arg, source, MIDI CC",
            str(state.query),
        )
        if query_changed:
            state = replace(state, query=str(query))

        imgui.same_line()
        _clicked, self._show_inactive_params = imgui.checkbox(
            "Show inactive##show_inactive_params",
            bool(self._show_inactive_params),
        )

        # 詳細 filter は popup にまとめ、検索欄と MIDI command の幅を確保する。
        imgui.same_line()
        enabled_filter_count = sum(
            (
                state.activity != "all",
                bool(state.ui_override_only),
                bool(state.midi_mapped_only),
                bool(state.error_only),
                bool(state.favorite_only),
            )
        )
        filter_button = (
            "Filters"
            if enabled_filter_count == 0
            else f"Filters {enabled_filter_count}"
        )
        if imgui.button(f"{filter_button}##parameter_filter_menu"):
            imgui.open_popup("Parameter filters##parameter_filter_popup")

        def menu_clicked(
            label: str,
            *,
            selected: bool,
            enabled: bool = True,
        ) -> bool:
            clicked, _selected = imgui.menu_item(
                label,
                None,
                bool(selected),
                bool(enabled),
            )
            return bool(clicked)

        with imgui.begin_popup("Parameter filters##parameter_filter_popup") as popup:
            if popup.opened:
                activity_options: tuple[
                    tuple[str, ParameterActivityFilter], ...
                ] = (
                    ("All activity##filter_activity_all", "all"),
                    ("Active only##filter_activity_active", "active"),
                    ("Inactive only##filter_activity_inactive", "inactive"),
                )
                for label, activity in activity_options:
                    if menu_clicked(
                        label,
                        selected=state.activity == activity,
                    ):
                        state = replace(state, activity=activity)
                        if activity == "inactive":
                            # 選択直後に空結果に見えないよう、既存 visibility gate も開く。
                            self._show_inactive_params = True
                imgui.separator()
                boolean_filters = (
                    ("UI override##filter_ui_override", "ui_override_only"),
                    ("MIDI mapped##filter_midi_mapped", "midi_mapped_only"),
                    ("Error##filter_error", "error_only"),
                    ("Favorite##filter_favorite", "favorite_only"),
                )
                for label, field in boolean_filters:
                    if field == "ui_override_only":
                        selected = state.ui_override_only
                    elif field == "midi_mapped_only":
                        selected = state.midi_mapped_only
                    elif field == "error_only":
                        selected = state.error_only
                    else:
                        selected = state.favorite_only
                    if menu_clicked(label, selected=selected):
                        if field == "ui_override_only":
                            state = replace(state, ui_override_only=not selected)
                        elif field == "midi_mapped_only":
                            state = replace(state, midi_mapped_only=not selected)
                        elif field == "error_only":
                            state = replace(state, error_only=not selected)
                        else:
                            state = replace(state, favorite_only=not selected)

        self._parameter_filter_state = state
        # MIDI は status へ混ぜず、主操作行の右端へ assignment menu として置く。
        changed = self._render_midi_mapping_menu()

        view = parameter_table_view_for_store(
            self._store,
            show_inactive_params=bool(self._show_inactive_params),
            filter_state=state,
            error_keys=self._parameter_error_keys,
            favorite_keys=self._favorite_parameter_keys,
        )
        self._parameter_table_view = view
        imgui.text_disabled(f"{view.filtered_count} / {view.total_count} parameters")
        imgui.same_line()
        imgui.text_disabled(f"{view.hidden_count} hidden")
        imgui.same_line()
        if imgui.button("Expand all##parameter_groups_expand_all"):
            history = self._history
            transaction = (
                history.transaction(source="expand_all_parameter_groups")
                if history is not None
                else nullcontext()
            )
            with transaction:
                changed = set_all_parameter_groups_collapsed(
                    self._store,
                    view,
                    collapsed=False,
                ) or changed
        imgui.same_line()
        if imgui.button("Collapse all##parameter_groups_collapse_all"):
            history = self._history
            transaction = (
                history.transaction(source="collapse_all_parameter_groups")
                if history is not None
                else nullcontext()
            )
            with transaction:
                changed = set_all_parameter_groups_collapsed(
                    self._store,
                    view,
                    collapsed=True,
                ) or changed

        imgui.same_line()
        self._render_shortcut_help()
        return changed

    def _remember_parameter_help_row(
        self,
        row: ParameterRow,
        _selected: bool,
    ) -> None:
        """row の hover/focus/select を次 frame の Help pane へ保持する。"""

        self._parameter_help_row = row

    def _render_reconcile_orphan_control(self) -> bool:
        """曖昧な parameter group の明示 1:1 relink 導線を描画する。"""

        imgui = self._imgui
        model = reconcile_orphan_panel_model(list_reconcile_orphans(self._store))
        self._reconcile_orphan_model = model

        if model.orphan_count == 0:
            return False

        imgui.text_disabled("RELINK")
        imgui.same_line()
        imgui.text_disabled(
            f"{model.orphan_count} ambiguous groups  ·  "
            f"{model.candidate_count} saved candidates"
        )
        imgui.same_line()
        if imgui.button("Review##reconcile_orphan_review"):
            imgui.open_popup("Parameter relink##reconcile_orphan_popup")

        request = None
        with imgui.begin_popup("Parameter relink##reconcile_orphan_popup") as popup:
            if popup.opened:
                request = render_reconcile_orphan_popup(
                    imgui,
                    model,
                    error_message=self._reconcile_error,
                )
        if request is None:
            return False

        try:
            manual_migrate_orphan(
                self._store,
                request.old_group,
                request.new_group,
                history=self._history,
            )
        except (KeyError, TypeError, ValueError) as exc:
            # 候補が code reload と同時に変わった場合は自動選択せず、
            # popup に理由を残して次 frame の最新一覧を再表示する。
            self._reconcile_error = str(exc)
            self._reconcile_orphan_model = reconcile_orphan_panel_model(
                list_reconcile_orphans(self._store)
            )
            return False

        self._reconcile_error = None
        self._reconcile_orphan_model = reconcile_orphan_panel_model(
            list_reconcile_orphans(self._store)
        )
        self._favorite_parameter_keys = favorite_parameter_key_set(self._store)
        self._parameter_table_view = None
        imgui.close_current_popup()
        return True

    def _on_key_press(self, symbol: int | None, modifiers: int) -> None:
        if symbol is None:
            return
        symbol_i = int(symbol)

        io = self._imgui.get_io()
        if bool(io.want_text_input) or bool(io.want_capture_keyboard):
            return

        # R/E/T は押下中だけ直接commitせず、明示preview modeを開始する。
        # Applyまでstoreは変えず、Esc/Cancelはpreviewを捨てるだけにする。
        mode: RangeEditMode | None = None
        if symbol_i == int(self._range_edit_key_r):
            mode = "shift"
        elif symbol_i == int(self._range_edit_key_e):
            mode = "min"
        elif symbol_i == int(self._range_edit_key_t):
            mode = "max"
        elif symbol_i == int(self._range_edit_key_escape):
            self._cancel_range_edit()
            return
        if mode is not None:
            self._range_edit_mode = mode
            self._range_edit_session = None
            return

        modifier_i = int(modifiers)
        shortcut_mask = int(self._shortcut_modifier_mask)
        if shortcut_mask and modifier_i & shortcut_mask:
            history = self._history
            if history is not None:
                if symbol_i == int(self._history_key_z):
                    if modifier_i & int(self._shortcut_shift_mask):
                        history.redo()
                    else:
                        history.undo()
                elif symbol_i == int(self._history_key_y):
                    history.redo()
            # Cmd/Ctrl を伴う OS/editor shortcut を transport として解釈しない。
            return

        transport = self._transport
        if transport is None:
            return
        is_recording = self._is_recording
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

    def _on_deactivate(self) -> None:
        self._cancel_range_edit()

    @property
    def parameter_edit_active(self) -> bool:
        """直前の GUI frame で ImGui item が操作中なら True。"""

        return bool(self._parameter_edit_active)

    def _cancel_range_edit(self) -> None:
        """未commit previewを破棄し、通常modeへ戻る。"""

        self._range_edit_mode = None
        self._range_edit_session = None

    def _maybe_preview_range_edit_by_midi(self) -> bool:
        """新しいCC差分をstore非破壊のRange Edit previewへ反映する。"""

        session = self._midi_session
        if session is None:
            return False

        last = session.last_cc_change
        if last is None:
            return False

        seq, cc = last
        seq_i = int(seq)
        cc_i = int(cc)
        if seq_i <= int(self._range_edit_last_seen_cc_seq):
            return False
        self._range_edit_last_seen_cc_seq = int(seq_i)

        current = session.value_for_cc(int(cc_i))
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

        mode = self._range_edit_mode
        if mode is None:
            return False
        edit = self._range_edit_session
        if edit is None:
            edit = range_edit_session_for_store(
                self._store,
                cc=cc_i,
                mode=mode,
            )
            if edit is None:
                return False
        elif edit.cc != cc_i:
            return False
        updated = preview_range_edit(edit, delta=float(delta))
        if updated == edit:
            return False
        self._range_edit_session = updated
        return True

    def _render_range_edit_mode(self) -> bool:
        """明示Range Edit modeの対象、preview、Apply/Cancelを描画する。"""

        mode = self._range_edit_mode
        if mode is None:
            return False
        imgui = self._imgui
        mode_label = {"shift": "SHIFT", "min": "MIN", "max": "MAX"}[mode]
        imgui.text(f"RANGE EDIT · {mode_label}")
        edit = self._range_edit_session
        if edit is None:
            imgui.text_disabled("Move a mapped MIDI control to choose linked parameters.")
        else:
            imgui.text_disabled(
                f"CC {edit.cc} · {len(edit.targets)} linked parameter"
                + ("s" if len(edit.targets) != 1 else "")
            )
            for target in edit.targets[:4]:
                lo, hi = target.pending_range
                imgui.text_disabled(f"{target.label}: {lo:g} .. {hi:g}")
            if len(edit.targets) > 4:
                imgui.text_disabled(f"+ {len(edit.targets) - 4} more")

        applied = False
        if imgui.button("Apply##range_edit_apply") and edit is not None:
            applied = bool(
                apply_range_edit_session(
                    self._store,
                    edit,
                    history=self._history,
                )
            )
            self._cancel_range_edit()
        imgui.same_line()
        if imgui.button("Cancel##range_edit_cancel"):
            self._cancel_range_edit()
        _section_separator(imgui)
        return applied

    def _render_bottom_drawer(
        self,
        *,
        geometry: BottomDrawerGeometry,
        monitor_snapshot: MonitorSnapshot | None,
        monitor: RuntimeMonitor | None,
    ) -> None:
        """Help と可変長 runtime details を固定高 pane 内に描画する。"""

        imgui = self._imgui
        _begin_toolbar_surface(
            imgui,
            "##parameter_help_drawer",
            geometry.help_width,
            geometry.height,
        )
        try:
            render_parameter_help_pane(
                imgui,
                self._parameter_help_row,
            )
        finally:
            _end_toolbar_surface(imgui)

        _same_line_with_spacing(imgui, geometry.gap)
        _begin_toolbar_surface(
            imgui,
            "##runtime_details_drawer",
            geometry.runtime_width,
            geometry.height,
        )
        try:
            imgui.text_disabled("RUNTIME")
            if monitor_snapshot is None:
                imgui.text_disabled("No runtime details")
                return

            alert_lines = monitor_alert_lines(monitor_snapshot)
            render_monitor_alerts(imgui, monitor_snapshot)
            render_profiler_panel(imgui, monitor_snapshot.profiler)
            render_diagnostics_panel(
                imgui,
                monitor_snapshot.diagnostics,
                center=None if monitor is None else monitor.diagnostic_center,
            )
            if (
                not alert_lines
                and monitor_snapshot.profiler is None
                and not monitor_snapshot.diagnostics
            ):
                imgui.text_disabled("No alerts or diagnostics")
        finally:
            _end_toolbar_surface(imgui)

    def _sync_font_for_window(self) -> None:
        """ウィンドウの backing scale に合わせてフォントを同期する。"""

        if self._custom_font_path is None:
            return

        backing_scale = _compute_window_backing_scale(self._window)
        effective_config = self._effective_config
        config_key: tuple[object, ...] = (
            effective_config.config_path,
            effective_config.parameter_gui_fallback_font_japanese,
            effective_config.font_dirs,
        )
        sync_key: tuple[object, ...] = (
            float(backing_scale),
            self._custom_font_path,
            float(self._font_size_base_px),
            config_key,
        )
        # フォント探索/resolve はディスクアクセスを含み得る。安定フレームでは行わず、
        # backing scale または runtime config が変わったときだけ再同期する。
        if self._font_sync_key == sync_key:
            return
        fallback = _gui_fallback_font_path_for_japanese(effective_config)
        favorite_font = _favorite_glyph_font_path()

        io = self._imgui.get_io()
        io.fonts.clear()
        font_px = float(self._font_size_base_px * backing_scale)
        io.fonts.add_font_from_file_ttf(
            str(self._custom_font_path),
            float(font_px),
            glyph_ranges=io.fonts.get_glyph_ranges_default(),
        )

        if fallback is not None and fallback.is_file():
            if fallback.resolve() != self._custom_font_path.resolve():
                font_config = self._imgui.core.FontConfig(merge_mode=True)
                io.fonts.add_font_from_file_ttf(
                    str(fallback),
                    float(font_px),
                    font_config=font_config,
                    glyph_ranges=io.fonts.get_glyph_ranges_japanese(),
                )

        if favorite_font is not None and favorite_font.is_file():
            # Japanese range には U+2605/U+2606 が含まれないため、同梱 Noto から
            # favorite icon の2 glyphだけを明示的に追加する。
            favorite_ranges = self._imgui.core.GlyphRanges((0x2605, 0x2606, 0))
            favorite_cfg = self._imgui.core.FontConfig(merge_mode=True)
            io.fonts.add_font_from_file_ttf(
                str(favorite_font),
                float(font_px),
                font_config=favorite_cfg,
                glyph_ranges=favorite_ranges,
            )
            self._favorite_glyph_ranges = favorite_ranges

        self._renderer.refresh_font_texture()

        self._font_backing_scale = backing_scale
        self._font_fallback_path_for_japanese = fallback
        self._favorite_glyph_font_path = favorite_font
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
        content_width = content_region_available_width(imgui)
        changed_any = self._render_toolbar_area(
            content_width=float(content_width),
            monitor_snapshot=monitor_snapshot,
        )
        changed_any = self._render_midi_clear_notice() or changed_any

        # MIDI global command は独立した履歴単位にし、通常のparameter editと
        # coalesceさせない。filter自体はstoreを変更しない。
        changed_any = self._render_parameter_table_toolbar() or changed_any
        table_view = self._parameter_table_view
        if table_view is None:
            raise RuntimeError("parameter table toolbar did not publish its view")
        changed_any = self._render_reconcile_orphan_control() or changed_any
        self._maybe_preview_range_edit_by_midi()
        changed_any = self._render_range_edit_mode() or changed_any
        coordinate_scale = _window_ui_coordinate_scale(
            self._window,
            ui_scale=float(self._ui_scale),
        )
        drawer_geometry = compute_bottom_drawer_geometry(
            float(content_width),
            coordinate_scale=coordinate_scale,
        )
        history = self._history
        transaction = (
            history.transaction(source="parameter_gui", patch=True)
            if history is not None
            else nullcontext()
        )
        effect_order_commands: list[EffectOrderCommand] = []
        with transaction:
            _section_separator(imgui)

            # 下端の固定 drawer を常に予約する。可変長の Help / diagnostics /
            # profiler は drawer 内だけをスクロールし、parameter 行を上下させない。
            drawer_spacing = _vertical_item_spacing(imgui)
            imgui.begin_child(
                "##parameter_table_scroll",
                0,
                -(drawer_geometry.height + drawer_spacing),
                border=False,
            )
            try:
                # ParamStore をテーブルとして描画し、編集結果を store に反映する。
                changed_any = (
                    bool(
                        render_store_parameter_table(
                            self._store,
                            table_view=table_view,
                            metric_scale=coordinate_scale,
                            midi_learn_state=self._midi_learn_state,
                            midi_last_cc_change=(
                                None
                                if self._midi_session is None
                                else self._midi_session.last_cc_change
                            ),
                            on_help_row=self._remember_parameter_help_row,
                            on_effect_order_command=effect_order_commands.append,
                        )
                    )
                    or changed_any
                )
            finally:
                imgui.end_child()

        # effect順序はparameter値用patch transactionへ混ぜない。drop/menu/resetの
        # 一操作ごとにfull mementoを作り、Undo/RedoでもDAG順を一単位で戻す。
        for command in effect_order_commands:
            if history is not None:
                history.break_coalescing()
            effect_transaction = (
                history.transaction(
                    source=("effect_order", command.chain_id),
                    patch=False,
                )
                if history is not None
                else nullcontext()
            )
            with effect_transaction:
                command_changed = apply_effect_order_command(
                    self._store,
                    command,
                )
            if command_changed:
                self._parameter_table_view = None
                changed_any = True
            if history is not None:
                history.break_coalescing()
        self._render_bottom_drawer(
            geometry=drawer_geometry,
            monitor_snapshot=monitor_snapshot,
            monitor=monitor,
        )
        parameter_edit_active = bool(imgui.is_any_item_active())
        self._parameter_edit_active = parameter_edit_active
        if history is not None and not parameter_edit_active:
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

        errors = CleanupErrors()

        window = getattr(self, "_window", None)
        if window is not None:
            # renderer.shutdown() が解放する GL resource の所有 context を
            # 必ず current にしてから backend を破棄する。
            errors.attempt(window.switch_to)

        renderer = getattr(self, "_renderer", None)
        if renderer is not None:
            errors.attempt(renderer.shutdown)

        imgui = getattr(self, "_imgui", None)
        context = getattr(self, "_context", None)
        if imgui is not None and context is not None:
            errors.attempt(lambda: imgui.destroy_context(context))

        if window is not None:
            errors.attempt(window.close)
        errors.raise_if_any()
