"""dash effect の破線化に関するテスト群。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix.api import E, G
from grafix.core.operation_authoring import primitive
from grafix.core.realize import RealizeError, realize
from grafix.core.realized_geometry import GeomTuple, RealizedGeometry


@primitive
def dash_test_line_0_10() -> GeomTuple:
    """x 軸上の 2 点ポリライン（長さ 10）を返す。"""
    coords = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], dtype=np.float32)
    offsets = np.array([0, 2], dtype=np.int32)
    return coords, offsets


@primitive
def dash_test_empty() -> GeomTuple:
    """空のジオメトリを返す。"""
    coords = np.zeros((0, 3), dtype=np.float32)
    offsets = np.zeros((1,), dtype=np.int32)
    return coords, offsets


@primitive
def dash_test_zero_then_line() -> GeomTuple:
    """長さ 0 の線と x 軸上の長さ 10 の線を順に返す。"""
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    return coords, np.array([0, 2, 4], dtype=np.int32)


def _iter_polylines(realized: RealizedGeometry):
    offsets = realized.offsets
    for i in range(len(offsets) - 1):
        s = int(offsets[i])
        e = int(offsets[i + 1])
        yield realized.coords[s:e]


def test_dash_straight_line_generates_expected_segments() -> None:
    g = G.dash_test_line_0_10()
    dashed = E.dash(dash_length=2.0, gap_length=1.0, offset=0.0, offset_jitter=0.0)(g)
    realized = realize(dashed)

    segments = list(_iter_polylines(realized))
    assert len(segments) == 4

    expected = [(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 10.0)]
    for seg, (x0, x1) in zip(segments, expected, strict=True):
        np.testing.assert_allclose([seg[0, 0], seg[-1, 0]], [x0, x1], rtol=0.0, atol=1e-6)
        np.testing.assert_allclose(seg[:, 1], 0.0, rtol=0.0, atol=1e-6)
        np.testing.assert_allclose(seg[:, 2], 0.0, rtol=0.0, atol=1e-6)


def test_dash_offset_shifts_phase() -> None:
    g = G.dash_test_line_0_10()
    dashed = E.dash(dash_length=2.0, gap_length=1.0, offset=1.0, offset_jitter=0.0)(g)
    realized = realize(dashed)

    segments = list(_iter_polylines(realized))
    assert len(segments) == 4

    expected = [(0.0, 1.0), (2.0, 4.0), (5.0, 7.0), (8.0, 10.0)]
    for seg, (x0, x1) in zip(segments, expected, strict=True):
        np.testing.assert_allclose([seg[0, 0], seg[-1, 0]], [x0, x1], rtol=0.0, atol=1e-6)


def test_dash_negative_jitter_wraps_phase_modulo_pattern() -> None:
    offset = 0.1
    jitter = 1.0
    samples = np.random.default_rng(0).uniform(-jitter, jitter, size=2)
    assert offset + float(samples[1]) < 0.0
    second_phase = (offset + float(samples[1])) % 3.0

    actual_lines = list(
        _iter_polylines(
            realize(
                E.dash(
                    dash_length=2.0,
                    gap_length=1.0,
                    offset=offset,
                    offset_jitter=jitter,
                )(G.dash_test_zero_then_line())
            )
        )
    )
    expected_lines = list(
        _iter_polylines(
            realize(
                E.dash(
                    dash_length=2.0,
                    gap_length=1.0,
                    offset=second_phase,
                    offset_jitter=0.0,
                )(G.dash_test_line_0_10())
            )
        )
    )

    assert len(actual_lines) == len(expected_lines) + 1
    for actual, expected in zip(actual_lines[1:], expected_lines, strict=True):
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-6)


def test_dash_zero_pattern_is_noop() -> None:
    g = G.dash_test_line_0_10()
    base = realize(g)

    dashed = E.dash(
        dash_length=0.0,
        gap_length=0.0,
        offset=0.0,
        offset_jitter=0.0,
    )(g)
    realized = realize(dashed)

    np.testing.assert_allclose(realized.coords, base.coords, rtol=0.0, atol=1e-6)
    assert realized.offsets.tolist() == base.offsets.tolist()


@pytest.mark.parametrize(
    "name",
    ("dash_length", "gap_length", "offset", "offset_jitter"),
)
def test_dash_rejects_negative_public_arguments_before_empty_noop(name: str) -> None:
    params = {
        "dash_length": 2.0,
        "gap_length": 1.0,
        "offset": 0.0,
        "offset_jitter": 0.0,
    }
    params[name] = -0.5

    for source in (G.dash_test_line_0_10(), G.dash_test_empty()):
        with pytest.raises(RealizeError) as exc_info:
            realize(E.dash(**params)(source))

        assert isinstance(exc_info.value.__cause__, ValueError)
        assert "0 以上" in str(exc_info.value.__cause__)


def test_dash_empty_geometry_is_noop() -> None:
    g = G.dash_test_empty()
    dashed = E.dash(dash_length=2.0, gap_length=1.0, offset=0.0, offset_jitter=0.0)(g)
    realized = realize(dashed)

    assert realized.coords.shape == (0, 3)
    assert realized.offsets.tolist() == [0]


def test_dash_rejects_nonfinite_pattern_sum_before_empty_input() -> None:
    finite_max = float(np.finfo(np.float64).max)

    with pytest.raises(RealizeError) as exc_info:
        realize(
            E.dash(dash_length=finite_max, gap_length=finite_max)(
                G.dash_test_empty()
            )
        )

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "dash_length + gap_length" in str(exc_info.value.__cause__)
