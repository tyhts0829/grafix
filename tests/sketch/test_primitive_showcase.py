"""全組み込みprimitiveを掲載するshowcaseの同期・描画契約を検証する。"""

from __future__ import annotations

import runpy
from pathlib import Path

import numpy as np
import pytest

import grafix
from grafix.core.builtins import _BUILTIN_PRIMITIVE_MODULES
from grafix.core.geometry import Geometry
from grafix.core.realize import realize
from sketch.showcase import primitives as showcase

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SHOWCASE_PATH = _PROJECT_ROOT / "sketch" / "showcase" / "primitives.py"


def _assert_standard_geometry(coords: np.ndarray, offsets: np.ndarray) -> None:
    """realize結果がpacked geometryの標準契約を満たすことを確認する。"""

    assert coords.dtype == np.float32
    assert coords.ndim == 2
    assert coords.shape[1] == 3
    assert np.isfinite(coords).all()

    assert offsets.dtype == np.int32
    assert offsets.ndim == 1
    assert offsets.size >= 1
    assert offsets[0] == 0
    assert offsets[-1] == coords.shape[0]
    assert np.all(offsets[1:] >= offsets[:-1])


def test_primitive_names_exactly_match_builtin_manifest_without_duplicates() -> None:
    expected = tuple(_BUILTIN_PRIMITIVE_MODULES)
    actual = tuple(showcase.PRIMITIVE_NAMES)

    assert len(actual) == len(expected)
    assert set(actual) == set(expected)
    assert len(actual) == len(set(actual))


def test_primitive_samples_follow_declared_order() -> None:
    samples = tuple(showcase._primitive_samples())

    assert tuple(name for name, _geometry in samples) == tuple(showcase.PRIMITIVE_NAMES)
    assert all(isinstance(geometry, Geometry) for _name, geometry in samples)


def test_each_primitive_sample_realizes_to_finite_standard_geometry() -> None:
    first_samples = tuple(showcase._primitive_samples())
    second_samples = tuple(showcase._primitive_samples())
    assert tuple(name for name, _geometry in second_samples) == tuple(showcase.PRIMITIVE_NAMES)

    for (name, first_geometry), (second_name, second_geometry) in zip(
        first_samples,
        second_samples,
        strict=True,
    ):
        assert second_name == name
        first = realize(first_geometry)
        second = realize(second_geometry)

        _assert_standard_geometry(first.coords, first.offsets)
        _assert_standard_geometry(second.coords, second.offsets)
        assert first.coords.shape[0] > 0, name
        np.testing.assert_array_equal(second.coords, first.coords, err_msg=name)
        np.testing.assert_array_equal(second.offsets, first.offsets, err_msg=name)
        assert second.coords.tobytes() == first.coords.tobytes(), name
        assert second.offsets.tobytes() == first.offsets.tobytes(), name


def test_draw_is_nonempty_and_time_independent() -> None:
    first_geometry = showcase.draw(0.0)
    second_geometry = showcase.draw(123.0)
    assert isinstance(first_geometry, Geometry)
    assert isinstance(second_geometry, Geometry)

    first = realize(first_geometry)
    second = realize(second_geometry)
    _assert_standard_geometry(first.coords, first.offsets)
    _assert_standard_geometry(second.coords, second.offsets)
    assert first.coords.shape[0] > 0
    np.testing.assert_array_equal(second.coords, first.coords)
    np.testing.assert_array_equal(second.offsets, first.offsets)
    assert second.coords.tobytes() == first.coords.tobytes()
    assert second.offsets.tobytes() == first.offsets.tobytes()


def test_import_does_not_start_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        pytest.fail("showcaseのimport時にgrafix.runを呼び出してはならない")

    monkeypatch.setattr(grafix, "run", fail_run)
    runpy.run_path(str(_SHOWCASE_PATH), run_name="_primitive_showcase_import_check")
