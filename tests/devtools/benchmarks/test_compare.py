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
    EnvironmentFingerprint,
    RunMeta,
    Sample,
    SourceIdentity,
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
