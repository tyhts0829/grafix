"""G/E から参照できる operation catalog の契約を検証する。"""

from __future__ import annotations

from pathlib import Path

import pytest

from grafix.api import E, G
from grafix.core.effect_registry import effect_registry
from grafix.core.primitive_registry import primitive_registry


def test_g_describe_exposes_primitive_spec_metadata() -> None:
    entry = G.describe("line")

    assert entry.name == "line"
    assert entry.kind == "primitive"
    assert entry.n_inputs == 0
    assert entry.accepted_args == ("center", "anchor", "length", "angle")
    assert entry.required_args == ()
    assert entry.defaults["length"] == 1.0
    assert entry.meta["length"].kind == "float"
    assert entry.description == "正規化済み引数から線分を生成する。"
    assert "Parameters\n----------" in entry.doc
    assert entry.source is not None
    assert Path(entry.source).name == "line.py"
    assert entry.provenance == "grafix.core.primitives.line:line"
    assert entry.spec is primitive_registry["line"]


def test_e_describe_excludes_geometry_inputs_from_effect_args() -> None:
    entry = E.describe("scale")

    assert entry.name == "scale"
    assert entry.kind == "effect"
    assert entry.n_inputs == 1
    assert entry.accepted_args == ("mode", "auto_center", "pivot", "scale")
    assert entry.required_args == ()
    assert entry.defaults["mode"] == "all"
    assert entry.meta["mode"].choices == ("all", "by_line", "by_face")
    assert entry.description == "スケール変換を適用（auto_center 対応）。"
    assert "Returns\n-------" in entry.doc
    assert entry.source is not None
    assert Path(entry.source).name == "scale.py"
    assert entry.provenance == "grafix.core.effects.scale:scale"
    assert entry.spec is effect_registry["scale"]


def test_catalog_loads_all_builtins_and_is_sorted() -> None:
    primitive_entries = G.catalog()
    effect_entries = E.catalog()

    primitive_names = tuple(entry.name for entry in primitive_entries)
    effect_names = tuple(entry.name for entry in effect_entries)
    assert primitive_names == tuple(sorted(primitive_names))
    assert effect_names == tuple(sorted(effect_names))
    assert "line" in primitive_names
    assert "scale" in effect_names
    assert all(entry.kind == "primitive" for entry in primitive_entries)
    assert all(entry.kind == "effect" for entry in effect_entries)


@pytest.mark.parametrize("namespace", (G, E))
def test_describe_rejects_unknown_operation(namespace: object) -> None:
    with pytest.raises(KeyError, match="未登録"):
        namespace.describe("does_not_exist")  # type: ignore[attr-defined]
