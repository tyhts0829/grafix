from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grafix.devtools import export_frame


def _draw(_t: float) -> None:
    return None


def test_main_passes_run_id_to_explicit_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(export_frame, "_resolve_callable", lambda _spec: _draw)
    monkeypatch.setattr(
        export_frame,
        "Export",
        lambda draw, **kwargs: calls.append({"draw": draw, **kwargs}),
    )

    output_path = tmp_path / "frame.png"
    code = export_frame.main(
        [
            "--callable",
            "example:draw",
            "--t",
            "1.25",
            "--canvas",
            "100",
            "200",
            "--out",
            str(output_path),
            "--run-id",
            "take-a",
        ]
    )

    assert code == 0
    assert calls == [
        {
            "draw": _draw,
            "t": 1.25,
            "fmt": "png",
            "path": output_path,
            "canvas_size": (100, 200),
            "run_id": "take-a",
        }
    ]


def test_main_passes_run_id_to_every_batch_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(export_frame, "_resolve_callable", lambda _spec: _draw)
    monkeypatch.setattr(
        export_frame,
        "default_png_output_path",
        lambda draw, *, run_id, canvas_size: Path("base.png"),
    )
    monkeypatch.setattr(
        export_frame,
        "Export",
        lambda draw, **kwargs: calls.append({"draw": draw, **kwargs}),
    )

    output_dir = tmp_path / "frames"
    code = export_frame.main(
        [
            "--callable",
            "example:draw",
            "--t",
            "0",
            "2",
            "--out-dir",
            str(output_dir),
            "--run-id",
            "take-b",
        ]
    )

    assert code == 0
    assert [call["path"] for call in calls] == [
        output_dir / "base_f001.png",
        output_dir / "base_f002.png",
    ]
    assert [call["t"] for call in calls] == [0.0, 2.0]
    assert all(call["run_id"] == "take-b" for call in calls)
