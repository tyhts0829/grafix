from __future__ import annotations

import importlib.metadata
import sys
from types import SimpleNamespace

import pytest

from grafix.devtools.benchmarks import environment
from grafix.devtools.benchmarks.environment import collect_environment_fingerprint


def test_effect_backend_versions_are_part_of_environment_identity() -> None:
    fingerprint = collect_environment_fingerprint()

    dependencies = fingerprint.values["dependencies"]
    assert dependencies["shapely"] == importlib.metadata.version("shapely")
    assert int(dependencies["shapely"].split(".", 1)[0]) == 2
    assert dependencies["pyclipper"] == importlib.metadata.version("pyclipper")

    geos_version = fingerprint.values["backends"]["geos"]
    assert isinstance(geos_version, str)
    assert geos_version


def test_geos_version_does_not_fall_back_to_shapely_1_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "shapely", SimpleNamespace())

    with pytest.raises(AttributeError, match="geos_version_string"):
        environment._geos_version({})


@pytest.mark.parametrize("version", [None, object()])
def test_geos_version_rejects_non_string_values(
    monkeypatch: pytest.MonkeyPatch,
    version: object,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "shapely",
        SimpleNamespace(geos_version_string=version),
    )

    with pytest.raises(TypeError, match="exact string"):
        environment._geos_version({})


def test_geos_version_rejects_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "shapely",
        SimpleNamespace(geos_version_string=""),
    )

    with pytest.raises(ValueError, match="must not be empty"):
        environment._geos_version({})
