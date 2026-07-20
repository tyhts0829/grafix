"""highpass effect（高周波強調）の実体変換に関するテスト群。"""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from numba import njit  # type: ignore[attr-defined, import-untyped]

from grafix.api import E, G
from grafix.core.effects.highpass import (
    MAX_KERNEL_RADIUS,
    MAX_TOTAL_VERTICES,
    highpass,
)
from grafix.core.effects.util import (
    RESAMPLE_CLOSED_DISTANCE_EPS,
    ResamplePlan,
    build_gaussian_kernel,
    pack_polylines,
    resample_polylines,
)
from grafix.core.primitive_registry import primitive
from grafix.core.realize import realize
from grafix.core.realized_geometry import GeomTuple


@njit(cache=False, fastmath=True)  # type: ignore[misc]
def _legacy_reflect_index(i: int, n: int) -> int:
    j = int(i)
    nn = int(n)
    if nn <= 1:
        return 0
    while j < 0 or j >= nn:
        if j < 0:
            j = -j
        elif j >= nn:
            j = 2 * nn - 2 - j
    return int(j)


@njit(cache=False, fastmath=True)  # type: ignore[misc]
def _legacy_highpass_reflect(
    points: np.ndarray,
    kernel: np.ndarray,
    gain: float,
) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 1:
        return points

    gain_size = float(gain)
    radius = int(kernel.shape[0] // 2)
    out = np.empty_like(points)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-radius, radius + 1):
            j = _legacy_reflect_index(i + k, n)
            weight = float(kernel[k + radius])
            ax += weight * float(points[j, 0])
            ay += weight * float(points[j, 1])
            az += weight * float(points[j, 2])
        bx = float(points[i, 0])
        by = float(points[i, 1])
        bz = float(points[i, 2])
        out[i, 0] = np.float32(bx + gain_size * (bx - ax))
        out[i, 1] = np.float32(by + gain_size * (by - ay))
        out[i, 2] = np.float32(bz + gain_size * (bz - az))
    return out


@njit(cache=False, fastmath=True)  # type: ignore[misc]
def _legacy_highpass_wrap(
    points: np.ndarray,
    kernel: np.ndarray,
    gain: float,
) -> np.ndarray:
    n = int(points.shape[0])
    if n <= 0:
        return points

    gain_size = float(gain)
    radius = int(kernel.shape[0] // 2)
    out = np.empty_like(points)
    for i in range(n):
        ax = 0.0
        ay = 0.0
        az = 0.0
        for k in range(-radius, radius + 1):
            j = (i + k) % n
            weight = float(kernel[k + radius])
            ax += weight * float(points[j, 0])
            ay += weight * float(points[j, 1])
            az += weight * float(points[j, 2])
        bx = float(points[i, 0])
        by = float(points[i, 1])
        bz = float(points[i, 2])
        out[i, 0] = np.float32(bx + gain_size * (bx - ax))
        out[i, 1] = np.float32(by + gain_size * (by - ay))
        out[i, 2] = np.float32(bz + gain_size * (bz - az))
    return out


def _legacy_highpass(
    g: GeomTuple,
    *,
    step: float,
    sigma: float,
    gain: float,
    closed: str,
) -> GeomTuple:
    coords, offsets = g
    plan = ResamplePlan.from_geometry(
        coords,
        offsets,
        step=step,
        closed=closed,
        max_vertices=MAX_TOTAL_VERTICES,
        closed_distance=RESAMPLE_CLOSED_DISTANCE_EPS,
    )
    kernel = build_gaussian_kernel(
        sigma_in_samples=sigma / step,
        max_radius=MAX_KERNEL_RADIUS,
    )
    resampled, offsets_out = resample_polylines(coords, plan)
    coords_out = np.empty_like(resampled)
    for line in plan.lines:
        source = resampled[line.output_start : line.output_stop]
        target = coords_out[line.output_start : line.output_stop]
        if line.closed:
            filtered = _legacy_highpass_wrap(source[:-1], kernel, gain)
            target[:-1] = filtered
            target[-1] = filtered[0]
        else:
            target[:] = _legacy_highpass_reflect(source, kernel, gain)
    return coords_out, offsets_out


@primitive
def highpass_test_zigzag() -> GeomTuple:
    """交互に上下するジグザグ線を返す（高周波強調の確認用）。"""
    n = 101
    x = np.arange(n, dtype=np.float32)
    y = np.where((np.arange(n) % 2) == 0, 1.0, -1.0).astype(np.float32)
    coords = np.stack([x, y, np.zeros_like(x)], axis=1).astype(np.float32, copy=False)
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


@primitive
def highpass_test_almost_closed_square() -> GeomTuple:
    """ほぼ閉じた四角形（端点が近い）を返す（auto closed の確認用）。"""
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 10.0, 0.0],
            [0.0, 10.0, 0.0],
            [0.005, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    offsets = np.array([0, coords.shape[0]], dtype=np.int32)
    return coords, offsets


def test_highpass_noop_when_gain_is_zero() -> None:
    g = G.highpass_test_zigzag()
    base = realize(g)
    out = realize(E.highpass(step=1.0, sigma=3.0, gain=0.0)(g))

    np.testing.assert_allclose(out.coords, base.coords, rtol=0.0, atol=0.0)
    assert out.offsets.tolist() == base.offsets.tolist()


def test_highpass_increases_zigzag_energy() -> None:
    g = G.highpass_test_zigzag()
    base = realize(g)
    out = realize(E.highpass(step=1.0, sigma=10.0, gain=3.0, closed="open")(g))

    base_y = base.coords[:, 1]
    out_y = out.coords[:, 1]
    assert float(np.std(out_y)) > float(np.std(base_y)) * 1.5


def test_highpass_auto_closed_outputs_closed_polyline() -> None:
    g = G.highpass_test_almost_closed_square()
    out = realize(E.highpass(step=2.0, sigma=2.0, gain=1.0, closed="auto")(g))

    assert out.offsets.tolist() == [0, out.coords.shape[0]]
    assert out.coords.shape[0] >= 4
    assert np.array_equal(out.coords[0], out.coords[out.coords.shape[0] - 1])


def test_highpass_open_and_closed_match_legacy_coefficients_bitwise() -> None:
    open_coords = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 2.0, -1.0], [2.0, 0.0, 3.0]],
        dtype=np.float32,
    )
    closed_coords = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 2.0], [0.0, 0.0, 0.0]],
        dtype=np.float32,
    )

    open_out, open_offsets = highpass(
        (open_coords, np.asarray([0, 3], dtype=np.int32)),
        step=3.0,
        sigma=3.0,
        gain=1.5,
        closed="open",
    )
    closed_out, closed_offsets = highpass(
        (closed_coords, np.asarray([0, 4], dtype=np.int32)),
        step=2.0,
        sigma=2.0,
        gain=1.5,
        closed="closed",
    )
    expected_open, expected_open_offsets = _legacy_highpass(
        (open_coords, np.asarray([0, 3], dtype=np.int32)),
        step=3.0,
        sigma=3.0,
        gain=1.5,
        closed="open",
    )
    expected_closed, expected_closed_offsets = _legacy_highpass(
        (closed_coords, np.asarray([0, 4], dtype=np.int32)),
        step=2.0,
        sigma=2.0,
        gain=1.5,
        closed="closed",
    )

    np.testing.assert_array_equal(
        open_out.view(np.uint32).reshape(-1),
        expected_open.view(np.uint32).reshape(-1),
    )
    np.testing.assert_array_equal(
        closed_out.view(np.uint32).reshape(-1),
        expected_closed.view(np.uint32).reshape(-1),
    )
    np.testing.assert_array_equal(open_offsets, expected_open_offsets)
    np.testing.assert_array_equal(closed_offsets, expected_closed_offsets)
    np.testing.assert_array_equal(closed_out[0], closed_out[-1])


def test_highpass_packed_lines_match_independent_processing_bitwise() -> None:
    lines = [
        np.empty((0, 3), dtype=np.float32),
        np.asarray([[-0.0, 0.0, -0.0]], dtype=np.float32),
        np.asarray(
            [[0.0, 0.0, 0.0], [0.75, 1.0, -0.5], [2.0, -0.5, 0.25]],
            dtype=np.float32,
        ),
        np.asarray(
            [[4.0, 0.0, 0.0], [6.0, 0.0, 1.0], [5.0, 2.0, 2.0], [4.0, 0.0, 0.0]],
            dtype=np.float32,
        ),
        np.asarray(
            [[8.0, 0.0, 0.0], [9.0, 1.0, -1.0], [8.005, 0.0, 0.0]],
            dtype=np.float32,
        ),
    ]
    packed = pack_polylines(lines)

    combined = highpass(
        packed,
        step=0.6,
        sigma=1.1,
        gain=-1.25,
        closed="auto",
    )
    independent_lines = [
        highpass(
            (line, np.asarray([0, line.shape[0]], dtype=np.int32)),
            step=0.6,
            sigma=1.1,
            gain=-1.25,
            closed="auto",
        )[0]
        for line in lines
    ]
    expected = pack_polylines(independent_lines)

    np.testing.assert_array_equal(
        combined[0].view(np.uint32),
        expected[0].view(np.uint32),
    )
    np.testing.assert_array_equal(combined[1], expected[1])


def test_highpass_vertex_cap_returns_original_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("grafix.core.effects.highpass")
    coords = np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.asarray([0, 2], dtype=np.int32)
    monkeypatch.setattr(module, "MAX_TOTAL_VERTICES", 3)

    coords_out, offsets_out = module.highpass(
        (coords, offsets),
        step=0.5,
        sigma=1.0,
        gain=1.0,
        closed="open",
    )

    assert coords_out is coords
    assert offsets_out is offsets
