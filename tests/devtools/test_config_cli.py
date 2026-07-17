"""``python -m grafix config validate/show`` の exit code と表示を検証する。"""

from __future__ import annotations

from pathlib import Path

import pytest

from grafix.__main__ import main as grafix_main
from grafix.core.runtime_config import set_config_path
from grafix.devtools import config_cli


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_config_path(None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    yield
    set_config_path(None)


def test_config_validate_returns_zero_for_valid_config(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "settings" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "paths:\n  output_dir: ./renders\n",
        encoding="utf-8",
    )

    assert config_cli.main(["validate", "--config", str(config_path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == f"config valid: {config_path}\n"


def test_config_validate_returns_two_and_suggests_typo(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "export:\n  png:\n    scael: 2.0\n",
        encoding="utf-8",
    )

    assert grafix_main(["config", "validate", str(config_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "config invalid:" in captured.err
    assert "export.png.scael" in captured.err
    assert "export.png.scale" in captured.err


def test_config_show_includes_source_effective_value_and_resolved_path(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "settings" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "paths:\n  output_dir: ../renders\n",
        encoding="utf-8",
    )

    assert config_cli.main(["show", str(config_path)]) == 0
    captured = capsys.readouterr()
    expected_resolved = tmp_path / "renders"
    assert captured.err == ""
    assert f"config_source: {config_path}\n" in captured.out
    assert "paths.output_dir:\n" in captured.out
    assert f"  source: {config_path}\n" in captured.out
    assert "  effective_value: '../renders'\n" in captured.out
    assert f"  resolved_path: {expected_resolved}\n" in captured.out


def test_config_validate_returns_two_for_non_finite_value(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "export:\n  png:\n    scale: .nan\n",
        encoding="utf-8",
    )

    assert config_cli.main(["validate", str(config_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "finite" in captured.err
