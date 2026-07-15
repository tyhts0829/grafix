from __future__ import annotations

from typing import Any, cast

import pyglet

from grafix.interactive.runtime.window_loop import MultiWindowLoop, WindowTask


def test_close_event_is_handled_until_runner_teardown(
    monkeypatch: Any,
) -> None:
    handlers: dict[str, object] = {}
    exit_calls: list[str] = []

    class Window:
        def push_handlers(self, **kwargs: object) -> None:
            handlers.update(kwargs)

    window = cast(Any, Window())
    loop = MultiWindowLoop(
        [WindowTask(window=window, draw_frame=lambda: None)],
        fps=60.0,
    )
    monkeypatch.setattr(pyglet.app, "exit", lambda: exit_calls.append("exit"))
    monkeypatch.setattr(pyglet.app, "run", lambda **_kwargs: None)
    monkeypatch.setattr(pyglet.clock, "schedule_interval", lambda *_args: None)
    monkeypatch.setattr(pyglet.clock, "unschedule", lambda *_args: None)

    loop.run()

    on_close = cast(Any, handlers["on_close"])
    assert on_close() is pyglet.event.EVENT_HANDLED
    assert exit_calls == ["exit"]
