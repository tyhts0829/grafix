"""大規模 ParamStore の frame 固定費を分離して測る formal benchmark。"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.favorites import (
    favorite_parameter_key_set,
    favorite_parameter_keys,
    set_parameters_favorite,
)
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.snapshot_ops import ParamSnapshot, store_snapshot
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui
from grafix.devtools.benchmarks.schema import (
    BenchmarkOutput,
    ContractResult,
    Metric,
    evaluate_contract,
    summarize_distribution,
)
from grafix.interactive.parameter_gui import store_bridge
from grafix.interactive.parameter_gui.group_blocks import (
    group_layout_from_rows,
    visible_group_layout,
)
from grafix.interactive.parameter_gui.parameter_filter import ParameterFilterState
from grafix.interactive.parameter_gui.parameter_filter import (
    parameter_search_token_may_be_dynamic,
    parameter_search_tokens,
)

ParameterHotPathOperation = Literal[
    "layout_reuse",
    "merge_steady",
    "snapshot_one",
    "visibility_default",
    "visibility_search",
    "favorite_view",
]

_SCOPE = "core+parameter-hotpath(no-imgui)"
_SEARCH_MIDI_STRIDE = 1_000


@dataclass(slots=True)
class ParameterHotPathScenario:
    """同一 process 内で繰り返し利用する parameter hot-path state。"""

    operation: ParameterHotPathOperation
    rows: int
    samples: int
    store: ParamStore
    records: list[FrameParamRecord]
    target_key: ParameterKey
    target_meta: ParamMeta
    snapshot: ParamSnapshot
    initial_merge_ms: float


def make_parameter_hot_path_scenario(
    parameters: dict[str, Any],
) -> ParameterHotPathScenario:
    """JSON-compatible な定義から benchmark state を構築する。"""

    operation = str(parameters["operation"])
    if operation not in {
        "layout_reuse",
        "merge_steady",
        "snapshot_one",
        "visibility_default",
        "visibility_search",
        "favorite_view",
    }:
        raise ValueError(f"未対応の parameter hot-path operation: {operation!r}")
    rows = int(parameters["rows"])
    samples = int(parameters.get("samples", 24))
    if rows < 1:
        raise ValueError("rows は 1 以上である必要があります")
    if samples < 1:
        raise ValueError("samples は 1 以上である必要があります")

    meta = ParamMeta(kind="float", ui_min=0.0, ui_max=float(rows))
    records = [
        FrameParamRecord(
            key=ParameterKey(
                op="line",
                site_id=f"hotpath-{index:06d}",
                arg="length",
            ),
            base=float(index),
            meta=meta,
            explicit=False,
            effective=float(index),
            source="code",
        )
        for index in range(rows)
    ]
    store = ParamStore()
    started = time.perf_counter_ns()
    merge_frame_params(store, records)
    initial_merge_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    if operation == "visibility_search":
        midi_keys: list[ParameterKey] = []
        runtime = store._runtime_ref()
        for index in range(0, rows, _SEARCH_MIDI_STRIDE):
            record = records[index]
            ok, error = update_state_from_ui(
                store,
                record.key,
                record.base,
                meta=record.meta,
                override=True,
                cc_key=index % 128,
            )
            if not ok:
                raise RuntimeError(f"search fixture MIDI setup failed: {error}")
            runtime.last_source_by_key[record.key] = "midi_live"
            midi_keys.append(record.key)
        runtime.record_effective_changes(midi_keys)
    snapshot = store_snapshot(store)
    target_key = records[0].key

    # setup 固定費と timed steady path を分離する。
    store_bridge.clear_parameter_table_model_cache()
    model = store_bridge._parameter_table_model_for_store(store)
    if operation == "layout_reuse":
        visible_group_layout(model.group_layout, (True,) * len(model.rows))
    if operation == "visibility_default":
        store_bridge.parameter_table_view_for_store(
            store,
            show_inactive_params=False,
        )
    elif operation == "visibility_search":
        store_bridge.parameter_table_view_for_store(
            store,
            show_inactive_params=False,
            filter_state=ParameterFilterState(
                query=f"hotpath-{rows - 1:06d}",
            ),
        )
    elif operation == "favorite_view":
        set_parameters_favorite(
            store,
            (record.key for record in records),
            favorite=True,
        )
        favorite_parameter_key_set(store)
        favorite_parameter_keys(store)

    return ParameterHotPathScenario(
        operation=cast(ParameterHotPathOperation, operation),
        rows=rows,
        samples=samples,
        store=store,
        records=records,
        target_key=target_key,
        target_meta=meta,
        snapshot=snapshot,
        initial_merge_ms=initial_merge_ms,
    )


def run_parameter_hot_path_scenario(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    """指定 hot path を self-sampling し、semantic contract と共に返す。"""

    if scenario.operation == "layout_reuse":
        return _run_layout_reuse(scenario)
    if scenario.operation == "merge_steady":
        return _run_merge_steady(scenario)
    if scenario.operation == "snapshot_one":
        return _run_snapshot_one(scenario)
    if scenario.operation == "favorite_view":
        return _run_favorite_view(scenario)
    return _run_visibility(scenario)


def _run_layout_reuse(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    model = store_bridge._parameter_table_model_for_store(scenario.store)
    visible_mask = (True,) * len(model.rows)
    build_ms: list[float] = []
    reuse_ms: list[float] = []
    built_layout = None
    reused_layout = None

    for _ in range(scenario.samples):
        started = time.perf_counter_ns()
        built_layout = group_layout_from_rows(
            model.rows,
            primitive_header_by_group=model.primitive_header_by_group,
            layer_style_name_by_site_id=model.layer_style_name_by_site_id,
            effect_chain_header_by_id=model.effect_chain_header_by_id,
            step_info_by_site=model.step_info_by_site,
            effect_step_ordinal_by_site=model.effect_step_ordinal_by_site,
        )
        build_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)

        started = time.perf_counter_ns()
        reused_layout = visible_group_layout(model.group_layout, visible_mask)
        reuse_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)

    assert built_layout is not None
    assert reused_layout is not None
    built_signature = tuple(
        (
            block.group_id,
            block.header_id,
            block.header,
            tuple(
                (item.row_index, item.visible_label)
                for item in block.items
            ),
        )
        for block in built_layout
    )
    layout_signature = tuple(
        (
            block.group_id,
            block.header_id,
            block.header,
            tuple(
                (item.row_index, item.visible_label)
                for item in block.items
            ),
        )
        for block in reused_layout
    )
    built_digest = _digest_items(built_signature)
    layout_digest = _digest_items(layout_signature)
    distribution = summarize_distribution(reuse_ms)
    p95 = distribution.p95 if distribution.p95 is not None else distribution.max
    assert p95 is not None
    return BenchmarkOutput(
        value={
            "operation": scenario.operation,
            "rows": scenario.rows,
            "samples": scenario.samples,
            "built_blocks": len(built_layout),
            "layout_blocks": len(reused_layout),
            "layout_identity_reused": reused_layout is model.group_layout,
            "layout_digest": layout_digest,
        },
        metrics=(
            _distribution_metric("parameter_layout.build", build_ms),
            _distribution_metric("parameter_layout.stable_reuse", reuse_ms),
            _gauge_metric(
                "parameter_layout.blocks",
                len(reused_layout),
                unit="blocks",
            ),
        ),
        contracts=(
            _contract(
                "parameter_layout.stable_identity",
                "hard",
                reused_layout is model.group_layout,
                "eq",
                True,
                "all-visible stable view must reuse immutable group layout",
            ),
            _contract(
                "parameter_layout.block_count_exact",
                "hard",
                len(reused_layout),
                "eq",
                len(built_layout),
                "prebuilt layout must preserve canonical grouping cardinality",
            ),
            _contract(
                "parameter_layout.semantic_layout_exact",
                "hard",
                layout_digest,
                "eq",
                built_digest,
                "reused row/header/label layout must match a canonical rebuild",
            ),
            _contract(
                "parameter_layout.reference_p95",
                "soft",
                float(p95),
                "le",
                1.0,
                "reference target for 10k stable layout reuse is 1 ms p95",
            ),
        ),
    )


def _run_merge_steady(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    store = scenario.store
    runtime = store._runtime_ref()
    revision_before = int(store.revision)
    table_revision_before = int(store.table_revision)
    effective_revision_before = int(runtime.effective_revision)
    semantic_digest_before = _store_semantic_digest(store)
    elapsed_ms: list[float] = []

    for _ in range(scenario.samples):
        records = _fresh_equivalent_records(scenario.records)
        started = time.perf_counter_ns()
        merge_frame_params(store, records)
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)

    revision_delta = int(store.revision) - revision_before
    table_revision_delta = int(store.table_revision) - table_revision_before
    effective_revision_delta = (
        int(runtime.effective_revision) - effective_revision_before
    )
    distribution = summarize_distribution(elapsed_ms)
    p95 = distribution.p95 if distribution.p95 is not None else distribution.max
    assert p95 is not None
    semantic_digest_after = _store_semantic_digest(store)
    return BenchmarkOutput(
        value={
            "operation": scenario.operation,
            "rows": scenario.rows,
            "samples": scenario.samples,
            "revision_delta": revision_delta,
            "table_revision_delta": table_revision_delta,
            "effective_revision_delta": effective_revision_delta,
            "semantic_digest_before": semantic_digest_before,
            "semantic_digest_after": semantic_digest_after,
            "initial_merge_ms": scenario.initial_merge_ms,
        },
        metrics=(
            _distribution_metric("parameter_merge.steady", elapsed_ms),
            _gauge_metric(
                "parameter_merge.initial_discovery",
                scenario.initial_merge_ms,
                unit="ms",
            ),
            _gauge_metric("parameter_merge.rows", scenario.rows, unit="rows"),
            _gauge_metric(
                "parameter_merge.revision_delta",
                revision_delta,
                unit="revisions",
            ),
            _gauge_metric(
                "parameter_merge.table_revision_delta",
                table_revision_delta,
                unit="revisions",
            ),
            _gauge_metric(
                "parameter_merge.effective_revision_delta",
                effective_revision_delta,
                unit="revisions",
            ),
        ),
        contracts=(
            _contract(
                "parameter_merge.steady.store_revision_stable",
                "hard",
                revision_delta,
                "eq",
                0,
                "stable frame must not advance persistent store revision",
            ),
            _contract(
                "parameter_merge.steady.table_revision_stable",
                "hard",
                table_revision_delta,
                "eq",
                0,
                "stable frame must not rebuild table structure",
            ),
            _contract(
                "parameter_merge.steady.effective_revision_stable",
                "hard",
                effective_revision_delta,
                "eq",
                0,
                "unchanged effective/source values must keep runtime revision",
            ),
            _contract(
                "parameter_merge.steady.semantic_state_stable",
                "hard",
                semantic_digest_after,
                "eq",
                semantic_digest_before,
                "stable merge must preserve snapshot/effective/source/explicit state",
            ),
            _contract(
                "parameter_merge.steady.reference_p95",
                "soft",
                float(p95),
                "le",
                8.0,
                "reference target for 10k steady merge is 8 ms p95",
            ),
        ),
    )


def _run_snapshot_one(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    store = scenario.store
    key = scenario.target_key
    meta = scenario.target_meta
    table_revision_before = int(store.table_revision)
    previous_snapshot = scenario.snapshot
    initial_snapshot = previous_snapshot
    initial_digest_before = _snapshot_digest(initial_snapshot)
    previous_value = previous_snapshot[key][1].ui_value
    elapsed_ms: list[float] = []
    old_snapshot_stable = 0
    new_snapshot_matches = 0
    rebuilt_entries = 0
    max_patch_entries = 0

    for index in range(scenario.samples):
        next_value = 0.25 if index % 2 == 0 else 0.75
        ok, error = update_state_from_ui(
            store,
            key,
            next_value,
            meta=meta,
            override=True,
        )
        if not ok:
            raise RuntimeError(f"snapshot benchmark update failed: {error}")

        started = time.perf_counter_ns()
        current_snapshot = store_snapshot(store)
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        rebuilt_entries += int(store._snapshot_cache_rebuilt_entries)
        max_patch_entries = max(
            max_patch_entries,
            int(getattr(current_snapshot, "patch_entries", 0)),
        )
        old_snapshot_stable += int(
            previous_snapshot[key][1].ui_value == previous_value
        )
        new_snapshot_matches += int(
            current_snapshot[key][1].ui_value == next_value
        )
        previous_snapshot = current_snapshot
        previous_value = next_value

    scenario.snapshot = previous_snapshot
    initial_digest_after = _snapshot_digest(initial_snapshot)
    final_digest = _snapshot_digest(previous_snapshot)
    table_revision_delta = int(store.table_revision) - table_revision_before
    distribution = summarize_distribution(elapsed_ms)
    p95 = distribution.p95 if distribution.p95 is not None else distribution.max
    assert p95 is not None
    return BenchmarkOutput(
        value={
            "operation": scenario.operation,
            "rows": scenario.rows,
            "samples": scenario.samples,
            "snapshot_entries": len(previous_snapshot),
            "old_snapshot_stable": old_snapshot_stable,
            "new_snapshot_matches": new_snapshot_matches,
            "rebuilt_entries": rebuilt_entries,
            "max_patch_entries": max_patch_entries,
            "initial_digest": initial_digest_before,
            "final_digest": final_digest,
        },
        metrics=(
            _distribution_metric("parameter_snapshot.one_key", elapsed_ms),
            _gauge_metric(
                "parameter_snapshot.entries",
                len(previous_snapshot),
                unit="entries",
            ),
            _gauge_metric(
                "parameter_snapshot.table_revision_delta",
                table_revision_delta,
                unit="revisions",
            ),
            _gauge_metric(
                "parameter_snapshot.rebuilt_entries",
                rebuilt_entries,
                unit="entries",
            ),
            _gauge_metric(
                "parameter_snapshot.max_patch_entries",
                max_patch_entries,
                unit="entries",
            ),
        ),
        contracts=(
            _contract(
                "parameter_snapshot.one_key.entry_count",
                "hard",
                len(previous_snapshot),
                "eq",
                scenario.rows,
                "snapshot must retain every parameter entry",
            ),
            _contract(
                "parameter_snapshot.one_key.old_frame_immutable",
                "hard",
                old_snapshot_stable,
                "eq",
                scenario.samples,
                "previous frame snapshot must remain immutable",
            ),
            _contract(
                "parameter_snapshot.initial_checksum_stable",
                "hard",
                initial_digest_after,
                "eq",
                initial_digest_before,
                "initial snapshot checksum must remain immutable",
            ),
            _contract(
                "parameter_snapshot.one_key.current_value_exact",
                "hard",
                new_snapshot_matches,
                "eq",
                scenario.samples,
                "new snapshot must expose every one-key edit",
            ),
            _contract(
                "parameter_snapshot.one_key.table_revision_stable",
                "hard",
                table_revision_delta,
                "eq",
                0,
                "value-only snapshot churn must not change table structure",
            ),
            _contract(
                "parameter_snapshot.one_key.rebuild_is_sparse",
                "hard",
                rebuilt_entries,
                "eq",
                scenario.samples,
                "each one-key edit must rebuild exactly one snapshot entry",
            ),
            _contract(
                "parameter_snapshot.one_key.patch_is_bounded",
                "hard",
                max_patch_entries,
                "le",
                64,
                "snapshot overlay must remain within its materialization bound",
            ),
            _contract(
                "parameter_snapshot.one_key.reference_p95",
                "soft",
                float(p95),
                "le",
                1.0,
                "reference target for 10k one-key snapshot is 1 ms p95",
            ),
        ),
    )


def _run_visibility(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    store = scenario.store
    search = scenario.operation == "visibility_search"
    build_count_before = int(store_bridge.parameter_table_model_build_count())
    view_build_count_before = int(store_bridge.parameter_table_view_build_count())
    elapsed_ms: list[float] = []
    static_search_ms: list[float] = []
    dynamic_search_ms: list[float] = []
    filtered_count = -1
    total_count = -1
    search_trace: list[tuple[str, int, str | None, str | None]] = []
    expected_search_counts: list[int] = []
    typing_queries = _search_typing_queries(scenario.rows)

    for sample_index in range(scenario.samples):
        state = None
        query = ""
        if search:
            # short/broad/static/dynamic/selective query を巡回し、同一 query の
            # stable cache hit ではなく実際の typing 中 rebuild を測る。
            query, expected_count = typing_queries[
                sample_index % len(typing_queries)
            ]
            expected_search_counts.append(expected_count)
            state = ParameterFilterState(query=query)
        started = time.perf_counter_ns()
        view = store_bridge.parameter_table_view_for_store(
            store,
            show_inactive_params=False,
            filter_state=state,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        elapsed_ms.append(elapsed)
        if search:
            tokens = parameter_search_tokens(query)
            target = (
                dynamic_search_ms
                if any(
                    parameter_search_token_may_be_dynamic(token)
                    for token in tokens
                )
                else static_search_ms
            )
            target.append(elapsed)
        filtered_count = int(view.filtered_count)
        total_count = int(view.total_count)
        if search:
            visible = view.visible_row_indices
            first = (
                None
                if not visible
                else _key_token(view.model.keys[visible[0]])
            )
            last = (
                None
                if not visible
                else _key_token(view.model.keys[visible[-1]])
            )
            search_trace.append((query, filtered_count, first, last))

    model_builds = (
        int(store_bridge.parameter_table_model_build_count())
        - build_count_before
    )
    view_builds = (
        int(store_bridge.parameter_table_view_build_count())
        - view_build_count_before
    )
    expected_filtered = (
        expected_search_counts[-1] if search else scenario.rows
    )
    expected_view_builds = scenario.samples if search else 0
    search_count_digest = _digest_items(item[1] for item in search_trace)
    expected_search_count_digest = _digest_items(expected_search_counts)
    visibility_digest = _digest_items(
        _key_token(view.model.keys[index])
        for index in view.visible_row_indices
    )
    distribution = summarize_distribution(elapsed_ms)
    p95 = distribution.p95 if distribution.p95 is not None else distribution.max
    assert p95 is not None
    target_ms = 8.0 if search else 1.0
    metrics = [
        _distribution_metric(
            (
                "parameter_visibility.search"
                if search
                else "parameter_visibility.default"
            ),
            elapsed_ms,
        ),
        _gauge_metric(
            "parameter_visibility.filtered_count",
            filtered_count,
            unit="rows",
        ),
        _gauge_metric(
            "parameter_visibility.model_builds",
            model_builds,
            unit="count",
        ),
        _gauge_metric(
            "parameter_visibility.view_builds",
            view_builds,
            unit="count",
        ),
    ]
    if static_search_ms:
        metrics.append(
            _distribution_metric(
                "parameter_visibility.search_static",
                static_search_ms,
            )
        )
    if dynamic_search_ms:
        metrics.append(
            _distribution_metric(
                "parameter_visibility.search_dynamic",
                dynamic_search_ms,
            )
        )
    contracts = [
        _contract(
            "parameter_visibility.total_count",
            "hard",
            total_count,
            "eq",
            scenario.rows,
            "visibility view must retain the full model cardinality",
        ),
        _contract(
            "parameter_visibility.filtered_count",
            "hard",
            filtered_count,
            "eq",
            expected_filtered,
            "default/search mask must select the deterministic row count",
        ),
        (
            _contract(
                "parameter_visibility.search_trace_counts",
                "hard",
                search_count_digest,
                "eq",
                expected_search_count_digest,
                "typing sequence must preserve every broad/dynamic/selective count",
            )
            if search
            else _contract(
                "parameter_visibility.default_trace_not_applicable",
                "hard",
                True,
                "eq",
                True,
                "default visibility has no query trace",
            )
        ),
        _contract(
            "parameter_visibility.structure_reuse",
            "hard",
            model_builds,
            "eq",
            0,
            "stable visibility evaluation must reuse table structure",
        ),
        _contract(
            "parameter_visibility.mask_reuse",
            "hard",
            view_builds,
            "eq",
            expected_view_builds,
            (
                "query typing must rebuild one filter view per changed query"
                if search
                else "stable visibility must reuse the immutable mask"
            ),
        ),
        _contract(
            "parameter_visibility.reference_p95",
            "soft",
            float(p95),
            "le",
            target_ms,
            "reference target is 1 ms default / 8 ms search p95",
        ),
    ]
    if dynamic_search_ms:
        dynamic_distribution = summarize_distribution(dynamic_search_ms)
        dynamic_p95 = (
            dynamic_distribution.p95
            if dynamic_distribution.p95 is not None
            else dynamic_distribution.max
        )
        assert dynamic_p95 is not None
        contracts.append(
            _contract(
                "parameter_visibility.dynamic_search.reference_p95",
                "soft",
                float(dynamic_p95),
                "le",
                8.0,
                "dynamic source/MIDI search reference target is 8 ms p95",
            )
        )
    return BenchmarkOutput(
        value={
            "operation": scenario.operation,
            "rows": scenario.rows,
            "samples": scenario.samples,
            "filtered_count": filtered_count,
            "total_count": total_count,
            "model_builds": model_builds,
            "view_builds": view_builds,
            "search_mode": "query-change" if search else "stable",
            "search_trace": search_trace,
            "visibility_digest": visibility_digest,
        },
        metrics=tuple(metrics),
        contracts=tuple(contracts),
    )


def _run_favorite_view(
    scenario: ParameterHotPathScenario,
) -> BenchmarkOutput:
    store = scenario.store
    expected_keys = tuple(record.key for record in scenario.records)
    expected_digest = _digest_items(_key_token(key) for key in expected_keys)
    favorite_revision_before = int(store.favorite_revision)
    table_revision_before = int(store.table_revision)
    immutable_view = favorite_parameter_key_set(store)
    ordered_view = favorite_parameter_keys(store)
    elapsed_ms: list[float] = []
    identity_matches = 0

    for _ in range(scenario.samples):
        started = time.perf_counter_ns()
        current_set = favorite_parameter_key_set(store)
        current_ordered = favorite_parameter_keys(store)
        elapsed_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
        identity_matches += int(
            current_set is immutable_view and current_ordered is ordered_view
        )

    actual_digest = _digest_items(_key_token(key) for key in ordered_view)
    revision_delta = int(store.favorite_revision) - favorite_revision_before
    table_revision_delta = int(store.table_revision) - table_revision_before
    distribution = summarize_distribution(elapsed_ms)
    p95 = distribution.p95 if distribution.p95 is not None else distribution.max
    assert p95 is not None
    return BenchmarkOutput(
        value={
            "operation": scenario.operation,
            "rows": scenario.rows,
            "samples": scenario.samples,
            "favorite_count": len(immutable_view),
            "identity_matches": identity_matches,
            "favorite_digest": actual_digest,
        },
        metrics=(
            _distribution_metric("parameter_favorites.stable_view", elapsed_ms),
            _gauge_metric(
                "parameter_favorites.count",
                len(immutable_view),
                unit="rows",
            ),
            _gauge_metric(
                "parameter_favorites.favorite_revision_delta",
                revision_delta,
                unit="revisions",
            ),
            _gauge_metric(
                "parameter_favorites.table_revision_delta",
                table_revision_delta,
                unit="revisions",
            ),
        ),
        contracts=(
            _contract(
                "parameter_favorites.count_exact",
                "hard",
                len(immutable_view),
                "eq",
                scenario.rows,
                "favorite immutable view must retain every selected key",
            ),
            _contract(
                "parameter_favorites.order_exact",
                "hard",
                actual_digest,
                "eq",
                expected_digest,
                "favorite ordered view must preserve deterministic key order",
            ),
            _contract(
                "parameter_favorites.identity_reused",
                "hard",
                identity_matches,
                "eq",
                scenario.samples,
                "stable favorite revision must reuse set and ordered tuple identity",
            ),
            _contract(
                "parameter_favorites.favorite_revision_stable",
                "hard",
                revision_delta,
                "eq",
                0,
                "stable favorite reads must not advance favorite revision",
            ),
            _contract(
                "parameter_favorites.table_revision_stable",
                "hard",
                table_revision_delta,
                "eq",
                0,
                "stable favorite reads must not advance table revision",
            ),
            _contract(
                "parameter_favorites.reference_p95",
                "soft",
                float(p95),
                "le",
                1.0,
                "reference target for 10k stable favorite view is 1 ms p95",
            ),
        ),
    )


def _search_typing_queries(rows: int) -> tuple[tuple[str, int], ...]:
    """known fixture の broad/dynamic/selective typing sequence を返す。"""

    target = f"hotpath-{rows - 1:06d}"
    midi_rows = (rows + _SEARCH_MIDI_STRIDE - 1) // _SEARCH_MIDI_STRIDE
    ui_rows = rows - midi_rows
    return (
        ("h", rows),
        ("x", 0),
        ("ho", rows),
        ("xo", 0),
        ("hot", rows),
        ("hotp", rows),
        ("hotpath", rows),
        ("hotpath-", rows),
        ("hotpath-0", rows),
        ("hotpath-00", rows),
        ("m", midi_rows),
        ("u", ui_rows),
        ("ui", ui_rows),
        ("cod", 0),
        (target, 1),
    )


def _key_token(key: ParameterKey) -> str:
    return f"{key.op}|{key.site_id}|{key.arg}"


def _fresh_equivalent_records(
    records: list[FrameParamRecord],
) -> list[FrameParamRecord]:
    """本番 frame 同様、等価だが新しい record/key object を作る。"""

    return [
        FrameParamRecord(
            key=ParameterKey(
                op=record.key.op,
                site_id=record.key.site_id,
                arg=record.key.arg,
            ),
            base=record.base,
            meta=record.meta,
            effective=record.effective,
            source=record.source,
            explicit=bool(record.explicit),
        )
        for record in records
    ]


def _snapshot_digest(snapshot: ParamSnapshot) -> str:
    keys = sorted(
        snapshot,
        key=lambda key: (key.op, key.site_id, key.arg),
    )
    return _digest_items(
        (
            key.op,
            key.site_id,
            key.arg,
            meta,
            state.override,
            state.ui_value,
            state.cc_key,
            ordinal,
            label,
        )
        for key in keys
        for meta, state, ordinal, label in (snapshot[key],)
    )


def _store_semantic_digest(store: ParamStore) -> str:
    runtime = store._runtime_ref()
    snapshot = store_snapshot(store)
    keys = sorted(
        snapshot,
        key=lambda key: (key.op, key.site_id, key.arg),
    )
    return _digest_items(
        (
            _snapshot_digest(snapshot),
            tuple(
                (
                    _key_token(key),
                    runtime.last_effective_by_key.get(key),
                    runtime.last_source_by_key.get(key),
                    store._explicit_by_key.get(key),
                )
                for key in keys
            ),
        )
    )


def _digest_items(items: Iterable[object]) -> str:
    digest = hashlib.sha256()
    for item in items:
        digest.update(repr(item).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _distribution_metric(name: str, values: list[float]) -> Metric:
    return Metric(
        name=name,
        kind="distribution",
        unit="ms",
        phase="measure",
        scope=_SCOPE,
        distribution=summarize_distribution(values),
    )


def _gauge_metric(name: str, value: object, *, unit: str) -> Metric:
    return Metric(
        name=name,
        kind="gauge",
        unit=unit,
        phase="measure",
        scope=_SCOPE,
        value=value,
    )


def _contract(
    contract_id: str,
    severity: str,
    actual: object,
    comparator: str,
    limit: object,
    reason: str,
) -> ContractResult:
    return evaluate_contract(
        contract_id=contract_id,
        severity=severity,
        actual=actual,
        comparator=comparator,
        limit=limit,
        reason=reason,
    )


__all__ = [
    "ParameterHotPathScenario",
    "make_parameter_hot_path_scenario",
    "run_parameter_hot_path_scenario",
]
