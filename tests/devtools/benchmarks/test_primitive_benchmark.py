from __future__ import annotations

import numpy as np
import pytest

from grafix.devtools.benchmarks.primitive_benchmark import (
    PrimitiveBenchmarkState,
)
from grafix.devtools.benchmarks.runner import (
    case_definitions,
    run_case_isolated,
    select_case_definitions,
)
from grafix.devtools.benchmarks.schema import Metric

_BUILTIN_PRIMITIVES = {
    "arc",
    "asemic",
    "bezier",
    "circle",
    "ellipse",
    "grid",
    "laplace_field_grid",
    "line",
    "lissajous",
    "lsystem",
    "polygon",
    "polyhedron",
    "polyline",
    "rect",
    "sphere",
    "spiral",
    "spline",
    "text",
    "torus",
    "wave",
}
_COMMON_METRICS = {
    "primitive",
    "quality",
    "n_vertices",
    "n_lines",
    "closed_lines",
    "output_bytes",
    "diagnostics",
}


def test_primitive_suite_covers_every_builtin_with_direct_actual_work() -> None:
    definitions = select_case_definitions(suites=("primitives",))

    assert {definition.parameters["primitive"] for definition in definitions} == (
        _BUILTIN_PRIMITIVES
    )
    assert len(definitions) == 25
    for definition in definitions:
        assert definition.category == "primitive"
        assert definition.suite == "primitives"
        assert "primitives" in definition.selectable_suites
        assert {"actual-work", "direct-raw", "exact-checksum"} <= set(
            definition.tags
        )
        assert definition.postprocess is not None

    cold_ids = {
        definition.case_id
        for definition in select_case_definitions(suites=("primitive-cold",))
    }
    assert cold_ids == {
        "primitive.asemic.cold_unique_bezier",
        "primitive.text.cold_unique_high_quality",
    }


@pytest.mark.parametrize(
    "case_id",
    tuple(
        definition.case_id
        for definition in select_case_definitions(suites=("primitives",))
    ),
)
def test_each_primitive_direct_case_emits_common_metrics_and_hard_contracts(
    case_id: str,
) -> None:
    definition = next(
        definition
        for definition in select_case_definitions(suites=("primitives",))
        if definition.case_id == case_id
    )
    primitive = str(definition.parameters["primitive"])
    state = definition.setup(dict(definition.parameters), 20260719)
    assert isinstance(state, PrimitiveBenchmarkState)
    assert state.raw_function.__module__ == f"grafix.core.primitives.{primitive}"
    assert state.raw_function.__name__ == primitive

    raw_output = definition.workload(state)
    assert isinstance(raw_output, tuple)
    assert len(raw_output) == 2
    coords, offsets = raw_output
    assert isinstance(coords, np.ndarray) and coords.flags.writeable
    assert isinstance(offsets, np.ndarray) and offsets.flags.writeable

    assert definition.postprocess is not None
    output = definition.postprocess(state, raw_output)
    assert output.value.coords.dtype == np.float32
    assert output.value.offsets.dtype == np.int32
    assert all(isinstance(metric, Metric) for metric in output.metrics)
    metrics = {metric.name: metric for metric in output.metrics}
    assert _COMMON_METRICS <= set(metrics)
    assert metrics["n_vertices"].kind == "counter"
    assert metrics["n_vertices"].unit == "count"
    assert metrics["output_bytes"].kind == "counter"
    assert metrics["output_bytes"].unit == "bytes"
    assert output.contracts
    assert all(contract.severity == "hard" for contract in output.contracts)
    assert all(contract.passed for contract in output.contracts)
    assert any(
        contract.contract_id == f"primitive.{primitive}.exact_checksum"
        for contract in output.contracts
    )


def test_primitive_case_runs_warm_in_isolated_process() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "primitive.arc.segments_512"
    )
    result = run_case_isolated(
        definition,
        seed=20260719,
        mode="warm",
        samples=2,
        warmup=1,
        target_ns=0,
        disable_gc=False,
        timeout_seconds=30.0,
    )

    assert result.status == "ok", result.error
    assert result.checksum_kind == "realized_geometry_exact_v1"
    assert result.checksum
    assert len(result.samples) == 2
    assert result.contracts
    assert all(contract.passed for contract in result.contracts)
    metrics = {metric.name: metric.value for metric in result.metrics}
    assert metrics["n_vertices"] == 513
    assert metrics["n_lines"] == 1
    assert metrics["diagnostics"] == 0
