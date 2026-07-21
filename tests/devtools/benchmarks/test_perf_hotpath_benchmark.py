from __future__ import annotations

from grafix.devtools.benchmarks.perf_hotpath_benchmark import (
    make_perf_backlog_scenario,
    run_perf_backlog_scenario,
)
from grafix.devtools.benchmarks.runner import case_definitions


def test_perf_backlog_scenario_preserves_ordered_prefix_semantics() -> None:
    result = run_perf_backlog_scenario(
        make_perf_backlog_scenario({"pending": 100, "samples": 4})
    )

    assert result.value["pending"] == 100
    assert result.value["samples"] == 4
    assert result.value["prefix_count"] == 10
    assert result.value["future_remaining"] == 100
    assert result.value["prefix_remaining"] == 90
    assert result.value["all_remaining"] == 0
    assert result.value["future_bounds"] == [1, 100]
    assert result.value["prefix_bounds"] == [11, 100]
    assert result.value["latency_counts"] == [0, 10, 100]
    assert result.value["latency_drop_counts"] == [0, 0, 0]
    assert len(str(result.value["semantic_digest"])) == 64
    metrics = {metric.name: metric for metric in result.metrics}
    for name in (
        "perf.causal_backlog.future",
        "perf.causal_backlog.prefix_10pct",
        "perf.causal_backlog.all",
    ):
        assert metrics[name].distribution is not None
        assert metrics[name].distribution.count == 4
    assert all(
        contract.passed
        for contract in result.contracts
        if contract.severity == "hard"
    )


def test_perf_backlog_registry_has_scaling_cases() -> None:
    definitions = {
        definition.case_id: definition for definition in case_definitions()
    }

    small = definitions["runtime.perf.causal_backlog.pending_100"]
    large = definitions["runtime.perf.causal_backlog.pending_4096"]

    assert small.parameters == {"pending": 100, "samples": 24}
    assert small.selectable_suites == ("parameters",)
    assert large.parameters == {"pending": 4_096, "samples": 24}
    assert large.selectable_suites == ("parameters", "soak")
    assert small.self_sampling is True
