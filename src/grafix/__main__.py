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


def _delegated_args(rest: list[str]) -> list[str]:
    """親 parser と子 parser の境界に置かれた ``--`` を除く。"""

    args = list(rest)
    if args and args[0] == "--":
        return args[1:]
    return args


def main(argv: list[str] | None = None) -> int:
    """Grafix CLI の subcommand を実行する。

    Parameters
    ----------
    argv : list[str] or None, optional
        CLI 引数。None の場合は ``sys.argv`` を使う。

    Returns
    -------
    int
        subcommand の process exit code。
    """

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(prog="python -m grafix")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "benchmark",
        help="effect ベンチ計測 → レポート生成",
        add_help=False,
    )
    sub.add_parser(
        "export",
        help="draw(t) を headless で SVG/PNG/G-code に書き出す",
        add_help=False,
    )
    sub.add_parser(
        "variations",
        help="named variations を thumbnail/contact sheet に一括書き出しする",
        add_help=False,
    )
    sub.add_parser(
        "run",
        help="sketch.pyをinteractive previewで実行し、任意で変更をwatchする",
        add_help=False,
    )
    sub.add_parser(
        "stub",
        help="project-local な grafix.api stub を生成する",
        add_help=False,
    )
    sub.add_parser(
        "init",
        help="最小 Grafix project を既存file非上書きで作る",
        add_help=False,
    )
    sub.add_parser(
        "examples",
        help="同梱 example の一覧表示・コピー",
        add_help=False,
    )
    sub.add_parser(
        "doctor",
        help="GL・外部command・MIDI・font・出力先を診断する",
        add_help=False,
    )
    sub.add_parser(
        "list",
        help="組み込み effect / primitive を一覧表示する",
        add_help=False,
    )
    sub.add_parser(
        "describe",
        help="operation の説明・引数・source を表示する",
        add_help=False,
    )
    sub.add_parser(
        "config",
        help="runtime config の validation / effective value 表示",
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

    if args.cmd == "stub":
        from grafix.devtools import generate_stub

        return int(generate_stub.main(_delegated_args(rest)))

    if args.cmd == "init":
        from grafix.devtools import onboarding

        return int(onboarding.main_init(_delegated_args(rest)))

    if args.cmd == "examples":
        from grafix.devtools import onboarding

        return int(onboarding.main_examples(_delegated_args(rest)))

    if args.cmd == "doctor":
        from grafix.devtools import doctor

        return int(doctor.main(_delegated_args(rest)))

    if args.cmd == "export":
        from grafix.devtools import export_frame

        export_argv = list(rest)
        if export_argv and export_argv[0] == "--":
            export_argv = export_argv[1:]
        return int(export_frame.main(export_argv))

    if args.cmd == "variations":
        from grafix.devtools import variation_batch

        return int(variation_batch.main(_delegated_args(rest)))

    if args.cmd == "run":
        from grafix.devtools import run_sketch

        return int(run_sketch.main(_delegated_args(rest)))

    if args.cmd == "list":
        from grafix.devtools import list_builtins

        list_argv = list(rest)
        if list_argv and list_argv[0] == "--":
            list_argv = list_argv[1:]
        return int(list_builtins.main(list_argv))

    if args.cmd == "describe":
        from grafix.devtools import describe_op

        describe_argv = list(rest)
        if describe_argv and describe_argv[0] == "--":
            describe_argv = describe_argv[1:]
        return int(describe_op.main(describe_argv))

    if args.cmd == "config":
        from grafix.devtools import config_cli

        config_argv = list(rest)
        if config_argv and config_argv[0] == "--":
            config_argv = config_argv[1:]
        return int(config_cli.main(config_argv))

    raise AssertionError(f"unknown cmd: {args.cmd!r}")


if __name__ == "__main__":
    raise SystemExit(main())
