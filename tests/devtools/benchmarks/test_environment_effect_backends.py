from __future__ import annotations

import importlib.metadata

from grafix.devtools.benchmarks.environment import collect_environment_fingerprint


def test_effect_backend_versions_are_part_of_environment_identity() -> None:
    fingerprint = collect_environment_fingerprint()

    dependencies = fingerprint.values["dependencies"]
    assert dependencies["shapely"] == importlib.metadata.version("shapely")
    assert dependencies["pyclipper"] == importlib.metadata.version("pyclipper")

    geos_version = fingerprint.values["backends"]["geos"]
    assert isinstance(geos_version, str)
    assert geos_version
