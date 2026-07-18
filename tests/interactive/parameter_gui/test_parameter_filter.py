from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from grafix.core.parameters.view import ParameterRow
from grafix.interactive.parameter_gui.parameter_filter import (
    ParameterFilterRecord,
    ParameterFilterState,
    filter_parameter_records,
    matches_parameter_search,
    parameter_row_midi_ccs,
    parameter_search_token_may_be_dynamic,
)


def _row(
    *,
    op: str = "spiral_field",
    arg: str = "radius",
    cc_key: int | tuple[int | None, int | None, int | None] | None = 74,
    override: bool = True,
) -> ParameterRow:
    return ParameterRow(
        label=f"1:{arg}",
        op=op,
        site_id="site",
        arg=arg,
        kind="float",
        ui_value=0.5,
        ui_min=0.0,
        ui_max=1.0,
        choices=None,
        cc_key=cc_key,
        override=override,
        ordinal=1,
    )


def _record(
    *,
    active: bool = True,
    override: bool = True,
    cc_key: int | tuple[int | None, int | None, int | None] | None = 74,
    has_error: bool = False,
    favorite: bool = False,
) -> ParameterFilterRecord:
    return ParameterFilterRecord(
        row=_row(override=override, cc_key=cc_key),
        label="Straße Orbit",
        source="UI",
        active=active,
        has_error=has_error,
        favorite=favorite,
    )


def test_search_uses_unicode_casefold_and_and_tokens_across_all_fields() -> None:
    record = _record()

    assert matches_parameter_search(
        record,
        "STRASSE spiral radius ui midi cc74 74",
    )
    assert matches_parameter_search(record, "orbit MIDI74")
    assert matches_parameter_search(record, "site")
    assert not matches_parameter_search(record, "orbit missing")


def test_midi_search_and_mapping_ignore_unassigned_tuple_components() -> None:
    row = _row(cc_key=(12, None, 12))
    record = ParameterFilterRecord(
        row=row,
        label="Vector",
        source="MIDI",
        active=True,
    )

    assert parameter_row_midi_ccs(row) == (12,)
    assert matches_parameter_search(record, "midi cc 12 cc12")
    assert not matches_parameter_search(record, "13")


def test_all_structured_filters_are_combined_with_and_semantics() -> None:
    matching = _record(
        active=False,
        override=True,
        cc_key=12,
        has_error=True,
        favorite=True,
    )
    active_nonmatch = _record(
        active=True,
        override=True,
        cc_key=12,
        has_error=True,
        favorite=True,
    )
    no_override = _record(
        active=False,
        override=False,
        cc_key=12,
        has_error=True,
        favorite=True,
    )
    state = ParameterFilterState(
        query="radius 12",
        activity="inactive",
        ui_override_only=True,
        midi_mapped_only=True,
        error_only=True,
        favorite_only=True,
    )

    result = filter_parameter_records(
        [matching, active_nonmatch, no_override],
        state,
    )

    assert result.mask == (True, False, False)
    assert result.filtered_count == 1
    assert result.total_count == 3


def test_filter_state_is_immutable_and_rejects_unknown_activity() -> None:
    state = ParameterFilterState()
    with pytest.raises(FrozenInstanceError):
        state.query = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="activity filter"):
        ParameterFilterState(activity="other")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "token",
    (
        "ode",
        "idi",
        "fro",
        "rozen",
        "ive",
        "cc74",
        "c74",
        "midi74",
        "idi74",
        "74",
        "-",
        "cc-",
        "c-",
        "midi-",
        "idi-",
        "di-",
        "i-",
    ),
)
def test_dynamic_search_token_detection_preserves_substring_semantics(
    token: str,
) -> None:
    assert parameter_search_token_may_be_dynamic(token)


def test_static_only_search_token_can_use_index() -> None:
    assert not parameter_search_token_may_be_dynamic("spiral_field")
