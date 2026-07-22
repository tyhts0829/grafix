from __future__ import annotations

from grafix.devtools.benchmarks import system_benchmark


def test_small_workloads_report_deterministic_output_and_cache_stats() -> None:
    signature_a = system_benchmark._geometry_signature_workload(iterations=5)
    signature_b = system_benchmark._geometry_signature_workload(iterations=5)
    assert signature_a == signature_b

    identity_geometry = system_benchmark._identity_geometry(points=50)
    identity = system_benchmark._rotate_scale_identity_workload(
        identity_geometry,
        iterations=3,
    )
    assert identity["output"]["n_vertices"] == 50
    assert identity["output"]["operations"] == 6
    assert identity["output"]["input_reuses"] == 6
    assert identity["output"]["input_object_reused"] is True

    site = system_benchmark._cached_site_id_workload(
        iterations=5,
        code=test_small_workloads_report_deterministic_output_and_cache_stats.__code__,
    )
    assert site["cache"] == {
        "hits": 4,
        "misses": 1,
        "evictions": 0,
        "entries": 1,
        "bytes": 0,
    }

    inputs = system_benchmark._concat_inputs(parts=3, vertices_per_part=2)
    concat = system_benchmark._concat_workload(inputs)
    assert concat["output"]["n_vertices"] == 6
    assert concat["output"]["n_lines"] == 3

    strokes = system_benchmark._random_strokes(count=8, seed=11)
    assert system_benchmark._gcode_ordering_workload(
        strokes
    ) == system_benchmark._gcode_ordering_workload(strokes)


def test_cold_import_runs_in_fresh_process_and_reports_rss() -> None:
    result = system_benchmark._cold_import_benchmark(repeats=1)

    assert result["status"] == "ok"
    assert result["n"] == 1
    assert result["median_ms"] >= 0.0
    assert result["peak_rss_bytes"] > 0
    assert result["output"] == {"module": "grafix"}
