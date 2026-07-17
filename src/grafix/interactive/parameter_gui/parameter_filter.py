"""Parameter GUI の検索・絞り込みを副作用なしで評価する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from grafix.core.parameters.view import ParameterRow

ParameterActivityFilter = Literal["all", "active", "inactive"]


@dataclass(frozen=True, slots=True)
class ParameterFilterState:
    """Parameter table に適用する小さな immutable filter state。"""

    query: str = ""
    activity: ParameterActivityFilter = "all"
    ui_override_only: bool = False
    midi_mapped_only: bool = False
    error_only: bool = False
    favorite_only: bool = False

    def __post_init__(self) -> None:
        if self.activity not in {"all", "active", "inactive"}:
            raise ValueError(f"未対応の activity filter: {self.activity!r}")


@dataclass(frozen=True, slots=True)
class ParameterFilterRecord:
    """検索対象文字列と動的 flag を 1 行へ合成した入力 record。

    `favorite` は Phase 4.3 の永続化方式から独立した入力境界である。現時点では
    呼び出し側が明示した flag だけを評価し、ParamStore の schema は変更しない。
    """

    row: ParameterRow
    label: str
    source: str
    active: bool
    has_error: bool = False
    favorite: bool = False


@dataclass(frozen=True, slots=True)
class ParameterFilterResult:
    """入力順と 1:1 の mask、および絞り込み件数。"""

    mask: tuple[bool, ...]
    filtered_count: int
    total_count: int


def parameter_row_midi_ccs(row: ParameterRow) -> tuple[int, ...]:
    """行に割り当て済みの MIDI CC を重複なしで返す。"""

    cc_key = row.cc_key
    if isinstance(cc_key, int):
        return (int(cc_key),)
    if not isinstance(cc_key, tuple):
        return ()
    return tuple(dict.fromkeys(int(cc) for cc in cc_key if cc is not None))


def parameter_row_has_midi_mapping(row: ParameterRow) -> bool:
    """行に 1 つ以上の MIDI CC が割り当てられているか。"""

    return bool(parameter_row_midi_ccs(row))


def _search_corpus(record: ParameterFilterRecord) -> str:
    midi = " ".join(
        f"midi cc {cc} cc{cc} midi{cc}" for cc in parameter_row_midi_ccs(record.row)
    )
    return " ".join(
        (
            str(record.label),
            str(record.row.label),
            str(record.row.op),
            str(record.row.arg),
            str(record.row.site_id),
            str(record.source),
            str(record.row.display_name or ""),
            str(record.row.description or ""),
            str(record.row.unit or ""),
            str(record.row.category or ""),
            midi,
        )
    ).casefold()


def matches_parameter_search(record: ParameterFilterRecord, query: str) -> bool:
    """Unicode casefold 済み AND token substring search を評価する。"""

    tokens = tuple(token for token in str(query).casefold().split() if token)
    if not tokens:
        return True
    corpus = _search_corpus(record)
    return all(token in corpus for token in tokens)


def parameter_record_matches(
    record: ParameterFilterRecord,
    state: ParameterFilterState,
) -> bool:
    """1 行が query と各 filter 条件をすべて満たすか。"""

    if state.activity == "active" and not record.active:
        return False
    if state.activity == "inactive" and record.active:
        return False
    if state.ui_override_only and not bool(record.row.override):
        return False
    if state.midi_mapped_only and not parameter_row_has_midi_mapping(record.row):
        return False
    if state.error_only and not record.has_error:
        return False
    if state.favorite_only and not record.favorite:
        return False
    return matches_parameter_search(record, state.query)


def filter_parameter_records(
    records: tuple[ParameterFilterRecord, ...] | list[ParameterFilterRecord],
    state: ParameterFilterState,
) -> ParameterFilterResult:
    """入力順を保った filter mask と件数を返す。"""

    mask = tuple(parameter_record_matches(record, state) for record in records)
    return ParameterFilterResult(
        mask=mask,
        filtered_count=sum(mask),
        total_count=len(mask),
    )


__all__ = [
    "ParameterActivityFilter",
    "ParameterFilterRecord",
    "ParameterFilterResult",
    "ParameterFilterState",
    "filter_parameter_records",
    "matches_parameter_search",
    "parameter_record_matches",
    "parameter_row_has_midi_mapping",
    "parameter_row_midi_ccs",
]
