from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from grafix.devtools import doctor


def _ok_check(name: str) -> doctor.DoctorCheck:
    return doctor.DoctorCheck(name=name, status="ok", summary="ok")


def test_run_doctor_returns_structured_warnings_for_absent_optional_commands(
    tmp_path: Path,
    monkeypatch,
) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")
    output = tmp_path / "not-created-output"
    monkeypatch.setattr(doctor, "_check_gl", lambda: _ok_check("gl"))
    monkeypatch.setattr(doctor, "_check_midi", lambda: _ok_check("midi"))
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)

    report = doctor.run_doctor(output_dir=output, font_path=font)

    by_name = {check.name: check for check in report.checks}
    assert tuple(by_name) == ("gl", "resvg", "ffmpeg", "midi", "font", "output_write")
    assert by_name["resvg"].status == "warning"
    assert by_name["ffmpeg"].status == "warning"
    assert by_name["output_write"].status == "ok"
    assert report.healthy is True
    assert report.to_dict()["healthy"] is True
    assert not output.exists()


def test_output_write_failure_makes_report_unhealthy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")
    output_file = tmp_path / "not-a-directory"
    output_file.write_text("x", encoding="utf-8")
    monkeypatch.setattr(doctor, "_check_gl", lambda: _ok_check("gl"))
    monkeypatch.setattr(doctor, "_check_midi", lambda: _ok_check("midi"))

    report = doctor.run_doctor(output_dir=output_file, font_path=font)

    assert report.healthy is False
    assert report.checks[-1].name == "output_write"
    assert report.checks[-1].status == "error"


def test_midi_native_failure_is_isolated_as_warning(monkeypatch) -> None:
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=-6,
            stdout="",
            stderr="native backend aborted",
        ),
    )

    result = doctor._check_midi()

    assert result.status == "warning"
    assert result.details == ("native backend aborted",)


def test_doctor_cli_json_uses_report_exit_status(monkeypatch, capsys) -> None:
    report = doctor.DoctorReport(
        checks=(doctor.DoctorCheck("gl", "warning", "not available"),)
    )
    monkeypatch.setattr(doctor, "run_doctor", lambda: report)

    assert doctor.main(["--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "healthy": True,
        "checks": [
            {
                "name": "gl",
                "status": "warning",
                "summary": "not available",
                "details": [],
            }
        ],
    }


@pytest.mark.parametrize(
    ("kwargs", "match"),
    (
        ({"name": 1}, "name"),
        ({"status": 1}, "status"),
        ({"summary": None}, "summary"),
        ({"details": ["detail"]}, "details"),
        ({"details": (1,)}, r"details\[0\]"),
    ),
)
def test_doctor_check_rejects_implicit_conversions(
    kwargs: dict[str, object],
    match: str,
) -> None:
    arguments: dict[str, object] = {
        "name": "gl",
        "status": "ok",
        "summary": "available",
    }
    arguments.update(kwargs)

    with pytest.raises(TypeError, match=match):
        doctor.DoctorCheck(**cast(Any, arguments))


def test_doctor_check_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        doctor.DoctorCheck(
            name="gl",
            status=cast(Any, "unknown"),
            summary="available",
        )


@pytest.mark.parametrize(
    "checks",
    (
        [],
        (object(),),
    ),
)
def test_doctor_report_requires_doctor_check_tuple(checks: object) -> None:
    with pytest.raises(TypeError, match="checks"):
        doctor.DoctorReport(checks=cast(Any, checks))
