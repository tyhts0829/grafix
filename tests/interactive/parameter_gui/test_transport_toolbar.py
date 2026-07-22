from types import SimpleNamespace
from typing import Any, cast

from grafix.interactive.parameter_gui.gui import ParameterGUI
from grafix.interactive.transport import TransportClock


class _FakeImGui:
    def __init__(self) -> None:
        self.clicked = {
            "transport_play",
            "transport_forward",
            "transport_slower",
        }

    def button(self, label: str, width: float = 0.0, height: float = 0.0) -> bool:
        return label.rpartition("##")[2] in self.clicked

    def same_line(self, position: float = 0.0, spacing: float = -1.0) -> None:
        pass

    def set_next_item_width(self, _width: float) -> None:
        pass

    def drag_float(self, *_args: object) -> tuple[bool, float]:
        return True, 2.5

    def text_disabled(self, _text: str) -> None:
        pass

    def text(self, _text: str) -> None:
        pass

    def separator(self) -> None:
        pass

    def is_item_hovered(self) -> bool:
        return False

    def is_item_focused(self) -> bool:
        return False

    def set_tooltip(self, _text: str) -> None:
        pass


class _KeyboardCaptureImGui:
    @staticmethod
    def get_io() -> object:
        return SimpleNamespace(want_text_input=False, want_capture_keyboard=True)


def test_transport_toolbar_controls_the_shared_clock(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui = cast(Any, initialized_parameter_gui)
    gui._imgui = _FakeImGui()
    gui._transport_fps = 10.0
    gui._transport = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=1.0,
    )

    gui._render_transport_toolbar()

    assert gui._transport.is_playing is False
    assert gui._transport.speed == 0.5
    assert gui._transport.t() == 2.5


def test_focused_imgui_control_keeps_keyboard_input_from_transport(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui = cast(Any, initialized_parameter_gui)
    gui._imgui = _KeyboardCaptureImGui()
    gui._transport = TransportClock(
        start_time=10.0,
        time_source=lambda: 10.0,
        initial_t=1.0,
        playing=False,
    )
    gui._transport_fps = 10.0
    gui._is_recording = None
    gui._history = None
    gui._range_edit_key_r = -1
    gui._range_edit_key_e = -1
    gui._range_edit_key_t = -1
    gui._transport_key_space = 32
    gui._transport_key_home = 36
    gui._transport_key_left = 37
    gui._transport_key_right = 39
    gui._transport_key_slower = 91
    gui._transport_key_faster = 93

    gui._on_key_press(39, 0)

    assert gui._transport.t() == 1.0


def test_range_edit_shortcuts_ignore_captured_keyboard(
    initialized_parameter_gui: ParameterGUI,
) -> None:
    gui = cast(Any, initialized_parameter_gui)
    gui._imgui = _KeyboardCaptureImGui()
    gui._range_edit_key_r = 82
    gui._range_edit_key_e = 69
    gui._range_edit_key_t = 84
    gui._range_edit_controller.cancel()

    gui._on_key_press(82, 0)
    gui._on_key_press(69, 0)
    gui._on_key_press(84, 0)

    assert gui._range_edit_controller.mode is None
    assert gui._range_edit_controller.session is None
