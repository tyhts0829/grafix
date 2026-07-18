from grafix.interactive.parameter_gui.pyglet_backend import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT,
    MINIMUM_PARAMETER_GUI_WINDOW_WIDTH,
)


def test_parameter_gui_backend_default_window_size_is_wide() -> None:
    assert (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT) == (1100, 1000)
    assert (
        MINIMUM_PARAMETER_GUI_WINDOW_WIDTH,
        MINIMUM_PARAMETER_GUI_WINDOW_HEIGHT,
    ) == (760, 480)
