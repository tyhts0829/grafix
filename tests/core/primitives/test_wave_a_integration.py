"""Wave A primitive の公開APIと既存 effect との統合を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix import E, G
from grafix.core.realize import RealizeError, RealizeSession, realize
from grafix.core.resource_budget import ResourceBudget, ResourceLimitError
from grafix.core.runtime_limits import RuntimeLimits


def test_wave_a_primitives_are_discoverable_with_complete_metadata() -> None:
    names = {entry.name for entry in G.catalog()}
    assert {"spiral", "spline", "wave"} <= names

    for name in ("spiral", "spline", "wave"):
        entry = G.describe(name)
        assert entry.description
        assert entry.meta
        assert all(meta.description for meta in entry.meta.values())

    assert "points" not in G.describe("spline").meta


def test_wave_a_primitives_realize_as_immutable_content_cached_geometry() -> None:
    geometries = (
        G.spiral(samples=33, turns=1.25),
        G.wave(samples=33, cycles=1.25),
        G.spline(
            points=((-1.0, 0.0), (-0.3, 0.5), (0.4, -0.4), (1.0, 0.0)),
            segments_per_span=8,
        ),
    )

    for geometry in geometries:
        with RealizeSession() as session:
            first = session.realize(geometry)
            second = session.realize(geometry)

        assert first is second
        assert not first.coords.flags.writeable
        assert not first.offsets.flags.writeable
        assert first.coords.dtype == np.float32
        assert first.offsets.dtype == np.int32


def test_wave_a_primitives_compose_with_transform_effects() -> None:
    geometries = (
        G.spiral(samples=17, turns=-1.5),
        G.wave(kind="triangle", samples=17, angle=23.0),
        G.spline(
            points=((0.0, 0.0, 1.0), (0.5, 1.0, 2.0), (1.0, 0.0, 3.0)),
            segments_per_span=8,
        ),
    )
    delta_tuple = (2.0, -3.0, 4.0)
    delta = np.array(delta_tuple, dtype=np.float32)

    for geometry in geometries:
        base = realize(geometry)
        moved = realize(E.translate(delta=delta_tuple)(geometry))

        np.testing.assert_allclose(moved.coords, base.coords + delta, atol=1e-6)
        np.testing.assert_array_equal(moved.offsets, base.offsets)


def test_wave_a_curves_compose_with_topology_effects() -> None:
    spiral = G.spiral(inner_radius=0.1, outer_radius=1.0, turns=2.0, samples=33)
    subdivided = realize(E.subdivide(subdivisions=1)(spiral))
    assert subdivided.coords.shape[0] > 33
    assert np.all(np.isfinite(subdivided.coords))

    wave = G.wave(length=4.0, amplitude=0.5, cycles=3.0, samples=129)
    dashed = realize(
        E.dash(
            dash_length=0.2,
            gap_length=0.1,
            offset=0.0,
            offset_jitter=0.0,
        )(wave)
    )
    assert dashed.offsets.size > 1
    assert np.all(np.isfinite(dashed.coords))

    closed_spline = G.spline(
        points=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
        closed=True,
        tension=0.5,
        segments_per_span=8,
    )
    filled = realize(
        E.fill(
            angle_sets=1,
            angle=30.0,
            density=4.0,
            spacing_gradient=0.0,
            remove_boundary=True,
        )(closed_spline)
    )
    assert filled.offsets.size > 1
    assert np.all(np.isfinite(filled.coords))


def test_wave_a_primitives_receive_realize_session_resource_budget() -> None:
    geometries = (
        G.spiral(samples=5),
        G.wave(samples=5),
        G.spline(
            points=((0.0, 0.0), (1.0, 1.0), (2.0, 0.0)),
            segments_per_span=2,
        ),
    )
    budget = ResourceBudget(
        max_output_vertices=4,
        max_output_lines=1,
        max_output_bytes=10_000,
    )

    for geometry in geometries:
        with RealizeSession(
            runtime_limits=RuntimeLimits(per_operation=budget, scene=budget)
        ) as session:
            with pytest.raises(RealizeError) as exc_info:
                session.realize(geometry)
        assert isinstance(exc_info.value.__cause__, ResourceLimitError)
