from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from grafix import G, ResourceBudget as PublicResourceBudget
from grafix import ResourceLimitError as PublicResourceLimitError
from grafix.core.effects.bold import bold
from grafix.core.effects.collapse import collapse
from grafix.core.effects.repeat import repeat
from grafix.core.primitives.grid import grid
from grafix.core.primitives.lissajous import lissajous
from grafix.core.primitives.torus import torus
from grafix.core.realize import RealizeError, RealizeSession
from grafix.core.resource_budget import (
    DEFAULT_RESOURCE_BUDGET,
    ResourceBudget,
    ResourceLimitError,
    current_resource_budget,
    ensure_geometry_output,
    resource_budget_context,
)


def _two_point_line() -> tuple[np.ndarray, np.ndarray]:
    return (
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        np.array([0, 2], dtype=np.int32),
    )


def _cause_chain(error: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in out:
        out.append(current)
        current = current.__cause__
    return out


def test_resource_budget_rejects_negative_limits() -> None:
    with pytest.raises(ValueError, match="max_output_vertices"):
        ResourceBudget(max_output_vertices=-1)

    with pytest.raises(TypeError, match="整数"):
        ResourceBudget(max_output_vertices=1.5)  # type: ignore[arg-type]


def test_resource_budget_types_are_available_from_root_api() -> None:
    assert PublicResourceBudget is ResourceBudget
    assert PublicResourceLimitError is ResourceLimitError


def test_resource_budget_context_is_restored_after_exception() -> None:
    budget = ResourceBudget(max_output_vertices=1)

    with pytest.raises(RuntimeError, match="stop"):
        with resource_budget_context(budget):
            assert current_resource_budget() is budget
            raise RuntimeError("stop")

    assert current_resource_budget() is DEFAULT_RESOURCE_BUDGET


def test_resource_limit_error_is_actionable() -> None:
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=10,
        max_output_bytes=10_000,
    )

    with resource_budget_context(budget), pytest.raises(ResourceLimitError) as exc_info:
        ensure_geometry_output(
            "demo",
            vertices=4,
            lines=1,
            hint="samples を減らしてください",
        )

    message = str(exc_info.value)
    assert "demo" in message
    assert "vertices=4" in message
    assert "samples を減らしてください" in message


def test_packed_int32_capacity_is_a_hard_limit() -> None:
    unlimited_for_test = ResourceBudget(
        max_output_vertices=1 << 40,
        max_output_lines=1 << 40,
        max_output_bytes=1 << 50,
    )

    with resource_budget_context(unlimited_for_test), pytest.raises(
        ResourceLimitError, match="int32 capacity"
    ):
        ensure_geometry_output("demo", vertices=1 << 31, lines=1)


@pytest.mark.parametrize(
    ("name", "operation"),
    [
        ("grid", lambda: grid(nx=2, ny=0)),
        ("lissajous", lambda: lissajous(samples=4)),
        ("torus", lambda: torus(major_segments=3, minor_segments=3)),
        ("repeat", lambda: repeat(_two_point_line(), count=1)),
        ("bold", lambda: bold(_two_point_line(), count=2)),
        ("collapse", lambda: collapse(_two_point_line(), subdivisions=2)),
    ],
)
def test_high_growth_operations_check_budget_before_output_allocation(
    name: str,
    operation: Callable[[], object],
) -> None:
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=100,
        max_output_bytes=10_000_000,
    )

    with resource_budget_context(budget), pytest.raises(ResourceLimitError, match=name):
        operation()


def test_realize_session_applies_its_budget_to_builtin_operation() -> None:
    geometry = G.grid(nx=2, ny=0)
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=100,
        max_output_bytes=10_000_000,
    )

    with RealizeSession(resource_budget=budget) as session:
        with pytest.raises(RealizeError) as exc_info:
            session.realize(geometry)

    assert any(isinstance(item, ResourceLimitError) for item in _cause_chain(exc_info.value))


def test_concat_uses_the_session_budget() -> None:
    geometry = G.grid(nx=1, ny=0) + G.grid(nx=1, ny=0, key="second")
    budget = ResourceBudget(
        max_output_vertices=3,
        max_output_lines=100,
        max_output_bytes=10_000_000,
    )

    with RealizeSession(resource_budget=budget) as session:
        with pytest.raises(RealizeError) as exc_info:
            session.realize(geometry)

    assert any(isinstance(item, ResourceLimitError) for item in _cause_chain(exc_info.value))
