"""immutable operation declaration と参照型の契約を検証する。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from grafix.core.definition_fingerprint import (
    EvaluationSpecFingerprint,
    ParameterSchemaFingerprint,
)
from grafix.core.operation_declaration import (
    EffectStepRef,
    EvaluationOpRef,
    create_op_declaration,
)
from grafix.core.operation_schema import ParameterOpSchema
from grafix.core.parameters.meta import ParamMeta


def _schema(*, description: str = "amount") -> ParameterOpSchema:
    return ParameterOpSchema(
        meta={"amount": ParamMeta(kind="float", description=description)},
        defaults={"amount": 1.0},
        param_order=("amount",),
        ui_visible={},
    )


def _primitive(*, amount: float = 1.0) -> object:
    return amount


def _effect(geometry: object, *, amount: float = 1.0) -> object:
    _ = amount
    return geometry


def test_factory_builds_frozen_declaration_and_typed_references() -> None:
    declaration = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
    )

    assert isinstance(declaration.evaluation_fingerprint, EvaluationSpecFingerprint)
    assert isinstance(declaration.schema_fingerprint, ParameterSchemaFingerprint)
    assert declaration.ref == EvaluationOpRef(
        kind="effect",
        name="scale",
        fingerprint=declaration.evaluation_fingerprint,
    )
    assert declaration.effect_step_ref == EffectStepRef(
        operation=declaration.ref,
        schema_fingerprint=declaration.schema_fingerprint,
    )
    with pytest.raises(FrozenInstanceError):
        declaration.name = "changed"  # type: ignore[misc]


def test_schema_only_change_keeps_evaluation_fingerprint() -> None:
    first = create_op_declaration(
        name="dot",
        kind="primitive",
        evaluator=_primitive,
        schema=_schema(description="first"),
        n_inputs=0,
    )
    second = create_op_declaration(
        name="dot",
        kind="primitive",
        evaluator=_primitive,
        schema=_schema(description="second"),
        n_inputs=0,
    )

    assert first.evaluation_fingerprint == second.evaluation_fingerprint
    assert first.schema_fingerprint != second.schema_fingerprint


def test_evaluation_contract_options_change_only_the_target_declaration() -> None:
    first = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
        evaluator_abi="1",
    )
    second = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
        evaluator_abi="2",
    )

    assert first.evaluation_fingerprint != second.evaluation_fingerprint
    assert first.schema_fingerprint == second.schema_fingerprint


def test_external_dependency_hook_is_part_of_evaluation_fingerprint() -> None:
    def first_hook(*_args: object) -> str:
        return "first"

    def second_hook(*_args: object) -> str:
        return "second"

    without_hook = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
    )
    first = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
        external_dependency_hook=first_hook,
    )
    second = create_op_declaration(
        name="scale",
        kind="effect",
        evaluator=_effect,
        schema=_schema(),
        n_inputs=1,
        external_dependency_hook=second_hook,
    )

    assert len(
        {
            without_hook.evaluation_fingerprint,
            first.evaluation_fingerprint,
            second.evaluation_fingerprint,
        }
    ) == 3
    assert (
        without_hook.schema_fingerprint
        == first.schema_fingerprint
        == second.schema_fingerprint
    )


def test_effect_step_ref_rejects_primitive_reference() -> None:
    declaration = create_op_declaration(
        name="dot",
        kind="primitive",
        evaluator=_primitive,
        schema=_schema(),
        n_inputs=0,
    )

    with pytest.raises(ValueError, match="effect"):
        EffectStepRef(
            operation=declaration.ref,
            schema_fingerprint=declaration.schema_fingerprint,
        )


def test_none_cache_policy_requires_explicit_stable_version() -> None:
    with pytest.raises(ValueError, match="version"):
        create_op_declaration(
            name="dynamic",
            kind="primitive",
            evaluator=_primitive,
            schema=_schema(),
            n_inputs=0,
            cache_policy="none",
        )
