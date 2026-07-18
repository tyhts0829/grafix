from __future__ import annotations

from grafix.devtools.benchmarks.mp_draw_benchmark import (
    run_mp_draw_benchmarks,
    run_mp_slider_churn_benchmarks,
)


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


def test_mp_slider_churn_benchmark_checks_progress_revision_and_checksum() -> None:
    result = run_mp_slider_churn_benchmarks(
        frames=24,
        frame_interval_s=0.005,
    )

    assert result["status"] == "ok"
    assert result["output"]["n_worker"] == 1
    assert result["output"]["frames"] == 24
    assert result["output"]["progress_contract_met"] is True
    for case_id in ("light_translate", "light_scale"):
        case = result["cases"][case_id]
        stable = case["stable"]
        changing = case["changing"]
        assert stable["snapshot_broadcasts"] == 1
        assert stable["checksum_matches_sync"] is True
        assert changing["fresh_result_ratio"] >= 0.5
        assert changing["max_consecutive_stale_frames"] <= 6
        assert changing["result_revisions_monotonic"] is True
        assert changing["last_result_revision"] == changing["final_input_revision"]
        assert changing["checksum_matches_sync"] is True
        assert changing["rejected_tasks"] == 0
        assert changing["progress_contract_met"] is True
