from __future__ import annotations

from grafix.devtools.benchmarks.runner import (
    case_definitions,
    run_case_isolated,
)


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
    assert result.metrics["n_vertices"] == 2
