from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.labels_ops import set_label
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.snapshot_ops import store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui


def _record(index: int, *, value: float | None = None) -> FrameParamRecord:
    base = float(index if value is None else value)
    return FrameParamRecord(
        key=ParameterKey(op="line", site_id=f"site-{index}", arg="length"),
        base=base,
        meta=ParamMeta(kind="float", ui_min=0.0, ui_max=10_000.0),
        explicit=False,
        effective=base,
    )


def test_snapshot_is_cached_until_store_structure_changes() -> None:
    store = ParamStore()
    record = _record(1)
    merge_frame_params(store, [record])
    revision = store.revision

    first = store_snapshot(store)
    second = store_snapshot(store)
    merge_frame_params(store, [record])
    third = store_snapshot(store)

    assert first is second is third
    assert store.revision == revision


def test_ui_and_label_updates_advance_revision_only_on_real_change() -> None:
    store = ParamStore()
    record = _record(1)
    merge_frame_params(store, [record])
    key = record.key
    revision = store.revision

    ok, error = update_state_from_ui(store, key, 1.0, meta=record.meta)
    assert ok is True and error is None
    assert store.revision == revision

    update_state_from_ui(store, key, 2.0, meta=record.meta)
    assert store.revision > revision
    revision = store.revision

    set_label(store, op=key.op, site_id=key.site_id, label="line")
    assert store.revision > revision
    revision = store.revision
    set_label(store, op=key.op, site_id=key.site_id, label="line")
    assert store.revision == revision


def test_large_unchanged_snapshot_is_built_once() -> None:
    store = ParamStore()
    records = [_record(index) for index in range(1_000)]
    merge_frame_params(store, records)

    snapshots = [store_snapshot(store) for _ in range(60)]

    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert len(snapshots[0]) == 1_000


def test_cached_snapshot_outer_mapping_cannot_be_mutated() -> None:
    store = ParamStore()
    record = _record(1)
    merge_frame_params(store, [record])
    snapshot = store_snapshot(store)

    with pytest.raises(TypeError):
        cast(dict[Any, Any], snapshot)[record.key] = snapshot[record.key]

    assert store_snapshot(store) is snapshot
    assert len(snapshot) == 1


def test_cached_snapshot_state_cannot_be_mutated() -> None:
    store = ParamStore()
    record = _record(1)
    merge_frame_params(store, [record])
    snapshot = store_snapshot(store)
    state = snapshot[record.key][1]

    with pytest.raises(FrozenInstanceError):
        state.ui_value = 999.0  # type: ignore[misc]

    assert store_snapshot(store) is snapshot
    assert snapshot[record.key][1].ui_value == 1.0
