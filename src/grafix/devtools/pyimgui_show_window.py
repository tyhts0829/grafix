import pyglet

from grafix.core.lifecycle import CleanupErrors
from grafix.interactive.parameter_gui.pyglet_backend import PygletImguiBackend
from grafix.interactive.pyglet_window_lifecycle import close_pyglet_window


def main() -> None:
    window = pyglet.window.Window(  # type: ignore[abstract]
        1280, 720, caption="pyimgui + pyglet demo", resizable=True
    )
    backend = None
    root_error: BaseException | None = None
    try:
        backend = PygletImguiBackend(window)
        imgui = backend.imgui

        @window.event
        def on_draw() -> None:
            backend.begin_frame(1.0 / 60.0)
            imgui.show_demo_window()
            backend.render()

        @window.event
        def on_close() -> object:
            pyglet.app.exit()
            return pyglet.event.EVENT_HANDLED

        pyglet.app.run()
    except BaseException as error:
        root_error = error
    finally:
        errors = CleanupErrors(initial_error=root_error)
        if backend is not None:
            errors.attempt(backend.close)
        errors.attempt(lambda: close_pyglet_window(window))
        errors.raise_if_any()


if __name__ == "__main__":
    main()
