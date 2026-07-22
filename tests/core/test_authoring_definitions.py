"""authoring definition の registration target と snapshot 契約を検証する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from grafix.core.authoring_definitions import (
    DefaultAuthoringDefinitions,
    RegistrationTarget,
    current_registration_target,
    registration_scope,
)
from grafix.core.operation_declaration import OpDeclaration, create_op_declaration
from grafix.core.operation_schema import ParameterOpSchema
from grafix.core.preset_catalog import PresetDeclaration


_EMPTY_SCHEMA = ParameterOpSchema(meta={}, defaults={}, param_order=(), ui_visible={})


def _evaluator() -> object:
    return None


def _operation(*, version: str) -> OpDeclaration:
    return create_op_declaration(
        name="shape",
        kind="primitive",
        evaluator=_evaluator,
        schema=_EMPTY_SCHEMA,
        n_inputs=0,
        evaluator_abi=version,
    )


def _preset() -> PresetDeclaration:
    def func() -> list[object]:
        return []

    return PresetDeclaration(
        name="scene",
        func=func,
        invoker=func,
        schema=_EMPTY_SCHEMA,
    )


def test_registration_target_dispatches_both_definition_kinds() -> None:
    target = RegistrationTarget()
    operation = _operation(version="1")
    preset = _preset()

    target.register(operation)
    target.register(preset)
    snapshot = target.snapshot()

    assert snapshot.operations.resolve("primitive", "shape").declaration is operation
    assert snapshot.presets["scene"] is preset


def test_registration_scope_is_nested_and_context_local() -> None:
    outer = RegistrationTarget()
    inner = RegistrationTarget()
    assert current_registration_target() is None

    with registration_scope(outer):
        assert current_registration_target() is outer
        with registration_scope(inner):
            assert current_registration_target() is inner
        assert current_registration_target() is outer

    assert current_registration_target() is None


def test_default_snapshot_is_immutable_after_overwrite() -> None:
    definitions = DefaultAuthoringDefinitions()
    first = _operation(version="1")
    second = _operation(version="2")
    definitions.register(first)
    before = definitions.snapshot()

    definitions.register(second, overwrite=True)
    after = definitions.snapshot()

    assert before.operations.resolve("primitive", "shape").declaration is first
    assert after.operations.resolve("primitive", "shape").declaration is second


def test_default_snapshot_is_safe_while_another_thread_overwrites() -> None:
    definitions = DefaultAuthoringDefinitions()
    first = _operation(version="1")
    second = _operation(version="2")
    definitions.register(first)

    def write() -> None:
        for index in range(200):
            definitions.register(first if index % 2 == 0 else second, overwrite=True)

    def read() -> list[OpDeclaration]:
        observed: list[OpDeclaration] = []
        for _ in range(200):
            entry = definitions.snapshot().operations.resolve("primitive", "shape")
            observed.append(entry.declaration)
        return observed

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(write)
        reader = executor.submit(read)
        writer.result()
        observed = reader.result()

    assert observed
    assert all(declaration is first or declaration is second for declaration in observed)
