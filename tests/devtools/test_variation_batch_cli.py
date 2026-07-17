from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from grafix import RenderOptions
from grafix.__main__ import main as grafix_main
from grafix.devtools import variation_batch


def _draw(_t: float) -> None:
    return None


class _Session:
    def __init__(self, draw: object, **kwargs: object) -> None:
        self.draw = draw
        self.kwargs = kwargs

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None


def test_cli_passes_headless_inputs_and_reports_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sessions: list[_Session] = []
    calls: list[dict[str, object]] = []

    def make_session(draw: object, **kwargs: object) -> _Session:
        session = _Session(draw, **kwargs)
        sessions.append(session)
        return session

    def fake_batch(session: object, output_dir: Path, **kwargs: object):
        calls.append({"session": session, "output_dir": Path(output_dir), **kwargs})
        return SimpleNamespace(
            output_directory=tmp_path / "variations",
            contact_sheet_path=tmp_path / "variations" / "contact-sheet.svg",
            summary_path=tmp_path / "variations" / "summary.json",
            success_count=2,
            failure_count=1,
            items=(
                SimpleNamespace(
                    status="failed",
                    variation_name="Broken",
                    error_type="RuntimeError",
                    error_message="boom",
                ),
            ),
        )

    monkeypatch.setattr(variation_batch, "_resolve_callable", lambda _spec: _draw)
    monkeypatch.setattr(variation_batch, "RenderSession", make_session)
    monkeypatch.setattr(variation_batch, "render_variation_batch", fake_batch)

    code = variation_batch.main(
        [
            "--callable",
            "example:draw",
            "--out-dir",
            str(tmp_path),
            "--canvas",
            "120",
            "90",
            "--parameter-source",
            "recovery",
            "--run-id",
            "take-a",
            "--name",
            "Quiet",
            "--name",
            "Broken",
            "--thumbnail-format",
            "svg",
            "--thumbnail-size",
            "240",
            "180",
            "--columns",
            "2",
        ]
    )

    assert code == 1
    assert sessions[0].draw is _draw
    assert sessions[0].kwargs["parameter_source"] == "recovery"
    assert sessions[0].kwargs["run_id"] == "take-a"
    options = sessions[0].kwargs["options"]
    assert isinstance(options, RenderOptions)
    assert options.canvas_size == (120, 90)
    assert calls[0]["variation_names"] == ("Quiet", "Broken")
    assert calls[0]["thumbnail_format"] == "svg"
    assert calls[0]["thumbnail_size"] == (240, 180)
    assert calls[0]["columns"] == 2
    output = capsys.readouterr()
    assert "2 succeeded, 1 failed" in output.out
    assert "Broken: RuntimeError: boom" in output.err


def test_cli_defaults_to_saved_parameters_and_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions: list[_Session] = []
    calls: list[dict[str, object]] = []

    def make_session(draw: object, **kwargs: object) -> _Session:
        session = _Session(draw, **kwargs)
        sessions.append(session)
        return session

    def fake_batch(_session: object, _output_dir: Path, **kwargs: object):
        calls.append(kwargs)
        return SimpleNamespace(
            output_directory=tmp_path / "variations",
            contact_sheet_path=tmp_path / "variations" / "contact-sheet.svg",
            summary_path=tmp_path / "variations" / "summary.json",
            success_count=1,
            failure_count=0,
            items=(),
        )

    monkeypatch.setattr(variation_batch, "_resolve_callable", lambda _spec: _draw)
    monkeypatch.setattr(variation_batch, "RenderSession", make_session)
    monkeypatch.setattr(variation_batch, "render_variation_batch", fake_batch)

    assert variation_batch.main(
        ["--callable", "example:draw", "--out-dir", str(tmp_path)]
    ) == 0
    assert sessions[0].kwargs["parameter_source"] == "saved"
    assert calls[0]["overwrite"] is False


def test_root_cli_delegates_variations_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegated: list[list[str]] = []
    monkeypatch.setattr(
        variation_batch,
        "main",
        lambda argv: delegated.append(list(argv)) or 7,
    )

    assert grafix_main(["variations", "--", "--callable", "example:draw"]) == 7
    assert delegated == [["--callable", "example:draw"]]
