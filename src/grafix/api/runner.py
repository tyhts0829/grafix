"""
どこで: `src/grafix/api/runner.py`。公開 API のランナー実装。
何を: pyglet + ModernGL を使い、`draw(t)` が返す Geometry/Layer/シーンをウィンドウに描画するランナーを提供する。
なぜ: `main.py` を実行して実際に線をプレビューできる経路を用意するため。
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

import pyglet
from pyglet.window import key

from grafix.core.layer import LayerStyleDefaults
from grafix.core.runtime_config import (
    RuntimeConfigFallback,
    runtime_config,
    runtime_config_with_fallback,
    set_config_path,
)
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
from grafix.core.runtime_limits import RuntimeLimitProfiles
from grafix.core.scene import SceneItem
from grafix.interactive.midi.factory import create_midi_controller
from grafix.interactive.midi import MidiSession
from grafix.interactive.midi.midi_controller import (
    MidiController,
    maybe_load_frozen_cc_snapshot,
    save_cc_snapshot,
)
from grafix.interactive.render_settings import RenderSettings
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
from grafix.interactive.runtime.diagnostics import DiagnosticAction, DiagnosticEvent
from grafix.interactive.runtime.parameter_recovery import (
    ParamStoreRecoverySession,
    param_store_load_diagnostic_events,
    recovered_session_diagnostic,
)
from grafix.interactive.runtime.window_layout import (
    DEFAULT_SCREEN_MARGIN,
    WindowRect,
    layout_window_pair,
)
from grafix.interactive.runtime.window_loop import MultiWindowLoop, WindowTask
from grafix.interactive.runtime.workspace_state import (
    WorkspaceState,
    WorkspaceStateLoadResult,
    clamp_workspace_state,
    load_workspace_state,
    save_workspace_state,
)

_logger = logging.getLogger(__name__)


def _variation_thumbnail_output_path(base_path: Path, name: str) -> Path:
    """variation名をpath componentとして安全にしたPNG保存先を返す。"""

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name).strip()).strip("._")
    if not safe_name:
        safe_name = "variation"
    safe_name = safe_name[:64].rstrip("._") or "variation"
    return base_path.with_name(f"{base_path.stem}_{safe_name}{base_path.suffix}")


def _variation_thumbnail_size(canvas_size: tuple[int, int]) -> tuple[int, int]:
    """canvas比率を保ち、長辺320pxのthumbnail寸法を返す。"""

    width, height = int(canvas_size[0]), int(canvas_size[1])
    scale = 320.0 / float(max(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _draw_variation_thumbnail_status(imgui: object, path: Path) -> None:
    """texture backend未接続時もmissing/存在済みを区別して表示する。"""

    text_disabled = getattr(imgui, "text_disabled")
    thumbnail_path = Path(path)
    if thumbnail_path.is_file():
        text_disabled(f"Thumbnail: {thumbnail_path.name}")
    else:
        text_disabled(f"Thumbnail unavailable (missing): {thumbnail_path}")

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
    monitor: Any | None = None,
) -> None:
    """session 終了時に recovery を確定し、正常終了だけ primary へ昇格する。"""

    # まず live override 付き recovery を確定する。以下の primary
    # finalize 中に障害が起き、未完了になっても復帰できる。
    try:
        if autosave is not None:
            autosave.flush()
        # code-first の primary へ確定し recovery を消すのは、
        # event loop が正常に制御を返した場合だけ。例外終了では
        # recovery を残し、次回起動時に live override を戻せるようにする。
        if primary_path is not None and session_completed_cleanly:
            finalize_param_store_session(store, primary_path)
    except Exception as exc:
        if monitor is not None:
            source = autosave.path if autosave is not None else primary_path
            monitor.publish_diagnostic(
                DiagnosticEvent(
                    category="save",
                    severity="error",
                    summary="Parameter save failed during shutdown",
                    details="".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ),
                    source=None if source is None else str(source),
                    actions=(DiagnosticAction("copy", "Copy details"),),
                    dedupe_key=f"parameter-shutdown-save:{type(exc).__name__}:{exc}",
                )
            )
        raise


def _close_midi_controller(controller: MidiController) -> None:
    """MIDI snapshot 保存に失敗しても入力 port の close まで試す。"""

    _run_cleanup_steps(
        [
            ("save MIDI CC snapshot", controller.save),
            ("close MIDI controller", controller.close),
        ]
    )


def _diagnostic_source_path(source: str) -> Path:
    """`path:line` または path の診断 source を既存 file として解決する。"""

    raw = str(source).strip()
    path_text, separator, line_text = raw.rpartition(":")
    if separator and line_text.isdigit() and path_text:
        raw = path_text
    path = Path(raw).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Diagnostic source does not exist: {path}")
    return path.resolve()


def _open_diagnostic_source(source: str) -> None:
    """診断 source を platform の既定 application で開く。"""

    path = _diagnostic_source_path(source)
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(  # noqa: S603 -- validated local file without shell expansion.
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _install_parameter_diagnostic_actions(
    *,
    monitor: Any,
    store: ParamStore,
    primary_path: Path | None,
    autosave: ParamStoreAutosave | None,
    history: ParamStoreHistory | None,
    snapshot_slots: ParamSnapshotSlots | None,
    open_source: Callable[[str], None] = _open_diagnostic_source,
) -> ParamStoreRecoverySession | None:
    """save/recovery/Open action を共有 DiagnosticCenter へ配線する。"""

    center = monitor.diagnostic_center

    def open_event(event: DiagnosticEvent) -> None:
        if event.source is None:
            raise ValueError("Diagnostic has no source to open")
        open_source(event.source)

    center.register_action("open", open_event)

    if autosave is not None:

        def retry_autosave(event: DiagnosticEvent) -> None:
            try:
                autosave.flush()
            finally:
                monitor.set_autosave(
                    status=autosave.status,
                    error=autosave.last_error,
                    source=str(autosave.path),
                )
            center.dismiss(event)

        center.register_action("retry", retry_autosave, category="save")

    if primary_path is None:
        return None

    for event in param_store_load_diagnostic_events(
        store,
        primary_path=primary_path,
    ):
        monitor.publish_diagnostic(event)

    if store.load_provenance != "session_recovery":
        return None

    recovery = ParamStoreRecoverySession(store, primary_path)
    monitor.publish_diagnostic(recovered_session_diagnostic(primary_path))
    monitor.set_recovered_session(True)

    def finish_decision(event: DiagnosticEvent) -> None:
        if autosave is not None:
            autosave.mark_clean()
            monitor.set_autosave(
                status=autosave.status,
                error=autosave.last_error,
                source=str(autosave.path),
            )
        if history is not None:
            history.clear()
        if snapshot_slots is not None:
            snapshot_slots.clear()
        monitor.set_recovered_session(False)
        center.dismiss(event)

    def keep(event: DiagnosticEvent) -> None:
        recovery.keep()
        finish_decision(event)

    def discard(event: DiagnosticEvent) -> None:
        diagnostics = recovery.discard()
        finish_decision(event)
        for diagnostic in diagnostics:
            monitor.publish_diagnostic(diagnostic)

    def compare(_event: DiagnosticEvent) -> None:
        monitor.publish_diagnostic(recovery.compare_diagnostic())

    center.register_action("keep", keep, category="recovery")
    center.register_action("discard", discard, category="recovery")
    center.register_action("compare", compare, category="recovery")
    return recovery


def _publish_runtime_config_fallback(
    monitor: Any,
    fallback: RuntimeConfigFallback,
) -> DiagnosticEvent:
    """interactive config fallbackを共通DiagnosticCenterへ常設する。"""

    actions = [DiagnosticAction("copy", "Copy details")]
    if fallback.source is not None:
        actions.append(DiagnosticAction("open", "Open config"))
    return monitor.publish_diagnostic(
        DiagnosticEvent(
            category="config",
            severity="error",
            summary="Runtime config is invalid; using packaged defaults",
            details=fallback.details,
            source=None if fallback.source is None else str(fallback.source),
            actions=tuple(actions),
            dedupe_key=f"config-fallback:{fallback.summary}",
        )
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


def _available_screen_bounds(window: Any) -> tuple[WindowRect, ...]:
    """window の display から現在使える screen bounds を返す。"""

    try:
        get_screens = getattr(window.display, "get_screens", None)
        screens = list(get_screens()) if callable(get_screens) else []
    except Exception:
        screens = []
    if not screens:
        try:
            screens = [window.screen]
        except (AttributeError, TypeError):
            return ()

    bounds: list[WindowRect] = []
    for screen in screens:
        full = _full_screen_bounds(screen)
        if full is None:
            continue
        usable = _macos_visible_screen_bounds(screen, full) or full
        safe = _safe_explicit_layout_bounds(usable)
        candidate = usable if safe is None else safe
        if candidate not in bounds:
            bounds.append(candidate)
    return tuple(bounds)


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


def _window_rect(window: Any) -> WindowRect | None:
    """duck-typed window から logical content rect を取得する。"""

    size = _window_content_size(window)
    if size is None:
        return None
    get_location = getattr(window, "get_location", None)
    try:
        if callable(get_location):
            x, y = get_location()
        else:
            x, y = window.x, window.y
        return WindowRect(int(x), int(y), int(size[0]), int(size[1]))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _window_can_apply_rect(window: Any, rect: WindowRect) -> bool:
    """partial mutation を避けるため rect 適用 API を事前検査する。"""

    size = _window_content_size(window)
    if size is None or not callable(getattr(window, "set_location", None)):
        return False
    target_size = (int(rect.width), int(rect.height))
    return target_size == size or callable(getattr(window, "set_size", None))


def _apply_window_rect(window: Any, rect: WindowRect) -> None:
    size = _window_content_size(window)
    assert size is not None
    target_size = (int(rect.width), int(rect.height))
    if target_size != size:
        window.set_size(*target_size)
    window.set_location(int(rect.x), int(rect.y))


def _apply_workspace_layout(
    *,
    preview_window: Any,
    inspector_window: Any | None,
    state: WorkspaceState,
) -> bool:
    """保存 layout を現在 screen へ clamp して window へ適用する。"""

    bounds = _available_screen_bounds(preview_window)
    if not bounds:
        return False
    clamped = clamp_workspace_state(state, screen_bounds=bounds)

    if not _window_can_apply_rect(preview_window, clamped.preview_rect):
        return False
    if inspector_window is not None:
        inspector_rect = clamped.inspector_rect
        if inspector_rect is None:
            return False
        if not _window_can_apply_rect(inspector_window, inspector_rect):
            return False
        if not callable(getattr(inspector_window, "set_visible", None)):
            return False

    _apply_window_rect(preview_window, clamped.preview_rect)
    if inspector_window is not None:
        assert clamped.inspector_rect is not None
        _apply_window_rect(inspector_window, clamped.inspector_rect)
        inspector_window.set_visible(bool(clamped.inspector_visible))
    return True


def _workspace_state_from_windows(
    *,
    preview_window: Any,
    inspector_window: Any | None,
    previous: WorkspaceState,
) -> WorkspaceState | None:
    """終了時 window から保存用 state を作り、取得不能なら None を返す。"""

    preview_rect = _window_rect(preview_window)
    if preview_rect is None:
        return None
    inspector_rect = previous.inspector_rect
    inspector_visible = previous.inspector_visible
    if inspector_window is not None:
        current_inspector_rect = _window_rect(inspector_window)
        if current_inspector_rect is not None:
            inspector_rect = current_inspector_rect
        inspector_visible = bool(getattr(inspector_window, "visible", inspector_visible))
    return WorkspaceState(
        preview_rect=preview_rect,
        inspector_rect=inspector_rect,
        inspector_visible=inspector_visible,
        ui_scale=previous.ui_scale,
    )


def _persist_workspace_state_on_shutdown(
    *,
    path: Path,
    preview_window: Any | None,
    inspector_window: Any | None,
    previous: WorkspaceState,
) -> None:
    """window が構築済みの場合だけ workspace を atomic 保存する。"""

    if preview_window is None:
        return
    state = _workspace_state_from_windows(
        preview_window=preview_window,
        inspector_window=inspector_window,
        previous=previous,
    )
    if state is None:
        _logger.debug("WorkspaceState save skipped: window rect unavailable")
        return
    save_workspace_state(state, path)


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
        if parameter_gui_window is not None and bool(
            getattr(parameter_gui_window, "visible", True)
        ):
            parameter_gui_window.activate()
    except Exception:
        pass


def _set_inspector_visible(
    *,
    preview_window: Any,
    inspector_window: Any,
    visible: bool,
) -> None:
    """Inspector の表示を切り替え、操作先 window を前面化する。"""

    inspector_window.set_visible(bool(visible))
    if visible:
        inspector_window.activate()
    else:
        preview_window.activate()


def _install_inspector_visibility_shortcut(
    *,
    preview_window: Any,
    inspector_window: Any,
) -> None:
    """preview/Inspector の Cmd/Ctrl+I に Inspector toggle を配線する。"""

    shortcut_modifier_mask = int(key.MOD_CTRL) | int(key.MOD_COMMAND)

    def toggle_inspector(symbol: int | None, modifiers: int) -> object | None:
        if symbol is None or int(symbol) != int(key.I):
            return None
        if not int(modifiers) & shortcut_modifier_mask:
            return None

        _set_inspector_visible(
            preview_window=preview_window,
            inspector_window=inspector_window,
            visible=not bool(getattr(inspector_window, "visible", True)),
        )
        return pyglet.event.EVENT_HANDLED

    # Inspector が hide 中は preview、表示中はどちらに focus があっても
    # 同じ shortcut で戻せる。preview 自体の command surface は増やさない。
    preview_window.push_handlers(on_key_press=toggle_inspector)
    inspector_window.push_handlers(on_key_press=toggle_inspector)


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
    evaluation_timeout: float | None = 5.0,
    fps: float = 60.0,
    seed: int | None = None,
    resource_budget: ResourceBudget = DEFAULT_RESOURCE_BUDGET,
    runtime_limit_profiles: RuntimeLimitProfiles | None = None,
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
        Layer.thickness 未指定時の線幅。キャンバス短辺に対する比率で、既定
        ``0.001`` は短辺の 0.1% に相当する。
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
        `draw(t)` を multiprocessing で実行する background worker 数。
        既定の 1 は UI event loop を塞がない 1 worker 非同期評価。`>=1` は
        spawn + Queue（pickle）で非同期化し、`0` の場合だけ main process で同期実行する。
        非同期評価では `draw` をモジュールトップレベルに定義し、起動側に
        `if __name__ == "__main__":` guard を置く必要がある。
    evaluation_timeout : float | None
        background worker の 1 回の `draw(t)` を待つ秒数。超過時は直近の成功表示を
        保ったまま worker を再起動する。`None` の場合は timeout を無効にする。
    fps : float
        目標フレームレート。`<=0` の場合はフレーム末尾で sleep せず、可能な限り速く回す。
        録画機能（V キー）は fps > 0 が必要。
    seed : int or None
        capture manifest に記録する作品 seed。乱数 global state は変更しない。
    resource_budget : ResourceBudget
        1 operation が確保できる頂点数・線数・byte 数の上限。コードから極端な値を
        指定した場合も、大規模配列を確保する前に `ResourceLimitError` で停止する。
    runtime_limit_profiles : RuntimeLimitProfiles or None
        preview/final ごとの per-operation、scene aggregate、CPU/GPU cache、
        capture queue 上限。指定時は `resource_budget` より優先する。

    Returns
    -------
    None
        preview ウィンドウを閉じると制御を返す。
        Inspector の close はウィンドウを hide し、Cmd/Ctrl+I で再表示できる。
    """

    set_config_path(config_path)
    from grafix.interactive.runtime.source_reload import current_source_reload

    source_reload = current_source_reload()
    try:
        cfg = runtime_config()
        config_fallback = None
    except (OSError, RuntimeError, ValueError):
        cfg, config_fallback = runtime_config_with_fallback()
    if config_fallback is not None and not parameter_gui:
        _logger.error(
            "Runtime config invalid; using packaged defaults: %s\n%s",
            config_fallback.summary,
            config_fallback.details,
        )

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

    workspace_path = output_path_for_draw(
        kind="workspace",
        ext="json",
        draw=draw,
        run_id=run_id,
    )
    preview_width = max(1, int(round(float(canvas_size[0]) * float(render_scale))))
    preview_height = max(1, int(round(float(canvas_size[1]) * float(render_scale))))
    fallback_workspace = WorkspaceState(
        preview_rect=WindowRect(
            int(cfg.window_pos_draw[0]),
            int(cfg.window_pos_draw[1]),
            preview_width,
            preview_height,
        ),
        inspector_rect=WindowRect(
            int(cfg.window_pos_parameter_gui[0]),
            int(cfg.window_pos_parameter_gui[1]),
            int(cfg.parameter_gui_window_size[0]),
            int(cfg.parameter_gui_window_size[1]),
        ),
        inspector_visible=True,
        ui_scale=1.0,
    )
    workspace_result: WorkspaceStateLoadResult = load_workspace_state(
        workspace_path,
        fallback=fallback_workspace,
    )

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
    unowned_midi_session: MidiSession | None = None
    draw_window: DrawWindowSystem | None = None
    gui_window: Any | None = None
    monitor: Any | None = None
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
            nonlocal unowned_midi_controller, unowned_midi_session
            session = unowned_midi_session
            unowned_midi_session = None
            controller = unowned_midi_controller
            unowned_midi_controller = None
            if session is not None:
                session.close()
            elif controller is not None:
                _close_midi_controller(controller)

        # DrawWindowSystem が完成するまでは runner が MIDI を所有する。
        closers.append(close_unowned_midi)
        frozen_cc_snapshot = maybe_load_frozen_cc_snapshot(
            port_name=midi_port_name,
            controller=midi_controller,
            profile_name=midi_profile_name,
            save_dir=midi_save_dir,
        )

        if parameter_gui:
            from grafix.interactive.runtime.monitor import RuntimeMonitor

            monitor = RuntimeMonitor()

        def reconnect_midi() -> MidiController | None:
            return create_midi_controller(
                port_name=midi_port_name,
                mode=str(midi_mode),
                profile_name=midi_profile_name,
                save_dir=midi_save_dir,
                priority_inputs=cfg.midi_inputs,
            )

        midi_session = MidiSession(
            controller=midi_controller,
            frozen_values=frozen_cc_snapshot,
            reconnect=None if midi_port_name is None else reconnect_midi,
            diagnostics=(
                None if monitor is None else monitor.diagnostic_center
            ),
            clear_frozen=lambda: save_cc_snapshot({}, midi_path),
        )
        unowned_midi_controller = None
        unowned_midi_session = midi_session

        workspace_diagnostic = workspace_result.diagnostic
        if workspace_diagnostic is not None:
            if monitor is not None:
                monitor.publish_diagnostic(workspace_diagnostic)
            else:
                _logger.warning(
                    "%s: %s",
                    workspace_diagnostic.summary,
                    workspace_diagnostic.details,
                )

        if monitor is not None:
            _install_parameter_diagnostic_actions(
                monitor=monitor,
                store=param_store,
                primary_path=param_store_path,
                autosave=param_autosave,
                history=param_history,
                snapshot_slots=param_snapshot_slots,
            )
            center = monitor.diagnostic_center

            if config_fallback is not None:
                _publish_runtime_config_fallback(monitor, config_fallback)

            def retry_midi(event: DiagnosticEvent) -> None:
                if midi_session.reconnect():
                    center.dismiss(event)

            def clear_frozen_midi(event: DiagnosticEvent) -> None:
                midi_session.clear_frozen_snapshot()
                center.dismiss(event)

            center.register_action("retry", retry_midi, category="midi")
            center.register_action("discard", clear_frozen_midi, category="midi")

        # --- サブシステムの組み立て ---
        # 描画ウィンドウは常に有効（メイン描画）。constructor が戻った直後に
        # closer を登録し、後続の set_location/GUI 構築失敗も回収する。
        draw_window = DrawWindowSystem(
            draw,
            settings=settings,
            defaults=defaults,
            store=param_store,
            midi_session=midi_session,
            monitor=monitor,
            fps=float(fps),
            n_worker=int(n_worker),
            evaluation_timeout=evaluation_timeout,
            run_id=run_id,
            resource_budget=resource_budget,
            runtime_limit_profiles=runtime_limit_profiles,
            source_reload=source_reload,
            effective_config=cfg,
            parameter_source="recovery" if parameter_persistence else "code",
            parameter_store_path=param_store_path,
            seed=seed,
        )
        # 正常構築後は DrawWindowSystem が MIDI の save/close を所有する。
        unowned_midi_session = None
        closers.append(draw_window.close)
        draw_window.window.set_location(*cfg.window_pos_draw)

        # `tasks` はループ駆動用（イベント処理→描画→flip の対象）。
        tasks = [
            WindowTask(
                window=draw_window.window,
                draw_frame=draw_window.draw_frame,
                on_close=pyglet.app.exit,
            )
        ]

        if parameter_gui:
            # Parameter GUI は依存が重い（pyimgui）なので、使うときだけ遅延 import する。
            from grafix.interactive.parameter_gui.variation_panel import (
                make_capture_service_thumbnail_capture,
            )
            from grafix.interactive.runtime.parameter_gui_system import (
                ParameterGUIWindowSystem,
            )

            variation_thumbnail_base = output_path_for_draw(
                kind="variation_thumbnail",
                ext="png",
                draw=draw,
                run_id=run_id,
                canvas_size=canvas_size,
            )
            variation_thumbnail_capture = make_capture_service_thumbnail_capture(
                draw_window.capture_service,
                frame_provider=draw_window.final_capture_frame,
                output_path_for_name=lambda name: _variation_thumbnail_output_path(
                    variation_thumbnail_base,
                    name,
                ),
                output_size=_variation_thumbnail_size(canvas_size),
            )

            gui = ParameterGUIWindowSystem(
                store=param_store,
                midi_session=midi_session,
                monitor=monitor,
                transport=draw_window.transport,
                transport_fps=float(fps),
                history=param_history,
                snapshot_slots=param_snapshot_slots,
                autosave=param_autosave,
                is_recording=lambda: draw_window.is_recording,
                variation_thumbnail_capture=variation_thumbnail_capture,
                variation_thumbnail_preview=_draw_variation_thumbnail_status,
                ui_scale=workspace_result.state.ui_scale,
            )
            closers.append(gui.close)
            gui_window = gui.window
            layout_applied = False
            if workspace_result.restored:
                layout_applied = _apply_workspace_layout(
                    preview_window=draw_window.window,
                    inspector_window=gui.window,
                    state=workspace_result.state,
                )
            if not layout_applied:
                layout_applied = _apply_initial_window_layout(
                    preview_window=draw_window.window,
                    parameter_gui_window=gui.window,
                    preferred_preview_position=cfg.window_pos_draw,
                    preferred_parameter_gui_position=cfg.window_pos_parameter_gui,
                )
            if not layout_applied:
                # screen / size API を持たない test double や backend では従来設定を維持する。
                gui.window.set_location(*cfg.window_pos_parameter_gui)
            tasks.append(
                WindowTask(
                    window=gui.window,
                    draw_frame=gui.draw_frame,
                    on_close=lambda: _set_inspector_visible(
                        preview_window=draw_window.window,
                        inspector_window=gui.window,
                        visible=False,
                    ),
                )
            )
            _install_inspector_visibility_shortcut(
                preview_window=draw_window.window,
                inspector_window=gui.window,
            )
        elif workspace_result.restored:
            _apply_workspace_layout(
                preview_window=draw_window.window,
                inspector_window=None,
                state=workspace_result.state,
            )

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
                monitor=monitor,
            ),
        ),
        (
            "persist WorkspaceState",
            lambda: _persist_workspace_state_on_shutdown(
                path=workspace_path,
                preview_window=(None if draw_window is None else draw_window.window),
                inspector_window=gui_window,
                previous=workspace_result.state,
            ),
        ),
    ]
    cleanup_steps.extend(
        (f"close subsystem {index}", close)
        for index, close in enumerate(reversed(closers), start=1)
    )
    _run_cleanup_steps(cleanup_steps, initial_error=session_error)
