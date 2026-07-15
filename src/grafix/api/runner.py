"""
どこで: `src/grafix/api/runner.py`。公開 API のランナー実装。
何を: pyglet + ModernGL を使い、`draw(t)` が返す Geometry/Layer/シーンをウィンドウに描画するランナーを提供する。
なぜ: `main.py` を実行して実際に線をプレビューできる経路を用意するため。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import pyglet

from grafix.core.layer import LayerStyleDefaults
from grafix.core.runtime_config import runtime_config, set_config_path
from grafix.core.parameters import (
    ParamSnapshotSlots,
    ParamStore,
    ParamStoreAutosave,
    ParamStoreHistory,
)
from grafix.core.parameters.persistence import (
    default_param_store_path,
    finalize_param_store_session,
    load_param_store_with_recovery,
    param_store_recovery_path,
    save_param_store_recovery,
)
from grafix.core.output_paths import output_path_for_draw
from grafix.core.resource_budget import DEFAULT_RESOURCE_BUDGET, ResourceBudget
from grafix.core.scene import SceneItem
from grafix.interactive.midi.factory import create_midi_controller
from grafix.interactive.midi.midi_controller import (
    MidiController,
    maybe_load_frozen_cc_snapshot,
)
from grafix.interactive.render_settings import RenderSettings
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
from grafix.interactive.runtime.window_layout import (
    DEFAULT_SCREEN_MARGIN,
    WindowRect,
    layout_window_pair,
)
from grafix.interactive.runtime.window_loop import MultiWindowLoop, WindowTask

_logger = logging.getLogger(__name__)


def _run_cleanup_steps(
    steps: list[tuple[str, Callable[[], None]]],
    *,
    initial_error: BaseException | None = None,
) -> None:
    """shutdown step を全て試し、最初の例外を最後に再送出する。"""

    first_error = initial_error
    for label, step in steps:
        try:
            step()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
            else:
                _logger.exception(
                    "Shutdown step failed after an earlier error: %s",
                    label,
                )

    if first_error is not None:
        raise first_error


def _persist_param_store_on_shutdown(
    *,
    store: ParamStore,
    primary_path: Path | None,
    autosave: ParamStoreAutosave | None,
    session_completed_cleanly: bool,
) -> None:
    """session 終了時に recovery を確定し、正常終了だけ primary へ昇格する。"""

    # まず live override 付き recovery を確定する。以下の primary
    # finalize 中に障害が起き、未完了になっても復帰できる。
    if autosave is not None:
        autosave.flush()
    # code-first の primary へ確定し recovery を消すのは、
    # event loop が正常に制御を返した場合だけ。例外終了では
    # recovery を残し、次回起動時に live override を戻せるようにする。
    if primary_path is not None and session_completed_cleanly:
        finalize_param_store_session(store, primary_path)


def _close_midi_controller(controller: MidiController) -> None:
    """MIDI snapshot 保存に失敗しても入力 port の close まで試す。"""

    _run_cleanup_steps(
        [
            ("save MIDI CC snapshot", controller.save),
            ("close MIDI controller", controller.close),
        ]
    )


def _window_content_size(window: Any) -> tuple[int, int] | None:
    """duck-typed window から現在の logical content size を得る。"""

    # pyglet dpi_scaling="platform" では width/get_size() が framebuffer
    # pixel（Retina なら2倍）なのに対し、set_size() は logical request 単位を
    # 受け取る。layout と setter の単位を揃えるため requested size を優先する。
    get_requested_size = getattr(window, "get_requested_size", None)
    if callable(get_requested_size):
        try:
            requested_width, requested_height = get_requested_size()
            width = int(requested_width)
            height = int(requested_height)
        except (TypeError, ValueError, OverflowError):
            pass
        else:
            if width > 0 and height > 0:
                return width, height

    # 古いbackend / test doubleには requested-size APIが無いため従来属性へ戻す。
    try:
        width = int(window.width)
        height = int(window.height)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _full_screen_bounds(screen: Any) -> WindowRect | None:
    """pyglet Screen 互換 object を top-left 原点の矩形へ変換する。"""

    try:
        bounds = WindowRect(
            x=int(screen.x),
            y=int(screen.y),
            width=int(screen.width),
            height=int(screen.height),
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if bounds.width < 2 or bounds.height < 2:
        return None
    return bounds


def _screen_for_position(window: Any, position: tuple[int, int]) -> Any | None:
    """preferred point を含む screen を選び、取得不能なら window.screen へ戻す。"""

    try:
        display = window.display
        get_screens = getattr(display, "get_screens", None)
        screens = list(get_screens()) if callable(get_screens) else []
    except Exception:
        screens = []

    point_x, point_y = int(position[0]), int(position[1])
    for screen in screens:
        bounds = _full_screen_bounds(screen)
        if bounds is None:
            continue
        if bounds.x <= point_x < bounds.right and bounds.y <= point_y < bounds.bottom:
            return screen

    try:
        return window.screen
    except (AttributeError, TypeError):
        return None


def _macos_visible_screen_bounds(screen: Any, full: WindowRect) -> WindowRect | None:
    """Cocoa NSScreen.visibleFrame を pyglet と同じ top-left 座標へ変換する。"""

    ns_screen = getattr(screen, "_ns_screen", None)
    frame_getter = getattr(ns_screen, "frame", None)
    visible_getter = getattr(ns_screen, "visibleFrame", None)
    if not callable(frame_getter) or not callable(visible_getter):
        return None

    try:
        frame = frame_getter()
        visible = visible_getter()
        frame_x = float(frame.origin.x)
        frame_y = float(frame.origin.y)
        frame_w = float(frame.size.width)
        frame_h = float(frame.size.height)
        visible_x = float(visible.origin.x)
        visible_y = float(visible.origin.y)
        visible_w = float(visible.size.width)
        visible_h = float(visible.size.height)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if frame_w <= 0.0 or frame_h <= 0.0 or visible_w <= 0.0 or visible_h <= 0.0:
        return None

    # Cocoa は bottom-left 原点、pyglet の set_location は top-left 原点。
    # Screen / NSScreen の単位が異なる環境にも比率で合わせる。
    scale_x = float(full.width) / frame_w
    scale_y = float(full.height) / frame_h
    candidate = WindowRect(
        x=int(round(float(full.x) + (visible_x - frame_x) * scale_x)),
        y=int(
            round(
                float(full.y)
                + (frame_y + frame_h - (visible_y + visible_h)) * scale_y
            )
        ),
        width=int(round(visible_w * scale_x)),
        height=int(round(visible_h * scale_y)),
    )

    # private Cocoa bridge の値が不整合でも full screen 外へは出さない。
    left = max(full.x, candidate.x)
    top = max(full.y, candidate.y)
    right = min(full.right, candidate.right)
    bottom = min(full.bottom, candidate.bottom)
    if right - left < 2 or bottom - top < 2:
        return None
    return WindowRect(left, top, right - left, bottom - top)


def _usable_screen_bounds(window: Any, position: tuple[int, int]) -> WindowRect | None:
    """menu bar / Dock を除く usable bounds を返し、非Cocoaでは full bounds を返す。"""

    screen = _screen_for_position(window, position)
    if screen is None:
        return None
    full = _full_screen_bounds(screen)
    if full is None:
        return None
    return _macos_visible_screen_bounds(screen, full) or full


def _rect_is_inside(rect: WindowRect, bounds: WindowRect) -> bool:
    return bool(
        rect.x >= bounds.x
        and rect.y >= bounds.y
        and rect.right <= bounds.right
        and rect.bottom <= bounds.bottom
    )


def _rects_overlap(a: WindowRect, b: WindowRect) -> bool:
    return not (
        a.right <= b.x
        or b.right <= a.x
        or a.bottom <= b.y
        or b.bottom <= a.y
    )


def _safe_explicit_layout_bounds(bounds: WindowRect) -> WindowRect | None:
    """native frame分のmarginを除いた、明示content rectの安全領域を返す。"""

    margin = int(DEFAULT_SCREEN_MARGIN)
    width = int(bounds.width - 2 * margin)
    height = int(bounds.height - 2 * margin)
    if width < 2 or height < 2:
        return None
    return WindowRect(
        int(bounds.x + margin),
        int(bounds.y + margin),
        width,
        height,
    )


def _apply_initial_window_layout(
    *,
    preview_window: Any,
    parameter_gui_window: Any,
    preferred_preview_position: tuple[int, int],
    preferred_parameter_gui_position: tuple[int, int],
) -> bool:
    """実windowへ安全な初期layoutを適用し、stubで計算不能なら False を返す。

    テスト double や古い backend に screen / size API が無い場合は一切変更せず、
    呼び出し側が従来の config 座標を使えるようにする。実際の mutation が失敗した
    場合は例外を隠さず、runner の lifecycle cleanup に委ねる。
    """

    preview_size = _window_content_size(preview_window)
    gui_size = _window_content_size(parameter_gui_window)
    usable_bounds = _usable_screen_bounds(preview_window, preferred_preview_position)
    if preview_size is None or gui_size is None or usable_bounds is None:
        return False

    preview_preferred_rect = WindowRect(
        int(preferred_preview_position[0]),
        int(preferred_preview_position[1]),
        int(preview_size[0]),
        int(preview_size[1]),
    )
    gui_preferred_rect = WindowRect(
        int(preferred_parameter_gui_position[0]),
        int(preferred_parameter_gui_position[1]),
        int(gui_size[0]),
        int(gui_size[1]),
    )
    gui_usable_bounds = _usable_screen_bounds(
        parameter_gui_window,
        preferred_parameter_gui_position,
    )
    preview_safe_bounds = _safe_explicit_layout_bounds(usable_bounds)
    gui_safe_bounds = (
        None
        if gui_usable_bounds is None
        else _safe_explicit_layout_bounds(gui_usable_bounds)
    )

    preview_set_location = getattr(preview_window, "set_location", None)
    gui_set_location = getattr(parameter_gui_window, "set_location", None)
    if not callable(preview_set_location) or not callable(gui_set_location):
        return False

    # 明示 config が既に安全なら、single / dual monitor を問わずユーザーの配置と
    # natural size をそのまま尊重する。現在の既定値のように overlap / overflow
    # している場合だけ、以下の single-screen responsive layout へ進む。
    if (
        preview_safe_bounds is not None
        and gui_safe_bounds is not None
        and _rect_is_inside(preview_preferred_rect, preview_safe_bounds)
        and _rect_is_inside(gui_preferred_rect, gui_safe_bounds)
        and not _rects_overlap(preview_preferred_rect, gui_preferred_rect)
    ):
        preview_set_location(*preferred_preview_position)
        gui_set_location(*preferred_parameter_gui_position)
        return True

    try:
        layout = layout_window_pair(
            preview_size=preview_size,
            parameter_gui_size=gui_size,
            usable_bounds=usable_bounds,
            preferred_preview_position=preferred_preview_position,
            preferred_parameter_gui_position=preferred_parameter_gui_position,
        )
    except (TypeError, ValueError, OverflowError):
        _logger.debug("Initial window layout could not be calculated", exc_info=True)
        return False

    preview_target_size = (layout.preview.width, layout.preview.height)
    gui_target_size = (layout.parameter_gui.width, layout.parameter_gui.height)
    preview_set_size = getattr(preview_window, "set_size", None)
    gui_set_size = getattr(parameter_gui_window, "set_size", None)
    if preview_target_size != preview_size and not callable(preview_set_size):
        return False
    if gui_target_size != gui_size and not callable(gui_set_size):
        return False

    if preview_target_size != preview_size:
        assert callable(preview_set_size)
        preview_set_size(*preview_target_size)
    if gui_target_size != gui_size:
        assert callable(gui_set_size)
        gui_set_size(*gui_target_size)
    preview_set_location(layout.preview.x, layout.preview.y)
    gui_set_location(layout.parameter_gui.x, layout.parameter_gui.y)
    _logger.debug(
        "Applied %s initial window layout: preview=%s gui=%s bounds=%s",
        layout.orientation,
        layout.preview,
        layout.parameter_gui,
        usable_bounds,
    )
    return True


def _activate_initial_windows(preview_window: Any, parameter_gui_window: Any | None) -> None:
    """preview を前面化した後に GUI を最後に activate する。"""

    try:
        preview_window.activate()
    except Exception:
        pass
    try:
        if parameter_gui_window is not None:
            parameter_gui_window.activate()
    except Exception:
        pass


def run(
    draw: Callable[[float], SceneItem],
    *,
    config_path: str | Path | None = None,
    run_id: str | None = None,
    background_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    line_thickness: float = 0.001,
    line_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    render_scale: float = 1.0,
    canvas_size: tuple[int, int] = (800, 800),
    parameter_gui: bool = True,
    parameter_persistence: bool = True,
    midi_port_name: str | None = "auto",
    midi_mode: str = "7bit",
    n_worker: int = 1,
    fps: float = 60.0,
    resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
) -> None:
    """pyglet ウィンドウを生成し `draw(t)` のシーンをリアルタイム描画する。

    Parameters
    ----------
    draw : Callable[[float], SceneItem]
        フレーム経過秒 t を受け取り Geometry / Layer / それらの列を返すコールバック。
    config_path : str | Path | None
        設定ファイル（config.yaml）のパス。指定した場合は探索より優先する。
    run_id : str | None
        作品スクリプトの同一性を表す識別子。出力ファイル名の接尾辞として使う。
        interactive capture は同名の完成品を上書きせず、必要に応じて連番を付ける。
    background_color : tuple[float, float, float]
        背景色 RGB。alpha は 1.0 固定。既定は白。
    line_thickness : float
        プレビュー用線幅（ワールド単位）。Layer.thickness 未指定時の基準値。
    line_color : tuple[float, float, float]
        線色 RGB。既定は黒。
    render_scale : float
        キャンバス寸法に掛けるピクセル倍率。高精細プレビュー用。
    canvas_size : tuple[int, int]
        キャンバス寸法（任意単位）。投影行列生成とウィンドウサイズ決定に使用。
    parameter_gui : bool
        True の場合、別ウィンドウで Parameter GUI を起動し、ParamStore を編集できるようにする。
    parameter_persistence : bool
        True の場合、ParamStore を JSON 保存し、次回起動時に復元する。
        保存先は `output/param_store/` 配下で sketch_dir の構造をミラーし、run_id があればファイル名に付く。
        GUI 変更は短い debounce 後に atomic autosave し、終了時にも未保存分を確定する。
    midi_port_name : str | None
        MIDI 入力ポート名。
        - `"auto"`: 利用可能な入力ポートがあれば 1 つ目へ自動接続する（既定）。
          config.yaml に `midi.inputs`（接続優先リスト）があれば、その順に接続を試す。
          どれも見つからなければ、利用可能な入力ポートの 1 つ目へフォールバックする。
          接続できない場合でも、前回保存した CC スナップショットを凍結して使う（描画が変わらない）。
        - `"TX-6 Bluetooth"` のような文字列: 指定ポートへ接続する。
        - None: MIDI を無効化する。
    midi_mode : str
        MIDI CC の解釈モード。`"7bit"` または `"14bit"`。
    n_worker : int
        `draw(t)` を multiprocessing で実行するワーカープロセス数。
        既定は同期実行の 1。`>=2` の場合は spawn + Queue（pickle）で非同期化する。
        CPU負荷の高いdrawでプレビュー応答性を優先するときだけ明示的に増やす。
    fps : float
        目標フレームレート。`<=0` の場合はフレーム末尾で sleep せず、可能な限り速く回す。
        録画機能（V キー）は fps > 0 が必要。
    resource_budget : ResourceBudget
        1 operation が確保できる頂点数・線数・byte 数の上限。コードから極端な値を
        指定した場合も、大規模配列を確保する前に `ResourceLimitError` で停止する。

    Returns
    -------
    None
        どちらかのウィンドウを閉じると制御を返す。
    """

    set_config_path(config_path)
    cfg = runtime_config()

    # Parameter GUI はメインプロセス上の registry（preset_registry）を参照して
    # preset 行を分類/ヘッダ表示する。
    # mp-draw worker 内で `P.*` が初めて使われても GUI 側では登録が見えないため、
    # GUI 有効時はここで user preset を先に autoload しておく。
    if parameter_gui:
        from grafix.api import presets as _presets

        _presets._autoload_preset_modules()

    # pyglet の Window 作成前にオプションを設定する。
    # （vsync はウィンドウ作成時に参照される想定のため、ここで固定しておく）
    # True にすると Parameter GUI のクリックやドラッグが抜ける事がある。
    pyglet.options["vsync"] = False

    # 描画の見た目/サイズに関わる設定値をまとめる。
    settings = RenderSettings(
        background_color=background_color,
        line_thickness=line_thickness,
        line_color=line_color,
        render_scale=render_scale,
        canvas_size=canvas_size,
    )

    # Layer 側で style 未指定のときに使う既定値（プレビューの見た目）。
    defaults = LayerStyleDefaults(color=line_color, thickness=line_thickness)

    # パラメータは「描画」と「GUI」で共有する。
    # GUI で値を変えると、次フレーム以降の parameter_context 参照に反映される。
    default_store_path = default_param_store_path(draw, run_id=run_id)

    param_store_path = default_store_path if parameter_persistence else None
    param_store = (
        load_param_store_with_recovery(param_store_path)
        if param_store_path is not None
        else ParamStore()
    )
    param_history = ParamStoreHistory(param_store) if parameter_gui else None
    param_snapshot_slots = ParamSnapshotSlots(param_store) if parameter_gui else None
    param_autosave = (
        ParamStoreAutosave(
            param_store,
            param_store_recovery_path(param_store_path),
            save=save_param_store_recovery,
        )
        if param_store_path is not None
        else None
    )

    # resource acquisition も loop と同じ保護範囲に入れる。GUI constructor や
    # window 配置で失敗しても、それまでに取得した MIDI/window/worker を解放する。
    closers: list[Callable[[], None]] = []
    unowned_midi_controller: MidiController | None = None
    session_completed_cleanly = False
    session_error: BaseException | None = None
    try:
        midi_path = output_path_for_draw(
            kind="midi", ext="json", draw=draw, run_id=run_id
        )
        midi_profile_name = midi_path.stem
        midi_save_dir = midi_path.parent
        midi_controller = create_midi_controller(
            port_name=midi_port_name,
            mode=str(midi_mode),
            profile_name=midi_profile_name,
            save_dir=midi_save_dir,
            priority_inputs=cfg.midi_inputs,
        )
        unowned_midi_controller = midi_controller

        def close_unowned_midi() -> None:
            nonlocal unowned_midi_controller
            controller = unowned_midi_controller
            unowned_midi_controller = None
            if controller is not None:
                _close_midi_controller(controller)

        # DrawWindowSystem が完成するまでは runner が MIDI を所有する。
        closers.append(close_unowned_midi)
        frozen_cc_snapshot = maybe_load_frozen_cc_snapshot(
            port_name=midi_port_name,
            controller=midi_controller,
            profile_name=midi_profile_name,
            save_dir=midi_save_dir,
        )

        monitor = None
        if parameter_gui:
            from grafix.interactive.runtime.monitor import RuntimeMonitor

            monitor = RuntimeMonitor()

        # --- サブシステムの組み立て ---
        # 描画ウィンドウは常に有効（メイン描画）。constructor が戻った直後に
        # closer を登録し、後続の set_location/GUI 構築失敗も回収する。
        draw_window = DrawWindowSystem(
            draw,
            settings=settings,
            defaults=defaults,
            store=param_store,
            midi_controller=midi_controller,
            frozen_cc_snapshot=frozen_cc_snapshot,
            monitor=monitor,
            fps=float(fps),
            n_worker=int(n_worker),
            run_id=run_id,
            resource_budget=resource_budget,
        )
        # 正常構築後は DrawWindowSystem が MIDI の save/close を所有する。
        unowned_midi_controller = None
        closers.append(draw_window.close)
        draw_window.window.set_location(*cfg.window_pos_draw)

        # `tasks` はループ駆動用（イベント処理→描画→flip の対象）。
        tasks = [WindowTask(window=draw_window.window, draw_frame=draw_window.draw_frame)]

        gui_window = None
        if parameter_gui:
            # Parameter GUI は依存が重い（pyimgui）なので、使うときだけ遅延 import する。
            from grafix.interactive.runtime.parameter_gui_system import (
                ParameterGUIWindowSystem,
            )

            gui = ParameterGUIWindowSystem(
                store=param_store,
                midi_controller=midi_controller,
                monitor=monitor,
                transport=draw_window.transport,
                transport_fps=float(fps),
                history=param_history,
                snapshot_slots=param_snapshot_slots,
                autosave=param_autosave,
                is_recording=lambda: draw_window.is_recording,
            )
            closers.append(gui.close)
            layout_applied = _apply_initial_window_layout(
                preview_window=draw_window.window,
                parameter_gui_window=gui.window,
                preferred_preview_position=cfg.window_pos_draw,
                preferred_parameter_gui_position=cfg.window_pos_parameter_gui,
            )
            if not layout_applied:
                # screen / size API を持たない test double や backend では従来設定を維持する。
                gui.window.set_location(*cfg.window_pos_parameter_gui)
            gui_window = gui.window
            tasks.append(WindowTask(window=gui.window, draw_frame=gui.draw_frame))

        # macOS + unbundled CLI 起動では、起動直後にウィンドウが他アプリの背面に残る事がある。
        # event loop 開始直後に 1 回だけ明示 activate して前面化する。
        def _activate_windows(_dt: float) -> None:
            # 最後に GUI を activate し、preview が操作面を覆わない状態で開始する。
            _activate_initial_windows(draw_window.window, gui_window)

        pyglet.clock.schedule_once(_activate_windows, 0.0)
        closers.append(lambda: pyglet.clock.unschedule(_activate_windows))

        # --- ループの実行 ---
        # ここで複数ウィンドウを 1 つの pyglet.app.run() で回す。
        loop = MultiWindowLoop(
            tasks,
            fps=fps,
            on_frame_start=None if monitor is None else monitor.tick_frame,
        )
        loop.run()
        session_completed_cleanly = True
    except BaseException as exc:
        session_error = exc

    cleanup_steps: list[tuple[str, Callable[[], None]]] = [
        (
            "persist ParameterStore",
            lambda: _persist_param_store_on_shutdown(
                store=param_store,
                primary_path=param_store_path,
                autosave=param_autosave,
                session_completed_cleanly=session_completed_cleanly,
            ),
        )
    ]
    cleanup_steps.extend(
        (f"close subsystem {index}", close)
        for index, close in enumerate(reversed(closers), start=1)
    )
    _run_cleanup_steps(cleanup_steps, initial_error=session_error)
