"""
どこで: `src/grafix/devtools/list_builtins.py`。
何を: 組み込み effect / primitive を CLI 用に列挙する。
なぜ: 利用可能な op 名の探索コストを下げるため。
"""

from __future__ import annotations

import argparse
import sys

from grafix.core.operation_catalog import OperationCatalog, current_operation_catalog


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


def _list_effects(catalog: OperationCatalog) -> list[str]:
    return [entry.name for entry in catalog.public_entries(kind="effect")]


def _list_primitives(catalog: OperationCatalog) -> list[str]:
    return [entry.name for entry in catalog.public_entries(kind="primitive")]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    target = str(args.target)

    catalog = current_operation_catalog()

    if target == "effects":
        for name in _list_effects(catalog):
            print(name)
        return 0

    if target == "primitives":
        for name in _list_primitives(catalog):
            print(name)
        return 0

    if target == "all":
        print("effects:")
        for name in _list_effects(catalog):
            print(name)
        print("")
        print("primitives:")
        for name in _list_primitives(catalog):
            print(name)
        return 0

    raise AssertionError(f"unknown target: {target!r}")
