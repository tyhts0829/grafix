from __future__ import annotations

import pytest

from grafix.devtools.benchmarks import (
    catalog,
    parameter_hotpath_benchmark,
)
from grafix.devtools.benchmarks.catalog import (
    case_definitions,
    select_case_definitions,
)


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
    assert parameter_hotpath_benchmark.benchmark_draw in provenance.support_implementations
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


def test_system_cases_with_internal_samples_run_once_per_isolated_measurement() -> None:
    self_sampling_ids = {
        definition.case_id
        for definition in case_definitions()
        if definition.self_sampling
        and definition.case_id
        in {
            "micro.asemic",
            "system.cold_import",
            "system.parameter_snapshot_model",
        }
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


def test_catalog_rejects_duplicate_case_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = catalog.effect_benchmark.case_definitions()[0]
    monkeypatch.setattr(
        catalog.effect_benchmark,
        "case_definitions",
        lambda: (duplicate, duplicate),
    )

    with pytest.raises(ValueError, match=f"duplicate benchmark case: {duplicate.case_id}"):
        catalog.case_definitions()
