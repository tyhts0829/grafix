from __future__ import annotations

import json
import operator
from dataclasses import replace
from pathlib import Path

import pytest

from grafix.devtools.benchmarks.definition import make_case_spec
from grafix.devtools.benchmarks.schema import (
    BenchmarkRun,
    BenchmarkSchemaError,
    CaseResult,
    CaseSpec,
    Distribution,
    EnvironmentFingerprint,
    FrozenJsonObject,
    Metric,
    RunMeta,
    Sample,
    SourceIdentity,
    benchmark_run_from_dict,
    benchmark_run_to_dict,
    case_compatibility_key,
    environment_compatibility_key,
    evaluate_contract,
    freeze_json_object,
    read_benchmark_run,
    summarize_distribution,
    summarize_samples,
    write_benchmark_run,
)


def _run() -> BenchmarkRun:
    samples = tuple(Sample(elapsed_ns=index * 100, iterations=2) for index in range(1, 21))
    parameters = freeze_json_object({"size": 1})
    spec = CaseSpec(
        case_id="case",
        version=1,
        label="case",
        category="micro",
        suite="smoke",
        fixture="fixture",
        parameters=parameters,
        seed=0,
        source_sha256="case-source",
        compatibility_key=case_compatibility_key(
            case_id="case",
            version=1,
            fixture="fixture",
            parameters=parameters,
            seed=0,
            source_sha256="case-source",
        ),
        tags=("exact",),
    )
    return BenchmarkRun(
        meta=RunMeta(
            run_id="run",
            created_at="2026-07-17T00:00:00+00:00",
            suite="smoke",
            profile="short",
            mode="warm",
            seed=0,
            samples=20,
            warmup=2,
            target_ns=1_000_000,
            timeout_seconds=120.0,
            argv=("run",),
        ),
        source=SourceIdentity(commit="abc", dirty=True, diff_sha256="diff"),
        environment=_environment(),
        cases=(
            CaseResult(
                spec=spec,
                status="ok",
                samples=samples,
                stats=summarize_samples(samples),
                checksum="checksum",
                checksum_kind="exact",
                setup_rss_bytes=10,
                baseline_rss_bytes=12,
                peak_rss_bytes=20,
                peak_rss_delta_bytes=8,
                metrics=(
                    Metric(
                        name="input_to_present_ms",
                        kind="gauge",
                        unit="ms",
                        phase="drag",
                        scope="scenario",
                        value=12.5,
                    ),
                ),
                contracts=(
                    evaluate_contract(
                        contract_id="ux.input_to_present",
                        severity="soft",
                        actual=12.5,
                        comparator="le",
                        limit=50.0,
                        reason="input-to-present p95 is within the target",
                    ),
                ),
            ),
        ),
    )


def _environment() -> EnvironmentFingerprint:
    values = freeze_json_object({"python": "3.12"})
    unavailable = freeze_json_object({})
    return EnvironmentFingerprint(
        compatibility_key=environment_compatibility_key(
            values,
            unavailable,
        ),
        values=values,
        unavailable=unavailable,
    )


def test_stats_keep_raw_units_and_only_emit_tail_for_enough_samples() -> None:
    short = summarize_samples([Sample(elapsed_ns=30, iterations=3)])
    assert short.median_ns == 10.0
    assert short.mad_ns == 0.0
    assert short.p95_ns is None
    assert short.p99_ns is None

    long = summarize_samples([Sample(elapsed_ns=index * 2, iterations=2) for index in range(1, 21)])
    assert long.n == 20
    assert long.median_ns == 10.5
    assert long.p95_ns is not None
    assert long.p99_ns is not None


def test_schema_v4_round_trip_is_strict_and_run_is_no_clobber(tmp_path: Path) -> None:
    run = _run()
    path = tmp_path / "run.json"
    write_benchmark_run(path, run)
    assert read_benchmark_run(path) == run

    with pytest.raises(FileExistsError):
        write_benchmark_run(path, run)

    with pytest.raises(BenchmarkSchemaError, match="unsupported schema"):
        write_benchmark_run(
            tmp_path / "wrong-version.json",
            replace(run, schema_version=2),
        )

    float_version = replace(
        run.cases[0],
        spec=replace(run.cases[0].spec, version=1.0),  # type: ignore[arg-type]
    )
    with pytest.raises(BenchmarkSchemaError, match="integer is required"):
        write_benchmark_run(
            tmp_path / "float-version.json",
            replace(run, cases=(float_version,)),
        )

    with pytest.raises(BenchmarkSchemaError, match="non-finite"):
        write_benchmark_run(
            tmp_path / "nan-timeout.json",
            replace(run, meta=replace(run.meta, timeout_seconds=float("nan"))),
        )

    bad_result = replace(
        run.cases[0],
        metrics=(
            Metric(
                name="bad",
                kind="gauge",
                unit="unitless",
                phase="measure",
                scope="case",
                value=float("nan"),
            ),
        ),
    )
    with pytest.raises(BenchmarkSchemaError, match="non-finite"):
        write_benchmark_run(
            tmp_path / "nan-metric.json",
            replace(run, cases=(bad_result,)),
        )

    bad_rss = replace(
        run.cases[0],
        setup_rss_bytes=13,
        baseline_rss_bytes=12,
    )
    with pytest.raises(BenchmarkSchemaError, match="RSS fields are inconsistent"):
        write_benchmark_run(
            tmp_path / "bad-rss.json",
            replace(run, cases=(bad_rss,)),
        )

    payload = benchmark_run_to_dict(run)
    payload["unknown"] = True
    with pytest.raises(BenchmarkSchemaError, match="unknown"):
        benchmark_run_from_dict(payload)

    payload = benchmark_run_to_dict(run)
    payload["schema_version"] = 3
    with pytest.raises(BenchmarkSchemaError, match="unsupported schema"):
        benchmark_run_from_dict(payload)

    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(BenchmarkSchemaError, match="JSONDecodeError"):
        read_benchmark_run(path)

    path.write_text('{"schema_version": NaN}', encoding="utf-8")
    with pytest.raises(BenchmarkSchemaError, match="non-finite JSON"):
        read_benchmark_run(path)


def test_json_contains_raw_samples_and_separate_identities() -> None:
    payload = json.loads(json.dumps(benchmark_run_to_dict(_run())))

    assert payload["source"]["commit"] == "abc"
    assert payload["environment"]["compatibility_key"]
    assert payload["cases"][0]["spec"]["compatibility_key"]
    assert len(payload["cases"][0]["samples"]) == 20
    assert payload["cases"][0]["metrics"][0]["kind"] == "gauge"
    assert payload["cases"][0]["contracts"][0]["severity"] == "soft"


def test_identity_trees_detach_nested_aliases_and_serialize_as_json() -> None:
    def implementation() -> None:
        return None

    parameter_source = {
        "nested": {
            "items": [1, {"state": "initial"}],
        }
    }
    spec = make_case_spec(
        case_id="immutable.case",
        version=1,
        label="immutable case",
        category="test",
        suite="test",
        fixture="fixture",
        parameters=parameter_source,
        seed=0,
        implementation=implementation,
    )
    case_key = spec.compatibility_key

    values_source = {
        "runtime": {
            "flags": ["one", {"enabled": True}],
        }
    }
    unavailable_source = {"gpu": "unavailable"}
    frozen_values = freeze_json_object(values_source)
    frozen_unavailable = freeze_json_object(unavailable_source)
    environment = EnvironmentFingerprint(
        compatibility_key=environment_compatibility_key(
            frozen_values,
            frozen_unavailable,
        ),
        values=frozen_values,
        unavailable=frozen_unavailable,
    )
    environment_key = environment.compatibility_key

    parameter_source["nested"]["items"][1]["state"] = "mutated"
    parameter_source["nested"]["items"].append(2)
    values_source["runtime"]["flags"][1]["enabled"] = False
    values_source["runtime"]["flags"].append("two")
    unavailable_source["gpu"] = "mutated"

    nested = spec.parameters["nested"]
    assert isinstance(nested, FrozenJsonObject)
    items = nested["items"]
    assert isinstance(items, tuple)
    leaf = items[1]
    assert isinstance(leaf, FrozenJsonObject)
    assert leaf["state"] == "initial"
    assert len(items) == 2
    assert spec.compatibility_key == case_key
    assert spec.compatibility_key == case_compatibility_key(
        case_id=spec.case_id,
        version=spec.version,
        fixture=spec.fixture,
        parameters=spec.parameters,
        seed=spec.seed,
        source_sha256=spec.source_sha256,
        checksum_policy=spec.checksum_policy,
        self_sampling=spec.self_sampling,
    )
    assert environment.compatibility_key == environment_key
    assert environment.compatibility_key == environment_compatibility_key(
        environment.values,
        environment.unavailable,
    )
    assert environment.unavailable["gpu"] == "unavailable"

    with pytest.raises(TypeError):
        operator.setitem(spec.parameters, "extra", True)
    with pytest.raises(TypeError):
        operator.setitem(leaf, "state", "mutated")

    run = _run()
    run = replace(
        run,
        environment=environment,
        cases=(replace(run.cases[0], spec=spec),),
    )
    payload = benchmark_run_to_dict(run)
    assert payload["cases"][0]["spec"]["parameters"]["nested"]["items"] == [
        1,
        {"state": "initial"},
    ]
    assert payload["environment"]["values"]["runtime"]["flags"] == [
        "one",
        {"enabled": True},
    ]
    payload["cases"][0]["spec"]["parameters"]["nested"]["items"][1]["state"] = "serialized mutation"
    assert leaf["state"] == "initial"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda payload: payload["cases"][0]["stats"].__setitem__("n", 999),
            "raw samples",
        ),
        (
            lambda payload: payload["cases"][0]["spec"].__setitem__(
                "compatibility_key", "tampered"
            ),
            "compatibility_key",
        ),
        (
            lambda payload: payload["cases"][0].__setitem__("status", "mystery"),
            "unsupported value",
        ),
        (
            lambda payload: payload["cases"][0].__setitem__("peak_rss_delta_bytes", -1),
            "non-negative",
        ),
    ],
)
def test_schema_rejects_semantically_inconsistent_payloads(
    mutate,
    match: str,
) -> None:
    payload = json.loads(json.dumps(benchmark_run_to_dict(_run())))
    mutate(payload)

    with pytest.raises(BenchmarkSchemaError, match=match):
        benchmark_run_from_dict(payload)


def test_reader_reports_invalid_utf8_as_schema_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(b"\xff")

    with pytest.raises(BenchmarkSchemaError, match="UnicodeDecodeError"):
        read_benchmark_run(path)


def test_schema_rejects_duplicate_case_ids() -> None:
    payload = json.loads(json.dumps(benchmark_run_to_dict(_run())))
    payload["cases"].append(payload["cases"][0])

    with pytest.raises(BenchmarkSchemaError, match="duplicate"):
        benchmark_run_from_dict(payload)


def test_schema_rejects_duplicate_metric_names_across_phases() -> None:
    run = _run()
    metric = run.cases[0].metrics[0]
    duplicate = replace(metric, phase="settle")
    payload = json.loads(
        json.dumps(
            benchmark_run_to_dict(
                replace(
                    run,
                    cases=(
                        replace(
                            run.cases[0],
                            metrics=(metric, duplicate),
                        ),
                    ),
                )
            )
        )
    )

    with pytest.raises(BenchmarkSchemaError, match="duplicate metric name"):
        benchmark_run_from_dict(payload)


def test_schema_rejects_invalid_typed_metric_and_contract_result() -> None:
    run = _run()
    metric = run.cases[0].metrics[0]
    bad_metric = replace(metric, kind="timer")
    with pytest.raises(BenchmarkSchemaError, match="unsupported value"):
        benchmark_run_from_dict(
            json.loads(
                json.dumps(
                    benchmark_run_to_dict(
                        replace(
                            run,
                            cases=(replace(run.cases[0], metrics=(bad_metric,)),),
                        )
                    )
                )
            )
        )

    contract = run.cases[0].contracts[0]
    bad_contract = replace(contract, passed=False)
    with pytest.raises(BenchmarkSchemaError, match="does not match"):
        benchmark_run_from_dict(
            json.loads(
                json.dumps(
                    benchmark_run_to_dict(
                        replace(
                            run,
                            cases=(
                                replace(
                                    run.cases[0],
                                    contracts=(bad_contract,),
                                ),
                            ),
                        )
                    )
                )
            )
        )


def test_failed_hard_contract_requires_contract_failure_status() -> None:
    run = _run()
    failed = evaluate_contract(
        contract_id="hard.limit",
        severity="hard",
        actual=51.0,
        comparator="le",
        limit=50.0,
        reason="latency must remain within the hard limit",
    )
    result = replace(run.cases[0], contracts=(failed,))
    with pytest.raises(BenchmarkSchemaError, match="contract-failure status"):
        benchmark_run_from_dict(
            json.loads(json.dumps(benchmark_run_to_dict(replace(run, cases=(result,)))))
        )

    failed_result = replace(
        result,
        status="contract-failure",
        error="failed hard contracts: hard.limit",
    )
    payload = json.loads(json.dumps(benchmark_run_to_dict(replace(run, cases=(failed_result,)))))
    assert benchmark_run_from_dict(payload).cases[0] == failed_result


def test_distribution_metric_keeps_raw_samples_and_validates_summary() -> None:
    run = _run()
    distribution = summarize_distribution(tuple(float(index) for index in range(20)))
    metric = Metric(
        name="input_to_present_ms",
        kind="distribution",
        unit="ms",
        phase="drag",
        scope="scenario",
        distribution=distribution,
    )
    payload = json.loads(
        json.dumps(
            benchmark_run_to_dict(
                replace(
                    run,
                    cases=(replace(run.cases[0], metrics=(metric,)),),
                )
            )
        )
    )

    decoded = benchmark_run_from_dict(payload)
    assert decoded.cases[0].metrics[0].distribution == distribution
    assert len(payload["cases"][0]["metrics"][0]["distribution"]["samples"]) == 20

    payload["cases"][0]["metrics"][0]["distribution"]["median"] = 999.0
    with pytest.raises(BenchmarkSchemaError, match="raw samples"):
        benchmark_run_from_dict(payload)


@pytest.mark.parametrize(
    ("distribution", "match"),
    (
        (
            Distribution(
                count=1,
                min=1.0,
                max=1.0,
                median=1.0,
                mad=0.0,
                p95=1.0,
                p99=None,
                mean=1.0,
            ),
            "requires all statistics",
        ),
        (
            Distribution(
                count=1,
                min=1.0,
                max=2.0,
                median=1.5,
                mad=-0.1,
                p95=1.8,
                p99=1.9,
                mean=1.5,
            ),
            "mad must be non-negative",
        ),
        (
            Distribution(
                count=1,
                min=1.0,
                max=5.0,
                median=3.0,
                mad=1.0,
                p95=2.0,
                p99=4.0,
                mean=3.0,
            ),
            "min <= median <= p95 <= p99 <= max",
        ),
        (
            Distribution(
                count=1,
                min=1.0,
                max=5.0,
                median=2.0,
                mad=1.0,
                p95=3.0,
                p99=4.0,
                mean=6.0,
            ),
            "mean must be between min and max",
        ),
        (
            Distribution(
                count=0,
                min=0.0,
                max=None,
                median=None,
                mad=None,
                p95=None,
                p99=None,
                mean=None,
            ),
            "empty distribution",
        ),
    ),
)
def test_schema_rejects_inconsistent_distribution_summary(
    distribution: Distribution,
    match: str,
) -> None:
    run = _run()
    metric = Metric(
        name="latency",
        kind="distribution",
        unit="ms",
        phase="measure",
        scope="case",
        distribution=distribution,
    )
    payload = json.loads(
        json.dumps(
            benchmark_run_to_dict(
                replace(
                    run,
                    cases=(replace(run.cases[0], metrics=(metric,)),),
                )
            )
        )
    )

    with pytest.raises(BenchmarkSchemaError, match=match):
        benchmark_run_from_dict(payload)
