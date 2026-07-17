"""Parameter の実効値 source とフレーム単位 MIDI snapshot を定義する。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

ValueSource = Literal["code", "ui", "midi_live", "midi_frozen"]
MidiValueSource = Literal["midi_live", "midi_frozen"]


@dataclass(frozen=True, slots=True)
class MidiFrameSnapshot(Mapping[int, float]):
    """1 frame 内で固定する immutable な MIDI CC 値と接続由来。

    Parameters
    ----------
    source
        値が接続中の入力由来なら ``midi_live``、保存済み値由来なら
        ``midi_frozen``。
    entries
        CC番号と0.0--1.0正規化値の組。CC番号順に保持する。
    """

    source: MidiValueSource
    entries: tuple[tuple[int, float], ...] = ()

    def __post_init__(self) -> None:
        if self.source not in {"midi_live", "midi_frozen"}:
            raise ValueError(f"unknown MIDI value source: {self.source!r}")
        normalized = tuple(
            sorted((int(cc), float(value)) for cc, value in self.entries)
        )
        if len({cc for cc, _value in normalized}) != len(normalized):
            raise ValueError("MidiFrameSnapshot entries contain duplicate CC numbers")
        object.__setattr__(self, "entries", normalized)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[int, float],
        *,
        source: MidiValueSource,
    ) -> MidiFrameSnapshot:
        """mapping を値コピーした immutable snapshot を返す。"""

        return cls(
            source=source,
            entries=tuple((int(cc), float(value)) for cc, value in values.items()),
        )

    def __getitem__(self, cc_number: int) -> float:
        key = int(cc_number)
        for cc, value in self.entries:
            if cc == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[int]:
        return (cc for cc, _value in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


__all__ = ["MidiFrameSnapshot", "MidiValueSource", "ValueSource"]
