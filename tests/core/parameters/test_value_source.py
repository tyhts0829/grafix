"""Parameter ValueSource と immutable MIDI frame snapshot のテスト。"""

from __future__ import annotations

import pickle

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
