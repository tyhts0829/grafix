from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from grafix.core import atomic_write
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks import BENCHMARK_SCHEMA_VERSION
from grafix.devtools.benchmarks import effect_benchmark
from grafix.devtools.benchmarks import system_benchmark
from grafix.devtools.benchmarks.cases import BenchmarkCase


def _geometry(coords: list[list[float]], offsets: list[int]) -> RealizedGeometry:
    return RealizedGeometry(
        coords=np.asarray(coords, dtype=np.float32),
        offsets=np.asarray(offsets, dtype=np.int32),
    )


def _tiny_cases() -> list[BenchmarkCase]:
    source = _geometry(
        [[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [0, 2],
    )
    mask = _geometry(
        [
            [-1.0, -1.0, 0.0],
            [1.0, -1.0, 0.0],
            [1.0, 1.0, 0.0],
            [-1.0, 1.0, 0.0],
            [-1.0, -1.0, 0.0],
        ],
        [0, 5],
    )
    return [
        BenchmarkCase(
            case_id="tiny_unary",
            label="tiny unary",
            description="arity test",
            inputs=(source,),
            tags=("unary",),
        ),
        BenchmarkCase(
            case_id="tiny_binary",
            label="tiny binary",
            description="clip / warp arity test",
            inputs=(source, mask),
            tags=("binary", "mask-grid"),
        ),
    ]


def test_cases_for_arity_returns_only_matching_inputs() -> None:
    cases = _tiny_cases()

    assert [case.case_id for case in effect_benchmark._cases_for_arity(cases, n_inputs=1)] == [
        "tiny_unary"
    ]
    assert [case.case_id for case in effect_benchmark._cases_for_arity(cases, n_inputs=2)] == [
        "tiny_binary"
    ]


def test_main_benchmarks_clip_and_warp_with_binary_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        effect_benchmark,
        "build_default_cases",
        lambda *, seed: _tiny_cases(),
    )

    exit_code = effect_benchmark.main(
        [
            "--out",
            str(tmp_path),
            "--run-id",
            "20260713_010203",
            "--only",
            "clip,warp",
            "--repeats",
            "1",
            "--warmup",
            "0",
        ]
    )

    assert exit_code == 0
    result_path = tmp_path / "runs" / "20260713_010203.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert "cases" not in result

    scenarios = {scenario["id"]: scenario for scenario in result["scenarios"]}
    assert scenarios["tiny_unary"]["n_inputs"] == 1
    assert scenarios["tiny_binary"]["n_inputs"] == 2
    assert len(scenarios["tiny_binary"]["inputs"]) == 2

    effects = {effect["name"]: effect for effect in result["effects"]}
    assert set(effects) == {"clip", "warp"}
    for name in ("clip", "warp"):
        assert effects[name]["n_inputs"] == 2
        assert set(effects[name]["results"]) == {"tiny_binary"}
        measured = effects[name]["results"]["tiny_binary"]
        assert measured["status"] == "ok"
        assert measured["median_ms"] >= 0.0
        assert measured["p95_ms"] >= measured["median_ms"]
        assert measured["output"]["bytes"] > 0
        assert measured["cold"]["status"] == "ok"
        assert measured["cold"]["peak_rss_bytes"] > 0

    assert list(result_path.parent.glob(f".{result_path.name}.*.tmp")) == []


def test_atomic_json_replace_failure_keeps_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "run.json"
    destination.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_write.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        effect_benchmark._write_json_atomic(destination, {"new": True})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_summarize_reports_median_and_interpolated_p95() -> None:
    stats = effect_benchmark._summarize([1_000_000, 2_000_000, 3_000_000])

    assert stats.median_ms == 2.0
    assert stats.p95_ms == pytest.approx(2.9)


def test_system_cli_is_explicit_and_separate_from_effect_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_system = {
        "profile": "short",
        "results": {
            "example": {
                "id": "example",
                "status": "ok",
                "median_ms": 1.0,
                "p95_ms": 1.5,
                "peak_rss_bytes": 1024,
                "output": {"items": 1},
            }
        },
    }
    monkeypatch.setattr(
        system_benchmark,
        "run_system_benchmarks",
        lambda **_kwargs: expected_system,
    )

    def fail_effect_cases(*, seed: int) -> list[BenchmarkCase]:
        raise AssertionError(f"effect cases must not be built: {seed}")

    monkeypatch.setattr(effect_benchmark, "build_default_cases", fail_effect_cases)

    exit_code = effect_benchmark.main(
        [
            "--system",
            "--out",
            str(tmp_path),
            "--run-id",
            "20260713_040000",
            "--repeats",
            "1",
            "--warmup",
            "0",
        ]
    )

    assert exit_code == 0
    payload = json.loads((tmp_path / "runs" / "20260713_040000.json").read_text(encoding="utf-8"))
    assert payload["meta"]["benchmark_mode"] == "system"
    assert payload["meta"]["system_profile"] == "short"
    assert payload["scenarios"] == []
    assert payload["effects"] == []
    assert payload["system"] == expected_system
