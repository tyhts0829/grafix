"""
どこで: `tools/benchmarks/effect_benchmark.py`。
何を: `grafix.core.effects` の effect をケース別にベンチし、JSON を出力する。
なぜ: どの effect がどんな入力で遅いかを一覧・比較し、最適化の当たりを付けるため。

主な流れ（読む順）:
- import 時に `_bootstrap_import_paths()` が `src/` と project root を `sys.path` に追加する。
- `main()` が:
  - effect 実装を import して registry を初期化し（失敗は記録）、
  - `cases`（入力 Geometry）× `effects`（対象 effect）で計測し、
  - 集計結果を `<out>/runs/<run_id>.json` に書く。

入出力と副作用:
- 生成物: JSON（実行環境情報、case 情報、effect ごとの計測値）
- filesystem: 出力ディレクトリ作成・JSON 書き込み
- import: `grafix.core.effects.*` を一括 import（効果の登録と依存チェック目的）
- 可能なら `git rev-parse HEAD` を実行して SHA を記録する
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _bootstrap_import_paths() -> None:
    """`python <file>.py` と `python -m ...` の両対応のために import path を整える。

    ベンチマークは tools 配下から直接実行されることが多いので、
    - project root（`pyproject.toml` 等があるディレクトリ）
    - `src/`（`grafix` パッケージがあるディレクトリ）
    を `sys.path` 先頭に追加して、インストール無しでも import できるようにする。
    """
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parents[2]
    src_dir = project_root / "src"

    # `sys.path` は「先頭ほど優先」なので insert(0, ...) する。
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_import_paths()

from grafix.core.effect_registry import effect_registry  # noqa: E402
from grafix.core.realized_geometry import RealizedGeometry  # noqa: E402
from tools.benchmarks.cases import BenchmarkCase, build_default_cases, describe_geometry  # noqa: E402


@dataclass(frozen=True, slots=True)
class _BenchStats:
    """計測結果（ns の列）を ms 単位で要約した統計量。"""

    mean_ms: float
    stdev_ms: float
    min_ms: float
    max_ms: float
    n: int


def main(argv: list[str] | None = None) -> int:
    """effect ベンチマーク CLI のエントリポイント。

    Parameters
    ----------
    argv:
        `argparse` に渡す引数列。`None` の場合は `sys.argv` を使う。

    Returns
    -------
    int
        終了コード（0: 成功、2: 入力不備などで実行不可）。
    """
    args = _parse_args(argv)

    out_root = Path(args.out).expanduser().resolve()
    run_id = _normalize_run_id(str(args.run_id))
    runs_dir = out_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / f"{run_id}.json"

    cases = build_default_cases(seed=int(args.seed))
    if args.cases:
        # `--cases a,b,c` を指定した場合は、該当 id のみを残す。
        only = {c.strip() for c in str(args.cases).split(",") if c.strip()}
        cases = [c for c in cases if c.case_id in only]

    if not cases:
        print("ケースが 0 件です。--cases を確認してください。")  # noqa: T201
        return 2

    import_errors = _import_builtin_effects()

    # registry に登録された effect 名に加え、import 失敗したモジュール名も一覧に含める。
    # （「存在するが依存が足りない」等を JSON で可視化するため）
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
        info = describe_geometry(c.geometry)
        case_meta.append(
            {
                "id": c.case_id,
                "label": c.label,
                "description": c.description,
                **info,
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

    results: dict[str, Any] = {"meta": meta, "cases": case_meta, "effects": []}

    repeats = int(args.repeats)
    warmup = int(args.warmup)
    disable_gc = bool(args.disable_gc)

    for eff_name in effects:
        eff_entry: dict[str, Any] = {
            "name": eff_name,
            "module": f"grafix.core.effects.{eff_name}",
            "params": {},
            "results": {},
        }

        if eff_name not in effect_registry:
            # import 失敗などで registry 未登録のものは、全 case を skipped にする。
            err = import_errors.get(eff_name, "import failed")
            for case in cases:
                eff_entry["results"][case.case_id] = {
                    "status": "skipped",
                    "error": f"module import failed: {err}",
                }
            results["effects"].append(eff_entry)
            continue

        eff_entry["params"] = _bench_params_for_effect(eff_name)
        func = effect_registry.get(eff_name)
        # effect 関数は内部で args を参照しやすい形（タプル列）で渡す想定。
        # JSON が diff しやすいようにキー順を固定しておく。
        args_tuple = tuple(
            sorted(eff_entry["params"].items(), key=lambda kv: str(kv[0]))
        )

        for case in cases:
            res = _bench_one(
                func=func,
                inputs=[case.geometry],
                args_tuple=args_tuple,
                warmup=warmup,
                repeats=repeats,
                disable_gc=disable_gc,
            )
            eff_entry["results"][case.case_id] = res

        results["effects"].append(eff_entry)

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[grafix-bench] wrote: {json_path}")  # noqa: T201
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """CLI 引数を定義してパースする。"""
    p = argparse.ArgumentParser(prog="effect_benchmark")
    p.add_argument(
        "--out",
        default="data/output/benchmarks",
        help="出力ルート（<out>/runs/<run_id>.json を作る）",
    )
    p.add_argument("--run-id", default="", help="出力ファイル名（%Y%m%d_%H%M%S。省略時は現在時刻）")
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
    return p.parse_args(argv)


def _normalize_run_id(value: str) -> str:
    """`--run-id` を正規化して返す（空なら現在時刻）。

    `runs/<run_id>.json` のファイル名に使うため、`%Y%m%d_%H%M%S` 形式のみ許可する。
    """
    if not value:
        value = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        datetime.strptime(value, "%Y%m%d_%H%M%S")
    except ValueError:
        raise SystemExit(f"--run-id must be %Y%m%d_%H%M%S: {value}")
    return value


def _import_builtin_effects() -> dict[str, str]:
    """built-in effect 実装を一括 import して registry を初期化する。

    `effect_registry` は import 時の登録（副作用）に依存しているため、
    `src/grafix/core/effects/*.py` を順に import して「登録漏れ」を避ける。

    Returns
    -------
    dict[str, str]
        import に失敗した effect 名とエラーメッセージの対応表。
        （依存が未導入の effect はここに入る想定）
    """
    effects_dir = Path(__file__).resolve().parents[2] / "src" / "grafix" / "core" / "effects"
    if not effects_dir.is_dir():
        raise RuntimeError(f"effects dir not found: {effects_dir}")

    # __init__.py / util.py を除いた直下 *.py を import して登録させる。
    import importlib

    import_errors: dict[str, str] = {}
    for fp in sorted(effects_dir.glob("*.py")):
        stem = fp.stem
        if stem in {"__init__", "util"}:
            continue
        try:
            importlib.import_module(f"grafix.core.effects.{stem}")
        except Exception as exc:  # noqa: BLE001
            import_errors[stem] = f"{exc.__class__.__name__}: {exc}"

    return import_errors


def _list_effects(*, extra: set[str] | None = None) -> list[str]:
    """registry の effect 名を安定ソートで返す（必要なら追加名も混ぜる）。"""
    # 登録順ではなく安定ソートで出す。
    names = {name for name, _func in effect_registry.items()}
    if extra:
        names |= {str(x) for x in extra}
    return sorted(names)


def _bench_params_for_effect(name: str) -> dict[str, Any]:
    """effect ごとのベンチ用パラメータを決める。

    基本は registry の defaults を使うが、ベンチとして意味が出にくい（no-op になりやすい）場合は
    最低限の上書きを行う。
    """
    defaults = effect_registry.get_defaults(name)
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
    inputs: list[RealizedGeometry],
    args_tuple: tuple[tuple[str, Any], ...],
    warmup: int,
    repeats: int,
    disable_gc: bool,
) -> dict[str, Any]:
    """単一 effect × 単一入力ケースの計測を行う。

    - warmup 回は計測せずに実行（初回コストやキャッシュの影響を薄める）
    - repeats 回の実行時間を ns で収集し、ms に直して要約する
    - 例外は `skipped` / `error` に分類して JSON に載せる
    """
    w = int(warmup)
    r = int(repeats)
    if w < 0:
        w = 0
    if r < 1:
        r = 1

    try:
        # warmup 中に落ちる場合は、そのまま本計測しても落ち続けるので即返す。
        for _ in range(w):
            _ = func(inputs, args_tuple)
    except Exception as exc:  # noqa: BLE001
        status, msg = _classify_exception(exc)
        return {"status": status, "error": msg}

    times_ns: list[int] = []
    was_gc_enabled = False
    if disable_gc:
        # GC のタイミングで計測がブレることがあるので、必要なら一時的に無効化する。
        was_gc_enabled = gc.isenabled()
        gc.disable()

    try:
        for _ in range(r):
            t0 = time.perf_counter_ns()
            _ = func(inputs, args_tuple)
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
        "stdev_ms": stats.stdev_ms,
        "min_ms": stats.min_ms,
        "max_ms": stats.max_ms,
        "n": stats.n,
    }


def _summarize(times_ns: list[int]) -> _BenchStats:
    """ns の計測列を、平均/標準偏差/最小/最大（ms）に要約する。"""
    if not times_ns:
        return _BenchStats(mean_ms=0.0, stdev_ms=0.0, min_ms=0.0, max_ms=0.0, n=0)

    n = int(len(times_ns))
    mean_ns = float(sum(times_ns)) / float(n)
    if n <= 1:
        stdev_ns = 0.0
    else:
        var = float(sum((float(t) - mean_ns) ** 2 for t in times_ns)) / float(n - 1)
        stdev_ns = float(var**0.5)

    min_ns = int(min(times_ns))
    max_ns = int(max(times_ns))
    return _BenchStats(
        mean_ms=mean_ns / 1_000_000.0,
        stdev_ms=stdev_ns / 1_000_000.0,
        min_ms=float(min_ns) / 1_000_000.0,
        max_ms=float(max_ns) / 1_000_000.0,
        n=n,
    )


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """例外を JSON 上の status に分類する。

    - `ImportError` 系は「依存が無い」可能性が高いので `skipped`
    - `shapely` 依存を匂わせるメッセージも `skipped`
    - それ以外は `error`
    """
    msg = f"{exc.__class__.__name__}: {exc}"
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        return "skipped", msg
    low = str(exc).lower()
    if "shapely" in low and ("必要" in low or "required" in low or "need" in low):
        return "skipped", msg
    return "error", msg


def _try_git_sha() -> str | None:
    """可能なら `git rev-parse HEAD` を実行してコミット SHA を返す。"""
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
