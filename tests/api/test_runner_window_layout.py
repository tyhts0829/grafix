# ruff: noqa: E402 -- pyglet option must be set before importing runner.

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pyglet

pyglet.options["shadow_window"] = False

import grafix.api.runner as runner_module
from grafix.interactive.runtime.window_layout import WindowRect


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

    bounds = runner_module._usable_screen_bounds(window, (200, 100))

    assert bounds == WindowRect(80, 25, 1360, 850)


def test_apply_initial_layout_resizes_and_places_realistic_windows() -> None:
    screen = SimpleNamespace(x=0, y=0, width=1440, height=900)
    preview = _Window(900, 900, screen)
    gui = _Window(800, 1000, screen)

    applied = runner_module._apply_initial_window_layout(
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

    assert runner_module._window_content_size(preview) == (900, 900)
    assert runner_module._window_content_size(gui) == (800, 1000)

    applied = runner_module._apply_initial_window_layout(
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

    applied = runner_module._apply_initial_window_layout(
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

    applied = runner_module._apply_initial_window_layout(
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

    applied = runner_module._apply_initial_window_layout(
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
    gui = SimpleNamespace(activate=lambda: calls.append("gui"))

    runner_module._activate_initial_windows(preview, gui)

    assert calls == ["preview", "gui"]


def test_apply_initial_layout_preserves_stub_compatible_fallback() -> None:
    class StubWindow:
        width = 900
        height = 900

        def set_location(self, _x: int, _y: int) -> None:
            raise AssertionError("layout fallback must not mutate the stub")

    applied = runner_module._apply_initial_window_layout(
        preview_window=StubWindow(),
        parameter_gui_window=StubWindow(),
        preferred_preview_position=(200, 100),
        preferred_parameter_gui_position=(980, 100),
    )

    assert applied is False
