from __future__ import annotations

import pytest

from grafix.core.parameters import ParamStore
from grafix.interactive.parameter_gui.gui import ParameterGUI


class _FailingWindow:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def switch_to(self) -> None:
        self._calls.append("switch_to")
        raise RuntimeError("switch failed")

    def close(self) -> None:
        self._calls.append("window.close")
        raise RuntimeError("window close failed")


class _FailingRenderer:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def shutdown(self) -> None:
        self._calls.append("renderer.shutdown")
        raise RuntimeError("renderer shutdown failed")


class _FailingImGui:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def destroy_context(self, context: object) -> None:
        assert context == "owned-context"
        self._calls.append("imgui.destroy_context")
        raise RuntimeError("context destroy failed")


def test_close_switches_to_owned_context_and_attempts_every_cleanup_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    gui = ParameterGUI.__new__(ParameterGUI)
    gui._closed = False
    gui._window = _FailingWindow(calls)
    gui._renderer = _FailingRenderer(calls)
    gui._imgui = _FailingImGui(calls)
    gui._context = "owned-context"

    with pytest.raises(RuntimeError, match="switch failed"):
        gui.close()

    assert calls == [
        "switch_to",
        "renderer.shutdown",
        "imgui.destroy_context",
        "window.close",
    ]

    # 最初の close が例外を返しても、二重解放はしない。
    gui.close()
    assert len(calls) == 4
    assert caplog.records == []


def test_partial_initialization_cleans_resources_and_preserves_root_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    window = _FailingWindow(calls)

    def fail_initialize(self: ParameterGUI, *_args: object, **_kwargs: object) -> None:
        self._renderer = _FailingRenderer(calls)
        self._imgui = _FailingImGui(calls)
        self._context = "owned-context"
        raise ValueError("font initialization failed")

    monkeypatch.setattr(ParameterGUI, "_initialize", fail_initialize)

    with pytest.raises(ValueError, match="font initialization failed"):
        ParameterGUI(window, store=ParamStore())

    assert calls == [
        "switch_to",
        "renderer.shutdown",
        "imgui.destroy_context",
        "window.close",
    ]
