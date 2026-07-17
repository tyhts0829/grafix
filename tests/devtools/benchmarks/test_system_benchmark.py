from __future__ import annotations

from grafix.devtools.benchmarks import system_benchmark


def test_small_workloads_report_deterministic_output_and_cache_stats() -> None:
    soak = system_benchmark._animated_soak(frames=12, sides=48)
    cache = soak["cache"]
    assert soak["output"]["unique_geometry_ids"] == 12
    assert cache["hits"] == soak["output"]["static_base_hits"] == 11
    assert cache["misses"] == 13
    assert cache["evictions"] == 11
    assert cache["entries"] > 0
    assert 0 < cache["bytes"] <= cache["budget_bytes"]

    end_to_end = system_benchmark._draw_realize_indices(grid_size=3)
    assert end_to_end["output"]["draw_lines"] > 0
    assert end_to_end["output"]["index_count"] > 0
    assert end_to_end["cache"]["misses"] == 2

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

    store = system_benchmark._parameter_store(rows=12)
    model = system_benchmark._parameter_snapshot_model_workload(store, frames=5)
    assert model["output"]["rows"] == 12
    assert model["output"]["snapshot_entries"] == 12
    assert model["output"]["render_calls"] == 5
    assert model["output"]["model_builds"] == 1
    assert model["cache"]["hits"] == 4
    assert model["cache"]["misses"] == 1

    renderer_geometry = system_benchmark._renderer_geometry(polylines=100)
    renderer = system_benchmark._renderer_cache_workload(
        renderer_geometry,
        frames=5,
    )
    assert renderer["output"]["n_lines"] == 100
    assert renderer["output"]["index_builds"] == 1
    assert renderer["output"]["uploads"] == 2
    assert renderer["cache"]["hits"] == 3
    assert renderer["cache"]["misses"] == 2
    assert renderer["cache"]["entries"] == 1
    assert 0 < renderer["cache"]["bytes"] <= renderer["cache"]["budget_bytes"]

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
