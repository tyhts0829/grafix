"""Parameter ValueSource と immutable MIDI frame snapshot のテスト。"""

from __future__ import annotations

import pickle
from math import inf, nan

import pytest

from grafix.core.parameters import MidiFrameSnapshot


def test_midi_frame_snapshot_copies_sorts_and_is_immutable() -> None:
    values = {12: 1.0, 3: 0.25}
    snapshot = MidiFrameSnapshot.from_mapping(values, source="midi_frozen")
    values[3] = 0.75

    assert snapshot.source == "midi_frozen"
    assert tuple(snapshot.items()) == ((3, 0.25), (12, 1.0))
    assert snapshot[3] == pytest.approx(0.25)
    with pytest.raises((AttributeError, TypeError)):
        snapshot.entries += ((7, 0.5),)  # type: ignore[misc]


def test_midi_frame_snapshot_roundtrips_through_worker_pickle() -> None:
    snapshot = MidiFrameSnapshot.from_mapping(
        {7: 0.5},
        source="midi_live",
    )

    restored = pickle.loads(pickle.dumps(snapshot))

    assert restored == snapshot
    assert restored.source == "midi_live"
    assert restored[7] == pytest.approx(0.5)


def test_midi_frame_snapshot_rejects_duplicate_cc_numbers() -> None:
    with pytest.raises(ValueError, match="duplicate CC"):
        MidiFrameSnapshot(
            source="midi_live",
            entries=((1, 0.25), (1, 0.5)),
        )


@pytest.mark.parametrize("cc", [True, 1.5, "1"])
def test_midi_frame_snapshot_rejects_non_integer_cc(cc: object) -> None:
    with pytest.raises(TypeError):
        MidiFrameSnapshot(
            source="midi_live",
            entries=((cc, 0.5),),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("cc", [-1, 128])
def test_midi_frame_snapshot_rejects_out_of_range_cc(cc: int) -> None:
    with pytest.raises(ValueError):
        MidiFrameSnapshot.from_mapping({cc: 0.5}, source="midi_live")


@pytest.mark.parametrize("value", [True, "0.5"])
def test_midi_frame_snapshot_rejects_non_numeric_value(value: object) -> None:
    with pytest.raises(TypeError):
        MidiFrameSnapshot(
            source="midi_live",
            entries=((1, value),),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [-0.01, 1.01, nan, inf])
def test_midi_frame_snapshot_rejects_out_of_range_value(value: float) -> None:
    with pytest.raises(ValueError):
        MidiFrameSnapshot.from_mapping({1: value}, source="midi_live")


@pytest.mark.parametrize("key", [True, 1.0, "1"])
def test_midi_frame_snapshot_lookup_requires_integer_cc(key: object) -> None:
    snapshot = MidiFrameSnapshot.from_mapping({1: 0.5}, source="midi_live")

    with pytest.raises(TypeError):
        snapshot[key]  # type: ignore[index]
