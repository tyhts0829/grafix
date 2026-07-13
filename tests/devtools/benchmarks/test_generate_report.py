from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from grafix.devtools.benchmarks import BENCHMARK_SCHEMA_VERSION
from grafix.devtools.benchmarks.generate_report import (
    build_timeseries_report,
    render_report_html,
)


def _write_run(
    runs_dir: Path,
    *,
    run_id: str,
    clip_mean_ms: float,
    warp_result: dict[str, Any],
    schema_version: int = BENCHMARK_SCHEMA_VERSION,
) -> None:
    payload = {
        "schema_version": schema_version,
        "meta": {"run_id": run_id, "created_at": run_id, "git_sha": "abc"},
        "scenarios": [
            {
                "id": "binary_mask",
                "label": "binary mask",
                "description": "source + mask",
                "tags": ["binary", "mask-grid"],
                "n_inputs": 2,
                "inputs": [
                    {
                        "n_vertices": 2,
                        "n_lines": 1,
                        "closed_lines": 0,
                        "all_closed": False,
                    },
                    {
                        "n_vertices": 5,
                        "n_lines": 1,
                        "closed_lines": 1,
                        "all_closed": True,
                    },
                ],
            }
        ],
        "effects": [
            {
                "name": "clip",
                "n_inputs": 2,
                "results": {
                    "binary_mask": {
                        "status": "ok",
                        "mean_ms": clip_mean_ms,
                        "median_ms": clip_mean_ms,
                        "p95_ms": clip_mean_ms * 1.2,
                        "cold": {
                            "status": "ok",
                            "median_ms": clip_mean_ms * 10,
                            "peak_rss_bytes": 64 * 1024 * 1024,
                        },
                        "output": {
                            "n_vertices": 2,
                            "n_lines": 1,
                            "bytes": 32,
                        },
                    }
                },
            },
            {
                "name": "warp",
                "n_inputs": 2,
                "results": {"binary_mask": warp_result},
            },
        ],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_system_run(runs_dir: Path, *, run_id: str) -> None:
    payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "meta": {
            "run_id": run_id,
            "created_at": run_id,
            "benchmark_mode": "system",
        },
        "scenarios": [],
        "effects": [],
        "system": {
            "profile": "short",
            "results": {
                "realize_session_animated_soak": {
                    "id": "realize_session_animated_soak",
                    "label": "RealizeSession animated soak",
                    "category": "system",
                    "status": "ok",
                    "median_ms": 1.2,
                    "p95_ms": 1.5,
                    "peak_rss_bytes": 32 * 1024 * 1024,
                    "output": {"frames": 10, "n_vertices": 5},
                    "cache": {
                        "hits": 7,
                        "misses": 3,
                        "evictions": 1,
                        "entries": 2,
                        "bytes": 512,
                    },
                }
            },
        },
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_report_reads_schema_v2_scenarios_and_keeps_case_errors(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(
        runs_dir,
        run_id="20260713_010000",
        clip_mean_ms=1.0,
        warp_result={"status": "error", "error": "example"},
    )
    _write_run(
        runs_dir,
        run_id="20260713_020000",
        clip_mean_ms=0.5,
        warp_result={"status": "ok", "mean_ms": 2.0},
    )
    _write_run(
        runs_dir,
        run_id="20260713_030000",
        clip_mean_ms=99.0,
        warp_result={"status": "ok", "mean_ms": 99.0},
        schema_version=BENCHMARK_SCHEMA_VERSION - 1,
    )
    _write_system_run(runs_dir, run_id="20260713_040000")

    report = build_timeseries_report(runs_dir=runs_dir)

    assert report["meta"]["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert report["meta"]["runs"] == 3
    assert report["meta"]["effect_runs"] == 2
    assert report["meta"]["system_runs"] == 1
    assert len(report["runs"]) == 2
    assert report["meta"]["last_system_run"] == "20260713_040000"
    assert report["scenarios"] == [{"id": "binary_mask", "label": "binary mask"}]

    chart = report["charts"][0]
    assert chart["scenario_id"] == "binary_mask"
    datasets = {dataset["label"]: dataset["data"] for dataset in chart["datasets"]}
    assert datasets["clip"] == [1.0, 0.5]
    assert datasets["warp"] == [None, 2.0]

    system = report["system"]
    assert system["run_id"] == "20260713_040000"
    assert system["profile"] == "short"
    assert system["rows"][0]["cache"]["hits"] == 7

    html = render_report_html(report)
    assert "Scenario: binary mask" in html
    assert "input[0]: verts=2 lines=1" in html
    assert "input[1]: verts=5 lines=1" in html
    assert "peak RSS MiB" in html
    assert "64.0" in html
    assert "2 / 1 / 0.0" in html
    assert "System / micro benchmarks" in html
    assert "RealizeSession animated soak" in html
    assert "hits=7" in html
    assert "frames=10" in html
    assert "32.0" in html
