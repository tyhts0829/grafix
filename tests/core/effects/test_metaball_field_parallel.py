"""metaball 距離場 kernel の loop 変換と並列実行を exact 比較する。"""

from __future__ import annotations

import math

import numba
import numpy as np
import pytest
from numba import njit  # type: ignore[attr-defined, import-untyped]

import grafix.core.effects.metaball as metaball_module
from grafix.core.operation_diagnostics import operation_diagnostic_context
from grafix.core.preview_quality import preview_quality_context
from grafix.core.realized_geometry import GeomTuple


@njit(cache=True)
def _legacy_field_kernel(
    xs: np.ndarray,
    ys: np.ndarray,
    ring_vertices: np.ndarray,
    ring_offsets: np.ndarray,
    inside_mask: np.ndarray,
    inv_r2: float,
) -> np.ndarray:
    """高速化前と同じ cell→ring→segment 順で距離場を評価する。"""

    ny = int(ys.shape[0])
    nx = int(xs.shape[0])
    n_rings = int(ring_offsets.shape[0]) - 1
    out = np.zeros((ny, nx), dtype=np.float64)
    for j in range(ny):
        y = float(ys[j])
        for i in range(nx):
            x = float(xs[i])
            value = 0.0
            for ring_index in range(n_rings):
                start = int(ring_offsets[ring_index])
                stop = int(ring_offsets[ring_index + 1])
                minimum_distance_sq = 1e300
                for segment_index in range(start, stop - 1):
                    ax = float(ring_vertices[segment_index, 0])
                    ay = float(ring_vertices[segment_index, 1])
                    bx = float(ring_vertices[segment_index + 1, 0])
                    by = float(ring_vertices[segment_index + 1, 1])
                    dx = bx - ax
                    dy = by - ay
                    denominator = dx * dx + dy * dy
                    if denominator <= 0.0:
                        distance_sq = (x - ax) * (x - ax) + (y - ay) * (y - ay)
                    else:
                        position = ((x - ax) * dx + (y - ay) * dy) / denominator
                        if position < 0.0:
                            position = 0.0
                        elif position > 1.0:
                            position = 1.0
                        closest_x = ax + position * dx
                        closest_y = ay + position * dy
                        distance_sq = (x - closest_x) * (x - closest_x) + (y - closest_y) * (
                            y - closest_y
                        )
                    if distance_sq < minimum_distance_sq:
                        minimum_distance_sq = distance_sq
                value += math.exp(-minimum_distance_sq * inv_r2)
            value += float(inside_mask[j, i])
            out[j, i] = value
    return out


def _packed_random_rings(
    rng: np.random.Generator,
    *,
    ring_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    rings = []
    for ring_index in range(ring_count):
        segment_count = int(rng.integers(1, 20))
        points = rng.uniform(-10.0, 10.0, size=(segment_count, 2))
        if segment_count >= 2 and ring_index % 2 == 0:
            points[1] = points[0]
        rings.append(np.concatenate((points, points[:1]), axis=0))
    if not rings:
        return (
            np.empty((0, 2), dtype=np.float64),
            np.asarray([0], dtype=np.int32),
        )
    vertices = np.concatenate(rings, axis=0).astype(np.float64)
    offsets = np.empty((len(rings) + 1,), dtype=np.int32)
    offsets[0] = 0
    np.cumsum(
        np.asarray([len(ring) for ring in rings], dtype=np.int32),
        out=offsets[1:],
    )
    return vertices, offsets


def test_metaball_field_kernel_matches_legacy_bytes_and_preserves_inputs() -> None:
    rng = np.random.default_rng(20260719)
    candidate = metaball_module._evaluate_field_grid_numba

    for _ in range(128):
        nx = int(rng.integers(0, 12))
        ny = int(rng.integers(0, 10))
        xs = np.sort(rng.uniform(-20.0, 20.0, size=nx)).astype(np.float64)
        ys = np.sort(rng.uniform(-20.0, 20.0, size=ny)).astype(np.float64)
        vertices, offsets = _packed_random_rings(
            rng,
            ring_count=int(rng.integers(0, 5)),
        )
        inside = rng.integers(0, 2, size=(ny, nx), dtype=np.uint8)
        inv_r2 = float(10.0 ** rng.uniform(-3.0, 3.0))
        inputs_before = tuple(value.tobytes() for value in (xs, ys, vertices, offsets, inside))

        expected = _legacy_field_kernel(
            xs,
            ys,
            vertices,
            offsets,
            inside,
            inv_r2,
        )
        actual = candidate(
            xs,
            ys,
            vertices,
            offsets,
            inside,
            inv_r2,
        )

        assert actual.tobytes() == expected.tobytes()
        assert actual.dtype == expected.dtype == np.float64
        assert actual.shape == expected.shape
        assert (
            tuple(value.tobytes() for value in (xs, ys, vertices, offsets, inside)) == inputs_before
        )


def test_metaball_packed_kernels_match_baseline_bits() -> None:
    rng = np.random.default_rng(1947)
    xs = np.linspace(-17.0, 19.0, 37, dtype=np.float64)
    ys = np.linspace(-11.0, 13.0, 29, dtype=np.float64)
    vertices, offsets = _packed_random_rings(rng, ring_count=5)
    inside = rng.integers(0, 2, size=(len(ys), len(xs)), dtype=np.uint8)
    args = (xs, ys, vertices, offsets, inside, 0.137)

    expected = metaball_module._evaluate_field_grid_baseline_numba(*args)
    serial = metaball_module._evaluate_field_grid_serial_numba(*args)
    parallel = metaball_module._evaluate_field_grid_parallel_numba(*args)

    assert serial.tobytes() == expected.tobytes()
    assert parallel.tobytes() == expected.tobytes()


def test_metaball_resource_gate_threshold_sides() -> None:
    min_points = metaball_module._PACKED_FIELD_MIN_GRID_POINTS
    assert min_points > 0
    assert not metaball_module._use_packed_field_path(
        nx=min_points - 1,
        ny=1,
        segment_count=1,
        ring_count=1,
    )
    assert metaball_module._use_packed_field_path(
        nx=min_points,
        ny=1,
        segment_count=1,
        ring_count=1,
    )

    cap = metaball_module._PACKED_FIELD_MAX_SEGMENT_SCRATCH_BYTES
    offset_bytes = 2 * metaball_module._PACKED_FIELD_OFFSET_BYTES
    segment_bytes = metaball_module._PACKED_FIELD_SEGMENT_BYTES
    max_segments = (cap - offset_bytes) // segment_bytes
    assert metaball_module._use_packed_field_path(
        nx=16,
        ny=16,
        segment_count=max_segments,
        ring_count=1,
    )
    assert not metaball_module._use_packed_field_path(
        nx=16,
        ny=16,
        segment_count=max_segments + 1,
        ring_count=1,
    )

    max_row_points = (
        metaball_module._PACKED_FIELD_MAX_ROW_SCRATCH_BYTES
        // np.dtype(np.float64).itemsize
    )
    assert metaball_module._use_packed_field_path(
        nx=max_row_points,
        ny=1,
        segment_count=1,
        ring_count=1,
    )
    assert not metaball_module._use_packed_field_path(
        nx=max_row_points + 1,
        ny=1,
        segment_count=1,
        ring_count=1,
    )


def test_metaball_forced_fallback_and_packed_paths_match_bits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(711)
    xs = np.linspace(-9.0, 12.0, 19, dtype=np.float64)
    ys = np.linspace(-8.0, 7.0, 17, dtype=np.float64)
    vertices, offsets = _packed_random_rings(rng, ring_count=4)
    inside = rng.integers(0, 2, size=(len(ys), len(xs)), dtype=np.uint8)
    args = (xs, ys, vertices, offsets, inside, 0.25)

    monkeypatch.setattr(
        metaball_module,
        "_PACKED_FIELD_MIN_GRID_POINTS",
        np.iinfo(np.int64).max,
    )
    fallback = metaball_module._evaluate_field_grid_numba(*args)

    monkeypatch.setattr(
        metaball_module,
        "_PACKED_FIELD_MIN_GRID_POINTS",
        0,
    )
    monkeypatch.setattr(
        metaball_module,
        "_PACKED_FIELD_MAX_SEGMENT_SCRATCH_BYTES",
        np.iinfo(np.int64).max,
    )
    monkeypatch.setattr(metaball_module, "get_num_threads", lambda: 1)
    packed = metaball_module._evaluate_field_grid_numba(*args)

    assert packed.tobytes() == fallback.tobytes()


def _ring(*, sides: int, radius: float) -> np.ndarray:
    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        num=sides,
        endpoint=False,
        dtype=np.float64,
    )
    coords = np.zeros((sides + 1, 3), dtype=np.float32)
    coords[:-1, 0] = (radius * np.cos(angles)).astype(np.float32)
    coords[:-1, 1] = (radius * np.sin(angles)).astype(np.float32)
    coords[-1] = coords[0]
    return coords


def _medium_rings() -> GeomTuple:
    outer = _ring(sides=128, radius=50.0)
    inner = _ring(sides=64, radius=20.0)
    coords = np.concatenate((outer, inner), axis=0)
    offsets = np.asarray([0, len(outer), len(outer) + len(inner)], np.int32)
    angle = math.radians(37.0)
    rotation = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(angle), -math.sin(angle)],
            [0.0, math.sin(angle), math.cos(angle)],
        ],
        dtype=np.float64,
    )
    coords = (
        coords.astype(np.float64) @ rotation.T + np.asarray([13.0, -7.0, 29.0], dtype=np.float64)
    ).astype(np.float32)
    return coords, offsets


@pytest.mark.parametrize("quality", ["draft", "final"])
@pytest.mark.parametrize("output", ["both", "exterior"])
def test_metaball_end_to_end_matches_legacy_field_bytes_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    quality: str,
    output: str,
) -> None:
    geometry = _medium_rings()
    candidate = metaball_module._evaluate_field_grid_numba
    kwargs = {
        "radius": 5.0,
        "threshold": 1.0,
        "grid_pitch": 0.5,
        "output": output,
        "keep_original": True,
    }

    monkeypatch.setattr(
        metaball_module,
        "_evaluate_field_grid_numba",
        _legacy_field_kernel,
    )
    with operation_diagnostic_context() as expected_diagnostics:
        with preview_quality_context(quality):  # type: ignore[arg-type]
            expected = metaball_module.metaball(geometry, **kwargs)

    monkeypatch.setattr(
        metaball_module,
        "_evaluate_field_grid_numba",
        candidate,
    )
    with operation_diagnostic_context() as actual_diagnostics:
        with preview_quality_context(quality):  # type: ignore[arg-type]
            actual = metaball_module.metaball(geometry, **kwargs)

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()
    assert actual[0].dtype == expected[0].dtype == np.float32
    assert actual[1].dtype == expected[1].dtype == np.int32
    assert actual_diagnostics.snapshot() == expected_diagnostics.snapshot()


def test_metaball_parallel_thread_counts_are_exact_when_available() -> None:
    rng = np.random.default_rng(47)
    xs = np.linspace(-15.0, 15.0, 81, dtype=np.float64)
    ys = np.linspace(-12.0, 12.0, 71, dtype=np.float64)
    vertices, offsets = _packed_random_rings(rng, ring_count=4)
    inside = rng.integers(0, 2, size=(len(ys), len(xs)), dtype=np.uint8)
    candidate = metaball_module._evaluate_field_grid_numba
    previous_threads = numba.get_num_threads()
    maximum_threads = int(numba.config.NUMBA_NUM_THREADS)
    reference: bytes | None = None
    try:
        for thread_count in (1, 2, 4):
            if thread_count > maximum_threads:
                continue
            numba.set_num_threads(thread_count)
            result = candidate(
                xs,
                ys,
                vertices,
                offsets,
                inside,
                0.125,
            )
            raw = result.tobytes()
            if reference is None:
                reference = raw
            assert raw == reference
    finally:
        numba.set_num_threads(previous_threads)


@pytest.mark.parametrize(
    ("segment_count", "thread_count", "expected_kernel"),
    [
        (999, 4, "serial"),
        (1_000, 4, "parallel"),
        (1_000, 1, "serial"),
    ],
)
def test_metaball_parallel_dispatch_threshold(
    monkeypatch: pytest.MonkeyPatch,
    segment_count: int,
    thread_count: int,
    expected_kernel: str,
) -> None:
    xs = np.zeros((10,), dtype=np.float64)
    ys = np.zeros((10,), dtype=np.float64)
    vertices = np.zeros((segment_count + 1, 2), dtype=np.float64)
    offsets = np.asarray([0, segment_count + 1], dtype=np.int32)
    inside = np.zeros((10, 10), dtype=np.uint8)

    def serial(*args: object) -> np.ndarray:
        return np.asarray([[1.0]], dtype=np.float64)

    def parallel(*args: object) -> np.ndarray:
        return np.asarray([[2.0]], dtype=np.float64)

    monkeypatch.setattr(
        metaball_module,
        "_PACKED_FIELD_MIN_GRID_POINTS",
        0,
    )
    monkeypatch.setattr(metaball_module, "get_num_threads", lambda: thread_count)
    monkeypatch.setattr(
        metaball_module,
        "_evaluate_field_grid_serial_numba",
        serial,
    )
    monkeypatch.setattr(
        metaball_module,
        "_evaluate_field_grid_parallel_numba",
        parallel,
    )
    result = metaball_module._evaluate_field_grid_numba(
        xs,
        ys,
        vertices,
        offsets,
        inside,
        1.0,
    )

    expected_value = 1.0 if expected_kernel == "serial" else 2.0
    assert result.item() == expected_value
