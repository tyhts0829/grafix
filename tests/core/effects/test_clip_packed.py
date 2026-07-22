"""clip の一括 path 変換と world 座標復元を exact 比較する。"""

from __future__ import annotations

import math

import numpy as np
import pytest

import grafix.core.effects.clip as clip_module
from grafix.core.effects.clip import (
    _int_paths_from_scaled,
    _restore_and_pack_int_paths,
    _to_int_path_open,
    _to_int_path_ring,
)
from grafix.core.geometry_kernels.packed import pack_polylines
from grafix.core.geometry_kernels.planar import PlanarFrame
from grafix.core.realized_geometry import GeomTuple


def _pack(lines: list[np.ndarray]) -> GeomTuple:
    coords = np.concatenate(lines, axis=0).astype(np.float32, copy=False)
    offsets = np.empty((len(lines) + 1,), dtype=np.int32)
    offsets[0] = 0
    np.cumsum(
        np.asarray([line.shape[0] for line in lines], dtype=np.int32),
        out=offsets[1:],
    )
    return coords, offsets


def _ring(*, sides: int, radius: float) -> np.ndarray:
    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        num=sides,
        endpoint=False,
        dtype=np.float64,
    )
    points = np.zeros((sides + 1, 3), dtype=np.float64)
    points[:-1, 0] = radius * np.cos(angles)
    points[:-1, 1] = radius * np.sin(angles)
    points[-1] = points[0]
    return points.astype(np.float32)


def _tilt(g: GeomTuple) -> GeomTuple:
    ax, ay, az = (math.radians(value) for value in (37.0, -23.0, 71.0))
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.asarray([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], np.float64)
    ry = np.asarray([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float64)
    rz = np.asarray([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], np.float64)
    matrix = rz @ ry @ rx
    coords = (
        g[0].astype(np.float64) @ matrix.T
        + np.asarray([13.0, -29.0, 41.0], dtype=np.float64)
    ).astype(np.float32)
    return coords, g[1].copy()


def _tilted_clip_fixture() -> tuple[GeomTuple, GeomTuple]:
    ys = np.linspace(-15.0, 15.0, num=257, dtype=np.float32)
    lines = [
        np.asarray([[-20.0, y, 0.0], [20.0, y, 0.0]], dtype=np.float32)
        for y in ys
    ]
    base = _pack(lines)
    mask = _pack([_ring(sides=128, radius=12.0), _ring(sides=64, radius=4.0)])
    return _tilt(base), _tilt(mask)


def test_batch_quantization_preserves_duplicate_and_endpoint_rules() -> None:
    rng = np.random.default_rng(20260719)
    lengths = rng.integers(0, 12, size=256, dtype=np.int32)
    offsets = np.empty((lengths.size + 1,), dtype=np.int32)
    offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    xy = rng.uniform(-3.0, 3.0, size=(int(offsets[-1]), 2))
    scaled = np.rint(xy * 1000.0).astype(np.int64)
    if scaled.shape[0] >= 8:
        scaled[1] = scaled[0]
        scaled[7] = scaled[6]

    expected_open = []
    expected_ring = []
    for index in range(int(offsets.size) - 1):
        start = int(offsets[index])
        stop = int(offsets[index + 1])
        open_path = _to_int_path_open(scaled[start:stop] / 1000.0, 1000)
        ring_path = _to_int_path_ring(scaled[start:stop] / 1000.0, 1000)
        if open_path is not None:
            expected_open.append(open_path)
        if ring_path is not None:
            expected_ring.append(ring_path)

    assert (
        _int_paths_from_scaled(scaled, offsets, min_vertices=2)
        == expected_open
    )
    assert (
        _int_paths_from_scaled(scaled, offsets, min_vertices=3)
        == expected_ring
    )


@pytest.mark.parametrize(
    "paths",
    [
        [
            [(-1000, 0), (1000, 0)],
            [(-1000, 500), (1000, 500)],
            [(-1000, 1000), (1000, 1000)],
        ],
        [
            [(-1000, 0), (0, 250), (1000, 0)],
            [(-1000, 1000), (-500, 1250), (0, 1000), (500, 750), (1000, 1000)],
        ],
    ],
)
def test_restore_and_pack_paths_matches_per_path_world_transform(
    paths: list[list[tuple[int, int]]],
) -> None:
    _, mask = _tilted_clip_fixture()
    frame = PlanarFrame.from_points(*mask)
    lines = []
    for path in paths:
        xy = np.asarray(path, dtype=np.float64) / 1000.0
        local = np.zeros((len(path), 3), dtype=np.float64)
        local[:, 0:2] = xy
        lines.append(frame.to_world(local))
    expected = pack_polylines(lines)

    actual = _restore_and_pack_int_paths(paths, frame=frame, scale=1000)

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()


def test_clip_batch_resource_limits_cover_primary_case_with_bounded_scratch() -> None:
    estimated_peak = (
        clip_module._BATCH_PATH_MAX_TOTAL_VERTICES * 384
        + clip_module._BATCH_PATH_MAX_TOTAL_LINES * 256
    )

    assert estimated_peak <= 8 * 1024 * 1024
    assert 2_770 <= clip_module._BATCH_PATH_MAX_TOTAL_VERTICES
    assert 1_002 <= clip_module._BATCH_PATH_MAX_TOTAL_LINES


@pytest.mark.parametrize("limited_resource", ["vertices", "lines"])
def test_clip_batch_resource_limit_boundary_matches_fallback_observably(
    monkeypatch: pytest.MonkeyPatch,
    limited_resource: str,
) -> None:
    base, mask = _tilted_clip_fixture()
    inputs = (base[0], base[1], mask[0], mask[1])
    before = tuple(array.tobytes() for array in inputs)
    for array in inputs:
        array.setflags(write=False)

    total_vertices = int(base[0].shape[0] + mask[0].shape[0])
    total_lines = int(base[1].size + mask[1].size - 2)
    monkeypatch.setattr(
        clip_module,
        "_BATCH_PATH_MAX_TOTAL_VERTICES",
        total_vertices,
    )
    monkeypatch.setattr(
        clip_module,
        "_BATCH_PATH_MAX_TOTAL_LINES",
        total_lines,
    )

    original_convert = clip_module._int_paths_from_scaled
    convert_calls = 0

    def _spy_convert(
        scaled: np.ndarray,
        offsets: np.ndarray,
        *,
        min_vertices: int,
    ) -> list[list[tuple[int, int]]]:
        nonlocal convert_calls
        convert_calls += 1
        return original_convert(
            scaled,
            offsets,
            min_vertices=min_vertices,
        )

    monkeypatch.setattr(clip_module, "_int_paths_from_scaled", _spy_convert)
    fast = clip_module.clip(
        base,
        mask,
        mode="inside",
        draw_outline=False,
    )
    assert convert_calls == 2

    if limited_resource == "vertices":
        monkeypatch.setattr(
            clip_module,
            "_BATCH_PATH_MAX_TOTAL_VERTICES",
            total_vertices - 1,
        )
    else:
        monkeypatch.setattr(
            clip_module,
            "_BATCH_PATH_MAX_TOTAL_LINES",
            total_lines - 1,
        )
    fallback = clip_module.clip(
        base,
        mask,
        mode="inside",
        draw_outline=False,
    )

    assert convert_calls == 2
    assert fast[0].tobytes() == fallback[0].tobytes()
    assert fast[1].tobytes() == fallback[1].tobytes()
    assert fast[0].dtype == fallback[0].dtype == np.float32
    assert fast[1].dtype == fallback[1].dtype == np.int32
    assert fast[0].strides == fallback[0].strides
    assert fast[1].strides == fallback[1].strides
    assert not np.shares_memory(fast[0], base[0])
    assert not np.shares_memory(fallback[0], base[0])
    assert tuple(array.tobytes() for array in inputs) == before
    assert all(not array.flags.writeable for array in inputs)
