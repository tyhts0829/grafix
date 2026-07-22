# ruff: noqa: E402 -- pyglet option must be set before importing window controller.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyglet

pyglet.options["shadow_window"] = False

import grafix.interactive.runtime.workspace_window_controller as workspace_module
from grafix.interactive.runtime.window_layout import WindowRect
from grafix.interactive.runtime.workspace_state import (
    WorkspaceState,
    load_workspace_state,
)


class _Window:
    def __init__(
        self,
        width: int,
        height: int,
        screen: Any,
        *,
        screens: list[Any] | None = None,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.screen = screen
        available_screens = list(screens) if screens is not None else [screen]
        self.display = SimpleNamespace(get_screens=lambda: available_screens)
        self.size_calls: list[tuple[int, int]] = []
        self.location_calls: list[tuple[int, int]] = []

    def get_requested_size(self) -> tuple[int, int]:
        return self.width, self.height

    def set_size(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.size_calls.append((self.width, self.height))

    def set_location(self, x: int, y: int) -> None:
        self.location_calls.append((int(x), int(y)))


def _native_rect(x: float, y: float, width: float, height: float) -> Any:
    return SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=width, height=height),
    )


def test_usable_screen_bounds_uses_cocoa_visible_frame() -> None:
    ns_screen = SimpleNamespace(
        frame=lambda: _native_rect(0, 0, 1440, 900),
        visibleFrame=lambda: _native_rect(80, 25, 1360, 850),
    )
    screen = SimpleNamespace(
        x=0,
        y=0,
        width=1440,
        height=900,
        _ns_screen=ns_screen,
    )
    window = _Window(900, 900, screen)

    bounds = workspace_module._usable_screen_bounds(window, (200, 100))

    assert bounds == WindowRect(80, 25, 1360, 850)


def test_apply_initial_layout_resizes_and_places_realistic_windows() -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _Window(900, 900, screen)
    gui = _Window(800, 1000, screen)

    applied = workspace_module._apply_initial_window_layout(
        preview_window=preview,
        parameter_gui_window=gui,
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert applied is True
    assert preview.size_calls == [(preview.width, preview.height)]
    assert gui.size_calls == [(gui.width, gui.height)]
    preview_x, preview_y = preview.location_calls[-1]
    gui_x, gui_y = gui.location_calls[-1]
    assert gui_x - (preview_x + preview.width) == 16
    assert preview_y == gui_y
    assert preview_x >= 32 and preview_y >= 32
    assert gui_x + gui.width <= 1440 - 32
    assert gui_y + gui.height <= 900 - 32


def test_apply_initial_layout_uses_requested_size_in_platform_dpi_mode() -> None:
    class HiDPIWindow(_Window):
        def __init__(
            self,
            requested_width: int,
            requested_height: int,
            screen: Any,
        ) -> None:
            # pyglet dpi_scaling="platform" と同様、公開width/heightは2xの
            # framebuffer値、requested sizeはlogical値を返す。
            super().__init__(requested_width * 2, requested_height * 2, screen)
            self.requested_size = (int(requested_width), int(requested_height))

        def get_requested_size(self) -> tuple[int, int]:
            return self.requested_size

        def set_size(self, width: int, height: int) -> None:
            self.requested_size = (int(width), int(height))
            self.width = int(width) * 2
            self.height = int(height) * 2
            self.size_calls.append((int(width), int(height)))

    screen = SimpleNamespace(x=0, y=0, width=1800, height=1100)
    preview = HiDPIWindow(900, 900, screen)
    gui = HiDPIWindow(800, 1000, screen)

    assert workspace_module._window_content_size(preview) == (900, 900)
    assert workspace_module._window_content_size(gui) == (800, 1000)

    applied = workspace_module._apply_initial_window_layout(
        preview_window=preview,
        parameter_gui_window=gui,
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert applied is True
    # 900+800+gap はscreen内に自然sizeで収まる。framebuffer値を誤用して
    # 725/995等へ再配分しないこと。
    assert preview.size_calls == []
    assert gui.size_calls == []
    preview_x, _preview_y = preview.location_calls[-1]
    gui_x, _gui_y = gui.location_calls[-1]
    assert gui_x - preview_x == 900 + 16


def test_apply_initial_layout_does_not_call_set_size_when_natural_sizes_fit() -> None:
    screen = SimpleNamespace(x=0, y=0, width=2400, height=1400)
    preview = _Window(900, 900, screen)
    gui = _Window(800, 1000, screen)

    applied = workspace_module._apply_initial_window_layout(
        preview_window=preview,
        parameter_gui_window=gui,
        preferred_preview_position=(100, 100),
        preferred_parameter_gui_position=(1016, 100),
    )

    assert applied is True
    assert preview.size_calls == []
    assert gui.size_calls == []
    assert preview.location_calls
    assert gui.location_calls


def test_apply_initial_layout_preserves_safe_dual_monitor_config() -> None:
    left_screen = SimpleNamespace(x=0, y=0, width=1920, height=1200)
    right_screen = SimpleNamespace(x=1920, y=0, width=1920, height=1200)
    screens = [left_screen, right_screen]
    preview = _Window(900, 900, left_screen, screens=screens)
    gui = _Window(800, 1000, left_screen, screens=screens)

    applied = workspace_module._apply_initial_window_layout(
        preview_window=preview,
        parameter_gui_window=gui,
        preferred_preview_position=(100, 100),
        preferred_parameter_gui_position=(2020, 100),
    )

    assert applied is True
    assert preview.size_calls == []
    assert gui.size_calls == []
    assert preview.location_calls == [(100, 100)]
    assert gui.location_calls == [(2020, 100)]


def test_apply_initial_layout_reflows_explicit_content_at_visible_frame_top() -> None:
    screen = SimpleNamespace(x=0, y=0, width=2400, height=1400)
    preview = _Window(900, 900, screen)
    gui = _Window(800, 1000, screen)

    applied = workspace_module._apply_initial_window_layout(
        preview_window=preview,
        parameter_gui_window=gui,
        preferred_preview_position=(100, 0),
        preferred_parameter_gui_position=(1016, 0),
    )

    assert applied is True
    # content top=visible top は title bar が visibleFrame 外へ出るため、安全な
    # 明示配置として温存せず DEFAULT_SCREEN_MARGIN 内へ reflow する。
    assert preview.location_calls[-1][1] >= 32
    assert gui.location_calls[-1][1] >= 32
    assert preview.location_calls[-1] != (100, 0)
    assert gui.location_calls[-1] != (1016, 0)


def test_activate_initial_windows_leaves_parameter_gui_in_front() -> None:
    calls: list[str] = []
    preview = SimpleNamespace(activate=lambda: calls.append("preview"))
    gui = SimpleNamespace(
        visible=True,
        activate=lambda: calls.append("gui"),
    )

    workspace_module._activate_initial_windows(preview, gui)

    assert calls == ["preview", "gui"]


def test_activate_initial_windows_does_not_reactivate_hidden_inspector() -> None:
    calls: list[str] = []
    preview = SimpleNamespace(activate=lambda: calls.append("preview"))
    gui = SimpleNamespace(
        visible=False,
        activate=lambda: calls.append("gui"),
    )

    workspace_module._activate_initial_windows(preview, gui)

    assert calls == ["preview"]


def test_apply_initial_layout_rejects_invalid_content_size_without_mutation() -> None:
    class InvalidWindow:
        def get_requested_size(self) -> tuple[int, int]:
            return 0, 0

        def set_location(self, _x: int, _y: int) -> None:
            raise AssertionError("invalid layout must not mutate the window")

    applied = workspace_module._apply_initial_window_layout(
        preview_window=InvalidWindow(),
        parameter_gui_window=InvalidWindow(),
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert applied is False


class _ShortcutWindow:
    def __init__(self, name: str) -> None:
        self.name = name
        self.visible = True
        self.handlers: dict[str, object] = {}
        self.calls: list[tuple[str, object]] = []

    def push_handlers(self, **kwargs: object) -> None:
        self.handlers.update(kwargs)

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        self.calls.append(("visible", self.visible))

    def activate(self) -> None:
        self.calls.append(("activate", self.name))


def test_inspector_close_hides_it_and_returns_focus_to_preview() -> None:
    preview = _ShortcutWindow("preview")
    inspector = _ShortcutWindow("inspector")

    workspace_module._set_inspector_visible(
        preview_window=preview,
        inspector_window=inspector,
        visible=False,
    )

    assert inspector.visible is False
    assert inspector.calls == [("visible", False)]
    assert preview.calls == [("activate", "preview")]


def test_cmd_or_ctrl_i_toggles_and_reactivates_inspector() -> None:
    preview = _ShortcutWindow("preview")
    inspector = _ShortcutWindow("inspector")
    workspace_module._install_inspector_visibility_shortcut(
        preview_window=preview,
        inspector_window=inspector,
    )
    preview_handler = preview.handlers["on_key_press"]
    inspector_handler = inspector.handlers["on_key_press"]

    assert callable(preview_handler)
    assert callable(inspector_handler)
    assert preview_handler(pyglet.window.key.I, 0) is None

    assert (
        preview_handler(pyglet.window.key.I, pyglet.window.key.MOD_COMMAND)
        is pyglet.event.EVENT_HANDLED
    )
    assert inspector.visible is False
    assert preview.calls == [("activate", "preview")]

    assert (
        inspector_handler(pyglet.window.key.I, pyglet.window.key.MOD_CTRL)
        is pyglet.event.EVENT_HANDLED
    )
    assert inspector.visible is True
    assert inspector.calls == [
        ("visible", False),
        ("visible", True),
        ("activate", "inspector"),
    ]


class _WorkspaceWindow:
    def __init__(self, *, rect: WindowRect, screen: Any) -> None:
        self.x = rect.x
        self.y = rect.y
        self.width = rect.width
        self.height = rect.height
        self.visible = True
        self.screen = screen
        self.display = SimpleNamespace(get_screens=lambda: [screen])
        self.calls: list[tuple[object, ...]] = []

    def get_requested_size(self) -> tuple[int, int]:
        return self.width, self.height

    def get_location(self) -> tuple[int, int]:
        return self.x, self.y

    def set_location(self, x: int, y: int) -> None:
        self.x = int(x)
        self.y = int(y)
        self.calls.append(("location", self.x, self.y))

    def set_size(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.calls.append(("size", self.width, self.height))

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        self.calls.append(("visible", self.visible))


def test_saved_workspace_is_clamped_to_current_screen_and_restores_visibility() -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _WorkspaceWindow(rect=WindowRect(0, 0, 800, 700), screen=screen)
    inspector = _WorkspaceWindow(rect=WindowRect(800, 0, 500, 700), screen=screen)
    saved = WorkspaceState(
        preview_rect=WindowRect(2000, -100, 900, 900),
        inspector_rect=WindowRect(3000, 100, 1000, 1200),
        inspector_visible=False,
        ui_scale=1.5,
    )

    assert workspace_module._apply_workspace_layout(
        preview_window=preview,
        inspector_window=inspector,
        state=saved,
    )

    safe = WindowRect(32, 32, 1376, 836)
    preview_rect = workspace_module._window_rect(preview)
    inspector_rect = workspace_module._window_rect(inspector)
    assert preview_rect is not None
    assert inspector_rect is not None
    assert workspace_module._rect_is_inside(preview_rect, safe)
    assert workspace_module._rect_is_inside(inspector_rect, safe)
    assert inspector.visible is False
    assert inspector.calls[-1] == ("visible", False)


def test_workspace_snapshot_keeps_loaded_ui_scale_and_hidden_inspector() -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _WorkspaceWindow(rect=WindowRect(40, 50, 700, 700), screen=screen)
    inspector = _WorkspaceWindow(rect=WindowRect(760, 50, 500, 800), screen=screen)
    inspector.visible = False
    previous = WorkspaceState(
        preview_rect=WindowRect(0, 0, 1, 1),
        inspector_rect=None,
        inspector_visible=True,
        ui_scale=1.75,
    )

    state = workspace_module._workspace_state_from_windows(
        preview_window=preview,
        inspector_window=inspector,
        previous=previous,
    )

    assert state == WorkspaceState(
        preview_rect=WindowRect(40, 50, 700, 700),
        inspector_rect=WindowRect(760, 50, 500, 800),
        inspector_visible=False,
        ui_scale=1.75,
    )


def test_shutdown_persists_current_workspace(tmp_path: Path) -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _WorkspaceWindow(rect=WindowRect(40, 50, 700, 700), screen=screen)
    inspector = _WorkspaceWindow(rect=WindowRect(760, 50, 500, 800), screen=screen)
    inspector.visible = False
    previous = WorkspaceState(
        preview_rect=WindowRect(0, 0, 1, 1),
        inspector_rect=None,
        inspector_visible=True,
        ui_scale=1.75,
    )
    path = tmp_path / "workspace.json"

    workspace_module._persist_workspace_state_on_shutdown(
        path=path,
        preview_window=preview,
        inspector_window=inspector,
        previous=previous,
    )

    result = load_workspace_state(path, fallback=previous)
    assert result.restored
    assert result.state == WorkspaceState(
        preview_rect=WindowRect(40, 50, 700, 700),
        inspector_rect=WindowRect(760, 50, 500, 800),
        inspector_visible=False,
        ui_scale=1.75,
    )


def test_workspace_controller_owns_restore_and_persist_lifecycle(
    tmp_path: Path,
) -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _WorkspaceWindow(rect=WindowRect(0, 0, 800, 700), screen=screen)
    inspector = _WorkspaceWindow(rect=WindowRect(800, 0, 500, 700), screen=screen)
    saved = WorkspaceState(
        preview_rect=WindowRect(40, 50, 700, 700),
        inspector_rect=WindowRect(760, 50, 500, 800),
        inspector_visible=False,
        ui_scale=1.5,
    )
    path = tmp_path / "workspace.json"
    controller = workspace_module.WorkspaceWindowController(
        path=path,
        state=saved,
        restored=True,
        preferred_preview_position=(200, 100),
        preferred_inspector_position=(980, 100),
    )

    controller.attach_preview(preview)
    controller.attach_inspector(inspector)

    assert controller.apply_layout()
    assert inspector.visible is False
    controller.persist()

    result = load_workspace_state(path, fallback=saved)
    assert result.restored
    assert result.state.preview_rect == workspace_module._window_rect(preview)
    assert result.state.inspector_rect == workspace_module._window_rect(inspector)
    assert result.state.inspector_visible is False
    assert result.state.ui_scale == 1.5


def test_workspace_controller_loads_missing_state_as_config_fallback(
    tmp_path: Path,
) -> None:
    controller = workspace_module.WorkspaceWindowController.load(
        path=tmp_path / "missing.json",
        preview_size=(640, 480),
        inspector_size=(760, 900),
        preferred_preview_position=(40, 50),
        preferred_inspector_position=(700, 50),
    )

    assert controller.restored is False
    assert controller.diagnostic is None
    assert controller.ui_scale == 1.0
