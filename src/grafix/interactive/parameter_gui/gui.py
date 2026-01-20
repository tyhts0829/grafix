# どこで: `src/grafix/interactive/parameter_gui/gui.py`。
# 何を: ParamStore を pyimgui で編集するための最小 GUI（初期化/1フレーム描画/破棄）を提供する。
# なぜ: 依存の重いライフサイクル管理を 1 箇所に閉じ込め、他モジュールを純粋に保つため。

from __future__ import annotations

from pathlib import Path
from typing import Any

from grafix.core.font_resolver import default_font_path
from grafix.core.parameters.layer_style import LAYER_STYLE_OP
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.meta_ops import set_meta
from grafix.core.parameters.snapshot_ops import store_snapshot_for_gui
from grafix.core.parameters.style import STYLE_OP
from grafix.core.parameters.store import ParamStore
from grafix.interactive.midi import MidiController

from .midi_learn import MidiLearnState
from .monitor_bar import render_monitor_bar
from .pyglet_backend import (
    DEFAULT_WINDOW_TARGET_FRAMEBUFFER_WIDTH_PX,
    _create_imgui_pyglet_renderer,
    _install_imgui_clipboard_callbacks,
    _sync_imgui_io_for_window,
)
from .store_bridge import clear_all_midi_assignments, render_store_parameter_table
from .table import COLUMN_WEIGHTS_DEFAULT
from .range_edit import RangeEditMode, apply_range_shift


def _default_gui_font_path() -> Path | None:
    try:
        return default_font_path()
    except Exception:
        return None


_DEFAULT_GUI_FONT_PATH = _default_gui_font_path()
_GUI_FONT_SIZE_BASE_PX = 12.0


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
        title: str = "Parameters",
        column_weights: tuple[float, float, float, float] = COLUMN_WEIGHTS_DEFAULT,
    ) -> None:
        """GUI の初期化（ImGui コンテキスト / renderer 作成）。"""

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
        self._midi_learn_state = MidiLearnState()
        self._range_edit_last_seen_cc_seq = 0
        self._range_edit_prev_value_by_cc: dict[int, float] = {}
        self._range_edit_r_down = False
        self._range_edit_e_down = False
        self._range_edit_t_down = False
        self._range_edit_key_r = 0
        self._range_edit_key_e = 0
        self._range_edit_key_t = 0
        self._show_inactive_params = False
        self._title = str(title)
        self._column_weights = column_weights
        self._sync_window_width_for_scale()

        # ImGui は「グローバルな current context」を前提にするため、自前コンテキストを作って切り替えながら使う。
        self._imgui = imgui
        self._context = imgui.create_context()
        imgui.style_colors_dark()
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
        self._window.push_handlers(
            on_key_press=self._on_key_press,
            on_key_release=self._on_key_release,
            on_deactivate=self._on_deactivate,
        )

        self._custom_font_path = _DEFAULT_GUI_FONT_PATH
        self._font_backing_scale: float | None = None
        self._sync_font_for_window()

        import time

        # ImGui に渡す delta_time 用の前回時刻。
        self._prev_time = time.monotonic()
        self._closed = False

    def _on_key_press(self, symbol: int | None, _modifiers: int) -> None:
        if symbol is None:
            return
        symbol_i = int(symbol)
        if symbol_i == int(self._range_edit_key_r):
            self._range_edit_r_down = True
        if symbol_i == int(self._range_edit_key_e):
            self._range_edit_e_down = True
        if symbol_i == int(self._range_edit_key_t):
            self._range_edit_t_down = True

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

    def _sync_window_width_for_scale(self) -> None:
        """backing scale に合わせてウィンドウ幅を同期する。"""

        target_fb_width = float(DEFAULT_WINDOW_TARGET_FRAMEBUFFER_WIDTH_PX)
        backing_scale = _compute_window_backing_scale(self._window)
        desired_width = int(round(target_fb_width / backing_scale))

        req_w, req_h = self._window.get_requested_size()
        if int(req_w) == int(desired_width):
            return
        self._window.set_size(int(desired_width), int(req_h))

    def _sync_font_for_window(self) -> None:
        """ウィンドウの backing scale に合わせてフォントを同期する。"""

        if self._custom_font_path is None:
            return

        backing_scale = _compute_window_backing_scale(self._window)
        if self._font_backing_scale == backing_scale:
            return

        io = self._imgui.get_io()
        io.fonts.clear()
        io.fonts.add_font_from_file_ttf(
            str(self._custom_font_path),
            float(_GUI_FONT_SIZE_BASE_PX * backing_scale),
        )

        refresh_font = getattr(self._renderer, "refresh_font_texture", None)
        if callable(refresh_font):
            refresh_font()

        self._font_backing_scale = backing_scale

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

        self._sync_window_width_for_scale()

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
        io.mouse_wheel = float(-float(io.mouse_wheel))

        # --- ImGui フレーム開始 ---
        imgui.new_frame()

        # Δt / Retina スケール / サイズなどをウィンドウ状態に同期する。
        _sync_imgui_io_for_window(imgui, self._window, dt=dt)

        # GUI は 1 ウィンドウで全面表示する（位置/サイズ固定）。
        imgui.set_next_window_position(0, 0)
        imgui.set_next_window_size(self._window.width, self._window.height)
        imgui.begin(
            self._title,
            flags=imgui.WINDOW_NO_RESIZE
            | imgui.WINDOW_NO_COLLAPSE
            | imgui.WINDOW_NO_TITLE_BAR,
        )

        monitor = self._monitor
        if monitor is not None:
            midi = self._midi_controller
            render_monitor_bar(
                imgui,
                monitor.snapshot(),
                midi_port_name=None if midi is None else str(midi.port_name),
            )

        self._maybe_apply_range_edit_by_midi()

        changed_any = False
        if imgui.button("Clear MIDI Assigns"):
            self._midi_learn_state.active_target = None
            self._midi_learn_state.active_component = None
            changed_any = bool(clear_all_midi_assignments(self._store)) or changed_any
        imgui.same_line()
        _clicked, self._show_inactive_params = imgui.checkbox(
            "Show inactive params",
            bool(self._show_inactive_params),
        )

        # ParamStore の表だけをスクロール領域に閉じ込め、監視バーは常に見えるようにする。
        imgui.begin_child("##parameter_table_scroll", 0, 0, border=False)
        try:
            # ParamStore をテーブルとして描画し、編集結果を store に反映する。
            changed_any = bool(
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
            ) or changed_any
        finally:
            imgui.end_child()
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
        if self._closed:
            return
        self._closed = True

        # backend が持つ GL リソースを破棄し、ImGui context を破棄してから window を閉じる。
        shutdown = getattr(self._renderer, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self._imgui.destroy_context(self._context)
        self._window.close()
