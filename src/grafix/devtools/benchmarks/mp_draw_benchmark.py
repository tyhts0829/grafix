"""mp-draw の起動・first result・steady throughput を sync と比較する。"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from grafix.core.atomic_write import atomic_write_text
from grafix.core.geometry import Geometry
from grafix.core.scene import normalize_scene
from grafix.interactive.runtime.mp_draw import MpDraw

_RESULT_TIMEOUT_S = 30.0


def light_draw(_t: float) -> Geometry:
    """Queue/dispatch overhead を見るための最小 draw。"""

    return Geometry.create(op="concat")


def heavy_draw(t: float, *, iterations: int = 100_000) -> Geometry:
    """約1フレーム分のCPU workを行う決定的draw。"""

    value = int(float(t) * 1_000.0) & 0xFFFFFFFF
    for index in range(max(1, int(iterations))):
        value = ((value * 1_664_525) + (index ^ 1_013_904_223)) & 0xFFFFFFFF
    if value < 0:  # pragma: no cover - loop が消去されないことを明示する到達不能分岐
        raise AssertionError(value)
    return Geometry.create(op="concat")


def run_mp_draw_benchmarks(
    *,
    repeats: int,
    steady_frames: int,
    heavy_iterations: int,
    n_worker: int = 4,
) -> dict[str, Any]:
    """light/heavy drawをsync 1本とMpDraw worker群で比較する。"""

    repeat_count = max(1, int(repeats))
    frame_count = max(int(n_worker), int(steady_frames))
    worker_count = max(2, int(n_worker))
    cases: dict[str, Any] = {}

    for case_id, draw in (
        ("light", light_draw),
        (
            "heavy",
            partial(heavy_draw, iterations=int(heavy_iterations)),
        ),
    ):
        sync_samples = [
            _measure_sync(draw, steady_frames=frame_count) for _ in range(repeat_count)
        ]
        mp_samples = [
            _measure_mp(
                draw,
                n_worker=worker_count,
                steady_frames=frame_count,
            )
            for _ in range(repeat_count)
        ]
        sync_summary = _summarize_mode(sync_samples)
        mp_summary = _summarize_mode(mp_samples)
        sync_fps = float(sync_summary["steady_latest_fps"]["median"])
        mp_fps = float(mp_summary["steady_latest_fps"]["median"])
        cases[case_id] = {
            "sync_n1": sync_summary,
            f"mp_n{worker_count}": mp_summary,
            "mp_to_sync_steady_ratio": 0.0 if sync_fps <= 0.0 else mp_fps / sync_fps,
        }

    total_samples_ms = [
        float(sample["startup_ms"] + sample["first_result_ms"] + sample["steady_ms"])
        for case in cases.values()
        for mode_name, mode in case.items()
        if str(mode_name).startswith(("sync_", "mp_")) and isinstance(mode, dict)
        for sample in mode["samples"]
    ]
    total = _summarize(total_samples_ms)
    return {
        "id": "mp_draw_n_worker",
        "label": "MpDraw sync n=1 vs multiprocessing",
        "category": "system",
        "status": "ok",
        "mean_ms": total["mean"],
        "median_ms": total["median"],
        "p95_ms": total["p95"],
        "n": total["n"],
        "output": {
            "steady_frames": frame_count,
            "heavy_iterations": int(heavy_iterations),
            "n_worker": worker_count,
            "measurement_scope": "draw + normalize_scene (realize excluded)",
        },
        "cases": cases,
    }


def _measure_sync(draw: Any, *, steady_frames: int) -> dict[str, float | int]:
    first_started = time.perf_counter_ns()
    normalize_scene(draw(0.0))
    first_ns = time.perf_counter_ns() - first_started

    steady_started = time.perf_counter_ns()
    for frame in range(int(steady_frames)):
        normalize_scene(draw(float(frame + 1)))
    steady_ns = time.perf_counter_ns() - steady_started
    return {
        "startup_ms": 0.0,
        "first_result_ms": first_ns / 1_000_000.0,
        "steady_ms": steady_ns / 1_000_000.0,
        "steady_latest_fps": float(steady_frames) * 1_000_000_000.0 / steady_ns,
        "submitted_frames": int(steady_frames),
        "completed_results": int(steady_frames),
    }


def _measure_mp(
    draw: Any,
    *,
    n_worker: int,
    steady_frames: int,
) -> dict[str, float | int]:
    startup_started = time.perf_counter_ns()
    mp_draw = MpDraw(draw, n_worker=int(n_worker))
    startup_ns = time.perf_counter_ns() - startup_started
    try:
        first_started = time.perf_counter_ns()
        mp_draw.submit(t=0.0, snapshot_revision=0, snapshot={})
        _wait_for_completed(mp_draw, target=1)
        first_ns = time.perf_counter_ns() - first_started

        baseline = mp_draw.completed_result_count
        submitted = 0
        steady_started = time.perf_counter_ns()
        deadline = time.monotonic() + _RESULT_TIMEOUT_S
        while mp_draw.completed_result_count - baseline < int(steady_frames):
            mp_draw.poll_latest()
            completed = mp_draw.completed_result_count - baseline
            while (
                submitted < int(steady_frames)
                and submitted - completed < int(n_worker)
            ):
                mp_draw.submit(
                    t=float(submitted + 1),
                    snapshot_revision=0,
                    snapshot={},
                )
                submitted += 1
                completed = mp_draw.completed_result_count - baseline
            if time.monotonic() >= deadline:
                raise TimeoutError("mp-draw steady result timeout")
            if mp_draw.completed_result_count - baseline == completed:
                time.sleep(0.0002)
        steady_ns = time.perf_counter_ns() - steady_started
        completed = mp_draw.completed_result_count - baseline
        return {
            "startup_ms": startup_ns / 1_000_000.0,
            "first_result_ms": first_ns / 1_000_000.0,
            "steady_ms": steady_ns / 1_000_000.0,
            "steady_latest_fps": float(completed) * 1_000_000_000.0 / steady_ns,
            "submitted_frames": submitted,
            "completed_results": completed,
        }
    finally:
        mp_draw.close()


def _wait_for_completed(mp_draw: MpDraw, *, target: int) -> None:
    deadline = time.monotonic() + _RESULT_TIMEOUT_S
    while mp_draw.completed_result_count < int(target):
        mp_draw.poll_latest()
        if time.monotonic() >= deadline:
            raise TimeoutError("mp-draw first result timeout")
        time.sleep(0.0002)


def _summarize_mode(samples: list[dict[str, float | int]]) -> dict[str, Any]:
    return {
        "startup_ms": _summarize([float(sample["startup_ms"]) for sample in samples]),
        "first_result_ms": _summarize(
            [float(sample["first_result_ms"]) for sample in samples]
        ),
        "steady_ms": _summarize([float(sample["steady_ms"]) for sample in samples]),
        "steady_latest_fps": _summarize(
            [float(sample["steady_latest_fps"]) for sample in samples]
        ),
        "samples": samples,
    }


def _summarize(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "n": 0}
    p95_index = min(len(ordered) - 1, max(0, int(0.95 * len(ordered))))
    return {
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95": ordered[p95_index],
        "n": len(ordered),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grafix mp-draw-benchmark")
    parser.add_argument(
        "--out",
        default="data/output/benchmarks/mp_draw_n_worker.json",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--steady-frames", type=int, default=48)
    parser.add_argument("--heavy-iterations", type=int, default=100_000)
    parser.add_argument("--n-worker", type=int, default=4)
    args = parser.parse_args(argv)

    result = run_mp_draw_benchmarks(
        repeats=int(args.repeats),
        steady_frames=int(args.steady_frames),
        heavy_iterations=int(args.heavy_iterations),
        n_worker=int(args.n_worker),
    )
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "benchmark": result,
    }
    out = Path(args.out).expanduser().resolve()
    atomic_write_text(out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"[grafix-bench] wrote: {out}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["heavy_draw", "light_draw", "main", "run_mp_draw_benchmarks"]
