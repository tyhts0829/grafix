"""``python -m grafix describe`` の出力契約を検証する。"""

from __future__ import annotations

from grafix.__main__ import main as grafix_main
from grafix.devtools import describe_op


def test_describe_cli_prints_registry_metadata(capsys) -> None:
    assert describe_op.main(["primitive", "line"]) == 0

    output = capsys.readouterr().out
    assert "name: line\n" in output
    assert "kind: primitive\n" in output
    assert "n_inputs: 0\n" in output
    assert "source:" in output and "line.py\n" in output
    assert "defaults:\n" in output
    assert "  length: 1.0\n" in output
    assert "meta:\n" in output
    assert "  length: kind='float'" in output
    assert "doc:\n" in output
    assert "正規化済み引数から線分を生成する。" in output


def test_describe_is_routed_from_package_cli(capsys) -> None:
    assert grafix_main(["describe", "effect", "scale"]) == 0
    output = capsys.readouterr().out
    assert "name: scale\n" in output
    assert "kind: effect\n" in output
    assert "n_inputs: 1\n" in output


def test_describe_cli_reports_unknown_name(capsys) -> None:
    assert describe_op.main(["effect", "does_not_exist"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "未登録の effect: 'does_not_exist'\n"
