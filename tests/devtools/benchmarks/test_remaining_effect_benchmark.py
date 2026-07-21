from __future__ import annotations

import numpy as np
import pytest

from grafix.core import builtins
from grafix.core.effect_registry import effect_registry
from grafix.core.preview_quality import current_preview_quality
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks import (
    remaining_effect_benchmark as remaining_benchmark,
)
from grafix.devtools.benchmarks.remaining_effect_benchmark import (
    RemainingEffectBenchmarkState,
    remaining_effect_benchmark_cases,
    target_remaining_effect_names,
)
from grafix.devtools.benchmarks.runner import (
    case_definitions,
    geometry_checksum,
    run_case_isolated,
    select_case_definitions,
)
from grafix.devtools.benchmarks.schema import Metric

_EXCLUDED = {"fill", "subdivide", "scale", "rotate", "translate"}
_COMMON_METRICS = {
    "effect",
    "quality",
    "input_vertices",
    "input_lines",
    "n_vertices",
    "n_lines",
    "closed_lines",
    "output_bytes",
    "actual_work",
    "diagnostics",
    "effect_source_sha256",
    "util_source_sha256",
}
_EXPECTED_LAYOUT_KEYS = {
    "coords_dtype",
    "offsets_dtype",
    "coords_strides",
    "offsets_strides",
    "coords_c_contiguous",
    "offsets_c_contiguous",
    "coords_f_contiguous",
    "offsets_f_contiguous",
    "coords_writeable",
    "offsets_writeable",
    "coords_owndata",
    "offsets_owndata",
    "coords_aligned",
    "offsets_aligned",
}
_EXPECTED_ALIAS_KEYS = {
    "output_is_input",
    "coords_is_input",
    "offsets_is_input",
    "coords_alias_input",
    "offsets_alias_input",
}


def test_remaining_effect_case_arguments_are_owned_and_read_only() -> None:
    case = remaining_effect_benchmark_cases()[0]
    with pytest.raises(TypeError):
        case.arguments["activate"] = False  # type: ignore[index]

    parameters = case.parameters()
    parameters["arguments"]["activate"] = False
    assert case.parameters()["arguments"].get("activate") is not False


def test_remaining_effect_suite_covers_exact_builtin_target_set() -> None:
    builtins.ensure_builtin_effects_registered()
    expected = {
        name for name in effect_registry if builtins.ensure_builtin_effect_registered(name)
    } - _EXCLUDED
    definitions = select_case_definitions(suites=("effects-remaining",))

    assert target_remaining_effect_names() == expected
    assert {definition.parameters["effect"] for definition in definitions} == expected
    assert len(definitions) == 40
    assert len({definition.case_id for definition in definitions}) == 40
    for definition in definitions:
        assert definition.category == "effect"
        assert definition.suite == "effects-remaining"
        assert "effects-remaining" in definition.selectable_suites
        assert {"actual-work", "direct-evaluator", "exact-checksum"} <= set(definition.tags)
        assert definition.postprocess is not None
        assert definition.measurement_context is not None
        assert definition.parameters["expected_checksum"]
        assert definition.parameters["expected_diagnostics"] is not None
        assert definition.parameters["expected_warnings"] is not None
        assert definition.parameters["expected_layout"] is not None
        assert definition.parameters["expected_alias"] is not None
        assert set(definition.parameters["expected_layout"]) == _EXPECTED_LAYOUT_KEYS
        assert set(definition.parameters["expected_alias"]) == _EXPECTED_ALIAS_KEYS
        assert (
            definition.parameters["expected_alias"]["offsets_is_input"]
            is definition.parameters["expected_alias"]["offsets_alias_input"]
        )

    cases = remaining_effect_benchmark_cases()
    for heavy in ("growth", "metaball", "reaction_diffusion"):
        qualities = {case.quality for case in cases if case.effect == heavy}
        assert qualities == {"draft", "final"}

    cold_effects = {
        definition.parameters["effect"]
        for definition in select_case_definitions(suites=("effects-remaining-cold",))
    }
    assert cold_effects == {
        "boolean",
        "buffer",
        "clip",
        "mirror3d",
        "offset_curve",
        "partition",
    }
    jit_effects = {
        definition.parameters["effect"]
        for definition in select_case_definitions(suites=("effects-remaining-jit",))
    }
    assert {
        "collapse",
        "dash",
        "displace",
        "growth",
        "highpass",
        "isocontour",
        "lowpass",
        "metaball",
        "mirror",
        "pixelate",
        "reaction_diffusion",
        "relax",
        "repeat",
        "resample",
        "trim",
        "warp",
        "weave",
    } == jit_effects


def test_foundational_effect_fixtures_are_exact_and_deterministic() -> None:
    first_regions = remaining_benchmark._build_inputs(
        fixture="binary_regions",
        seed=20260719,
    )
    second_regions = remaining_benchmark._build_inputs(
        fixture="binary_regions",
        seed=0,
    )
    assert len(first_regions) == 2
    assert [value.coords.shape for value in first_regions] == [
        (3_074, 3),
        (2_049, 3),
    ]
    assert [value.offsets.tolist() for value in first_regions] == [
        [0, 2_049, 3_074],
        [0, 2_049],
    ]
    assert [geometry_checksum(value) for value in first_regions] == [
        geometry_checksum(value) for value in second_regions
    ]
    assert geometry_checksum(first_regions[0]) != geometry_checksum(first_regions[1])

    first_duplicates = remaining_benchmark._build_inputs(
        fixture="dedup_duplicates",
        seed=20260719,
    )[0]
    second_duplicates = remaining_benchmark._build_inputs(
        fixture="dedup_duplicates",
        seed=0,
    )[0]
    assert first_duplicates.coords.shape == (96_000, 3)
    assert first_duplicates.offsets.shape == (48_001,)
    assert geometry_checksum(first_duplicates) == geometry_checksum(second_duplicates)
    first_group = first_duplicates.coords[:8]
    assert np.all(first_group[[0, 3, 4, 7]] == first_group[0])
    assert np.all(first_group[[1, 2, 5, 6]] == first_group[1])


@pytest.mark.parametrize(
    ("case_id", "expected_metrics"),
    (
        (
            "effect.remaining.boolean.binary_regions",
            {
                "work.mode": "xor",
                "work.input_rings": 3,
                "work.output_rings": 3,
                "work.input_paths": 3,
                "work.output_paths": 3,
                "n_vertices": 4_819,
            },
        ),
        (
            "effect.remaining.deduplicate.dedup_duplicates",
            {
                "work.input_segments": 48_000,
                "work.output_segments": 12_000,
                "work.removed_segments": 36_000,
            },
        ),
        (
            "effect.remaining.offset_curve.many_lines",
            {
                "work.levels": 1,
                "work.generated_paths": 10_000,
                "work.input_paths": 5_000,
                "work.output_paths": 10_000,
                "n_vertices": 20_000,
                "n_lines": 10_000,
            },
        ),
        (
            "effect.remaining.offset_curve.polyline_long",
            {
                "work.levels": 1,
                "work.generated_paths": 2,
                "work.input_paths": 1,
                "work.output_paths": 2,
                "n_vertices": 57_078,
                "n_lines": 2,
            },
        ),
        (
            "effect.remaining.resample.polyline_spaced_long",
            {
                "work.step": 0.5,
                "work.resampled_vertices": 12_532,
                "n_vertices": 12_532,
                "n_lines": 1,
            },
        ),
        (
            "effect.remaining.resample.upsample.polyline_spaced_long",
            {
                "work.step": 0.1,
                "work.resampled_vertices": 62_656,
                "n_vertices": 62_656,
                "n_lines": 1,
            },
        ),
        (
            "effect.remaining.simplify.polyline_long",
            {
                "work.tolerance": 0.05,
                "work.removed_vertices": 49_897,
            },
        ),
    ),
)
def test_foundational_effect_direct_cases_pass_frozen_contracts(
    case_id: str,
    expected_metrics: dict[str, object],
) -> None:
    definition = next(
        value
        for value in select_case_definitions(suites=("effects-remaining",))
        if value.case_id == case_id
    )
    # frozen checksum は benchmark CLI の既定 seed=0 に対する契約。
    state = definition.setup(definition.materialize_parameters(), 0)
    assert isinstance(state, RemainingEffectBenchmarkState)
    assert definition.measurement_context is not None
    assert definition.postprocess is not None

    with definition.measurement_context(state):
        raw_output = definition.workload(state)
        output = definition.postprocess(state, raw_output)

    metrics = {metric.name: metric.value for metric in output.metrics}
    assert metrics["actual_work"] is True
    assert {name: metrics[name] for name in expected_metrics} == expected_metrics
    assert output.contracts
    assert all(contract.severity == "hard" for contract in output.contracts)
    assert all(contract.passed for contract in output.contracts)


@pytest.mark.parametrize(
    "case_id",
    (
        "effect.remaining.affine.polyline_long",
        "effect.remaining.displace.polyline_long",
        "effect.remaining.drop.many_lines",
        "effect.remaining.reaction_diffusion.draft.rings_medium",
        "effect.remaining.reaction_diffusion.final.rings_medium",
    ),
)
def test_remaining_effect_direct_cases_pass_frozen_hard_contracts(
    case_id: str,
) -> None:
    definition = next(
        value
        for value in select_case_definitions(suites=("effects-remaining",))
        if value.case_id == case_id
    )
    # frozen checksum は benchmark CLI の既定 seed=0 に対する契約。
    state = definition.setup(definition.materialize_parameters(), 0)
    assert isinstance(state, RemainingEffectBenchmarkState)
    assert definition.measurement_context is not None
    assert definition.postprocess is not None

    quality_before = current_preview_quality()
    with definition.measurement_context(state):
        assert current_preview_quality() == definition.parameters["quality"]
        raw_output = definition.workload(state)
        output = definition.postprocess(state, raw_output)
    assert current_preview_quality() == quality_before

    assert all(isinstance(metric, Metric) for metric in output.metrics)
    metrics = {metric.name: metric for metric in output.metrics}
    assert _COMMON_METRICS <= set(metrics)
    assert metrics["actual_work"].value is True
    assert len(str(metrics["effect_source_sha256"].value)) == 64
    assert len(str(metrics["util_source_sha256"].value)) == 64
    if case_id == "effect.remaining.reaction_diffusion.draft.rings_medium":
        assert metrics["work.steps.requested"].value == 800
        assert metrics["work.steps.effective"].value == 600
        assert metrics["work.grid_pitch.requested"].value == 0.8
        assert metrics["work.grid_pitch.effective"].value == 2.0077973938621607
    assert output.contracts
    assert all(contract.severity == "hard" for contract in output.contracts)
    assert all(contract.passed for contract in output.contracts)
    assert any(contract.contract_id.endswith(".baseline_checksum") for contract in output.contracts)
    assert any(
        contract.contract_id.endswith(".baseline_diagnostics") for contract in output.contracts
    )
    assert any(contract.contract_id.endswith(".baseline_alias") for contract in output.contracts)


def test_remaining_effect_case_runs_warm_in_isolated_process() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "effect.remaining.quantize.polyline_long"
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
    assert result.checksum == definition.parameters["expected_checksum"]
    assert len(result.samples) == 2
    assert result.contracts
    assert all(contract.passed for contract in result.contracts)
    metrics = {metric.name: metric.value for metric in result.metrics}
    assert metrics["effect"] == "quantize"
    assert metrics["n_vertices"] == 50_000
    assert metrics["actual_work"] is True


def test_benchmark_inputs_cannot_be_made_writeable() -> None:
    definition = next(
        value
        for value in select_case_definitions(suites=("effects-remaining",))
        if value.case_id == "effect.remaining.affine.polyline_long"
    )
    state = definition.setup(definition.materialize_parameters(), 20260719)
    assert isinstance(state, RemainingEffectBenchmarkState)
    assert definition.measurement_context is not None
    assert definition.postprocess is not None

    snapshot = remaining_benchmark._geometry_mutation_snapshot(state.inputs[0])
    with pytest.raises(ValueError):
        state.inputs[0].coords.setflags(write=True)
    with pytest.raises(ValueError):
        state.inputs[0].offsets.setflags(write=True)
    assert remaining_benchmark._geometry_mutation_snapshot(state.inputs[0]) == snapshot

    with definition.measurement_context(state):
        raw_output = definition.workload(state)
        output = definition.postprocess(state, raw_output)

    input_contract = next(
        contract
        for contract in output.contracts
        if contract.contract_id.endswith(".input_unchanged")
    )
    assert input_contract.passed is True


def test_input_snapshot_covers_bytes_shape_strides_and_all_flags() -> None:
    base = np.arange(24, dtype=np.float32).reshape(4, 6)
    snapshot = remaining_benchmark._array_mutation_snapshot(base)

    assert snapshot.dtype == base.dtype.str
    assert snapshot.shape == base.shape
    assert snapshot.strides == base.strides
    assert snapshot.c_contiguous is bool(base.flags.c_contiguous)
    assert snapshot.f_contiguous is bool(base.flags.f_contiguous)
    assert snapshot.writeable is bool(base.flags.writeable)
    assert snapshot.owndata is bool(base.flags.owndata)
    assert snapshot.aligned is bool(base.flags.aligned)
    assert snapshot.raw_bytes == base.tobytes(order="A")

    assert remaining_benchmark._array_mutation_snapshot(base[:, ::2]) != snapshot
    base.setflags(write=False)
    assert remaining_benchmark._array_mutation_snapshot(base) != snapshot

    raw = bytearray(1 + 4 * np.dtype(np.int32).itemsize)
    unaligned = np.ndarray((4,), dtype=np.int32, buffer=raw, offset=1)
    assert unaligned.flags.aligned is False
    assert remaining_benchmark._array_mutation_snapshot(unaligned).aligned is False


def test_alias_contract_distinguishes_same_object_from_view() -> None:
    definition = next(
        value
        for value in select_case_definitions(suites=("effects-remaining",))
        if value.case_id == "effect.remaining.affine.polyline_long"
    )
    state = definition.setup(definition.materialize_parameters(), 20260719)
    assert isinstance(state, RemainingEffectBenchmarkState)
    assert definition.measurement_context is not None
    assert definition.postprocess is not None

    with definition.measurement_context(state):
        raw_output = definition.workload(state)
        assert isinstance(raw_output, RealizedGeometry)
        view_output = RealizedGeometry(
            coords=raw_output.coords,
            offsets=raw_output.offsets.view(),
        )
        # Geometry checksum と shares_memory は同じでも object identity は異なる。
        assert geometry_checksum(view_output) == geometry_checksum(raw_output)
        alias = remaining_benchmark._alias_values(view_output, state.inputs)
        assert alias["offsets_alias_input"] is True
        assert alias["offsets_is_input"] is False
        output = definition.postprocess(state, view_output)

    alias_contract = next(
        contract
        for contract in output.contracts
        if contract.contract_id.endswith(".baseline_alias")
    )
    assert alias_contract.passed is False
