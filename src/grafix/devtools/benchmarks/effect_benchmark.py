"""
どこで: `src/grafix/devtools/benchmarks/effect_benchmark.py`。
何を: `grafix.core.effects` の effect をケース別にベンチし、JSON を出力する。
なぜ: どの effect がどんな入力で遅いかを一覧・比較し、最適化の当たりを付けるため。
"""

from __future__ import annotations

import argparse
import gc
import json
import multiprocessing as mp
import pkgutil
import platform
import resource
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from grafix.core.atomic_write import atomic_text_writer
from grafix.core.effect_registry import effect_registry
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks import BENCHMARK_SCHEMA_VERSION
from grafix.devtools.benchmarks.cases import (
    BenchmarkCase,
    build_default_cases,
    describe_geometry,
)


@dataclass(frozen=True, slots=True)
class _BenchStats:
    mean_ms: float
    median_ms: float
    p95_ms: float
    stdev_ms: float
    min_ms: float
    max_ms: float
    n: int


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    out_root = Path(args.out).expanduser().resolve()
    run_id = _normalize_run_id(str(args.run_id))
    runs_dir = out_root / "runs"
    json_path = runs_dir / f"{run_id}.json"

    if bool(args.system) or bool(args.system_long):
        return _run_system_suite(args=args, out_root=out_root, json_path=json_path, run_id=run_id)

    cases = build_default_cases(seed=int(args.seed))
    if args.cases:
        only = {c.strip() for c in str(args.cases).split(",") if c.strip()}
        cases = [c for c in cases if c.case_id in only]

    if not cases:
        print("ケースが 0 件です。--cases を確認してください。")  # noqa: T201
        return 2

    import_errors = _import_builtin_effects()

    effects = _list_effects(extra=set(import_errors.keys()))
    if args.only:
        only = {s.strip() for s in str(args.only).split(",") if s.strip()}
        effects = [e for e in effects if e in only]
    if args.skip:
        skip = {s.strip() for s in str(args.skip).split(",") if s.strip()}
        effects = [e for e in effects if e not in skip]

    if not effects:
        print("effect が 0 件です。--only/--skip を確認してください。")  # noqa: T201
        return 2

    case_meta = []
    for c in cases:
        input_meta = [describe_geometry(geometry) for geometry in c.inputs]
        case_meta.append(
            {
                "id": c.case_id,
                "label": c.label,
                "description": c.description,
                "tags": list(c.tags),
                "n_inputs": c.n_inputs,
                "inputs": input_meta,
            }
        )

    meta: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "repeats": int(args.repeats),
        "warmup": int(args.warmup),
        "seed": int(args.seed),
        "out_dir": str(out_root),
        "json_filename": json_path.name,
    }
    if import_errors:
        meta["import_errors"] = dict(import_errors)
    git_sha = _try_git_sha()
    if git_sha is not None:
        meta["git_sha"] = git_sha

    results: dict[str, Any] = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "meta": meta,
        "scenarios": case_meta,
        "effects": [],
    }

    repeats = int(args.repeats)
    warmup = int(args.warmup)
    disable_gc = bool(args.disable_gc)
    cold_processes = max(0, int(args.cold_processes))

    for eff_name in effects:
        eff_entry: dict[str, Any] = {
            "name": eff_name,
            "module": f"grafix.core.effects.{eff_name}",
            "n_inputs": None,
            "params": {},
            "results": {},
        }

        if eff_name not in effect_registry:
            err = import_errors.get(eff_name, "import failed")
            eff_entry["import_error"] = f"module import failed: {err}"
            results["effects"].append(eff_entry)
            continue

        spec = effect_registry[eff_name]
        n_inputs = spec.n_inputs
        eff_entry["n_inputs"] = n_inputs
        eff_entry["params"] = _bench_params_for_effect(
            eff_name,
            defaults=spec.defaults,
        )
        func = spec.evaluator
        args_tuple = tuple(sorted(eff_entry["params"].items(), key=lambda kv: str(kv[0])))

        for case in _cases_for_arity(cases, n_inputs=n_inputs):
            res = _bench_one(
                func=func,
                inputs=case.inputs,
                args_tuple=args_tuple,
                warmup=warmup,
                repeats=repeats,
                disable_gc=disable_gc,
            )
            if cold_processes:
                res["cold"] = _bench_cold(
                    effect_name=eff_name,
                    inputs=case.inputs,
                    args_tuple=args_tuple,
                    repeats=cold_processes,
                )
            eff_entry["results"][case.case_id] = res

        results["effects"].append(eff_entry)

    _write_json_atomic(json_path, results)

    print(f"[grafix-bench] wrote: {json_path}")  # noqa: T201
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="grafix benchmark")
    p.add_argument(
        "--out",
        default="data/output/benchmarks",
        help="出力ルート（<out>/runs/<run_id>.json を作る）",
    )
    p.add_argument(
        "--run-id", default="", help="出力ファイル名（YYYYMMDD_HHMMSS。省略時は現在時刻）"
    )
    p.add_argument("--repeats", type=int, default=10, help="本計測の反復回数")
    p.add_argument("--warmup", type=int, default=2, help="ウォームアップ回数（JIT 除外用）")
    p.add_argument("--seed", type=int, default=0, help="ケース生成用 seed")
    p.add_argument("--only", default="", help="effect をカンマ区切りで指定（例: scale,rotate）")
    p.add_argument("--skip", default="", help="除外する effect をカンマ区切りで指定")
    p.add_argument("--cases", default="", help="ケース id をカンマ区切りで指定（例: ring_big）")
    p.add_argument(
        "--disable-gc",
        action="store_true",
        help="計測中の GC を無効化する（ノイズ低減。メモリ増に注意）",
    )
    p.add_argument(
        "--cold-processes",
        type=int,
        default=1,
        help="隔離 spawn process で測る first-call 回数（0 で無効）",
    )
    p.add_argument(
        "--system",
        action="store_true",
        help="通常の effect 計測を行わず、短い system/micro suite を計測する",
    )
    p.add_argument(
        "--system-long",
        action="store_true",
        help="長時間の system/micro suite を計測する（明示 opt-in）",
    )
    return p.parse_args(argv)


def _run_system_suite(
    *,
    args: argparse.Namespace,
    out_root: Path,
    json_path: Path,
    run_id: str,
) -> int:
    """effect計測とは分離したsystem/micro suiteを書き出す。"""

    from grafix.devtools.benchmarks.system_benchmark import run_system_benchmarks

    long = bool(args.system_long)
    meta: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "repeats": int(args.repeats),
        "warmup": int(args.warmup),
        "seed": int(args.seed),
        "out_dir": str(out_root),
        "json_filename": json_path.name,
        "benchmark_mode": "system",
        "system_profile": "long" if long else "short",
    }
    git_sha = _try_git_sha()
    if git_sha is not None:
        meta["git_sha"] = git_sha

    results: dict[str, Any] = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "meta": meta,
        "scenarios": [],
        "effects": [],
        "system": run_system_benchmarks(
            repeats=max(1, int(args.repeats)),
            warmup=max(0, int(args.warmup)),
            long=long,
        ),
    }
    _write_json_atomic(json_path, results)
    print(f"[grafix-bench] wrote: {json_path}")  # noqa: T201
    return 0


def _normalize_run_id(value: str) -> str:
    if not value:
        value = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        datetime.strptime(value, "%Y%m%d_%H%M%S")
    except ValueError:
        raise SystemExit(f"--run-id must be %Y%m%d_%H%M%S: {value}")
    return value


def _import_builtin_effects() -> dict[str, str]:
    # `grafix.core.effects` 配下を列挙して import し、registry を埋める。
    import importlib

    import grafix.core.effects

    import_errors: dict[str, str] = {}
    for modinfo in sorted(pkgutil.iter_modules(grafix.core.effects.__path__), key=lambda m: m.name):
        name = str(modinfo.name)
        if name in {"__init__", "util"}:
            continue
        try:
            importlib.import_module(f"grafix.core.effects.{name}")
        except Exception as exc:  # noqa: BLE001
            import_errors[name] = f"{exc.__class__.__name__}: {exc}"

    return import_errors


def _list_effects(*, extra: set[str] | None = None) -> list[str]:
    # 登録順ではなく安定ソートで出す。
    names = set(effect_registry)
    if extra:
        names |= {str(x) for x in extra}
    return sorted(names)


def _cases_for_arity(cases: list[BenchmarkCase], *, n_inputs: int) -> list[BenchmarkCase]:
    """入力数が effect の arity と一致するケースだけを返す。"""

    return [case for case in cases if case.n_inputs == int(n_inputs)]


def _bench_params_for_effect(
    name: str,
    *,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(defaults)

    # no-op になりやすいものや、ベンチとして意味が出にくいものは上書きする。
    overrides: dict[str, dict[str, Any]] = {
        "translate": {"delta": (12.0, 5.0, 0.0)},
        "scale": {"scale": (1.15, 0.9, 1.0)},
        "rotate": {"rotation": (10.0, 20.0, 5.0)},
        "affine": {
            "scale": (1.05, 1.02, 1.0),
            "rotation": (5.0, 10.0, 0.0),
            "delta": (12.0, 5.0, 0.0),
        },
        "subdivide": {"subdivisions": 2},
        "repeat": {"count": 5},
        "mirror": {"n_mirror": 3},
        # shapely 系は依存未導入なら skipped になる設計（パラメータは軽め）。
        "buffer": {"distance": 5.0, "quad_segs": 8, "join": "round"},
        "partition": {"site_count": 30, "seed": 0},
    }

    if name in overrides:
        params.update(overrides[name])
    return params


def _bench_one(
    *,
    func,
    inputs: tuple[RealizedGeometry, ...],
    args_tuple: tuple[tuple[str, Any], ...],
    warmup: int,
    repeats: int,
    disable_gc: bool,
) -> dict[str, Any]:
    w = int(warmup)
    r = int(repeats)
    if w < 0:
        w = 0
    if r < 1:
        r = 1

    try:
        for _ in range(w):
            _ = func(inputs, args_tuple)
    except Exception as exc:  # noqa: BLE001
        status, msg = _classify_exception(exc)
        return {"status": status, "error": msg}

    times_ns: list[int] = []
    was_gc_enabled = False
    if disable_gc:
        was_gc_enabled = gc.isenabled()
        gc.disable()

    output: object | None = None
    try:
        for _ in range(r):
            t0 = time.perf_counter_ns()
            output = func(inputs, args_tuple)
            dt = time.perf_counter_ns() - t0
            times_ns.append(int(dt))
    except Exception as exc:  # noqa: BLE001
        status, msg = _classify_exception(exc)
        return {"status": status, "error": msg}
    finally:
        if disable_gc and was_gc_enabled:
            gc.enable()

    stats = _summarize(times_ns)
    return {
        "status": "ok",
        "mean_ms": stats.mean_ms,
        "median_ms": stats.median_ms,
        "p95_ms": stats.p95_ms,
        "stdev_ms": stats.stdev_ms,
        "min_ms": stats.min_ms,
        "max_ms": stats.max_ms,
        "n": stats.n,
        "output": _describe_output(output),
    }


def _summarize(times_ns: list[int]) -> _BenchStats:
    if not times_ns:
        return _BenchStats(
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            stdev_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            n=0,
        )

    n = int(len(times_ns))
    mean_ns = float(sum(times_ns)) / float(n)
    if n <= 1:
        stdev_ns = 0.0
    else:
        var = float(sum((float(t) - mean_ns) ** 2 for t in times_ns)) / float(n - 1)
        stdev_ns = float(var**0.5)

    min_ns = int(min(times_ns))
    max_ns = int(max(times_ns))
    ordered = sorted(times_ns)
    return _BenchStats(
        mean_ms=mean_ns / 1_000_000.0,
        median_ms=_percentile(ordered, 0.5) / 1_000_000.0,
        p95_ms=_percentile(ordered, 0.95) / 1_000_000.0,
        stdev_ms=stdev_ns / 1_000_000.0,
        min_ms=float(min_ns) / 1_000_000.0,
        max_ms=float(max_ns) / 1_000_000.0,
        n=n,
    )


def _percentile(ordered: list[int], fraction: float) -> float:
    """昇順の整数列から線形補間 percentile を返す。"""

    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * float(fraction)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower]) * (1.0 - weight) + float(ordered[upper]) * weight


def _describe_output(output: object | None) -> dict[str, int]:
    """effect 出力の頂点数、line 数、配列 byte 数を返す。"""

    if isinstance(output, RealizedGeometry):
        coords, offsets = output.coords, output.offsets
    elif isinstance(output, tuple) and len(output) == 2:
        coords = output[0]
        offsets = output[1]
    else:
        return {"n_vertices": 0, "n_lines": 0, "bytes": 0}

    coords_array = getattr(coords, "nbytes", 0)
    offsets_array = getattr(offsets, "nbytes", 0)
    try:
        n_vertices = int(coords.shape[0])
        n_lines = max(0, int(offsets.size) - 1)
    except (AttributeError, TypeError, ValueError):
        return {"n_vertices": 0, "n_lines": 0, "bytes": 0}
    return {
        "n_vertices": n_vertices,
        "n_lines": n_lines,
        "bytes": int(coords_array) + int(offsets_array),
    }


def _peak_rss_bytes() -> int:
    """現在 process の peak RSS を byte で返す。"""

    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return rss if sys.platform == "darwin" else rss * 1024


def _cold_worker(
    sender: Any,
    effect_name: str,
    inputs: tuple[RealizedGeometry, ...],
    args_tuple: tuple[tuple[str, Any], ...],
) -> None:
    """隔離 process 内で effect の初回評価だけを計測する。"""

    try:
        from grafix.core.builtins import ensure_builtin_effect_registered

        ensure_builtin_effect_registered(effect_name)
        spec = effect_registry[effect_name]
        started = time.perf_counter_ns()
        output = spec.evaluator(inputs, args_tuple)
        elapsed_ns = time.perf_counter_ns() - started
        sender.send(
            {
                "status": "ok",
                "wall_ms": float(elapsed_ns) / 1_000_000.0,
                "peak_rss_bytes": _peak_rss_bytes(),
                "output": _describe_output(output),
            }
        )
    except Exception as exc:  # noqa: BLE001
        status, message = _classify_exception(exc)
        sender.send({"status": status, "error": message})
    finally:
        sender.close()


def _bench_cold(
    *,
    effect_name: str,
    inputs: tuple[RealizedGeometry, ...],
    args_tuple: tuple[tuple[str, Any], ...],
    repeats: int,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """各回を fresh spawn process で実行し、cold first-call を集約する。"""

    samples: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    for _ in range(max(1, int(repeats))):
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_cold_worker,
            args=(sender, effect_name, inputs, args_tuple),
            daemon=True,
        )
        process.start()
        sender.close()
        try:
            if receiver.poll(float(timeout_s)):
                sample = receiver.recv()
            else:
                process.terminate()
                sample = {"status": "error", "error": "cold process timeout"}
        except EOFError:
            sample = {
                "status": "error",
                "error": f"cold process exited without result: {process.exitcode}",
            }
        finally:
            receiver.close()
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
                process.join()
        samples.append(dict(sample))

    ok_samples = [sample for sample in samples if sample.get("status") == "ok"]
    if not ok_samples:
        return {"status": "error", "samples": samples}
    wall_ns = [int(float(sample["wall_ms"]) * 1_000_000.0) for sample in ok_samples]
    stats = _summarize(wall_ns)
    return {
        "status": "ok",
        "median_ms": stats.median_ms,
        "p95_ms": stats.p95_ms,
        "peak_rss_bytes": max(int(sample["peak_rss_bytes"]) for sample in ok_samples),
        "n": len(ok_samples),
        "output": ok_samples[-1]["output"],
        "samples": samples,
    }


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    msg = f"{exc.__class__.__name__}: {exc}"
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        return "skipped", msg
    low = str(exc).lower()
    if "shapely" in low and ("必要" in low or "required" in low or "need" in low):
        return "skipped", msg
    return "error", msg


def _write_json_atomic(path: Path, payload: object) -> None:
    """JSON を sibling temp へ書いた後、正式 path へ原子的に置換する。"""

    with atomic_text_writer(path) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _try_git_sha() -> str | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return None
    sha = cp.stdout.strip()
    return sha if sha else None


if __name__ == "__main__":
    raise SystemExit(main())
