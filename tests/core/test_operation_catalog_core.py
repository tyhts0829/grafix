"""operation catalog builder と immutable snapshot の契約を検証する。"""

from __future__ import annotations

import pytest

from grafix.core.operation_catalog import (
    OperationCatalog,
    OperationCatalogBuilder,
    compose_operation_catalogs,
)
from grafix.core.operation_declaration import OpDeclaration, create_op_declaration
from grafix.core.operation_schema import ParameterOpSchema


_EMPTY_SCHEMA = ParameterOpSchema(meta={}, defaults={}, param_order=(), ui_visible={})


def _evaluator() -> object:
    return None


def _declaration(name: str, *, version: str = "1") -> OpDeclaration:
    return create_op_declaration(
        name=name,
        kind="primitive",
        evaluator=_evaluator,
        schema=_EMPTY_SCHEMA,
        n_inputs=0,
        evaluator_abi=version,
    )


def test_freeze_returns_snapshot_not_live_builder_view() -> None:
    builder = OperationCatalogBuilder()
    first = _declaration("first")
    builder.register(first)
    snapshot = builder.freeze()

    builder.register(_declaration("second"))

    assert snapshot.resolve("primitive", "first").declaration is first
    assert ("primitive", "second") not in snapshot
    assert len(snapshot) == 1


def test_duplicate_registration_is_atomic() -> None:
    builder = OperationCatalogBuilder()
    original = _declaration("same", version="1")
    duplicate = _declaration("same", version="2")
    builder.register(original)

    with pytest.raises(ValueError, match="既に登録"):
        builder.register(duplicate)

    assert builder.freeze().resolve("primitive", "same").declaration is original


def test_overwrite_replaces_only_the_requested_entry_and_old_snapshot_is_stable() -> None:
    builder = OperationCatalogBuilder()
    first_a = _declaration("a", version="1")
    first_b = _declaration("b", version="1")
    builder.register(first_a)
    builder.register(first_b)
    before = builder.freeze()

    second_a = _declaration("a", version="2")
    builder.register(second_a, overwrite=True)
    after = builder.freeze()

    assert before.resolve("primitive", "a").declaration is first_a
    assert before.resolve("primitive", "b").declaration is first_b
    assert after.resolve("primitive", "a").declaration is second_a
    assert after.resolve("primitive", "b").declaration is first_b


def test_catalog_resolves_exact_evaluation_reference() -> None:
    builder = OperationCatalogBuilder()
    declaration = _declaration("stable")
    builder.register(declaration)
    catalog = builder.freeze()

    assert catalog.resolve_ref(declaration.ref).declaration is declaration

    changed = _declaration("stable", version="2")
    with pytest.raises(LookupError, match="fingerprint"):
        catalog.resolve_ref(changed.ref)


def test_catalog_entry_reuses_its_frozen_evaluation_reference() -> None:
    builder = OperationCatalogBuilder()
    builder.register(_declaration("stable"))
    entry = builder.freeze().resolve("primitive", "stable")

    assert entry.ref is entry.evaluation.ref
    assert entry.ref is entry.ref


def test_composition_reuses_immutable_snapshot_when_either_side_is_empty() -> None:
    builder = OperationCatalogBuilder()
    builder.register(_declaration("stable"))
    populated = builder.freeze()
    empty = OperationCatalog({})

    assert compose_operation_catalogs(populated, empty) is populated
    assert compose_operation_catalogs(empty, populated) is populated
