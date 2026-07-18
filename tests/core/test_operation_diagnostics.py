from __future__ import annotations

import numpy as np

from grafix.core.effects.subdivide import MAX_SUBDIVISIONS, subdivide
from grafix.core.effects.util import GridSpec
from grafix.core.operation_diagnostics import (
    current_operation_diagnostics,
    emit_operation_diagnostic,
    operation_diagnostic_context,
)


def _line() -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], dtype=np.float32),
        np.asarray([0, 2], dtype=np.int32),
    )


def _float32_stop_boundary_line() -> tuple[np.ndarray, np.ndarray]:
    endpoint = np.nextafter(np.float32(0.32), np.float32(np.inf))
    return (
        np.asarray([[0.0, 0.0, 0.0], [endpoint, 0.0, 0.0]], dtype=np.float32),
        np.asarray([0, 2], dtype=np.int32),
    )


def test_operation_diagnostic_context_isolated_and_deduplicated() -> None:
    with operation_diagnostic_context() as buffer:
        for _ in range(2):
            emit_operation_diagnostic(
                op="example",
                original_value=12,
                effective_value=10,
                reason="clamped",
            )

        assert len(buffer) == 1
        assert current_operation_diagnostics() == buffer.snapshot()

    assert current_operation_diagnostics() == ()


def test_subdivide_normal_path_has_no_diagnostic() -> None:
    with operation_diagnostic_context() as buffer:
        subdivide(_line(), subdivisions=1)

    assert buffer.snapshot() == ()


def test_subdivide_clamp_emits_one_original_and_effective_payload() -> None:
    requested = MAX_SUBDIVISIONS + 4
    with operation_diagnostic_context() as buffer:
        subdivide(_line(), subdivisions=requested)

    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.op == "subdivide"
    assert diagnostic.original_value == requested
    assert diagnostic.effective_value == MAX_SUBDIVISIONS
    assert "clamped" in diagnostic.reason
    assert diagnostic.severity == "warning"


def test_subdivide_negative_value_emits_one_clamp_diagnostic() -> None:
    with operation_diagnostic_context() as buffer:
        subdivide(_line(), subdivisions=-2)

    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.original_value == -2
    assert diagnostic.effective_value == 0
    assert "clamped" in diagnostic.reason


def test_subdivide_float32_early_stop_reports_actual_effective_level() -> None:
    with operation_diagnostic_context() as buffer:
        coords, offsets = subdivide(
            _float32_stop_boundary_line(),
            subdivisions=10,
        )

    assert coords.shape == (33, 3)
    assert offsets.tolist() == [0, 33]
    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.original_value == 10
    assert diagnostic.effective_value == 5
    assert "minimum segment length stopped" in diagnostic.reason


def test_grid_normal_path_has_no_diagnostic() -> None:
    with operation_diagnostic_context() as buffer:
        grid = GridSpec.from_bbox(
            (0.0, 0.0),
            (2.0, 1.0),
            pitch=1.0,
            max_cells=6,
            overflow="reject",
        )

    assert grid is not None
    assert buffer.snapshot() == ()


def test_grid_reject_emits_one_diagnostic() -> None:
    with operation_diagnostic_context() as buffer:
        grid = GridSpec.from_bbox(
            (0.0, 0.0),
            (2.0, 1.0),
            pitch=1.0,
            max_cells=5,
            overflow="reject",
        )

    assert grid is None
    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.op == "GridSpec.from_bbox"
    assert diagnostic.effective_value is None
    assert "rejected" in diagnostic.reason


def test_grid_repeated_non_finite_rejection_is_deduplicated() -> None:
    with operation_diagnostic_context() as buffer:
        for _ in range(2):
            assert (
                GridSpec.from_bbox(
                    (0.0, 0.0),
                    (2.0, 1.0),
                    pitch=float("nan"),
                )
                is None
            )

    assert len(buffer) == 1


def test_grid_coarsen_emits_one_diagnostic() -> None:
    with operation_diagnostic_context() as buffer:
        grid = GridSpec.from_bbox(
            (0.0, 0.0),
            (100.0, 100.0),
            pitch=1.0,
            max_cells=100,
            overflow="coarsen",
        )

    assert grid is not None
    assert len(buffer) == 1
    diagnostic = buffer.snapshot()[0]
    assert diagnostic.original_value == 1.0
    assert diagnostic.effective_value == grid.pitch
    assert "coarsened" in diagnostic.reason
