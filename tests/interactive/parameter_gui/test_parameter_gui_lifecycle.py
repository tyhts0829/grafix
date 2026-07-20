from __future__ import annotations

from typing import Any, cast

import pytest

from grafix.core.parameters import ParamStore
from grafix.core.runtime_config import RuntimeConfig
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
    initialized_parameter_gui: ParameterGUI,
) -> None:
    calls: list[str] = []
    gui = cast(Any, initialized_parameter_gui)
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
    effective_runtime_config: RuntimeConfig,
) -> None:
    calls: list[str] = []
    window = _FailingWindow(calls)

    def fail_initialize(self: ParameterGUI, *_args: object, **_kwargs: object) -> None:
        gui_state = cast(Any, self)
        gui_state._renderer = _FailingRenderer(calls)
        gui_state._imgui = _FailingImGui(calls)
        gui_state._context = "owned-context"
        raise ValueError("font initialization failed")

    monkeypatch.setattr(ParameterGUI, "_initialize", fail_initialize)

    with pytest.raises(ValueError, match="font initialization failed"):
        ParameterGUI(
            window,
            effective_config=effective_runtime_config,
            store=ParamStore(),
        )

    assert calls == [
        "switch_to",
        "renderer.shutdown",
        "imgui.destroy_context",
        "window.close",
    ]


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"transport_fps": "60"}, TypeError, "transport_fps"),
        ({"transport_fps": 0.0}, ValueError, "transport_fps"),
        ({"ui_scale": True}, TypeError, "ui_scale"),
        ({"ui_scale": float("nan")}, ValueError, "ui_scale"),
        ({"title": 1}, TypeError, "title"),
        ({"title": ""}, ValueError, "title"),
    ],
)
def test_parameter_gui_rejects_noncanonical_scalar_configuration_before_init(
    effective_runtime_config: RuntimeConfig,
    kwargs: dict[str, object],
    error: type[Exception],
    match: str,
) -> None:
    window = _FailingWindow([])
    with pytest.raises(error, match=match):
        ParameterGUI(
            window,
            effective_config=effective_runtime_config,
            store=ParamStore(),
            **kwargs,  # type: ignore[arg-type]
        )
