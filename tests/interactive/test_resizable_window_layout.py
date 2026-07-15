from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from typing import Any, cast

import pyglet
import pytest

from grafix.core.parameters import ParamStore
from grafix.interactive.gl.draw_renderer import DrawRenderer, _aspect_fit_viewport
from grafix.interactive.parameter_gui import gui as gui_module
from grafix.interactive.parameter_gui import pyglet_backend
from grafix.interactive.render_settings import RenderSettings


class _FakeWindow:
    def __init__(self, *, width: int, height: int, scale: float = 2.0) -> None:
        self.width = int(width)
        self.height = int(height)
        self.scale = float(scale)
        self.set_size_calls: list[tuple[int, int]] = []
        self.clear_calls = 0

    def get_framebuffer_size(self) -> tuple[int, int]:
        return int(self.width * self.scale), int(self.height * self.scale)

    def set_size(self, width: int, height: int) -> None:
        self.set_size_calls.append((int(width), int(height)))
        self.width = int(width)
        self.height = int(height)

    def clear(self) -> None:
        self.clear_calls += 1


class _FakeImGui:
    WINDOW_NO_RESIZE = 1
    WINDOW_NO_COLLAPSE = 2
    WINDOW_NO_TITLE_BAR = 4

    def __init__(self) -> None:
        self.io = SimpleNamespace(mouse_wheel=0.0)
        self.next_window_sizes: list[tuple[int, int]] = []

    def get_io(self) -> Any:
        return self.io

    def set_current_context(self, _context: object) -> None:
        pass

    def new_frame(self) -> None:
        pass

    def set_next_window_position(self, _x: int, _y: int) -> None:
        pass

    def set_next_window_size(self, width: int, height: int) -> None:
        self.next_window_sizes.append((int(width), int(height)))

    def begin(self, _title: str, *, flags: int) -> None:
        assert flags == 7

    def button(self, _label: str) -> bool:
        return False

    def same_line(self) -> None:
        pass

    def checkbox(self, _label: str, value: bool) -> tuple[bool, bool]:
        return False, bool(value)

    def text_disabled(self, _text: str) -> None:
        pass

    def begin_child(
        self,
        _name: str,
        _width: int,
        _height: int,
        *,
        border: bool,
    ) -> None:
        assert border is False

    def end_child(self) -> None:
        pass

    def end(self) -> None:
        pass

    def render(self) -> None:
        pass

    def get_draw_data(self) -> object:
        return object()


class _FakeImGuiRenderer:
    def __init__(self) -> None:
        self.render_calls = 0

    def render(self, _draw_data: object) -> None:
        self.render_calls += 1


def test_parameter_gui_draw_keeps_requested_logical_width_on_retina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _FakeWindow(width=800, height=1000, scale=2.0)
    imgui = _FakeImGui()
    renderer = _FakeImGuiRenderer()
    gui = gui_module.ParameterGUI.__new__(gui_module.ParameterGUI)
    gui._closed = False
    gui._prev_time = time.monotonic()
    gui._imgui = cast(Any, imgui)
    gui._context = object()
    gui._custom_font_path = None
    gui._window = window
    gui._renderer = renderer
    gui._monitor = None
    gui._transport = None
    gui._history = None
    gui._snapshot_slots = None
    gui._midi_controller = None
    gui._store = ParamStore()
    gui._midi_learn_state = cast(
        Any,
        SimpleNamespace(
            active_target=None,
            active_component=None,
        ),
    )
    gui._show_inactive_params = False
    gui._column_weights = (0.2, 0.6, 0.15, 0.2)
    gui._title = "Parameters"

    monkeypatch.setattr(gui_module, "_sync_imgui_io_for_window", lambda *_a, **_k: None)
    monkeypatch.setattr(
        gui_module,
        "render_store_parameter_table",
        lambda *_a, **_k: False,
    )
    fake_pyglet = SimpleNamespace(
        gl=SimpleNamespace(glClearColor=lambda *_args: None),
    )
    monkeypatch.setitem(sys.modules, "pyglet", fake_pyglet)

    gui.draw_frame()

    assert window.get_framebuffer_size() == (1600, 2000)
    assert window.set_size_calls == []
    assert imgui.next_window_sizes == [(800, 1000)]
    assert renderer.render_calls == 1
    assert window.clear_calls == 1


def test_parameter_gui_window_is_resizable_and_keeps_requested_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CreatedWindow:
        def set_minimum_size(self, width: int, height: int) -> None:
            captured["minimum_size"] = (int(width), int(height))

    sentinel = CreatedWindow()

    def config(**kwargs: object) -> object:
        captured["config"] = dict(kwargs)
        return "gl-config"

    def window(**kwargs: object) -> object:
        captured["window"] = dict(kwargs)
        return sentinel

    fake_pyglet = SimpleNamespace(
        gl=SimpleNamespace(Config=config),
        window=SimpleNamespace(Window=window),
    )
    monkeypatch.setitem(sys.modules, "pyglet", fake_pyglet)

    result = pyglet_backend.create_parameter_gui_window(width=840, height=720)

    assert result is sentinel
    assert captured["window"] == {
        "width": 840,
        "height": 720,
        "caption": "Grafix Inspector",
        "resizable": True,
        "vsync": False,
        "config": "gl-config",
    }
    assert captured["minimum_size"] == (560, 480)


def test_draw_window_is_resizable(monkeypatch: pytest.MonkeyPatch) -> None:
    # pyglet.gl import 時の shadow context を headless test で作らない。
    pyglet.options["shadow_window"] = False
    from grafix.interactive import draw_window as draw_window_module

    captured: dict[str, object] = {}

    class CreatedWindow:
        def set_minimum_size(self, width: int, height: int) -> None:
            captured["minimum_size"] = (int(width), int(height))

    sentinel = CreatedWindow()

    def config(**kwargs: object) -> object:
        captured["config"] = dict(kwargs)
        return "gl-config"

    def window(**kwargs: object) -> object:
        captured["window"] = dict(kwargs)
        return sentinel

    monkeypatch.setattr(draw_window_module, "Config", config)
    monkeypatch.setattr(
        draw_window_module,
        "pyglet",
        SimpleNamespace(window=SimpleNamespace(Window=window)),
    )

    result = draw_window_module.create_draw_window(
        RenderSettings(canvas_size=(320, 240), render_scale=1.5)
    )

    assert result is sentinel
    assert captured["window"] == {
        "width": 480,
        "height": 360,
        "resizable": True,
        "caption": "Grafix",
        "config": "gl-config",
    }
    assert captured["minimum_size"] == (320, 320)


@pytest.mark.parametrize(
    ("framebuffer_size", "canvas_size", "expected"),
    [
        ((1200, 800), (800, 800), (200, 0, 800, 800)),
        ((800, 800), (800, 400), (0, 200, 800, 400)),
        ((1600, 1200), (800, 600), (0, 0, 1600, 1200)),
        ((0, 0), (800, 600), (0, 0, 1, 1)),
    ],
)
def test_aspect_fit_viewport_centers_canvas_without_distortion(
    framebuffer_size: tuple[int, int],
    canvas_size: tuple[int, int],
    expected: tuple[int, int, int, int],
) -> None:
    assert _aspect_fit_viewport(framebuffer_size, canvas_size) == expected


def test_draw_renderer_uses_aspect_fit_size_for_viewport_and_line_width() -> None:
    class Context:
        def __init__(self) -> None:
            self.viewport: tuple[int, int, int, int] | None = None
            self.clear_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def clear(self, *args: object, **kwargs: object) -> None:
            self.clear_calls.append((args, dict(kwargs)))

    uniform = SimpleNamespace(value=(1.0, 1.0))
    context = Context()
    renderer = DrawRenderer.__new__(DrawRenderer)
    renderer.ctx = cast(Any, context)
    renderer.program = {"viewport_size": uniform}
    renderer._canvas_w = 800
    renderer._canvas_h = 800
    renderer._framebuffer_size = (1, 1)
    renderer._viewport = (0, 0, 1, 1)
    renderer._viewport_size = (1, 1)

    renderer.viewport(1200, 800)

    assert context.viewport == (200, 0, 800, 800)
    assert renderer._framebuffer_size == (1200, 800)
    assert renderer._viewport_size == (800, 800)
    assert uniform.value == (800.0, 800.0)

    renderer.clear((0.25, 0.5, 0.75))
    assert context.clear_calls == [
        (
            (0.25, 0.5, 0.75, 1.0),
            {"viewport": (0, 0, 1200, 800)},
        )
    ]
    assert context.viewport == (200, 0, 800, 800)
