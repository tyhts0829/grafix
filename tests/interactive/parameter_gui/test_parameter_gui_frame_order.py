from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.interactive.parameter_gui import pyglet_backend as backend_module
from grafix.interactive.parameter_gui.gui import ParameterGUI


class _FakeIo:
    def __init__(self) -> None:
        self.delta_time = -1.0
        self.display_size = (-1.0, -1.0)
        self.display_fb_scale = (-1.0, -1.0)
        self.mouse_wheel = 2.0


class _FakeImgui:
    def __init__(self, calls: list[str]) -> None:
        self.io = _FakeIo()
        self._calls = calls
        self.io_at_new_frame: tuple[
            tuple[float, float], tuple[float, float], float, float
        ] | None = None

    def get_io(self) -> _FakeIo:
        return self.io

    def set_current_context(self, _context: object) -> None:
        pass

    def new_frame(self) -> None:
        self._calls.append("new_frame")
        self.io_at_new_frame = (
            self.io.display_size,
            self.io.display_fb_scale,
            self.io.delta_time,
            self.io.mouse_wheel,
        )

    def render(self) -> None:
        self._calls.append("render")

    def get_draw_data(self) -> object:
        return object()


@pytest.mark.parametrize("framebuffer_scale", [1.0, 2.0])
def test_backend_syncs_current_window_io_before_new_frame_and_owns_render(
    monkeypatch: pytest.MonkeyPatch,
    framebuffer_scale: float,
) -> None:
    calls: list[str] = []
    imgui = _FakeImgui(calls)
    window = SimpleNamespace(
        width=640,
        height=360,
        get_framebuffer_size=lambda: (
            int(640 * framebuffer_scale),
            int(360 * framebuffer_scale),
        ),
        clear=lambda: calls.append("clear"),
    )
    renderer = SimpleNamespace(
        render=lambda _draw_data: calls.append("backend_render"),
    )

    backend = cast(Any, object.__new__(backend_module.PygletImguiBackend))
    backend._closed = False
    backend._window = window
    backend._imgui = imgui
    backend._context = object()
    backend._renderer = renderer

    sync_io = backend._sync_io

    def observe_sync_io(*, dt: float) -> None:
        sync_io(dt=dt)
        calls.append("sync_io")

    monkeypatch.setattr(backend, "_sync_io", observe_sync_io)
    monkeypatch.setitem(
        sys.modules,
        "pyglet",
        SimpleNamespace(
            gl=SimpleNamespace(
                glClearColor=lambda *_args: calls.append("clear_color")
            )
        ),
    )

    backend.begin_frame(0.125)
    backend.render()

    assert calls == [
        "sync_io",
        "new_frame",
        "render",
        "clear_color",
        "clear",
        "backend_render",
    ]
    assert imgui.io_at_new_frame == (
        (640.0, 360.0),
        (framebuffer_scale, framebuffer_scale),
        0.125,
        -0.5,
    )


def test_parameter_gui_frame_panels_keep_semantic_order_and_aggregate_changes() -> None:
    calls: list[str] = []
    gui = cast(Any, object.__new__(ParameterGUI))
    gui._imgui = SimpleNamespace(
        get_content_region_available_width=lambda: 720.0,
    )
    gui._render_toolbar_area = lambda **_kwargs: calls.append("toolbar") or False
    gui._render_midi_clear_notice = lambda: calls.append("midi_notice") or True
    gui._render_parameter_table_toolbar = (
        lambda: calls.append("table_toolbar") or False
    )
    gui._render_reconcile_orphan_control = (
        lambda: calls.append("reconcile") or False
    )
    gui._maybe_preview_range_edit_by_midi = (
        lambda: calls.append("range_preview") or False
    )
    gui._render_range_edit_mode = lambda: calls.append("range_controls") or False
    gui._render_parameter_workspace = (
        lambda **_kwargs: calls.append("table_and_drawer") or False
    )

    assert gui._render_frame_panels(monitor_snapshot=None) is True
    assert calls == [
        "toolbar",
        "midi_notice",
        "table_toolbar",
        "reconcile",
        "range_preview",
        "range_controls",
        "table_and_drawer",
    ]


def test_parameter_gui_draw_frame_wraps_panels_with_backend_lifecycle() -> None:
    calls: list[str] = []

    class _FrameImgui:
        WINDOW_NO_RESIZE = 1
        WINDOW_NO_COLLAPSE = 2
        WINDOW_NO_TITLE_BAR = 4

        @staticmethod
        def set_next_window_position(_x: int, _y: int) -> None:
            calls.append("window_position")

        @staticmethod
        def set_next_window_size(_width: int, _height: int) -> None:
            calls.append("window_size")

        @staticmethod
        def begin(_title: str, *, flags: int) -> None:
            assert flags == 7
            calls.append("window_begin")

        @staticmethod
        def is_any_item_active() -> bool:
            calls.append("item_activity")
            return False

        @staticmethod
        def end() -> None:
            calls.append("window_end")

    gui = cast(Any, object.__new__(ParameterGUI))
    gui._closed = False
    gui._prev_time = time.monotonic()
    gui._imgui = _FrameImgui()
    gui._backend = SimpleNamespace(
        activate_context=lambda: calls.append("backend_activate"),
        begin_frame=lambda _dt: calls.append("backend_begin"),
        render=lambda: calls.append("backend_render"),
    )
    gui._sync_font_for_window = lambda: calls.append("font_sync")
    gui._window = SimpleNamespace(width=640, height=480)
    gui._title = "Parameters"
    gui._monitor = None
    gui._history = SimpleNamespace(
        break_coalescing=lambda: calls.append("history_break"),
    )
    gui._session = SimpleNamespace(parameter_edit_active=True)
    gui._render_frame_panels = (
        lambda **_kwargs: calls.append("panels") or True
    )

    assert gui._draw_frame() is True
    assert gui._session.parameter_edit_active is False
    assert calls == [
        "backend_activate",
        "font_sync",
        "backend_begin",
        "window_position",
        "window_size",
        "window_begin",
        "panels",
        "item_activity",
        "history_break",
        "window_end",
        "backend_render",
    ]
