from __future__ import annotations

from grafix.devtools.benchmarks.runner import (
    case_definitions,
    run_case_isolated,
)
from grafix.devtools.benchmarks.schema import Metric


def test_effect_case_runs_in_isolated_process_with_exact_geometry_checksum() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "effect.translate.line_small"
    )
    result = run_case_isolated(
        definition,
        seed=0,
        mode="warm",
        samples=1,
        warmup=0,
        target_ns=0,
        disable_gc=False,
        timeout_seconds=30.0,
    )

    assert result.status == "ok", result.error
    assert result.checksum_kind == "realized_geometry_exact_v1"
    assert result.checksum
    metrics = {metric.name: metric.value for metric in result.metrics}
    assert metrics["n_vertices"] == 2


def test_heavy_effect_registry_splits_draft_and_final_quality_cases() -> None:
    definitions = {definition.case_id: definition for definition in case_definitions()}

    for effect_name in ("growth", "metaball", "reaction_diffusion"):
        draft_id = f"effect.{effect_name}.draft.rings_2"
        final_id = f"effect.{effect_name}.final.rings_2"
        assert definitions[draft_id].parameters["quality"] == "draft"
        assert definitions[final_id].parameters["quality"] == "final"
        assert definitions[draft_id].parameters["expected_checksum"]
        assert definitions[final_id].parameters["expected_checksum"]
        assert "quality-draft" in definitions[draft_id].tags
        assert "quality-final" in definitions[final_id].tags
        assert f"effect.{effect_name}.rings_2" not in definitions


def test_growth_quality_cases_emit_typed_work_metrics_and_checksum_contracts() -> None:
    definitions = {definition.case_id: definition for definition in case_definitions()}
    draft = definitions["effect.growth.draft.rings_2"]
    final = definitions["effect.growth.final.rings_2"]

    draft_output = draft.workload(draft.setup(dict(draft.parameters), 0))
    draft_metrics = {metric.name: metric for metric in draft_output.metrics}
    assert all(isinstance(metric, Metric) for metric in draft_output.metrics)
    assert draft_metrics["quality"].value == "draft"
    assert draft_metrics["work.iterations.requested"].value == 250
    assert draft_metrics["work.iterations.effective"].value == 32
    assert draft_metrics["n_vertices"].kind == "counter"
    assert draft_metrics["n_lines"].kind == "counter"
    assert len(draft_output.contracts) == 1
    assert draft_output.contracts[0].contract_id == "effect.growth.draft_checksum"
    assert draft_output.contracts[0].severity == "hard"
    assert draft_output.contracts[0].passed

    final_output = final.workload(final.setup(dict(final.parameters), 0))
    final_metrics = {metric.name: metric for metric in final_output.metrics}
    assert final_metrics["quality"].value == "final"
    assert final_metrics["work.iterations.requested"].value == 250
    assert final_metrics["work.iterations.effective"].value == 250
    assert len(final_output.contracts) == 1
    assert final_output.contracts[0].contract_id == "effect.growth.final_checksum"
    assert final_output.contracts[0].severity == "hard"
    assert final_output.contracts[0].passed
