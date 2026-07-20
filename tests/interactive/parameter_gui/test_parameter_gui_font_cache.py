from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from grafix.interactive.parameter_gui import gui as gui_module


class _Fonts:
    def __init__(self) -> None:
        self.clear_calls = 0
        self.add_calls = 0
        self.added_fonts: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def clear(self) -> None:
        self.clear_calls += 1

    def add_font_from_file_ttf(self, *_args: object, **_kwargs: object) -> None:
        self.add_calls += 1
        self.added_fonts.append((_args, dict(_kwargs)))

    @staticmethod
    def get_glyph_ranges_default() -> tuple[()]:
        return ()

    @staticmethod
    def get_glyph_ranges_japanese() -> tuple[()]:
        return ()


class _Renderer:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_font_texture(self) -> None:
        self.refresh_calls += 1


class _GlyphRanges:
    def __init__(self, values: tuple[int, ...]) -> None:
        self.values = tuple(values)


class _FontConfig:
    def __init__(self, *, merge_mode: bool) -> None:
        self.merge_mode = bool(merge_mode)


def test_default_gui_font_only_treats_missing_file_as_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        gui_module,
        "default_font_path",
        lambda: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    assert gui_module._default_gui_font_path() is None

    monkeypatch.setattr(
        gui_module,
        "default_font_path",
        lambda: (_ for _ in ()).throw(RuntimeError("resolver bug")),
    )
    with pytest.raises(RuntimeError, match="resolver bug"):
        gui_module._default_gui_font_path()


def test_font_resolution_uses_fixed_config_after_ambient_config_changes(
    monkeypatch,
    initialized_parameter_gui: gui_module.ParameterGUI,
) -> None:
    fonts = _Fonts()
    io = SimpleNamespace(fonts=fonts)
    imgui = SimpleNamespace(
        core=SimpleNamespace(GlyphRanges=_GlyphRanges, FontConfig=_FontConfig),
        get_io=lambda: io,
    )
    renderer = _Renderer()
    window = SimpleNamespace(scale=1.0)
    parameter_gui = cast(Any, initialized_parameter_gui)
    fixed_config = parameter_gui._effective_config
    resolve_calls = 0
    resolved_configs: list[object] = []

    def resolve_fallback(effective_config: object) -> None:
        nonlocal resolve_calls
        resolve_calls += 1
        resolved_configs.append(effective_config)
        return None

    monkeypatch.setattr(
        gui_module,
        "_gui_fallback_font_path_for_japanese",
        resolve_fallback,
    )

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

    ambient_config = replace(
        fixed_config,
        parameter_gui_fallback_font_japanese="Noto Sans JP",
        font_dirs=(Path("fonts"),),
    )
    monkeypatch.setattr(
        gui_module,
        "runtime_config",
        lambda: ambient_config,
        raising=False,
    )
    parameter_gui._sync_font_for_window()
    assert resolve_calls == 2
    assert resolved_configs == [fixed_config, fixed_config]


def test_favorite_star_glyphs_are_merged_from_bundled_font(
    monkeypatch,
    initialized_parameter_gui: gui_module.ParameterGUI,
) -> None:
    class GlyphRanges:
        def __init__(self, values: tuple[int, ...]) -> None:
            self.values = tuple(values)

    class FontConfig:
        def __init__(self, *, merge_mode: bool) -> None:
            self.merge_mode = bool(merge_mode)

    fonts = _Fonts()
    io = SimpleNamespace(fonts=fonts)
    imgui = SimpleNamespace(
        core=SimpleNamespace(GlyphRanges=GlyphRanges, FontConfig=FontConfig),
        get_io=lambda: io,
    )
    favorite_font = Path(__file__)
    monkeypatch.setattr(
        gui_module,
        "_gui_fallback_font_path_for_japanese",
        lambda _effective_config: None,
    )
    monkeypatch.setattr(
        gui_module,
        "_favorite_glyph_font_path",
        lambda: favorite_font,
    )

    parameter_gui = cast(Any, initialized_parameter_gui)
    parameter_gui._custom_font_path = Path(__file__)
    parameter_gui._font_size_base_px = 12.0
    parameter_gui._font_sync_key = None
    parameter_gui._window = SimpleNamespace(scale=1.0)
    parameter_gui._imgui = imgui
    parameter_gui._renderer = _Renderer()

    parameter_gui._sync_font_for_window()

    assert fonts.add_calls == 2
    favorite_args, favorite_kwargs = fonts.added_fonts[-1]
    assert favorite_args[:2] == (str(favorite_font), 12.0)
    assert cast(Any, favorite_kwargs["font_config"]).merge_mode is True
    assert cast(Any, favorite_kwargs["glyph_ranges"]).values == (0x2605, 0x2606, 0)


def test_japanese_fallback_font_merge_failure_is_not_silenced(
    tmp_path: Path,
    monkeypatch,
    initialized_parameter_gui: gui_module.ParameterGUI,
) -> None:
    class FailingFonts(_Fonts):
        def add_font_from_file_ttf(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> None:
            super().add_font_from_file_ttf(*_args, **_kwargs)
            if self.add_calls == 2:
                raise RuntimeError("font merge failed")

    fallback = tmp_path / "fallback.ttf"
    fallback.write_bytes(b"font")
    fonts = FailingFonts()
    imgui = SimpleNamespace(
        core=SimpleNamespace(GlyphRanges=_GlyphRanges, FontConfig=_FontConfig),
        get_io=lambda: SimpleNamespace(fonts=fonts),
    )
    monkeypatch.setattr(
        gui_module,
        "_gui_fallback_font_path_for_japanese",
        lambda _effective_config: fallback,
    )
    monkeypatch.setattr(gui_module, "_favorite_glyph_font_path", lambda: None)

    parameter_gui = cast(Any, initialized_parameter_gui)
    parameter_gui._custom_font_path = Path(__file__)
    parameter_gui._font_size_base_px = 12.0
    parameter_gui._font_sync_key = None
    parameter_gui._window = SimpleNamespace(scale=1.0)
    parameter_gui._imgui = imgui
    parameter_gui._renderer = _Renderer()

    with pytest.raises(RuntimeError, match="font merge failed"):
        parameter_gui._sync_font_for_window()
