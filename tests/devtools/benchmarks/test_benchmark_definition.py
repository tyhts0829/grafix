from __future__ import annotations

from pathlib import Path

import pytest

from grafix.devtools.benchmarks.definition import make_case_spec
from grafix.devtools.benchmarks.catalog import (
    case_definitions,
)


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
