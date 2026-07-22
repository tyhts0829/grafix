from __future__ import annotations

from grafix.devtools.benchmarks import runner
from grafix.devtools.benchmarks.catalog import (
    case_definitions,
)
from grafix.devtools.benchmarks.runner import run_case_isolated
from grafix.devtools.benchmarks.schema import (
    Metric,
)


def test_runner_exposes_only_the_execution_composition_api() -> None:
    assert runner.__all__ == ["run_case_isolated"]
    assert not hasattr(runner, "case_definitions")
    assert not hasattr(runner, "canonical_checksum")


def test_isolated_runner_returns_raw_samples_checksum_and_rss_delta() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    result = run_case_isolated(
        definition,
        seed=0,
        mode="warm",
        samples=2,
        warmup=0,
        target_ns=0,
        disable_gc=False,
        timeout_seconds=30.0,
    )

    assert result.status == "ok", result.error
    assert len(result.samples) == 2
    assert result.stats is not None
    assert result.stats.n == 2
    assert result.checksum
    assert result.baseline_rss_bytes is not None
    assert result.peak_rss_delta_bytes is not None
    assert result.peak_rss_delta_bytes >= 0
    assert all(isinstance(metric, Metric) for metric in result.metrics)
    assert {metric.name for metric in result.metrics} >= {"parts", "recipe_id"}


def test_self_sampling_scenario_runs_one_semantic_outer_sample() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "interactive.slider.input_to_present.rows_32.workers_0"
    )
    result = run_case_isolated(
        definition,
        seed=0,
        mode="warm",
        samples=3,
        warmup=2,
        target_ns=1_000_000_000,
        disable_gc=False,
        timeout_seconds=30.0,
    )

    assert result.status == "ok", result.error
    assert len(result.samples) == 1
    assert result.stats is not None and result.stats.n == 1
    latency = next(metric for metric in result.metrics if metric.name == "ux01.input_to_present")
    assert latency.distribution is not None
    assert latency.distribution.count == definition.parameters["drag_frames"]
