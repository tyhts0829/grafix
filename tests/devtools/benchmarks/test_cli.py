from __future__ import annotations

import json
from pathlib import Path

import pytest

from grafix.__main__ import main as grafix_main
from grafix.devtools.benchmarks import cli


def test_list_outputs_registry_json(capsys) -> None:
    assert cli.main(["list", "--suite", "smoke", "--json"]) == 0
    entries = json.loads(capsys.readouterr().out)

    assert entries
    assert all("smoke" in entry["selectable_suites"] for entry in entries)
    assert all(entry["id"] for entry in entries)


def test_top_level_cli_dispatches_benchmark_actions(capsys) -> None:
    assert grafix_main(["benchmark", "list", "--suite", "smoke"]) == 0
    assert "core.concat_recipe.parts_10" in capsys.readouterr().out


def test_run_and_report_cli_create_schema_v3_artifacts(tmp_path: Path) -> None:
    assert (
        cli.main(
            [
                "run",
                "--case",
                "core.concat_recipe.parts_10",
                "--profile",
                "smoke",
                "--samples",
                "1",
                "--warmup",
                "0",
                "--target-ms",
                "0",
                "--run-id",
                "test-run",
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )
    run_path = tmp_path / "runs" / "test-run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["cases"][0]["samples"]
    assert payload["cases"][0]["checksum"]

    assert cli.main(["report", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "report.html").is_file()
    assert (tmp_path / "warnings.json").is_file()

    assert (
        cli.main(
            [
                "run",
                "--case",
                "core.concat_recipe.parts_10",
                "--run-id",
                "test-run",
                "--out",
                str(tmp_path),
            ]
        )
        == 2
    )
    assert (
        cli.main(
            [
                "run",
                "--case",
                "core.concat_recipe.parts_10",
                "--mode",
                "process-cold",
                "--warmup",
                "1",
                "--out",
                str(tmp_path),
            ]
        )
        == 2
    )


def test_cli_rejects_ignored_or_duplicate_selection_arguments(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        cli.main(
            [
                "run",
                "--suite",
                "smoke",
                "--case",
                "core.concat_recipe.parts_10",
            ]
        )

    assert (
        cli.main(
            [
                "run",
                "--case",
                "core.concat_recipe.parts_10",
                "--case",
                "core.concat_recipe.parts_10",
                "--out",
                str(tmp_path),
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "arguments",
    (
        ["run", "--case", ""],
        ["run", "--case", ","],
        ["run", "--suite", ""],
        ["run", "--target-ms", "nan"],
        ["run", "--target-ms", "inf"],
        ["run", "--target-ms=-1e-10"],
        ["run", "--timeout", "nan"],
        ["run", "--timeout", "inf"],
    ),
)
def test_run_rejects_empty_selectors_and_non_finite_values(
    arguments: list[str],
) -> None:
    assert cli.main(arguments) == 2


def test_effective_child_environment_forces_deterministic_hash_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONHASHSEED", "random")

    environment = cli._effective_child_environment(mode="warm")
    assert environment["PYTHONHASHSEED"] == "0"
    assert environment["PYTHONPYCACHEPREFIX"] == "<isolated-empty>"
