from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from grafix.interactive.parameter_gui import gui as gui_module


class _Fonts:
    def __init__(self) -> None:
        self.clear_calls = 0
        self.add_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1

    def add_font_from_file_ttf(self, *_args: object, **_kwargs: object) -> None:
        self.add_calls += 1

    @staticmethod
    def get_glyph_ranges_default() -> tuple[()]:
        return ()


class _Renderer:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_font_texture(self) -> None:
        self.refresh_calls += 1


def test_font_resolution_runs_only_when_scale_or_config_changes(monkeypatch) -> None:
    fonts = _Fonts()
    io = SimpleNamespace(fonts=fonts)
    imgui = SimpleNamespace(get_io=lambda: io)
    renderer = _Renderer()
    window = SimpleNamespace(scale=1.0)
    config_holder: dict[str, Any] = {
        "value": SimpleNamespace(
            config_path=None,
            parameter_gui_fallback_font_japanese=None,
            font_dirs=(),
        )
    }
    resolve_calls = 0

    def resolve_fallback() -> None:
        nonlocal resolve_calls
        resolve_calls += 1
        return None

    monkeypatch.setattr(gui_module, "runtime_config", lambda: config_holder["value"])
    monkeypatch.setattr(
        gui_module,
        "_gui_fallback_font_path_for_japanese",
        resolve_fallback,
    )

    parameter_gui = object.__new__(gui_module.ParameterGUI)
    parameter_gui._custom_font_path = Path(__file__)
    parameter_gui._font_size_base_px = 12.0
    parameter_gui._font_backing_scale = None
    parameter_gui._font_fallback_path_for_japanese = None
    parameter_gui._font_sync_key = None
    parameter_gui._window = window
    parameter_gui._imgui = imgui
    parameter_gui._renderer = renderer

    parameter_gui._sync_font_for_window()
    parameter_gui._sync_font_for_window()
    assert resolve_calls == 1
    assert fonts.clear_calls == 1
    assert renderer.refresh_calls == 1

    window.scale = 2.0
    parameter_gui._sync_font_for_window()
    assert resolve_calls == 2

    config_holder["value"] = SimpleNamespace(
        config_path=Path("other.yaml"),
        parameter_gui_fallback_font_japanese="Noto Sans JP",
        font_dirs=(Path("fonts"),),
    )
    parameter_gui._sync_font_for_window()
    assert resolve_calls == 3
