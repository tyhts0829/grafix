from __future__ import annotations

from typing import Any, cast

import pyglet
import pytest

from grafix.interactive.runtime.window_loop import MultiWindowLoop, WindowTask


def test_close_event_is_handled_until_runner_teardown(
    monkeypatch: Any,
) -> None:
    handlers: dict[str, object] = {}
    close_calls: list[str] = []

    class Window:
        def push_handlers(self, **kwargs: object) -> None:
            handlers.update(kwargs)

    window = cast(Any, Window())
    loop = MultiWindowLoop(
        (
            WindowTask(
                window=window,
                draw_frame=lambda: None,
                on_close=lambda: close_calls.append("close"),
            ),
        ),
        fps=60.0,
    )
    monkeypatch.setattr(pyglet.app, "run", lambda **_kwargs: None)
    monkeypatch.setattr(pyglet.clock, "schedule_interval", lambda *_args: None)
    monkeypatch.setattr(pyglet.clock, "unschedule", lambda *_args: None)

    loop.run()

    on_close = cast(Any, handlers["on_close"])
    assert on_close() is pyglet.event.EVENT_HANDLED
    assert close_calls == ["close"]


def test_each_window_uses_its_own_close_policy(monkeypatch: Any) -> None:
    handlers: dict[str, dict[str, object]] = {}
    calls: list[str] = []

    class Window:
        def __init__(self, name: str) -> None:
            self.name = name
            self.visible = True

        def push_handlers(self, **kwargs: object) -> None:
            handlers.setdefault(self.name, {}).update(kwargs)

        def set_visible(self, visible: bool) -> None:
            self.visible = bool(visible)

    preview = cast(Any, Window("preview"))
    inspector = cast(Any, Window("inspector"))
    monkeypatch.setattr(pyglet.app, "exit", lambda: calls.append("exit"))
    loop = MultiWindowLoop(
        (
            WindowTask(
                window=preview,
                draw_frame=lambda: None,
                on_close=pyglet.app.exit,
            ),
            WindowTask(
                window=inspector,
                draw_frame=lambda: None,
                on_close=lambda: inspector.set_visible(False),
            ),
        ),
        fps=60.0,
    )
    monkeypatch.setattr(pyglet.app, "run", lambda **_kwargs: None)
    monkeypatch.setattr(pyglet.clock, "schedule_interval", lambda *_args: None)
    monkeypatch.setattr(pyglet.clock, "unschedule", lambda *_args: None)

    loop.run()

    assert cast(Any, handlers["inspector"]["on_close"])() is pyglet.event.EVENT_HANDLED
    assert inspector.visible is False
    assert calls == []
    assert cast(Any, handlers["preview"]["on_close"])() is pyglet.event.EVENT_HANDLED
    assert calls == ["exit"]


def test_hidden_window_is_skipped_by_draw_loop(monkeypatch: Any) -> None:
    scheduled: list[Any] = []
    drawn: list[str] = []
    presented: list[int] = []
    full_loops: list[int] = []
    scheduler_jitter: list[int] = []

    class Window:
        def __init__(self, name: str, *, visible: bool) -> None:
            self.name = name
            self.visible = visible

        def push_handlers(self, **_kwargs: object) -> None:
            pass

        def draw(self, _dt: float) -> None:
            drawn.append(self.name)

    preview = cast(Any, Window("preview", visible=True))
    inspector = cast(Any, Window("inspector", visible=False))
    loop = MultiWindowLoop(
        (
            WindowTask(
                window=preview,
                draw_frame=lambda: None,
                on_close=lambda: None,
                on_presented=presented.append,
            ),
            WindowTask(
                window=inspector,
                draw_frame=lambda: None,
                on_close=lambda: None,
            ),
        ),
        fps=60.0,
        on_frame_finished=full_loops.append,
        on_scheduler_jitter=scheduler_jitter.append,
    )
    monkeypatch.setattr(pyglet.app, "windows", {preview, inspector})
    monkeypatch.setattr(pyglet.app, "run", lambda **_kwargs: None)
    monkeypatch.setattr(
        pyglet.clock,
        "schedule_interval",
        lambda callback, _interval: scheduled.append(callback),
    )
    monkeypatch.setattr(pyglet.clock, "unschedule", lambda *_args: None)

    loop.run()
    scheduled[0](1.0 / 60.0)
    scheduled[0](1.0 / 60.0)

    assert drawn == ["preview", "preview"]
    assert len(presented) == 2
    assert presented[0] >= 0
    assert len(full_loops) == 2
    assert full_loops[0] >= presented[0]
    assert len(scheduler_jitter) == 1
    assert scheduler_jitter[0] >= 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("draw_frame", None),
        ("on_close", 0),
        ("on_presented", "callback"),
    ),
)
def test_window_task_rejects_non_callable_callbacks(
    field: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {
        "window": object(),
        "draw_frame": lambda: None,
        "on_close": lambda: None,
        "on_presented": None,
    }
    kwargs[field] = value

    with pytest.raises(TypeError, match=field):
        WindowTask(**cast(Any, kwargs))


@pytest.mark.parametrize(
    "tasks",
    (
        [],
        [WindowTask(object(), lambda: None, lambda: None)],
        iter((WindowTask(object(), lambda: None, lambda: None),)),
        (object(),),
    ),
)
def test_multi_window_loop_requires_window_task_tuple(tasks: object) -> None:
    with pytest.raises(TypeError, match="tasks"):
        MultiWindowLoop(cast(Any, tasks), fps=60.0)


def test_multi_window_loop_rejects_empty_task_tuple() -> None:
    with pytest.raises(ValueError, match="tasks"):
        MultiWindowLoop((), fps=60.0)


@pytest.mark.parametrize(
    ("fps", "error"),
    (
        (True, TypeError),
        ("60", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_multi_window_loop_validates_fps(
    fps: object,
    error: type[Exception],
) -> None:
    task = WindowTask(object(), lambda: None, lambda: None)

    with pytest.raises(error, match="fps"):
        MultiWindowLoop((task,), fps=cast(Any, fps))


@pytest.mark.parametrize(
    "field",
    ("on_frame_start", "on_frame_finished", "on_scheduler_jitter"),
)
def test_multi_window_loop_rejects_non_callable_callbacks(field: str) -> None:
    task = WindowTask(object(), lambda: None, lambda: None)

    with pytest.raises(TypeError, match=field):
        MultiWindowLoop(
            (task,),
            fps=60.0,
            **cast(Any, {field: object()}),
        )
