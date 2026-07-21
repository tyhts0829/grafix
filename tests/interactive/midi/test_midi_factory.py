"""interactive.midi.factory の required mido 境界をテストする。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import grafix.interactive.midi.factory as factory


class _StringSubclass(str):
    pass


class DummyMidiController:
    def __init__(
        self,
        port_name: str,
        *,
        mode: str = "7bit",
        profile_name: str | None = None,
        save_dir: Path | None = None,
    ) -> None:
        self.port_name = port_name
        self.mode = mode
        self.profile_name = profile_name
        self.save_dir = save_dir


def test_none_port_disables_midi() -> None:
    assert factory.create_midi_controller(
        port_name=None, mode="7bit", profile_name="main"
    ) is None


@pytest.mark.parametrize("mode", [7, b"7bit", _StringSubclass("7bit")])
def test_factory_rejects_non_exact_string_mode(mode: object) -> None:
    with pytest.raises(TypeError, match="mode.*str"):
        factory.create_midi_controller(
            port_name=None,
            mode=mode,  # type: ignore[arg-type]
            profile_name="main",
        )


def test_factory_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        factory.create_midi_controller(
            port_name=None,
            mode="16bit",
            profile_name="main",
        )


def test_auto_propagates_missing_required_mido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mido", None)
    with pytest.raises(ModuleNotFoundError):
        factory.create_midi_controller(
            port_name="auto",
            mode="7bit",
            profile_name="main",
        )


def test_explicit_port_propagates_missing_required_mido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mido", None)
    with pytest.raises(ModuleNotFoundError):
        factory.create_midi_controller(
            port_name="TX-6 Bluetooth", mode="7bit", profile_name="main"
        )


def test_auto_propagates_mido_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mido = types.ModuleType("mido")

    def fail() -> list[str]:
        raise RuntimeError("backend failed")

    mido.get_input_names = fail  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mido", mido)

    with pytest.raises(RuntimeError, match="backend failed"):
        factory.create_midi_controller(
            port_name="auto",
            mode="7bit",
            profile_name="main",
        )


def test_auto_uses_first_input_name(monkeypatch: pytest.MonkeyPatch) -> None:
    mido = types.ModuleType("mido")
    mido.get_input_names = lambda: ["P1", "P2"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mido", mido)
    monkeypatch.setattr(factory, "MidiController", DummyMidiController)

    ctrl = factory.create_midi_controller(
        port_name="auto", mode="14bit", profile_name="main"
    )
    assert ctrl is not None
    assert ctrl.port_name == "P1"
    assert ctrl.mode == "14bit"
    assert ctrl.profile_name == "main"


def test_explicit_port_creates_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mido", types.ModuleType("mido"))
    monkeypatch.setattr(factory, "MidiController", DummyMidiController)

    ctrl = factory.create_midi_controller(
        port_name="My Port", mode="7bit", profile_name="main"
    )
    assert ctrl is not None
    assert ctrl.port_name == "My Port"
    assert ctrl.mode == "7bit"
    assert ctrl.profile_name == "main"


def test_auto_uses_priority_inputs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    mido = types.ModuleType("mido")
    mido.get_input_names = lambda: ["P1", "P2"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mido", mido)
    monkeypatch.setattr(factory, "MidiController", DummyMidiController)

    ctrl = factory.create_midi_controller(
        port_name="auto",
        mode="7bit",
        profile_name="main",
        priority_inputs=(
            ("Missing", "7bit"),
            ("P2", "14bit"),
        ),
    )
    assert ctrl is not None
    assert ctrl.port_name == "P2"
    assert ctrl.mode == "14bit"


def test_auto_does_not_fall_back_when_explicit_priorities_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mido = types.ModuleType("mido")
    mido.get_input_names = lambda: ["P1", "P2"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mido", mido)
    monkeypatch.setattr(factory, "MidiController", DummyMidiController)

    assert factory.create_midi_controller(
        port_name="auto",
        mode="7bit",
        profile_name="main",
        priority_inputs=(("Missing", "14bit"),),
    ) is None


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"profile_name": 1}, TypeError),
        ({"profile_name": ""}, ValueError),
        ({"save_dir": "midi"}, TypeError),
        ({"priority_inputs": []}, TypeError),
        ({"priority_inputs": (["P1", "7bit"],)}, TypeError),
        ({"priority_inputs": (("P1", "16bit"),)}, ValueError),
        ({"port_name": 1}, TypeError),
        ({"port_name": _StringSubclass("auto")}, TypeError),
        ({"port_name": ""}, ValueError),
    ],
)
def test_factory_rejects_noncanonical_connection_configuration(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    monkeypatch.setitem(sys.modules, "mido", types.ModuleType("mido"))
    values: dict[str, object] = {
        "port_name": "P1",
        "mode": "7bit",
        "profile_name": "main",
    }
    values.update(kwargs)
    with pytest.raises(error):
        factory.create_midi_controller(**values)  # type: ignore[arg-type]
