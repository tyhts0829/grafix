from __future__ import annotations

from dataclasses import replace

import pytest

from grafix.devtools.benchmarks import (
    executor,
    mp_draw_benchmark,
    renderer_benchmark,
)
from grafix.devtools.benchmarks.catalog import (
    case_definitions,
)
from grafix.devtools.benchmarks.metrics import canonical_checksum


def test_slider_interactive_target_is_a_hard_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mode(*, interactive_target_met: bool) -> dict[str, object]:
        summary = {
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "n": 0,
        }
        return {
            "fresh_result_ratio": 1.0,
            "fresh_results_during_drag": 1,
            "max_consecutive_stale_frames": 0,
            "revision_lag": summary,
            "input_to_result_ms": summary,
            "final_revision_latency_ms": 0.0,
            "last_result_revision": 1,
            "final_input_revision": 1,
            "result_revisions_monotonic": True,
            "checksum_matches_sync": True,
            "snapshot_broadcasts": 0,
            "snapshot_payload_copies": 1,
            "snapshot_acks": 1,
            "submitted_tasks": 1,
            "enqueued_tasks": 1,
            "dropped_tasks": 0,
            "completed_results": 1,
            "rejected_tasks": 0,
            "progress_contract_met": True,
            "interactive_target_met": interactive_target_met,
            "elapsed_ms": 0.0,
        }

    monkeypatch.setattr(
        mp_draw_benchmark,
        "run_mp_slider_churn_benchmarks",
        lambda **_kwargs: {
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "n": 2,
            "output": {
                "frames": 1,
                "frame_interval_s": 0.0,
                "n_worker": 1,
                "measurement_scope": "test",
                "progress_contract_met": True,
            },
            "cases": {
                "light_translate": {
                    "stable": mode(interactive_target_met=True),
                    "changing": mode(interactive_target_met=False),
                }
            },
        },
    )

    output = mp_draw_benchmark.workload_mp_slider_churn({"frames": 1, "frame_interval_s": 0.0})
    failed = [
        contract
        for contract in output.contracts
        if contract.severity == "hard" and not contract.passed
    ]

    assert [contract.contract_id for contract in failed] == [
        "mp.slider.light_translate.changing.interactive_target"
    ]


def test_mp_draw_workload_reads_only_the_two_explicit_mode_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {"mean": 1.0, "median": 1.0, "p95": 1.0, "n": 1}
    mode = {
        "startup_ms": summary,
        "first_result_ms": summary,
        "steady_ms": summary,
        "steady_latest_fps": summary,
    }
    monkeypatch.setattr(
        mp_draw_benchmark,
        "run_mp_draw_benchmarks",
        lambda **_kwargs: {
            "mean_ms": 1.0,
            "median_ms": 1.0,
            "p95_ms": 1.0,
            "n": 1,
            "output": {
                "steady_frames": 4,
                "heavy_iterations": 1_000,
                "n_worker": 2,
                "measurement_scope": "test",
            },
            "cases": {
                "light": {
                    "sync_n1": mode,
                    "mp_n2": mode,
                    "mp_to_sync_steady_ratio": 1.0,
                }
            },
        },
    )

    output = mp_draw_benchmark.workload_mp_draw(
        {"repeats": 1, "steady_frames": 4, "heavy_iterations": 1_000}
    )
    metric_names = {metric.name for metric in output.metrics}

    assert "cases.light.mp_to_sync_steady_ratio" in metric_names
    assert "cases.light.sync_n1.startup_ms.median" in metric_names
    assert "cases.light.mp_n2.startup_ms.median" in metric_names


def test_renderer_cases_separate_static_offsets_from_animated_topology() -> None:
    static_state = renderer_benchmark.setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = renderer_benchmark.setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = {
        metric.name: metric.value
        for metric in renderer_benchmark.workload_animated_renderer(static_state).metrics
    }
    animated = {
        metric.name: metric.value
        for metric in renderer_benchmark.workload_animated_renderer(animated_state).metrics
    }

    assert static["index_builds"] == 1
    assert static["full_uploads"] == 1
    assert static["vertex_only_uploads"] == 3
    assert animated["index_builds"] == 4
    assert animated["full_uploads"] == 4
    assert animated["vertex_only_uploads"] == 0


def test_renderer_helpers_report_deterministic_output_and_cache_stats() -> None:
    soak = renderer_benchmark.animated_soak(frames=12, sides=48)
    soak_cache = soak["cache"]
    assert soak["output"]["unique_geometry_ids"] == 12
    assert soak_cache["hits"] == soak["output"]["static_base_hits"] == 11
    assert soak_cache["misses"] == 13
    assert soak_cache["evictions"] == 11
    assert soak_cache["entries"] > 0
    assert 0 < soak_cache["bytes"] <= soak_cache["budget_bytes"]

    end_to_end = renderer_benchmark.draw_realize_indices(grid_size=3)
    assert end_to_end["output"]["draw_lines"] > 0
    assert end_to_end["output"]["index_count"] > 0
    assert end_to_end["cache"]["misses"] == 2

    geometry = renderer_benchmark.renderer_geometry(polylines=100)
    renderer = renderer_benchmark.renderer_cache_workload(geometry, frames=5)
    assert renderer["output"]["n_lines"] == 100
    assert renderer["output"]["index_builds"] == 1
    assert renderer["output"]["uploads"] == 2
    assert renderer["cache"]["hits"] == 3
    assert renderer["cache"]["misses"] == 2
    assert renderer["cache"]["entries"] == 1
    assert 0 < renderer["cache"]["bytes"] <= renderer["cache"]["budget_bytes"]

    multilayer = renderer_benchmark.renderer_multilayer_dynamic_workload(
        layers=8,
        frames=6,
        polylines=12,
        stable_topology=True,
    )
    assert multilayer["output"]["index_builds"] == 8
    assert multilayer["output"]["full_uploads"] == 8
    assert multilayer["output"]["vertex_only_uploads"] == 8 * 5
    assert multilayer["output"]["dynamic_entries"] == 8
    assert multilayer["output"]["dynamic_entries"] <= multilayer["output"]["dynamic_entry_limit"]

    changing_multilayer = renderer_benchmark.renderer_multilayer_dynamic_workload(
        layers=3,
        frames=4,
        polylines=12,
        stable_topology=False,
    )
    assert changing_multilayer["output"]["index_builds"] == 3 * 4
    assert changing_multilayer["output"]["full_uploads"] == 3 * 4
    assert changing_multilayer["output"]["vertex_only_uploads"] == 0


def test_rotate_scale_identity_case_encodes_nested_realized_geometry() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "micro.rotate_scale_identity"
    )
    definition = replace(
        definition,
        parameters={
            "workload": "rotate_scale_identity",
            "points": 4,
            "iterations": 1,
        },
    )

    result = executor.measure_in_process(
        definition,
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "ok"
    assert result.checksum_kind == "canonical_json_sha256_v2"
    assert result.checksum == ("e2888531661e82b09aa1424136e3ee7a88e5e69a3c60ddb070a275574290206b")


def test_asemic_case_returns_canonical_realized_geometry() -> None:
    definition = next(item for item in case_definitions() if item.case_id == "micro.asemic")
    definition = replace(
        definition,
        parameters={"workload": "asemic", "text": "abc", "nodes": 16},
    )

    result = executor.measure_in_process(
        definition,
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "ok", result.error
    assert result.checksum_kind == "realized_geometry_exact_v1"


def test_renderer_checksum_is_independent_of_performance_counters() -> None:
    static_state = renderer_benchmark.setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = renderer_benchmark.setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = renderer_benchmark.workload_animated_renderer(static_state)
    animated = renderer_benchmark.workload_animated_renderer(animated_state)
    static_metrics = {metric.name: metric.value for metric in static.metrics}
    animated_metrics = {metric.name: metric.value for metric in animated.metrics}

    assert static_metrics["index_builds"] != animated_metrics["index_builds"]
    assert canonical_checksum(static.value) == canonical_checksum(animated.value)
    assert static_metrics["full_vertex_upload_bytes"] > 0
    assert static_metrics["vertex_only_upload_bytes"] > 0
