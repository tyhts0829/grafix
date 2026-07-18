from __future__ import annotations

from dataclasses import replace

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.interactive.parameter_gui import store_bridge
from grafix.interactive.parameter_gui.parameter_filter import ParameterFilterState


def _store_with_rows(count: int) -> tuple[ParamStore, list[FrameParamRecord]]:
    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=float(count))
    records = [
        FrameParamRecord(
            key=ParameterKey(
                op="model_bench",
                site_id="site",
                arg=f"value_{index:04d}",
            ),
            base=float(index),
            meta=meta,
            explicit=False,
            effective=float(index),
        )
        for index in range(count)
    ]
    store = ParamStore()
    merge_frame_params(store, records)
    return store, records


def test_1000_rows_reuse_one_table_model_for_60_frames(monkeypatch) -> None:
    store, records = _store_with_rows(1_000)
    store_bridge.clear_parameter_table_model_cache()
    render_calls = 0

    def fake_render(rows, **_kwargs):
        nonlocal render_calls
        render_calls += 1
        assert len(rows) == 1_000
        return False, list(rows)

    monkeypatch.setattr(store_bridge, "render_parameter_table", fake_render)

    first = store_bridge._parameter_table_model_for_store(store)
    for _ in range(60):
        assert (
            store_bridge.render_store_parameter_table(
                store,
                show_inactive_params=True,
            )
            is False
        )

    assert render_calls == 60
    assert store_bridge.parameter_table_model_build_count() == 1
    assert store_bridge._parameter_table_model_for_store(store) is first

    # effective はフレーム動的値なので、更新しても静的モデルは作り直さない。
    store._runtime_ref().last_effective_by_key[records[0].key] = 999.0
    assert store_bridge._parameter_table_model_for_store(store) is first
    assert store_bridge.parameter_table_model_build_count() == 1


def test_table_model_patches_value_change_and_rebuilds_for_registry(monkeypatch) -> None:
    store, records = _store_with_rows(2)
    store_bridge.clear_parameter_table_model_cache()

    first = store_bridge._parameter_table_model_for_store(store)
    ok, error = update_state_from_ui(
        store,
        records[0].key,
        1.5,
        meta=records[0].meta,
    )
    assert ok is True and error is None
    second = store_bridge._parameter_table_model_for_store(store)
    assert second is not first
    assert store_bridge.parameter_table_model_build_count() == 1
    row_index = second.row_index_by_key[records[0].key]
    assert second.rows[row_index].ui_value == 1.5

    primitive, effect, preset = store_bridge._registry_revision()
    monkeypatch.setattr(
        store_bridge,
        "_registry_revision",
        lambda: (primitive + 1, effect, preset),
    )
    third = store_bridge._parameter_table_model_for_store(store)
    assert third is not second
    assert store_bridge.parameter_table_model_build_count() == 2


def test_show_inactive_without_activity_filter_skips_activity_mask(
    monkeypatch,
) -> None:
    store, records = _store_with_rows(3)

    def fail_activity_mask(*_args, **_kwargs):
        raise AssertionError("activity mask should not be evaluated")

    monkeypatch.setattr(store_bridge, "active_mask_for_rows", fail_activity_mask)

    cases = (
        (None, frozenset(), frozenset()),
        (ParameterFilterState(query="model_bench"), frozenset(), frozenset()),
        (
            ParameterFilterState(favorite_only=True),
            frozenset(),
            frozenset({records[0].key}),
        ),
        (
            ParameterFilterState(error_only=True),
            frozenset({records[1].key}),
            frozenset(),
        ),
    )
    for state, error_keys, favorite_keys in cases:
        view = store_bridge.parameter_table_view_for_store(
            store,
            show_inactive_params=True,
            filter_state=state,
            error_keys=error_keys,
            favorite_keys=favorite_keys,
        )
        assert view.total_count == 3


def test_activity_mask_is_kept_when_visibility_or_activity_filter_needs_it(
    monkeypatch,
) -> None:
    store, _records = _store_with_rows(3)
    calls = 0

    def count_activity_mask(rows, **_kwargs):
        nonlocal calls
        calls += 1
        return [True] * len(rows)

    monkeypatch.setattr(store_bridge, "active_mask_for_rows", count_activity_mask)

    store_bridge.parameter_table_view_for_store(
        store,
        show_inactive_params=False,
    )
    store_bridge.parameter_table_view_for_store(
        store,
        show_inactive_params=True,
        filter_state=ParameterFilterState(activity="active"),
    )
    assert calls == 2


def test_unchanged_render_does_not_consume_returned_rows(monkeypatch) -> None:
    store, _records = _store_with_rows(3)

    class RowsThatMustNotBeConsumed:
        def __iter__(self):
            raise AssertionError("unchanged rows should not be restored")

    def fake_render(_rows, **_kwargs):
        return False, RowsThatMustNotBeConsumed()

    monkeypatch.setattr(store_bridge, "render_parameter_table", fake_render)

    assert (
        store_bridge.render_store_parameter_table(
            store,
            show_inactive_params=True,
        )
        is False
    )


def test_changed_render_refreshes_only_value_without_model_rebuild(monkeypatch) -> None:
    store, records = _store_with_rows(1_000)
    store_bridge.clear_parameter_table_model_cache()

    def fake_render(rows, **_kwargs):
        updated = list(rows)
        updated[0] = replace(updated[0], ui_value=123.5)
        return True, updated

    monkeypatch.setattr(store_bridge, "render_parameter_table", fake_render)
    assert store_bridge.render_store_parameter_table(store) is True

    model = store_bridge._parameter_table_model_for_store(store)
    index = model.row_index_by_key[records[0].key]
    assert model.rows[index].ui_value == 123.5
    assert store_bridge.parameter_table_model_build_count() == 1


def test_value_change_log_overflow_falls_back_to_safe_model_rebuild() -> None:
    store, records = _store_with_rows(1)
    store_bridge.clear_parameter_table_model_cache()
    store_bridge._parameter_table_model_for_store(store)

    for value in range(4_100):
        ok, error = update_state_from_ui(
            store,
            records[0].key,
            float(value),
            meta=records[0].meta,
        )
        assert ok is True and error is None

    model = store_bridge._parameter_table_model_for_store(store)
    assert model.rows[0].ui_value == 4_099.0
    assert store_bridge.parameter_table_model_build_count() == 2
