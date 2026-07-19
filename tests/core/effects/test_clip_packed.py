"""clip の一括 path 変換と world 座標復元を exact 比較する。"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pyclipper  # type: ignore[import-not-found, import-untyped]
import pytest

import grafix.core.effects.clip as clip_module
from grafix.core.effects.clip import (
    _int_paths_from_scaled,
    _restore_and_pack_int_paths,
    _to_int_path_open,
    _to_int_path_ring,
    clip,
)
from grafix.core.effects.util import PlanarFrame, empty_geom, pack_polylines
from grafix.core.operation_diagnostics import operation_diagnostic_context
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


def _legacy_active_clip(
    base: GeomTuple,
    mask: GeomTuple,
    *,
    mode: str,
    draw_outline: bool,
) -> GeomTuple:
    """高速化前と同じ per-line 変換・復元で active path の期待値を作る。"""

    scale = 1000
    base_coords, base_offsets = base
    mask_coords, mask_offsets = mask
    frame = PlanarFrame.from_points(mask_coords, mask_offsets)
    aligned_base = frame.to_local(base_coords)
    aligned_mask = frame.to_local(mask_coords)

    subject_paths: list[list[tuple[int, int]]] = []
    for index in range(int(base_offsets.size) - 1):
        start = int(base_offsets[index])
        stop = int(base_offsets[index + 1])
        path = _to_int_path_open(aligned_base[start:stop, 0:2], scale)
        if path is not None:
            subject_paths.append(path)

    clip_paths: list[list[tuple[int, int]]] = []
    for index in range(int(mask_offsets.size) - 1):
        start = int(mask_offsets[index])
        stop = int(mask_offsets[index + 1])
        path = _to_int_path_ring(aligned_mask[start:stop, 0:2], scale)
        if path is not None:
            clip_paths.append(path)

    outline_lines: list[np.ndarray] = []
    if draw_outline:
        for ring in clip_paths:
            xy = np.asarray(ring + [ring[0]], dtype=np.float64) / float(scale)
            local = np.zeros((xy.shape[0], 3), dtype=np.float64)
            local[:, 0:2] = xy
            outline_lines.append(frame.to_world(local))

    pc = pyclipper.Pyclipper()  # type: ignore[attr-defined]
    pc.AddPaths(subject_paths, pyclipper.PT_SUBJECT, False)  # type: ignore[attr-defined]
    pc.AddPaths(clip_paths, pyclipper.PT_CLIP, True)  # type: ignore[attr-defined]
    cliptype = (
        pyclipper.CT_INTERSECTION  # type: ignore[attr-defined]
        if mode == "inside"
        else pyclipper.CT_DIFFERENCE  # type: ignore[attr-defined]
    )
    tree = pc.Execute2(  # type: ignore[attr-defined]
        cliptype,
        pyclipper.PFT_EVENODD,  # type: ignore[attr-defined]
        pyclipper.PFT_EVENODD,  # type: ignore[attr-defined]
    )
    out_paths = pyclipper.OpenPathsFromPolyTree(tree)  # type: ignore[attr-defined]

    out_lines: list[np.ndarray] = []
    for path in out_paths:
        if len(path) < 2:  # type: ignore[arg-type]
            continue
        xy = np.asarray(path, dtype=np.float64) / float(scale)
        local = np.zeros((xy.shape[0], 3), dtype=np.float64)
        local[:, 0:2] = xy
        out_lines.append(frame.to_world(local))
    out_lines.extend(outline_lines)
    return pack_polylines(out_lines) if out_lines else empty_geom()


def _tilted_clip_fixture() -> tuple[GeomTuple, GeomTuple]:
    ys = np.linspace(-15.0, 15.0, num=257, dtype=np.float32)
    lines = [
        np.asarray([[-20.0, y, 0.0], [20.0, y, 0.0]], dtype=np.float32)
        for y in ys
    ]
    base = _pack(lines)
    mask = _pack([_ring(sides=128, radius=12.0), _ring(sides=64, radius=4.0)])
    return _tilt(base), _tilt(mask)


@pytest.mark.parametrize(
    ("mode", "draw_outline"),
    [
        ("inside", False),
        ("outside", False),
        ("inside", True),
        ("outside", True),
    ],
)
def test_clip_batch_pipeline_matches_legacy_bytes(
    mode: str,
    draw_outline: bool,
) -> None:
    base, mask = _tilted_clip_fixture()
    base_before = (base[0].tobytes(), base[1].tobytes())
    mask_before = (mask[0].tobytes(), mask[1].tobytes())

    expected = _legacy_active_clip(
        base,
        mask,
        mode=mode,
        draw_outline=draw_outline,
    )
    actual = clip(
        base,
        mask,
        mode=mode,
        draw_outline=draw_outline,
    )

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()
    assert actual[0].dtype == expected[0].dtype == np.float32
    assert actual[1].dtype == expected[1].dtype == np.int32
    assert actual[0].shape == expected[0].shape
    assert actual[1].shape == expected[1].shape
    assert actual[0].strides == expected[0].strides
    assert actual[1].strides == expected[1].strides
    assert actual[0].flags.owndata == expected[0].flags.owndata
    assert (base[0].tobytes(), base[1].tobytes()) == base_before
    assert (mask[0].tobytes(), mask[1].tobytes()) == mask_before


@pytest.mark.parametrize("layout", ["fortran", "strided", "readonly"])
def test_clip_batch_pipeline_preserves_array_layout_behavior(layout: str) -> None:
    base, mask = _tilted_clip_fixture()
    if layout == "fortran":
        base = np.asfortranarray(base[0]), base[1]
        mask = np.asfortranarray(mask[0]), mask[1]
    elif layout == "strided":
        base_storage = np.empty((base[0].shape[0], 6), dtype=np.float32)
        mask_storage = np.empty((mask[0].shape[0], 6), dtype=np.float32)
        base_storage[:, 0::2] = base[0]
        mask_storage[:, 0::2] = mask[0]
        base = base_storage[:, 0::2], base[1]
        mask = mask_storage[:, 0::2], mask[1]
    else:
        base[0].flags.writeable = False
        base[1].flags.writeable = False
        mask[0].flags.writeable = False
        mask[1].flags.writeable = False

    expected = _legacy_active_clip(
        base,
        mask,
        mode="inside",
        draw_outline=False,
    )
    actual = clip(base, mask, mode="inside", draw_outline=False)

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()


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
    with (
        warnings.catch_warnings(record=True) as fast_warnings,
        operation_diagnostic_context() as fast_diagnostics,
    ):
        warnings.simplefilter("always")
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
    with (
        warnings.catch_warnings(record=True) as fallback_warnings,
        operation_diagnostic_context() as fallback_diagnostics,
    ):
        warnings.simplefilter("always")
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
    assert [str(item.message) for item in fast_warnings] == [
        str(item.message) for item in fallback_warnings
    ]
    assert [item.category for item in fast_warnings] == [
        item.category for item in fallback_warnings
    ]
    assert fast_diagnostics.snapshot() == fallback_diagnostics.snapshot()
    assert tuple(array.tobytes() for array in inputs) == before
    assert all(not array.flags.writeable for array in inputs)
