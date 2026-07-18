from __future__ import annotations

import json
from typing import Any, cast

import pytest

from grafix.core.geometry import Geometry
from grafix.core.layer import Layer, LayerStyleDefaults
from grafix.core.parameters import ParamStore
from grafix.core.pipeline import realize_scene
from grafix.core.realize import RealizeSession
from grafix.interactive.runtime.mp_draw import DrawResult
from grafix.interactive.runtime.perf import PerfCollector
from grafix.interactive.runtime.scene_runner import SceneRunner


def test_profiler_collects_bounded_operation_layer_and_cache_snapshot() -> None:
    perf = PerfCollector(
        enabled=True,
        console_output=False,
        top_n=2,
        max_series=4,
    )
    geometry = Geometry.create("polygon", params={"n_sides": 5})
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)

    with RealizeSession(profiler=perf) as session:
        with perf.frame():
            realize_scene(
                lambda _t: Layer(geometry, site_id="ink", name="Ink"),
                0.0,
                defaults,
                session=session,
            )
        with perf.frame():
            realize_scene(
                lambda _t: Layer(geometry, site_id="ink", name="Ink"),
                1.0,
                defaults,
                session=session,
            )

    snapshot = perf.snapshot()
    assert snapshot.frame_count == 2
    assert len(snapshot.operations) <= 2
    assert len(snapshot.layers) <= 2
    assert snapshot.operations[0].name == "polygon"
    assert snapshot.layers[0].name == "Ink"
    assert snapshot.cache_hits >= 1
    assert snapshot.cache_misses >= 1
    assert snapshot.cache_hit_rate == pytest.approx(0.5)


def test_profiler_snapshot_discards_unbounded_dynamic_series() -> None:
    perf = PerfCollector(
        enabled=True,
        console_output=False,
        top_n=3,
        max_series=4,
    )

    with perf.frame():
        for index in range(100):
            perf.record_operation(f"dynamic-{index}", index + 1)
            perf.record_layer(f"layer-{index}", index + 1)

    snapshot = perf.snapshot()
    assert len(snapshot.operations) <= 3
    assert len(snapshot.layers) <= 3
    assert all(item.name != "<other>" for item in snapshot.operations)
    assert all(item.name != "<other>" for item in snapshot.layers)


def test_realize_cache_eviction_is_forwarded_to_profiler() -> None:
    perf = PerfCollector(enabled=True, console_output=False)
    defaults = LayerStyleDefaults(color=(0.0, 0.0, 0.0), thickness=0.01)
    first = Geometry.create("polygon", params={"n_sides": 5})
    second = Geometry.create("polygon", params={"n_sides": 6})

    with RealizeSession(max_cache_bytes=100, profiler=perf) as session:
        with perf.frame():
            realize_scene(lambda _t: first, 0.0, defaults, session=session)
        with perf.frame():
            realize_scene(lambda _t: second, 1.0, defaults, session=session)

    assert perf.snapshot().cache_evictions >= 1


class _LaggedMpDraw:
    def __init__(self, result: DrawResult) -> None:
        self._result = result
        self._published = False

    def submit(self, **_kwargs: object) -> None:
        return

    def poll_latest(self) -> DrawResult | None:
        if self._published:
            return None
        self._published = True
        return self._result

    def latest_successful_result(self) -> DrawResult:
        return self._result

    def begin_epoch(self, epoch: int | None = None) -> int:
        return 0 if epoch is None else int(epoch)

    def close(self) -> None:
        return


def test_scene_runner_records_worker_submit_to_result_lag() -> None:
    perf = PerfCollector(enabled=True, console_output=False)
    geometry = Geometry.create("polygon", params={"n_sides": 5})
    result = DrawResult(
        frame_id=1,
        layers=[Layer(geometry, site_id="ink", name="Ink")],
        records=[],
        labels=[],
        worker_lag_ms=24.5,
    )
    runner = SceneRunner(lambda _t: geometry, perf=perf, n_worker=0)
    runner._mp_draw = cast(Any, _LaggedMpDraw(result))
    try:
        with perf.frame():
            runner.run(
                0.0,
                store=ParamStore(),
                cc_snapshot=None,
                defaults=LayerStyleDefaults(
                    color=(0.0, 0.0, 0.0),
                    thickness=0.01,
                ),
                recording=False,
            )
    finally:
        runner.close()

    snapshot = perf.snapshot()
    assert snapshot.worker_lag_samples == 1
    assert snapshot.worker_lag_ms == pytest.approx(24.5)


def test_structured_json_trace_works_without_gui(tmp_path) -> None:
    trace_path = tmp_path / "performance.jsonl"
    perf = PerfCollector(
        enabled=True,
        console_output=False,
        print_every=1,
        trace_path=trace_path,
    )

    with perf.frame():
        with perf.section("scene"):
            pass
        perf.record_operation("relax", 2_000_000)
        perf.record_layer("Ink", 3_000_000)
        perf.record_cache(hits=3, misses=1, evictions=2)
        perf.record_worker_lag(12.5)
        perf.record_preview_result(
            requested_revision=8,
            presented_revision=6,
            fresh=False,
        )

    [payload] = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert payload["schema"] == "grafix.performance.trace.v1"
    assert payload["frame_index"] == 1
    assert payload["operations"][0]["name"] == "relax"
    assert payload["layers"][0]["name"] == "Ink"
    assert payload["cache"] == {
        "evictions": 2,
        "hit_rate": 0.75,
        "hits": 3,
        "misses": 1,
    }
    assert payload["worker"]["average_lag_ms"] == pytest.approx(12.5)
    assert payload["preview"] == {
        "average_revision_lag": 2.0,
        "fresh_result_ratio": 0.0,
        "fresh_results": 0,
        "max_consecutive_stale_frames": 1,
        "max_revision_lag": 2,
        "revision_lag_samples": 1,
        "samples": 1,
    }


def test_profiler_tracks_preview_freshness_revision_lag_and_stale_streaks() -> None:
    perf = PerfCollector(enabled=True, console_output=False)

    with perf.frame():
        perf.record_preview_result(
            requested_revision=10,
            presented_revision=8,
            fresh=False,
        )
        perf.record_preview_result(
            requested_revision=11,
            presented_revision=9,
            fresh=False,
        )
        perf.record_preview_result(
            requested_revision=12,
            presented_revision=12,
            fresh=True,
        )

    snapshot = perf.snapshot()
    assert snapshot.preview_samples == 3
    assert snapshot.preview_fresh_results == 1
    assert snapshot.preview_fresh_result_ratio == pytest.approx(1.0 / 3.0)
    assert snapshot.preview_max_consecutive_stale_frames == 2
    assert snapshot.preview_revision_lag_samples == 3
    assert snapshot.preview_revision_lag == pytest.approx(4.0 / 3.0)
    assert snapshot.preview_revision_lag_max == 2


def test_profiler_stale_streak_resets_with_the_aggregation_window() -> None:
    perf = PerfCollector(
        enabled=True,
        console_output=False,
        print_every=2,
    )

    for revision in (1, 2):
        with perf.frame():
            perf.record_preview_result(
                requested_revision=revision,
                presented_revision=0,
                fresh=False,
            )

    assert perf.snapshot().preview_max_consecutive_stale_frames == 2

    with perf.frame():
        perf.record_preview_result(
            requested_revision=3,
            presented_revision=0,
            fresh=False,
        )

    snapshot = perf.snapshot()
    assert snapshot.frame_count == 1
    assert snapshot.preview_max_consecutive_stale_frames == 1


def test_trace_path_enables_collection_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    trace_path = tmp_path / "headless.jsonl"
    monkeypatch.delenv("GRAFIX_PERF", raising=False)
    monkeypatch.setenv("GRAFIX_PERF_TRACE", str(trace_path))
    monkeypatch.setenv("GRAFIX_PERF_EVERY", "1")

    perf = PerfCollector.from_env()
    with perf.frame():
        perf.record_operation("circle", 1_000)

    assert perf.enabled is True
    assert json.loads(trace_path.read_text())["operations"][0]["name"] == "circle"
