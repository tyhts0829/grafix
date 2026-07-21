from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Iterator

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks import runner
from grafix.devtools.benchmarks.environment import (
    collect_environment_fingerprint,
    collect_source_identity,
    make_case_spec,
)
from grafix.devtools.benchmarks.runner import (
    canonical_checksum,
    case_definitions,
    geometry_checksum,
    run_case_isolated,
    select_case_definitions,
)
from grafix.devtools.benchmarks.schema import (
    BenchmarkOutput,
    CaseResult,
    Metric,
    case_result_to_dict,
    evaluate_contract,
)


def test_isolated_process_timeout_kills_the_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeProcess:
        pid = 4242
        returncode = -signal.SIGKILL

        def communicate(self, *, timeout: float | None = None) -> tuple[str, str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise subprocess.TimeoutExpired(
                    ["benchmark-child"],
                    0.0 if timeout is None else timeout,
                )
            return "", ""

    started: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        started["command"] = command
        started.update(kwargs)
        return FakeProcess()

    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_isolated_process(
            ["benchmark-child"],
            timeout=0.1,
            env={},
        )

    assert started["start_new_session"] is True
    assert killed == [(4242, signal.SIGKILL)]
    assert calls == 2


def test_child_result_must_match_the_requested_case_spec() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    expected = definition.spec(seed=0)
    wrong = CaseResult(
        spec=replace(expected, label="wrong case"),
        status="error",
        error="synthetic",
    )

    with pytest.raises(ValueError, match="case spec differs"):
        runner._validated_child_result(
            json.loads(json.dumps(case_result_to_dict(wrong))),
            expected_spec=expected,
        )


def test_geometry_checksum_includes_dtype_shape_and_bytes() -> None:
    first = RealizedGeometry(
        coords=np.asarray([[0.0, 1.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )
    changed = RealizedGeometry(
        coords=np.asarray([[0.0, 2.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )

    assert geometry_checksum(first) != geometry_checksum(changed)
    checksum, kind = canonical_checksum(first)
    assert checksum == geometry_checksum(first)
    assert kind == "realized_geometry_exact_v1"


def test_registry_selects_suite_and_rejects_unknown_case() -> None:
    all_ids = {definition.case_id for definition in case_definitions()}
    smoke = select_case_definitions(suites=("smoke",))

    assert smoke
    assert {definition.case_id for definition in smoke} <= all_ids
    assert all("smoke" in definition.selectable_suites for definition in smoke)

    provenance = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "runtime.provenance.rows_1000"
    )
    assert runner._benchmark_draw in provenance.support_implementations
    assert any(
        definition.case_id == "runtime.provenance_changed.rows_1000"
        for definition in case_definitions()
    )
    slider_churn = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "mp.draw.slider_churn"
    )
    assert slider_churn.parameters == {
        "frames": 120,
        "frame_interval_s": pytest.approx(1.0 / 60.0),
    }
    assert "mp" in slider_churn.selectable_suites
    assert slider_churn.self_sampling is True


def test_case_definition_parameters_are_deeply_read_only() -> None:
    definition = next(
        item
        for item in case_definitions()
        if item.case_id == "effect.remaining.affine.polyline_long"
    )

    with pytest.raises(TypeError):
        definition.parameters["effect"] = "scale"  # type: ignore[index]
    expected_layout = definition.parameters["expected_layout"]
    with pytest.raises(TypeError):
        expected_layout["coords_dtype"] = "float64"  # type: ignore[index]

    materialized = definition.materialize_parameters()
    materialized["expected_layout"]["coords_dtype"] = "float64"
    assert definition.parameters["expected_layout"]["coords_dtype"] == "<f4"
    multilayer = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "interactive.renderer.multilayer.stable_offsets.layers_8"
    )
    assert multilayer.parameters["layers"] == 8
    assert multilayer.parameters["stable_topology"] is True
    assert "interactive" in multilayer.selectable_suites
    assert any(
        definition.case_id == "interactive.renderer.multilayer.stable_offsets.layers_100"
        and definition.selectable_suites == ("soak",)
        for definition in case_definitions()
    )


def test_system_cases_with_internal_samples_run_once_per_isolated_measurement() -> None:
    self_sampling_ids = {
        definition.case_id
        for definition in runner._system_definitions()
        if definition.self_sampling
    }

    assert self_sampling_ids == {
        "micro.asemic",
        "system.cold_import",
        "system.parameter_snapshot_model",
    }


def test_renderer_cases_with_internal_timing_run_once_per_isolated_measurement() -> None:
    definitions = {
        definition.case_id: definition
        for definition in case_definitions()
        if definition.case_id
        in {
            "interactive.renderer.static_100k",
            "interactive.renderer.static_1m",
        }
    }

    assert set(definitions) == {
        "interactive.renderer.static_100k",
        "interactive.renderer.static_1m",
    }
    assert all(definition.self_sampling for definition in definitions.values())


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


def test_typed_metric_output_preserves_hard_contract_failure() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    failed = evaluate_contract(
        contract_id="synthetic.hard",
        severity="hard",
        actual=False,
        comparator="eq",
        limit=True,
        reason="synthetic hard guardrail",
    )
    failing_definition = replace(
        definition,
        setup=lambda _parameters, _seed: None,
        workload=lambda _state: BenchmarkOutput(
            value={"ok": True},
            metrics=(
                Metric(
                    name="interactive_target_met",
                    kind="gauge",
                    unit="boolean",
                    phase="measure",
                    scope="test",
                    value=False,
                ),
            ),
            contracts=(failed,),
        ),
    )
    result = runner._measure_in_process(
        failing_definition,
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "contract-failure"
    assert result.samples
    assert result.checksum
    assert result.contracts == (failed,)
    assert "synthetic.hard" in (result.error or "")


@pytest.mark.parametrize(
    "stage",
    ["setup", "context", "warmup", "workload", "postprocess"],
)
def test_import_error_at_any_benchmark_stage_is_an_error(stage: str) -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    def fail_import(*_args: object, **_kwargs: object) -> object:
        raise ImportError(f"{stage} import failed")

    @contextmanager
    def failing_context(_state: object) -> Iterator[None]:
        raise ImportError("context import failed")
        yield

    calls = 0

    def workload(_state: object) -> object:
        nonlocal calls
        calls += 1
        if stage == "warmup" and calls == 1:
            raise ImportError("warmup import failed")
        if stage == "workload":
            raise ImportError("workload import failed")
        return {"ok": True}

    tested = replace(
        definition,
        setup=(fail_import if stage == "setup" else lambda _params, _seed: None),
        workload=workload,
        postprocess=(
            fail_import
            if stage == "postprocess"
            else lambda _state, output: BenchmarkOutput(value=output)
        ),
        measurement_context=(failing_context if stage == "context" else None),
    )
    result = runner._measure_in_process(
        tested,
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=1 if stage == "warmup" else 0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "error"
    assert "ImportError" in (result.error or "")


def test_measurement_context_receives_workload_error() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )
    received: list[type[BaseException] | None] = []

    class RecordingContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            received.append(exc_type)
            return False

    def workload(_state: object) -> object:
        raise RuntimeError("workload failed")

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=workload,
            measurement_context=lambda _state: RecordingContext(),
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "error"
    assert received == [RuntimeError]


def test_measurement_context_exit_error_is_a_case_error() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    class FailingExitContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            raise RuntimeError("context exit failed")

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=lambda _state: BenchmarkOutput(value={"ok": True}),
            postprocess=None,
            measurement_context=lambda _state: FailingExitContext(),
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "error"
    assert result.error == "RuntimeError: context exit failed"


def test_measurement_context_cannot_suppress_a_benchmark_error() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    @contextmanager
    def suppressing_context(_state: object) -> Iterator[None]:
        try:
            yield
        except RuntimeError:
            return

    def workload(_state: object) -> object:
        raise RuntimeError("workload failed")

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=workload,
            measurement_context=suppressing_context,
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "error"
    assert result.error == "RuntimeError: workload failed"


def test_measurement_context_cannot_suppress_base_exception() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    class SuppressingContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            return True

    def workload(_state: object) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner._measure_in_process(
            replace(
                definition,
                setup=lambda _parameters, _seed: None,
                workload=workload,
                measurement_context=lambda _state: SuppressingContext(),
            ),
            spec=definition.spec(seed=0),
            seed=0,
            mode="warm",
            samples=1,
            warmup=0,
            target_ns=0,
            disable_gc=False,
        )


def test_measurement_context_receives_and_does_not_swallow_base_exception() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )
    received: list[type[BaseException] | None] = []

    class RecordingContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            received.append(exc_type)
            return False

    def workload(_state: object) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner._measure_in_process(
            replace(
                definition,
                setup=lambda _parameters, _seed: None,
                workload=workload,
                measurement_context=lambda _state: RecordingContext(),
            ),
            spec=definition.spec(seed=0),
            seed=0,
            mode="warm",
            samples=1,
            warmup=0,
            target_ns=0,
            disable_gc=False,
        )

    assert received == [KeyboardInterrupt]


def test_measurement_context_preserves_primary_and_teardown_errors() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    class FailingExitContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            raise RuntimeError("teardown failed")

    def workload(_state: object) -> object:
        raise ValueError("workload failed")

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=workload,
            measurement_context=lambda _state: FailingExitContext(),
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "error"
    assert result.error == (
        "ValueError: workload failed; while handling: RuntimeError: teardown failed"
    )


def test_measurement_context_teardown_cannot_mask_base_exception() -> None:
    definition = next(
        item for item in case_definitions() if item.case_id == "core.concat_recipe.parts_10"
    )

    class FailingExitContext:
        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object,
        ) -> bool:
            raise RuntimeError("teardown failed")

    def workload(_state: object) -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt) as exc_info:
        runner._measure_in_process(
            replace(
                definition,
                setup=lambda _parameters, _seed: None,
                workload=workload,
                measurement_context=lambda _state: FailingExitContext(),
            ),
            spec=definition.spec(seed=0),
            seed=0,
            mode="warm",
            samples=1,
            warmup=0,
            target_ns=0,
            disable_gc=False,
        )

    assert exc_info.value.__notes__ == [
        "measurement context teardown also failed: RuntimeError: teardown failed"
    ]


def test_case_output_rejects_non_tuple_and_duplicate_metric_names() -> None:
    metric = Metric(
        name="value",
        kind="gauge",
        unit="count",
        phase="measure",
        scope="test",
        value=1,
    )
    with pytest.raises(TypeError, match="tuple"):
        BenchmarkOutput(
            value=None,
            metrics={"value": 1},  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="tuple"):
        BenchmarkOutput(
            value=None,
            metrics=[metric],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="一意"):
        BenchmarkOutput(
            value=None,
            metrics=(metric, replace(metric, phase="settle")),
        )


def test_warm_samples_preserve_an_earlier_hard_contract_failure() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    calls = 0

    def workload(_state: object) -> BenchmarkOutput:
        nonlocal calls
        calls += 1
        contract = evaluate_contract(
            contract_id="synthetic.across-samples",
            severity="hard",
            actual=calls > 1,
            comparator="eq",
            limit=True,
            reason="all outer samples must pass",
        )
        return BenchmarkOutput(
            value={"stable": True},
            metrics=(
                Metric(
                    name="stable",
                    kind="gauge",
                    unit="count",
                    phase="measure",
                    scope="test",
                    value=1,
                ),
            ),
            contracts=(contract,),
        )

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=workload,
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=3,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "contract-failure"
    assert result.contracts[0].passed is False


def test_measurement_context_wraps_warmup_samples_and_postprocess() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    events: list[str] = []
    state = {"inside": False}

    @contextmanager
    def measurement_context(_state: object) -> Iterator[None]:
        events.append("enter")
        state["inside"] = True
        try:
            yield
        finally:
            state["inside"] = False
            events.append("exit")

    def workload(_state: object) -> object:
        assert state["inside"] is True
        events.append("workload")
        return {"stable": True}

    def postprocess(_state: object, output: object) -> BenchmarkOutput:
        assert state["inside"] is True
        events.append("postprocess")
        return BenchmarkOutput(value=output)

    result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: state,
            workload=workload,
            postprocess=postprocess,
            measurement_context=measurement_context,
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=2,
        warmup=1,
        target_ns=0,
        disable_gc=False,
    )

    assert result.status == "ok", result.error
    assert events == [
        "enter",
        "workload",
        "workload",
        "postprocess",
        "workload",
        "postprocess",
        "exit",
    ]
    assert state["inside"] is False


def test_warm_samples_reject_semantic_or_typed_metric_drift() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    calls = 0

    def changing_output(_state: object) -> BenchmarkOutput:
        nonlocal calls
        calls += 1
        return BenchmarkOutput(value={"sample": calls})

    checksum_result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=changing_output,
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=2,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )
    assert checksum_result.status == "error"
    assert "different output checksums" in (checksum_result.error or "")

    calls = 0

    def changing_metric(_state: object) -> BenchmarkOutput:
        nonlocal calls
        calls += 1
        return BenchmarkOutput(
            value={"stable": True},
            metrics=(
                Metric(
                    name="changing",
                    kind="gauge",
                    unit="count",
                    phase="measure",
                    scope="test",
                    value=calls,
                ),
            ),
        )

    metric_result = runner._measure_in_process(
        replace(
            definition,
            setup=lambda _parameters, _seed: None,
            workload=changing_metric,
        ),
        spec=definition.spec(seed=0),
        seed=0,
        mode="warm",
        samples=2,
        warmup=0,
        target_ns=0,
        disable_gc=False,
    )
    assert metric_result.status == "error"
    assert "typed metrics changed" in (metric_result.error or "")


def test_slider_interactive_target_is_a_hard_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from grafix.devtools.benchmarks import mp_draw_benchmark

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

    output = runner._workload_mp_slider_churn({"frames": 1, "frame_interval_s": 0.0})
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
    from grafix.devtools.benchmarks import mp_draw_benchmark

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

    output = runner._workload_mp_draw({"repeats": 1, "steady_frames": 4, "heavy_iterations": 1_000})
    metric_names = {metric.name for metric in output.metrics}

    assert "cases.light.mp_to_sync_steady_ratio" in metric_names
    assert "cases.light.sync_n1.startup_ms.median" in metric_names
    assert "cases.light.mp_n2.startup_ms.median" in metric_names


def test_renderer_cases_separate_static_offsets_from_animated_topology() -> None:
    static_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = {
        metric.name: metric.value
        for metric in runner._workload_animated_renderer(static_state).metrics
    }
    animated = {
        metric.name: metric.value
        for metric in runner._workload_animated_renderer(animated_state).metrics
    }

    assert static["index_builds"] == 1
    assert static["full_uploads"] == 1
    assert static["vertex_only_uploads"] == 3
    assert animated["index_builds"] == 4
    assert animated["full_uploads"] == 4
    assert animated["vertex_only_uploads"] == 0


def test_concat_checksum_tracks_leaf_order_not_parenthesization() -> None:
    leaves = tuple(Geometry.create("leaf", params={"index": index}) for index in range(3))
    left = (leaves[0] + leaves[1]) + leaves[2]
    right = leaves[0] + (leaves[1] + leaves[2])
    reordered = leaves[1] + (leaves[0] + leaves[2])

    assert canonical_checksum(left) == canonical_checksum(right)
    assert canonical_checksum(left) != canonical_checksum(reordered)


def test_canonical_checksum_rejects_unknown_or_nondeterministic_values() -> None:
    @dataclass
    class ArbitraryRecord:
        value: int

    invalid_values = (
        object(),
        ArbitraryRecord(1),
        {1: "non-string-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        np.asarray([object()], dtype=object),
        (
            np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
            np.asarray([0, 1], dtype=np.int32),
        ),
        np.asarray([(1, 2)], dtype=[("x", "i4"), ("y", "i4")]),
        np.longdouble("0.5"),
        np.clongdouble("0.5+0.25j"),
        (1, 2),
    )

    for value in invalid_values:
        with pytest.raises((TypeError, ValueError)):
            canonical_checksum(value)


def test_canonical_checksum_rejects_bytes_subclasses() -> None:
    class MisleadingBytes(bytes):
        def hex(self, *args: object, **kwargs: object) -> str:
            del args, kwargs
            return "00"

    with pytest.raises(TypeError, match="unsupported benchmark checksum value"):
        canonical_checksum(MisleadingBytes(b"abc"))


def test_canonical_checksum_normalizes_supported_numpy_scalars() -> None:
    assert canonical_checksum({"value": np.int64(3)}) == canonical_checksum({"value": 3})
    assert canonical_checksum({"value": np.float32(0.5)}) == canonical_checksum({"value": 0.5})


def test_canonical_checksum_type_tags_cannot_collide_with_user_mappings() -> None:
    array = np.asarray([1.0], dtype=np.float32)

    assert canonical_checksum(b"value") != canonical_checksum(
        {"$grafix_checksum_type": "bytes", "hex": b"value".hex()}
    )
    assert canonical_checksum(array) != canonical_checksum(
        {
            "$grafix_checksum_type": "ndarray",
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        }
    )


def test_canonical_checksum_mapping_is_independent_of_insertion_order() -> None:
    assert canonical_checksum({"a": 1, "b": 2}) == canonical_checksum({"b": 2, "a": 1})


def test_canonical_checksum_does_not_collapse_tuple_into_json_array() -> None:
    with pytest.raises(TypeError, match="unsupported benchmark checksum value"):
        canonical_checksum((1, 2))


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

    result = runner._measure_in_process(
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

    result = runner._measure_in_process(
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
    static_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = runner._workload_animated_renderer(static_state)
    animated = runner._workload_animated_renderer(animated_state)
    static_metrics = {metric.name: metric.value for metric in static.metrics}
    animated_metrics = {metric.name: metric.value for metric in animated.metrics}

    assert static_metrics["index_builds"] != animated_metrics["index_builds"]
    assert canonical_checksum(static.value) == canonical_checksum(animated.value)
    assert static_metrics["full_vertex_upload_bytes"] > 0
    assert static_metrics["vertex_only_upload_bytes"] > 0


def test_case_source_hash_includes_transitive_fixture_source(tmp_path: Path) -> None:
    support = tmp_path / "fixture.py"
    support.write_text("VALUE = 1\n", encoding="utf-8")

    def implementation() -> None:
        return None

    first = make_case_spec(
        case_id="case",
        version=1,
        label="case",
        category="test",
        suite="test",
        fixture="fixture",
        parameters={},
        seed=0,
        implementation=implementation,
        support_source_files=(support,),
    )
    support.write_text("VALUE = 2\n", encoding="utf-8")
    second = make_case_spec(
        case_id="case",
        version=1,
        label="case",
        category="test",
        suite="test",
        fixture="fixture",
        parameters={},
        seed=0,
        implementation=implementation,
        support_source_files=(support,),
    )

    assert first.source_sha256 != second.source_sha256
    assert first.compatibility_key != second.compatibility_key


def test_case_source_hash_rejects_uninspectable_implementation() -> None:
    dynamic = eval(compile("lambda: 1", "<dynamic-benchmark>", "eval"))

    with pytest.raises(ValueError, match="implementation source"):
        make_case_spec(
            case_id="case",
            version=1,
            label="case",
            category="test",
            suite="test",
            fixture="fixture",
            parameters={},
            seed=0,
            implementation=dynamic,
        )


def test_case_source_hash_rejects_missing_support_source(tmp_path: Path) -> None:
    def implementation() -> None:
        return None

    with pytest.raises(FileNotFoundError):
        make_case_spec(
            case_id="case",
            version=1,
            label="case",
            category="test",
            suite="test",
            fixture="fixture",
            parameters={},
            seed=0,
            implementation=implementation,
            support_source_files=(tmp_path / "missing.py",),
        )


def test_environment_fingerprint_uses_effective_child_overrides() -> None:
    fingerprint = collect_environment_fingerprint(
        environment_overrides={
            "PYTHONHASHSEED": "0",
            "NUMBA_CACHE_DIR": "<isolated-empty>",
        }
    )

    assert fingerprint.values["environment"]["PYTHONHASHSEED"] == "0"
    assert fingerprint.values["environment"]["NUMBA_CACHE_DIR"] == "<isolated-empty>"


def test_source_identity_hashes_untracked_files_from_repository_root(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    nested = repository / "src" / "package"
    nested.mkdir(parents=True)
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Grafix Test",
            "-c",
            "user.email=grafix@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=repository,
        check=True,
    )
    untracked = repository / "outside-nested.txt"
    untracked.write_text("first\n", encoding="utf-8")
    first = collect_source_identity(root=nested)
    untracked.write_text("second\n", encoding="utf-8")
    second = collect_source_identity(root=nested)

    assert first.dirty is True
    assert second.dirty is True
    assert first.diff_sha256 != second.diff_sha256
