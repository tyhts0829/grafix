from __future__ import annotations

import pytest

from grafix.devtools import pyimgui_show_window as module


def test_main_preserves_body_error_when_window_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_error = LookupError("backend construction failed")

    class Window:
        def switch_to(self) -> None:
            raise RuntimeError("context activation failed")

        def close(self) -> None:
            raise RuntimeError("window close failed")

    monkeypatch.setattr(module.pyglet.window, "Window", lambda *_args, **_kwargs: Window())

    def fail_backend(_window: object) -> object:
        raise root_error

    monkeypatch.setattr(module, "PygletImguiBackend", fail_backend)

    with pytest.raises(LookupError, match="backend construction failed") as captured:
        module.main()

    assert captured.value is root_error
