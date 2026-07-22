import sys
from types import ModuleType, SimpleNamespace

from grafix.interactive.parameter_gui.pyglet_backend import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT,
    MINIMUM_PARAMETER_GUI_WINDOW_WIDTH,
    PygletImguiBackend,
    content_region_available_width,
)


def test_parameter_gui_backend_default_window_size_is_wide() -> None:
    assert (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT) == (1100, 1000)
    assert (
        MINIMUM_PARAMETER_GUI_WINDOW_WIDTH,
        MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT,
    ) == (760, 480)


def test_backend_constructs_and_owns_programmable_pipeline_renderer(
    monkeypatch,
) -> None:
    imgui_module = ModuleType("imgui")
    imgui_module.__path__ = []  # type: ignore[attr-defined]
    integrations_module = ModuleType("imgui.integrations")
    integrations_module.__path__ = []  # type: ignore[attr-defined]
    pyglet_module = ModuleType("imgui.integrations.pyglet")

    class Renderer:
        def __init__(self, window: object) -> None:
            self.window = window
            self.shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    pyglet_module.PygletProgrammablePipelineRenderer = Renderer  # type: ignore[attr-defined]
    io = SimpleNamespace(
        get_clipboard_text_fn=lambda: "configured",
        set_clipboard_text_fn=None,
    )
    context = object()
    imgui_module.create_context = lambda: context  # type: ignore[attr-defined]
    imgui_module.set_current_context = lambda _context: None  # type: ignore[attr-defined]
    imgui_module.get_io = lambda: io  # type: ignore[attr-defined]
    imgui_module.destroy_context = lambda _context: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "imgui", imgui_module)
    monkeypatch.setitem(sys.modules, "imgui.integrations", integrations_module)
    monkeypatch.setitem(sys.modules, "imgui.integrations.pyglet", pyglet_module)

    window = SimpleNamespace(switch_to=lambda: None)
    backend = PygletImguiBackend(window)
    renderer = backend._renderer

    assert isinstance(renderer, Renderer)
    assert renderer.window is window
    backend.close()
    assert renderer.shutdown_calls == 1


def test_content_width_uses_the_pyimgui_2_scalar_api() -> None:
    class Imgui:
        @staticmethod
        def get_content_region_available_width() -> float:
            return 321.5

    assert content_region_available_width(Imgui()) == 321.5
