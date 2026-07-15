# どこで: `src/grafix/interactive/parameter_gui/gui.py`。
# 何を: ParamStore を pyimgui で編集するための最小 GUI（初期化/1フレーム描画/破棄）を提供する。
# なぜ: 依存の重いライフサイクル管理を 1 箇所に閉じ込め、他モジュールを純粋に保つため。

from __future__ import annotations

from contextlib import nullcontext
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
from grafix.core.parameters.snapshot_ops import store_snapshot_for_gui
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.style import STYLE_OP
from grafix.core.runtime_config import runtime_config
from grafix.interactive.midi import MidiController
from grafix.interactive.runtime.frame_clock import TransportClock

from .midi_learn import MidiLearnState
from .monitor_bar import render_monitor_bar
from .pyglet_backend import (
    _create_imgui_pyglet_renderer,
    _install_imgui_clipboard_callbacks,
    _sync_imgui_io_for_window,
)
from .range_edit import RangeEditMode, apply_range_shift
from .store_bridge import clear_all_midi_assignments, render_store_parameter_table
from .theme import apply_parameter_gui_theme


def _toolbar_divider(imgui: Any) -> None:
    """同じ行の操作グループを、控えめな区切りで分離する。"""

    imgui.same_line()
    imgui.text_disabled("|")
    imgui.same_line()


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

    def _render_transport_toolbar(self) -> None:
        """時間を止めて同じ frame を調整する transport 操作を描画する。"""

        transport = self._transport
        if transport is None:
            return

        imgui = self._imgui
        snapshot = transport.snapshot()
        available_width = _available_content_width(imgui)
        is_recording = getattr(self, "_is_recording", None)
        if is_recording is not None and is_recording():
            imgui.text(f"REC  t={snapshot.t:.3f}s  fixed 1x | transport locked")
            return

        play_label = "Pause##transport_play" if snapshot.is_playing else "Play##transport_play"
        if imgui.button(play_label):
            transport.toggle()
        imgui.same_line()
        if imgui.button("Reset##transport_reset"):
            transport.reset()
        imgui.same_line()
        if imgui.button("-1 frame##transport_back"):
            transport.step_frame(fps=self._transport_fps, frames=-1)
        imgui.same_line()
        if imgui.button("+1 frame##transport_forward"):
            transport.step_frame(fps=self._transport_fps, frames=1)

        _toolbar_divider(imgui)
        if imgui.button("0.5x##transport_slower"):
            transport.set_speed(max(0.125, transport.speed / 2.0))
        imgui.same_line()
        if imgui.button("2x##transport_faster"):
            transport.set_speed(min(8.0, transport.speed * 2.0))
        imgui.same_line()
        imgui.text_disabled(f"{transport.speed:g}x")

        if available_width is None or available_width >= 700.0:
            _toolbar_divider(imgui)
            timeline_width = (
                240.0
                if available_width is None
                else max(180.0, min(300.0, available_width - 440.0))
            )
        else:
            timeline_width = max(160.0, min(360.0, available_width - 52.0))
        imgui.set_next_item_width(float(timeline_width))
        changed_t, next_t = imgui.drag_float(
            "Time##transport_time",
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

        history = self._history
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
        _toolbar_divider(imgui)

        snapshot_slots: tuple[SnapshotSlot, SnapshotSlot] = ("A", "B")
        for index, slot in enumerate(snapshot_slots):
            if index > 0:
                _toolbar_divider(imgui)
            if imgui.button(f"Save {slot}##snapshot_set_{slot}"):
                slots.capture(slot)
            imgui.same_line()
            slot_available = slots.has(slot)
            load_clicked = imgui.button(f"Load {slot}##snapshot_load_{slot}")
            if load_clicked and slot_available:
                with history.transaction(source=("snapshot", slot)):
                    changed = slots.restore(slot) or changed
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

        self._render_transport_toolbar()

        changed_any = self._render_history_toolbar()
        history = self._history
        transaction = (
            history.transaction(source="parameter_gui") if history is not None else nullcontext()
        )
        with transaction:
            changed_any = self._maybe_apply_range_edit_by_midi() or changed_any

            if imgui.button("Clear MIDI##clear_midi_assigns"):
                self._midi_learn_state.active_target = None
                self._midi_learn_state.active_component = None
                changed_any = bool(clear_all_midi_assignments(self._store)) or changed_any
            imgui.same_line()
            _clicked, self._show_inactive_params = imgui.checkbox(
                "Inactive##show_inactive_params",
                bool(self._show_inactive_params),
            )

            monitor = self._monitor
            if monitor is not None:
                midi = self._midi_controller
                _toolbar_divider(imgui)
                render_monitor_bar(
                    imgui,
                    monitor.snapshot(),
                    midi_port_name=None if midi is None else str(midi.port_name),
                )
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
