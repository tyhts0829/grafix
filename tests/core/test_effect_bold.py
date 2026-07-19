"""core.effects.bold をテスト。"""

from __future__ import annotations

import math
import warnings

import numpy as np

from grafix.core.effects.bold import bold
from grafix.core.realized_geometry import GeomTuple


def _geometry(*, coords: list[tuple[float, float, float]], offsets: list[int]) -> GeomTuple:
    c = np.asarray(coords, dtype=np.float32)
    o = np.asarray(offsets, dtype=np.int32)
    return c, o


def _legacy_bold_reference(
    g: GeomTuple,
    *,
    count: int,
    radius: float,
    seed: int,
) -> GeomTuple:
    """高速化前と同じ copy-major loop で active-path の期待値を作る。"""

    coords, offsets = g
    copies = int(count)
    n_vertices = int(coords.shape[0])
    n_lines = int(offsets.size) - 1

    rng = np.random.default_rng(int(seed))
    u = rng.random(copies - 1)
    v = rng.random(copies - 1)
    sampled_radius = float(radius) * np.sqrt(u)
    theta = 2.0 * math.pi * v
    offsets_xy = np.zeros((copies, 2), dtype=np.float64)
    offsets_xy[1:, 0] = sampled_radius * np.cos(theta)
    offsets_xy[1:, 1] = sampled_radius * np.sin(theta)

    base_coords64 = coords.astype(np.float64, copy=False)
    out_coords64 = np.empty((n_vertices * copies, 3), dtype=np.float64)
    for copy_index in range(copies):
        start = copy_index * n_vertices
        end = start + n_vertices
        out_coords64[start:end] = base_coords64
        out_coords64[start:end, 0] += offsets_xy[copy_index, 0]
        out_coords64[start:end, 1] += offsets_xy[copy_index, 1]

    tail = offsets[1:].astype(np.int64, copy=False)
    out_offsets = np.empty((n_lines * copies + 1,), dtype=np.int32)
    out_offsets[0] = 0
    for copy_index in range(copies):
        start = 1 + copy_index * n_lines
        end = start + n_lines
        out_offsets[start:end] = (
            tail + copy_index * n_vertices
        ).astype(np.int32, copy=False)

    return out_coords64.astype(np.float32, copy=False), out_offsets


def test_bold_empty_inputs_returns_empty_geometry() -> None:
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    out_coords, out_offsets = bold((coords, offsets))
    assert out_coords.shape == (0, 3)
    assert out_coords.dtype == np.float32
    assert out_offsets.tolist() == [0]
    assert out_offsets.dtype == np.int32


def test_bold_count_le_1_is_noop() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)],
        offsets=[0, 2],
    )
    out_coords, out_offsets = bold((base_coords, base_offsets), count=1, radius=1.0)
    assert out_coords is base_coords
    assert out_offsets is base_offsets


def test_bold_radius_le_0_is_noop() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)],
        offsets=[0, 2],
    )
    out_coords, out_offsets = bold((base_coords, base_offsets), count=3, radius=0.0)
    assert out_coords is base_coords
    assert out_offsets is base_offsets


def test_bold_repeats_geometry_and_preserves_offsets_structure() -> None:
    base_coords, base_offsets = _geometry(
        coords=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 1.0, 0.0),
            (10.0, 2.0, 0.0),
        ],
        offsets=[0, 2, 5],
    )

    out_coords, out_offsets = bold((base_coords, base_offsets), count=3, radius=1.0, seed=123)

    assert out_coords.dtype == np.float32
    assert out_offsets.dtype == np.int32

    assert out_coords.shape == (15, 3)
    assert out_offsets.tolist() == [0, 2, 5, 7, 10, 12, 15]

    n = int(base_coords.shape[0])
    assert np.allclose(out_coords[:n], base_coords, atol=1e-6)

    for k in range(3):
        s = k * n
        e = s + n
        delta = out_coords[s:e].astype(np.float64, copy=False) - base_coords.astype(
            np.float64, copy=False
        )
        assert np.allclose(delta[:, 2], 0.0, atol=1e-6)
        assert np.allclose(delta[:, 0], delta[0, 0], atol=1e-6)
        assert np.allclose(delta[:, 1], delta[0, 1], atol=1e-6)


def test_bold_is_deterministic_for_same_seed() -> None:
    base_coords, base_offsets = _geometry(
        coords=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        offsets=[0, 3],
    )

    out1_coords, out1_offsets = bold((base_coords, base_offsets), count=5, radius=1.0, seed=999)
    out2_coords, out2_offsets = bold((base_coords, base_offsets), count=5, radius=1.0, seed=999)

    assert out1_offsets.tolist() == out2_offsets.tolist()
    assert np.allclose(out1_coords, out2_coords, atol=0.0)


def test_bold_packed_output_matches_legacy_bytes_for_random_inputs() -> None:
    rng = np.random.default_rng(20260719)

    for case_index in range(128):
        n_lines = int(rng.integers(1, 9))
        lengths = rng.integers(0, 9, size=n_lines, dtype=np.int32)
        if not np.any(lengths):
            lengths[0] = 1
        offsets = np.empty(n_lines + 1, dtype=np.int32)
        offsets[0] = 0
        np.cumsum(lengths, out=offsets[1:])
        coords = rng.normal(size=(int(offsets[-1]), 3)).astype(np.float32)
        coords.flat[case_index % coords.size] = np.float32(-0.0)
        coords_before = coords.tobytes()
        offsets_before = offsets.tobytes()
        count = int(rng.integers(2, 17))
        radius = float(10.0 ** rng.uniform(-7.0, 5.0))
        seed = int(rng.integers(0, 2**31 - 1))

        expected_coords, expected_offsets = _legacy_bold_reference(
            (coords, offsets),
            count=count,
            radius=radius,
            seed=seed,
        )
        actual_coords, actual_offsets = bold(
            (coords, offsets),
            count=count,
            radius=radius,
            seed=seed,
        )

        assert actual_coords.tobytes() == expected_coords.tobytes()
        assert actual_offsets.tobytes() == expected_offsets.tobytes()
        assert actual_coords.dtype == expected_coords.dtype == np.float32
        assert actual_offsets.dtype == expected_offsets.dtype == np.int32
        assert actual_coords.shape == expected_coords.shape
        assert actual_offsets.shape == expected_offsets.shape
        assert actual_coords.strides == expected_coords.strides
        assert actual_offsets.strides == expected_offsets.strides
        assert actual_coords.flags.owndata == expected_coords.flags.owndata
        assert coords.tobytes() == coords_before
        assert offsets.tobytes() == offsets_before


def test_bold_packed_output_is_exact_for_supported_array_layouts() -> None:
    rng = np.random.default_rng(91)
    base = rng.normal(size=(24, 3)).astype(np.float32)
    layouts = (
        np.asfortranarray(base),
        base[::-2],
        base.copy(),
    )
    layouts[-1].flags.writeable = False

    for coords in layouts:
        offsets = np.asarray([0, 3, int(coords.shape[0])], dtype=np.int32)
        expected = _legacy_bold_reference(
            (coords, offsets),
            count=7,
            radius=0.625,
            seed=47,
        )
        actual = bold((coords, offsets), count=7, radius=0.625, seed=47)

        assert actual[0].tobytes() == expected[0].tobytes()
        assert actual[1].tobytes() == expected[1].tobytes()


def test_bold_nonfinite_warning_behavior_matches_legacy_path() -> None:
    coords = np.asarray(
        [
            (np.inf, 0.0, 0.0),
            (-np.inf, -0.0, 1.0),
            (np.nan, 2.0, 3.0),
        ],
        dtype=np.float32,
    )
    coords.view(np.uint32)[0, 0] = np.uint32(0x7F800001)
    offsets = np.asarray([0, 3], dtype=np.int32)

    with warnings.catch_warnings(record=True) as expected_warnings:
        warnings.simplefilter("always")
        with np.errstate(all="warn"):
            expected = _legacy_bold_reference(
                (coords, offsets),
                count=5,
                radius=0.75,
                seed=13,
            )
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter("always")
        with np.errstate(all="warn"):
            actual = bold((coords, offsets), count=5, radius=0.75, seed=13)

    assert actual[0].tobytes() == expected[0].tobytes()
    assert actual[1].tobytes() == expected[1].tobytes()
    assert [
        (item.category, str(item.message)) for item in actual_warnings
    ] == [
        (item.category, str(item.message)) for item in expected_warnings
    ]
