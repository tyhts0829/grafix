from __future__ import annotations

from grafix.devtools.benchmarks.mp_draw_benchmark import run_mp_draw_benchmarks


def test_mp_draw_benchmark_reports_sync_and_worker_metrics() -> None:
    result = run_mp_draw_benchmarks(
        repeats=1,
        steady_frames=4,
        heavy_iterations=1_000,
        n_worker=2,
    )

    assert result["status"] == "ok"
    assert result["output"] == {
        "steady_frames": 4,
        "heavy_iterations": 1_000,
        "n_worker": 2,
        "measurement_scope": "draw + normalize_scene (realize excluded)",
    }
    for case_id in ("light", "heavy"):
        case = result["cases"][case_id]
        assert case["mp_to_sync_steady_ratio"] > 0.0
        for mode_name in ("sync_n1", "mp_n2"):
            mode = case[mode_name]
            assert mode["startup_ms"]["median"] >= 0.0
            assert mode["first_result_ms"]["median"] > 0.0
            assert mode["steady_latest_fps"]["median"] > 0.0
            assert mode["samples"][0]["submitted_frames"] == 4
            assert mode["samples"][0]["completed_results"] == 4
