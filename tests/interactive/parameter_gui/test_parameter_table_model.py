from __future__ import annotations

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.interactive.parameter_gui import store_bridge


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


def test_table_model_invalidates_on_store_or_registry_revision(monkeypatch) -> None:
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

    primitive, effect, preset = store_bridge._registry_revision()
    monkeypatch.setattr(
        store_bridge,
        "_registry_revision",
        lambda: (primitive + 1, effect, preset),
    )
    third = store_bridge._parameter_table_model_for_store(store)
    assert third is not second
    assert store_bridge.parameter_table_model_build_count() == 3
