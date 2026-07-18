from __future__ import annotations

from dataclasses import replace

import pytest

from grafix.devtools.benchmarks.compare import (
    IncompatibleBenchmarkError,
    compare_runs,
)
from grafix.devtools.benchmarks.schema import (
    BenchmarkRun,
    CaseResult,
    CaseSpec,
    ContractResult,
    EnvironmentFingerprint,
    Metric,
    RunMeta,
    Sample,
    SourceIdentity,
    evaluate_contract,
    summarize_samples,
)


def _run(
    run_id: str,
    *,
    elapsed_ns: int,
    source: str,
    environment_key: str = "env",
    case_key: str = "case",
    checksum: str = "same",
    checksum_kind: str = "exact",
    metrics: tuple[Metric, ...] = (),
    contracts: tuple[ContractResult, ...] = (),
    self_sampling: bool = False,
) -> BenchmarkRun:
    spec = CaseSpec(
        case_id="example",
        version=1,
        label="example",
        category="micro",
        suite="micro",
        fixture="fixture",
        parameters={},
        seed=0,
        source_sha256="source",
        compatibility_key=case_key,
        self_sampling=self_sampling,
    )
    sample = Sample(elapsed_ns=elapsed_ns, iterations=1)
    return BenchmarkRun(
        meta=RunMeta(
            run_id=run_id,
            created_at="2026-07-17T00:00:00+00:00",
            suite="micro",
            profile="short",
            mode="warm",
            seed=0,
        ),
        source=SourceIdentity(commit=source, dirty=False, diff_sha256=""),
        environment=EnvironmentFingerprint(
            compatibility_key=environment_key,
            values={},
        ),
        cases=(
            CaseResult(
                spec=spec,
                status="ok",
                samples=(sample,),
                stats=summarize_samples([sample]),
                checksum=checksum,
                checksum_kind=checksum_kind,
                metrics=metrics,
                contracts=contracts,
            ),
        ),
    )


def test_compare_allows_different_source_and_reports_ratio() -> None:
    comparison = compare_runs(
        _run("base", elapsed_ns=200, source="aaa"),
        _run("head", elapsed_ns=100, source="bbb"),
    )

    assert comparison.environment_compatible is True
    assert comparison.rows[0]["ratio"] == 0.5
    assert comparison.rows[0]["checksum_equal"] is True
    assert comparison.rows[0]["checksum_kind_equal"] is True


def test_compare_treats_checksum_kind_change_as_semantic_mismatch() -> None:
    comparison = compare_runs(
        _run("base", elapsed_ns=200, source="aaa", checksum_kind="exact-v1"),
        _run("head", elapsed_ns=100, source="bbb", checksum_kind="exact-v2"),
    )

    assert comparison.rows[0]["checksum_kind_equal"] is False
    assert comparison.rows[0]["checksum_equal"] is False


def test_compare_rejects_environment_mode_and_case_mismatch() -> None:
    base = _run("base", elapsed_ns=200, source="aaa")
    with pytest.raises(IncompatibleBenchmarkError, match="environment"):
        compare_runs(
            base,
            _run(
                "head",
                elapsed_ns=100,
                source="bbb",
                environment_key="other",
            ),
        )

    with pytest.raises(IncompatibleBenchmarkError, match="measurement mode"):
        compare_runs(base, replace(base, meta=replace(base.meta, mode="process-cold")))

    with pytest.raises(IncompatibleBenchmarkError, match="case compatibility"):
        compare_runs(
            base,
            _run(
                "head",
                elapsed_ns=100,
                source="bbb",
                case_key="other",
            ),
        )


def test_compare_rejects_measurement_settings_and_case_set_changes() -> None:
    base = _run("base", elapsed_ns=200, source="aaa")

    with pytest.raises(IncompatibleBenchmarkError, match="measurement settings"):
        compare_runs(
            base,
            replace(
                base,
                meta=replace(base.meta, samples=base.meta.samples + 1),
            ),
        )

    with pytest.raises(IncompatibleBenchmarkError, match="missing cases"):
        compare_runs(base, replace(base, cases=()))


def test_compare_ignores_outer_sampling_knobs_for_self_sampling_case() -> None:
    base = _run(
        "base",
        elapsed_ns=200,
        source="aaa",
        self_sampling=True,
    )
    head = _run(
        "head",
        elapsed_ns=100,
        source="bbb",
        self_sampling=True,
    )
    head = replace(
        head,
        meta=replace(
            head.meta,
            samples=20,
            warmup=3,
            target_ns=250_000_000,
        ),
    )

    comparison = compare_runs(base, head)

    assert comparison.environment_compatible is True
    assert comparison.rows[0]["ratio"] == 0.5


def test_compare_reports_selected_metric_tail_and_contracts() -> None:
    base_metric = Metric(
        name="input_to_present_ms",
        kind="distribution",
        unit="ms",
        phase="drag",
        scope="scenario",
        distribution=runner_distribution(20.0, 30.0, 35.0),
    )
    head_metric = replace(
        base_metric,
        distribution=runner_distribution(10.0, 15.0, 18.0),
    )
    base_contract = evaluate_contract(
        contract_id="ux.latency",
        severity="soft",
        actual=30.0,
        comparator="le",
        limit=50.0,
        reason="interactive p95 remains within target",
    )
    head_contract = replace(base_contract, actual=15.0)
    comparison = compare_runs(
        _run(
            "base",
            elapsed_ns=200,
            source="aaa",
            metrics=(base_metric,),
            contracts=(base_contract,),
        ),
        _run(
            "head",
            elapsed_ns=100,
            source="bbb",
            metrics=(head_metric,),
            contracts=(head_contract,),
        ),
        metric_names=("input_to_present_ms",),
    )

    row = comparison.rows[0]
    assert row["metrics"][0]["median_ratio"] == 0.5
    assert row["metrics"][0]["p95_ratio"] == 0.5
    assert row["contracts"][0]["head_passed"] is True
    assert row["base_hard_contracts_passed"] is True


@pytest.mark.parametrize("head_status", ("error", "timeout", "resource-limit"))
def test_compare_keeps_status_regression_when_head_is_unmeasured(
    head_status: str,
) -> None:
    metric = Metric(
        name="latency",
        kind="gauge",
        unit="ms",
        phase="measure",
        scope="case",
        value=10.0,
    )
    contract = evaluate_contract(
        contract_id="latency.limit",
        severity="soft",
        actual=10.0,
        comparator="le",
        limit=20.0,
        reason="latency remains within target",
    )
    base = _run(
        "base",
        elapsed_ns=200,
        source="aaa",
        metrics=(metric,),
        contracts=(contract,),
    )
    head_result = replace(
        base.cases[0],
        status=head_status,
        samples=(),
        stats=None,
        checksum=None,
        checksum_kind=None,
        metrics=(),
        contracts=(),
        error=f"{head_status} while measuring",
    )
    head = replace(
        base,
        meta=replace(base.meta, run_id="head"),
        source=replace(base.source, commit="bbb"),
        cases=(head_result,),
    )

    comparison = compare_runs(
        base,
        head,
        metric_names=("latency",),
    )

    assert comparison.warnings == ()
    assert len(comparison.rows) == 1
    row = comparison.rows[0]
    assert row["compatible"] is True
    assert row["base_status"] == "ok"
    assert row["head_status"] == head_status
    assert row["ratio"] is None
    assert row["metrics"] == []
    assert row["contracts"] == []


@pytest.mark.parametrize(
    "head_metric",
    (
        Metric(
            name="latency",
            kind="gauge",
            unit="ns",
            phase="drag",
            scope="scenario",
            value=10.0,
        ),
        Metric(
            name="latency",
            kind="gauge",
            unit="ms",
            phase="settle",
            scope="scenario",
            value=10.0,
        ),
    ),
)
def test_compare_rejects_metric_unit_or_phase_mismatch(
    head_metric: Metric,
) -> None:
    base_metric = Metric(
        name="latency",
        kind="gauge",
        unit="ms",
        phase="drag",
        scope="scenario",
        value=20.0,
    )
    with pytest.raises(IncompatibleBenchmarkError, match="metric"):
        compare_runs(
            _run(
                "base",
                elapsed_ns=200,
                source="aaa",
                metrics=(base_metric,),
            ),
            _run(
                "head",
                elapsed_ns=100,
                source="bbb",
                metrics=(head_metric,),
            ),
        )


def runner_distribution(
    median: float,
    p95: float,
    p99: float,
):
    from grafix.devtools.benchmarks.schema import Distribution

    return Distribution(
        count=20,
        min=1.0,
        max=p99,
        median=median,
        mad=1.0,
        p95=p95,
        p99=p99,
        mean=median,
    )
