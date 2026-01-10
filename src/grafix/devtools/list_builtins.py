"""
どこで: `src/grafix/devtools/list_builtins.py`。
何を: 組み込み effect / primitive を CLI 用に列挙する。
なぜ: 利用可能な op 名の探索コストを下げるため。
"""

from __future__ import annotations

import argparse
import importlib
import sys

from grafix.core.effect_registry import effect_registry
from grafix.core.primitive_registry import primitive_registry


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m grafix list")
    p.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=("effects", "primitives", "all"),
        help="一覧対象（省略時: all）",
    )
    return p.parse_args(argv)


def _import_builtin_ops() -> None:
    # public API 起点で import し、registry を初期化する。
    importlib.import_module("grafix.api.primitives")
    importlib.import_module("grafix.api.effects")


def _list_effects() -> list[str]:
    return sorted(name for name, _ in effect_registry.items() if not name.startswith("_"))


def _list_primitives() -> list[str]:
    return sorted(name for name, _ in primitive_registry.items() if not name.startswith("_"))


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    target = str(args.target)

    _import_builtin_ops()

    if target == "effects":
        for name in _list_effects():
            print(name)
        return 0

    if target == "primitives":
        for name in _list_primitives():
            print(name)
        return 0

    if target == "all":
        print("effects:")
        for name in _list_effects():
            print(name)
        print("")
        print("primitives:")
        for name in _list_primitives():
            print(name)
        return 0

    raise AssertionError(f"unknown target: {target!r}")

