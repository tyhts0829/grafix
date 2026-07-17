"""runtime config の strict validation と effective value 表示 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grafix.core.runtime_config import RuntimeConfigReport, runtime_config_report, set_config_path


def _add_config_path_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", help="検証する config.yaml（省略時は通常探索）")
    parser.add_argument("--config", dest="config_path", help="path と同義の明示 config")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m grafix config")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="config を strict validation する")
    show_parser = subparsers.add_parser("show", help="effective config と出典を表示する")
    _add_config_path_arguments(validate_parser)
    _add_config_path_arguments(show_parser)
    return parser.parse_args(argv)


def _selected_path(args: argparse.Namespace) -> str | None:
    positional = args.path
    option = args.config_path
    if positional is not None and option is not None:
        raise ValueError("config path は positional と --config のどちらか一方だけ指定してください")
    if option is not None:
        return str(option)
    if positional is not None:
        return str(positional)
    return None


def _format_resolved_path(value: Path | tuple[Path, ...] | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, tuple):
        return repr(tuple(str(path) for path in value))
    return str(value)


def _print_report(report: RuntimeConfigReport) -> None:
    print(f"config_source: {report.active_source}")
    for value in report.values:
        print(f"{value.key}:")
        print(f"  source: {value.source}")
        print(f"  effective_value: {value.effective_value!r}")
        if value.is_path:
            print(f"  resolved_path: {_format_resolved_path(value.resolved_path)}")


def main(argv: list[str] | None = None) -> int:
    """``config validate/show`` を実行し、成否を exit code で返す。"""

    if argv is None:
        argv = sys.argv[1:]
    args = _parse_args(argv)

    try:
        selected_path = _selected_path(args)
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    set_config_path(selected_path)
    try:
        report = runtime_config_report()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"config invalid: {exc}", file=sys.stderr)
        return 2
    finally:
        set_config_path(None)

    if args.command == "validate":
        print(f"config valid: {report.active_source}")
        return 0
    if args.command == "show":
        _print_report(report)
        return 0
    raise AssertionError(f"unknown config command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
