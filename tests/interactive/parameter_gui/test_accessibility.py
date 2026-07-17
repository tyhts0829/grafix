from __future__ import annotations

from types import SimpleNamespace

import pytest

from grafix.interactive.parameter_gui.gui import (
    _enable_keyboard_navigation,
    _item_tooltip,
)
from grafix.interactive.parameter_gui.shortcuts import (
    resolve_shortcut_keys,
    shortcut_help_lines,
)
from grafix.interactive.parameter_gui.table import _set_item_tooltip


class _TooltipImgui:
    def __init__(self, *, hovered: bool, focused: bool) -> None:
        self.hovered = hovered
        self.focused = focused
        self.tooltips: list[str] = []

    def is_item_hovered(self) -> bool:
        return self.hovered

    def is_item_focused(self) -> bool:
        return self.focused

    def set_tooltip(self, text: str) -> None:
        self.tooltips.append(text)


@pytest.mark.parametrize("helper", [_item_tooltip, _set_item_tooltip])
def test_tooltip_is_available_from_keyboard_focus(helper: object) -> None:
    imgui = _TooltipImgui(hovered=False, focused=True)
    helper(imgui, "Keyboard-accessible help")  # type: ignore[operator]
    assert imgui.tooltips == ["Keyboard-accessible help"]


def test_shortcut_config_resolves_keys_and_produces_help_list() -> None:
    bindings = (
        ("play_pause", "SPACE"),
        ("range_shift", "R"),
        ("cancel", "ESCAPE"),
        ("undo", "Z"),
    )
    keys = SimpleNamespace(SPACE=32, R=82, ESCAPE=27, Z=90)

    assert resolve_shortcut_keys(bindings, key_namespace=keys) == {
        "play_pause": 32,
        "range_shift": 82,
        "cancel": 27,
        "undo": 90,
    }
    lines = shortcut_help_lines(bindings)
    assert "Play / Pause — Space" in lines
    assert "Range: shift — R" in lines
    assert "Undo — Cmd/Ctrl+Z" in lines


def test_shortcut_config_rejects_unknown_key_name() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        resolve_shortcut_keys(
            (("play_pause", "UNKNOWN"),),
            key_namespace=SimpleNamespace(),
        )


def test_keyboard_navigation_flag_enables_native_tab_and_enter_navigation() -> None:
    io = SimpleNamespace(config_flags=0b1000)
    imgui = SimpleNamespace(
        CONFIG_NAV_ENABLE_KEYBOARD=0b0010,
        get_io=lambda: io,
    )

    assert _enable_keyboard_navigation(imgui) is True
    assert io.config_flags == 0b1010
