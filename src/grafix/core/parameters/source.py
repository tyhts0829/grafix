"""Parameter の実効値 source とフレーム単位 MIDI snapshot を定義する。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from grafix.core.value_validation import (
    exact_integer,
    exact_string_choice,
    finite_real,
)

ValueSource = Literal["code", "ui", "midi_live", "midi_frozen"]
MidiValueSource = Literal["midi_live", "midi_frozen"]
ParameterLoadMode: TypeAlias = Literal["code", "saved", "recovery"] | Path


def _cc_number(value: object) -> int:
    cc = exact_integer(value, name="MIDI CC番号")
    if cc < 0 or cc > 127:
        raise ValueError("MIDI CC番号は0..127である必要があります")
    return cc


def _midi_value(value: object) -> float:
    normalized = finite_real(value, name="MIDI CC値", minimum=0.0)
    if normalized > 1.0:
        raise ValueError("MIDI CC値は有限な0.0..1.0である必要があります")
    return normalized


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
        object.__setattr__(
            self,
            "source",
            exact_string_choice(
                self.source,
                name="source",
                choices=("midi_live", "midi_frozen"),
            ),
        )
        if type(self.entries) is not tuple:
            raise TypeError("MidiFrameSnapshot entries は tuple である必要があります")
        normalized_entries: list[tuple[int, float]] = []
        for entry in self.entries:
            if type(entry) is not tuple or len(entry) != 2:
                raise TypeError("MIDI entry は (CC番号, 値) の tuple である必要があります")
            cc, value = entry
            normalized_entries.append((_cc_number(cc), _midi_value(value)))
        normalized = tuple(sorted(normalized_entries))
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
            entries=tuple(values.items()),
        )

    def __getitem__(self, cc_number: int) -> float:
        key = _cc_number(cc_number)
        for cc, value in self.entries:
            if cc == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[int]:
        return (cc for cc, _value in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


__all__ = ["MidiFrameSnapshot", "MidiValueSource", "ParameterLoadMode", "ValueSource"]
