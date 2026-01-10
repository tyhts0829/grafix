# どこで: `src/grafix/__main__.py`。
# 何を: `python -m grafix ...` の CLI エントリポイントを提供する。
# なぜ: 開発用コマンド（ベンチ/スタブ生成）を短い導線で実行できるようにするため。

from __future__ import annotations

import argparse
import sys


def _extract_out_dir(argv: list[str]) -> str:
    out = "data/output/benchmarks"
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
    return out


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(prog="python -m grafix")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "benchmark",
        help="effect ベンチ計測 → レポート生成",
        add_help=False,
    )
    sub.add_parser("generate_stub", help="grafix.api のスタブ（__init__.pyi）を再生成する")
    sub.add_parser(
        "list",
        help="組み込み effect / primitive を一覧表示する",
        add_help=False,
    )

    args, rest = p.parse_known_args(argv)

    if args.cmd == "benchmark":
        from grafix.devtools.benchmarks import effect_benchmark, generate_report

        bench_argv = list(rest)
        if bench_argv and bench_argv[0] == "--":
            bench_argv = bench_argv[1:]

        if any(a in {"-h", "--help"} for a in bench_argv):
            try:
                effect_benchmark.main(["--help"])
            except SystemExit as exc:
                return int(exc.code) if exc.code is not None else 0
            return 0

        code = int(effect_benchmark.main(bench_argv))
        if code != 0:
            return code
        out_dir = _extract_out_dir(bench_argv)
        return int(generate_report.main(out=out_dir))

    if args.cmd == "generate_stub":
        from grafix.devtools import generate_stub

        generate_stub.main()
        return 0

    if args.cmd == "list":
        from grafix.devtools import list_builtins

        list_argv = list(rest)
        if list_argv and list_argv[0] == "--":
            list_argv = list_argv[1:]
        return int(list_builtins.main(list_argv))

    raise AssertionError(f"unknown cmd: {args.cmd!r}")


if __name__ == "__main__":
    raise SystemExit(main())
