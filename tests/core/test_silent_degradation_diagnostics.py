from __future__ import annotations

import numpy as np

from grafix.core.effects.extrude import extrude
from grafix.core.effects.fill import fill
from grafix.core.effects.growth import growth
from grafix.core.effects.relax import relax
from grafix.core.effects.trim import trim
from grafix.core.effects.weave import weave
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.primitives.sphere import sphere
from grafix.core.realized_geometry import GeomTuple


def _line() -> GeomTuple:
    coords = np.asarray([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], dtype=np.float32)
    return coords, np.asarray([0, 2], dtype=np.int32)


def _square() -> GeomTuple:
    coords = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 10.0, 0.0],
            [0.0, 10.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    return coords, np.asarray([0, 5], dtype=np.int32)


def _chain() -> GeomTuple:
    coords = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 0.0],
            [2.0, 1.0, 0.0],
            [3.0, -2.0, 0.0],
            [4.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    return coords, np.asarray([0, 5], dtype=np.int32)


def _single_diagnostic(call: object) -> tuple[str, object, object]:
    assert callable(call)
    with operation_diagnostic_context() as diagnostics:
        call()
    assert len(diagnostics) == 1
    item = diagnostics.snapshot()[0]
    return item.op, item.original_value, item.effective_value


def test_extrude_clamp_reports_requested_and_effective_scale() -> None:
    assert _single_diagnostic(
        lambda: extrude(_line(), scale=4.0, subdivisions=0)
    ) == ("extrude.scale", 4.0, 3.0)


def test_fill_clamp_reports_requested_and_effective_angle_sets() -> None:
    assert _single_diagnostic(
        lambda: fill(_square(), angle_sets=0, density=5.0)
    ) == ("fill.angle_sets", 0, 1)


def test_weave_clamp_reports_requested_and_effective_step() -> None:
    assert _single_diagnostic(
        lambda: weave(
            _square(),
            num_candidate_lines=0,
            relaxation_iterations=0,
            step=1.0,
        )
    ) == ("weave.step", 1.0, 0.5)


def test_relax_clamp_reports_requested_and_effective_step() -> None:
    assert _single_diagnostic(
        lambda: relax(_chain(), relaxation_iterations=1, step=1.0)
    ) == ("relax.step", 1.0, 0.5)


def test_sphere_clamp_reports_requested_and_effective_subdivisions() -> None:
    assert _single_diagnostic(lambda: sphere(subdivisions=-1)) == (
        "sphere.subdivisions",
        -1.0,
        0,
    )


def test_trim_clamp_reports_requested_and_effective_start() -> None:
    assert _single_diagnostic(
        lambda: trim(_line(), start_param=-1.0, end_param=0.5)
    ) == ("trim.start_param", -1.0, 0.0)


def test_growth_invalid_mask_reports_empty_fallback() -> None:
    assert _single_diagnostic(
        lambda: growth(_line(), seed_count=1, iters=1)
    ) == ("growth.mask", "invalid_planar_frame", "empty_output")


def test_normal_trim_path_has_no_operation_diagnostic() -> None:
    with operation_diagnostic_context() as diagnostics:
        trim(_line(), start_param=0.2, end_param=0.8)

    assert diagnostics.snapshot() == ()
