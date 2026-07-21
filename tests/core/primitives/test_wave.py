"""wave primitiveの波形、数値契約、resource境界を検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from grafix import G
from grafix.core.primitives import wave as wave_module
from grafix.core.realize import RealizeError, realize
from grafix.core.resource_budget import (
    ResourceBudget,
    ResourceLimitError,
    resource_budget_context,
)

raw_wave = wave_module.wave


def test_wave_sine_phase_and_open_topology() -> None:
    """phaseは始点へ適用され、samples頂点の開いた1本線になる。"""

    coords, offsets = raw_wave(
        kind="sine",
        length=2.0,
        amplitude=2.0,
        cycles=1.0,
        phase=90.0,
        samples=5,
    )

    assert coords.shape == (5, 3)
    assert offsets.tolist() == [0, 5]
    np.testing.assert_allclose(coords[:, 0], [-1.0, -0.5, 0.0, 0.5, 1.0])
    np.testing.assert_allclose(coords[:, 1], [2.0, 0.0, -2.0, 0.0, 2.0], atol=1e-6)
    np.testing.assert_array_equal(coords[:, 2], np.zeros(5, dtype=np.float32))


def test_wave_triangle_phase_zero_starts_at_zero_and_rises() -> None:
    """triangleのphase=0は数値的に0から始まり、直後に増加する。"""

    coords, offsets = raw_wave(
        kind="triangle",
        length=1.0,
        amplitude=2.0,
        cycles=1.0,
        phase=0.0,
        samples=5,
    )

    assert offsets.tolist() == [0, 5]
    assert abs(float(coords[0, 1])) <= np.finfo(np.float32).eps
    assert coords[1, 1] > coords[0, 1]
    np.testing.assert_allclose(coords[:, 1], [0.0, 2.0, 0.0, -2.0, 0.0])


def test_wave_negative_cycles_and_amplitude_have_independent_sign_meanings() -> None:
    """負cyclesは位相方向、負amplitudeは局所Yだけを反転する。"""

    positive, _ = raw_wave(
        length=2.0,
        amplitude=0.75,
        cycles=1.0,
        phase=0.0,
        samples=9,
    )
    negative_cycles, _ = raw_wave(
        length=2.0,
        amplitude=0.75,
        cycles=-1.0,
        phase=0.0,
        samples=9,
    )
    negative_amplitude, _ = raw_wave(
        length=2.0,
        amplitude=-0.75,
        cycles=1.0,
        phase=0.0,
        samples=9,
    )

    np.testing.assert_array_equal(negative_cycles[:, 0], positive[:, 0])
    np.testing.assert_array_equal(negative_amplitude[:, 0], positive[:, 0])
    assert np.all(np.diff(negative_cycles[:, 0]) > 0.0)
    np.testing.assert_allclose(negative_cycles[:, 1], -positive[:, 1], atol=1e-7)
    np.testing.assert_allclose(negative_amplitude[:, 1], -positive[:, 1], atol=1e-7)


def test_wave_rotates_in_xy_plane_around_center() -> None:
    """angleは局所波形をcenterまわりに回転し、Zはcenterを維持する。"""

    coords, offsets = raw_wave(
        length=2.0,
        amplitude=0.0,
        cycles=3.0,
        samples=3,
        angle=90.0,
        center=(3.0, 4.0, 5.0),
    )

    assert offsets.tolist() == [0, 3]
    np.testing.assert_allclose(
        coords,
        [[3.0, 3.0, 5.0], [3.0, 4.0, 5.0], [3.0, 5.0, 5.0]],
        atol=1e-6,
    )


def test_wave_zero_length_still_returns_finite_single_polyline() -> None:
    """length=0でもsamplesを変えず、有限な1本の開ポリラインを返す。"""

    coords, offsets = raw_wave(length=0.0, cycles=0.25, samples=7)

    assert coords.shape == (7, 3)
    assert offsets.tolist() == [0, 7]
    assert np.isfinite(coords).all()
    np.testing.assert_array_equal(coords[:, 0], np.zeros(7, dtype=np.float32))
    assert coords[-1, 1] > coords[0, 1]


@pytest.mark.parametrize("kind", ["SINE", "square", "", "triangle-wave"])
def test_wave_rejects_invalid_kind(kind: str) -> None:
    """未定義kindを既定値へ読み替えない。"""

    with pytest.raises(ValueError, match="kind"):
        G.wave(kind=kind)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("length", np.nan),
        ("length", np.inf),
        ("amplitude", -np.inf),
        ("cycles", np.nan),
        ("phase", np.inf),
        ("angle", -np.inf),
    ],
)
def test_wave_rejects_nonfinite_scalar(name: str, value: float) -> None:
    """公開float引数のNaNとInfを拒否する。"""

    with pytest.raises(ValueError, match=name):
        G.wave(**{name: value})


@pytest.mark.parametrize(
    "center",
    [
        (np.nan, 0.0, 0.0),
        (0.0, np.inf, 0.0),
        (0.0, 0.0, -np.inf),
    ],
)
def test_wave_rejects_nonfinite_center(
    center: tuple[float, float, float],
) -> None:
    """centerの各成分も有限値に限定する。"""

    with pytest.raises(ValueError, match="center"):
        G.wave(center=center)


@pytest.mark.parametrize("samples", [0, 1, -3])
def test_wave_rejects_samples_below_two(samples: int) -> None:
    """2頂点未満のsamplesを遅延評価時に拒否する。"""

    with pytest.raises(RealizeError) as exc_info:
        realize(G.wave(samples=samples))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "samples は 2 以上" in str(exc_info.value.__cause__)


@pytest.mark.parametrize("samples", [np.nan, np.inf])
def test_wave_rejects_non_integer_samples(samples: float) -> None:
    """非整数のsamplesを公開API境界で拒否する。"""

    with pytest.raises(TypeError, match="samples"):
        G.wave(samples=samples)  # type: ignore[arg-type]


def test_wave_rejects_negative_length() -> None:
    """頂点順を曖昧にする負lengthを拒否する。"""

    with pytest.raises(RealizeError) as exc_info:
        realize(G.wave(length=-1.0))

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "length" in str(exc_info.value.__cause__)


def test_wave_rejects_finite_inputs_that_overflow_output_coordinates() -> None:
    """有限入力でもfloat32座標を生成できない範囲なら明示的に拒否する。"""

    maximum = np.finfo(np.float64).max
    with pytest.raises(ValueError, match="出力 X 座標"):
        raw_wave(length=maximum, center=(maximum, 0.0, 0.0), samples=2)


def test_wave_accepts_finite_subnormal_values_under_strict_numpy_errstate() -> None:
    """有限なsubnormalの丸めはambientなNumPyエラー設定に依存しない。"""

    tiny = float(np.nextafter(0.0, 1.0))
    with np.errstate(all="raise"):
        coords, offsets = raw_wave(
            length=tiny,
            amplitude=tiny,
            cycles=tiny,
            samples=3,
        )

    assert offsets.tolist() == [0, 3]
    assert np.isfinite(coords).all()


def test_wave_raw_arrays_are_fresh_writable_and_input_independent() -> None:
    """raw出力は毎回独立し、center入力を参照・変更しない。"""

    center = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    original = center.copy()

    coords_a, offsets_a = raw_wave(center=center, samples=8)  # type: ignore[arg-type]
    coords_b, offsets_b = raw_wave(center=center, samples=8)  # type: ignore[arg-type]

    assert coords_a.dtype == np.float32
    assert offsets_a.dtype == np.int32
    assert coords_a.flags.c_contiguous
    assert offsets_a.flags.c_contiguous
    assert coords_a.flags.owndata
    assert offsets_a.flags.owndata
    assert coords_a.flags.writeable
    assert offsets_a.flags.writeable
    assert not np.shares_memory(coords_a, coords_b)
    assert not np.shares_memory(offsets_a, offsets_b)
    assert not np.shares_memory(coords_a, center)
    np.testing.assert_array_equal(center, original)

    coords_a[:] = 99.0
    offsets_a[:] = 0
    assert not np.all(coords_b == 99.0)
    assert offsets_b.tolist() == [0, 8]


def test_wave_resource_budget_accepts_exact_boundary() -> None:
    """最終geometryとscratchを含むexact byte/vertex/line境界を受理する。"""

    samples = 7
    estimated_bytes = samples * (3 * 4 + 4 * 8) + 2 * 4
    budget = ResourceBudget(
        max_output_vertices=samples,
        max_output_lines=1,
        max_output_bytes=estimated_bytes,
    )

    with resource_budget_context(budget):
        coords, offsets = raw_wave(samples=samples)

    assert coords.shape == (samples, 3)
    assert offsets.tolist() == [0, samples]


@pytest.mark.parametrize(
    ("vertices", "lines", "byte_delta"),
    [
        (6, 1, 0),
        (7, 0, 0),
        (7, 1, -1),
    ],
)
def test_wave_resource_budget_rejects_one_below_boundary(
    vertices: int,
    lines: int,
    byte_delta: int,
) -> None:
    """vertex、line、byteの各上限を1つでも超えたら確保前に拒否する。"""

    samples = 7
    estimated_bytes = samples * (3 * 4 + 4 * 8) + 2 * 4
    budget = ResourceBudget(
        max_output_vertices=vertices,
        max_output_lines=lines,
        max_output_bytes=estimated_bytes + byte_delta,
    )

    with resource_budget_context(budget), pytest.raises(ResourceLimitError, match="wave"):
        raw_wave(samples=samples)


def test_wave_resource_rejection_precedes_numpy_output_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """budget違反では最初のsample配列も確保しない。"""

    def fail_allocation(*args: object, **kwargs: object) -> np.ndarray:
        raise AssertionError(f"unexpected allocation: {args!r}, {kwargs!r}")

    monkeypatch.setattr(wave_module.np, "linspace", fail_allocation)
    budget = ResourceBudget(
        max_output_vertices=1,
        max_output_lines=1,
        max_output_bytes=1024,
    )

    with resource_budget_context(budget), pytest.raises(ResourceLimitError, match="wave"):
        raw_wave(samples=2)
