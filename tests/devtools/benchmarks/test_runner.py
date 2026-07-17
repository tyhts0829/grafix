from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from grafix.core.geometry import Geometry
from grafix.core.realized_geometry import RealizedGeometry
from grafix.devtools.benchmarks import runner
from grafix.devtools.benchmarks.environment import (
    collect_environment_fingerprint,
    collect_source_identity,
    make_case_spec,
)
from grafix.devtools.benchmarks.runner import (
    canonical_checksum,
    case_definitions,
    geometry_checksum,
    run_case_isolated,
    select_case_definitions,
)
from grafix.devtools.benchmarks.schema import CaseResult, case_result_to_dict


def test_isolated_process_timeout_kills_the_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeProcess:
        pid = 4242
        returncode = -signal.SIGKILL

        def communicate(self, *, timeout: float | None = None) -> tuple[str, str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise subprocess.TimeoutExpired(["benchmark-child"], timeout)
            return "", ""

    started: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        started["command"] = command
        started.update(kwargs)
        return FakeProcess()

    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_isolated_process(
            ["benchmark-child"],
            timeout=0.1,
            env={},
        )

    assert started["start_new_session"] is True
    assert killed == [(4242, signal.SIGKILL)]
    assert calls == 2


def test_child_result_must_match_the_requested_case_spec() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    expected = definition.spec(seed=0)
    wrong = CaseResult(
        spec=replace(expected, label="wrong case"),
        status="error",
        error="synthetic",
    )

    with pytest.raises(ValueError, match="case spec differs"):
        runner._validated_child_result(
            json.loads(json.dumps(case_result_to_dict(wrong))),
            expected_spec=expected,
        )


def test_geometry_checksum_includes_dtype_shape_and_bytes() -> None:
    first = RealizedGeometry(
        coords=np.asarray([[0.0, 1.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )
    changed = RealizedGeometry(
        coords=np.asarray([[0.0, 2.0, 0.0]], dtype=np.float32),
        offsets=np.asarray([0, 1], dtype=np.int32),
    )

    assert geometry_checksum(first) != geometry_checksum(changed)
    checksum, kind = canonical_checksum(first)
    assert checksum == geometry_checksum(first)
    assert kind == "realized_geometry_exact_v1"


def test_registry_selects_suite_and_rejects_unknown_case() -> None:
    all_ids = {definition.case_id for definition in case_definitions()}
    smoke = select_case_definitions(suites=("smoke",))

    assert smoke
    assert {definition.case_id for definition in smoke} <= all_ids
    assert all("smoke" in definition.selectable_suites for definition in smoke)

    provenance = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "runtime.provenance.rows_1000"
    )
    assert runner._benchmark_draw in provenance.support_implementations
    assert any(
        definition.case_id == "runtime.provenance_changed.rows_1000"
        for definition in case_definitions()
    )


def test_isolated_runner_returns_raw_samples_checksum_and_rss_delta() -> None:
    definition = next(
        definition
        for definition in case_definitions()
        if definition.case_id == "core.concat_recipe.parts_10"
    )
    result = run_case_isolated(
        definition,
        seed=0,
        mode="warm",
        samples=2,
        warmup=0,
        target_ns=0,
        disable_gc=False,
        timeout_seconds=30.0,
    )

    assert result.status == "ok", result.error
    assert len(result.samples) == 2
    assert result.stats is not None
    assert result.stats.n == 2
    assert result.checksum
    assert result.baseline_rss_bytes is not None
    assert result.peak_rss_delta_bytes is not None
    assert result.peak_rss_delta_bytes >= 0


def test_renderer_cases_separate_static_offsets_from_animated_topology() -> None:
    static_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = runner._workload_animated_renderer(static_state).metrics
    animated = runner._workload_animated_renderer(animated_state).metrics

    assert static["index_builds"] == 1
    assert static["full_uploads"] == 1
    assert static["vertex_only_uploads"] == 3
    assert animated["index_builds"] == 4
    assert animated["full_uploads"] == 4
    assert animated["vertex_only_uploads"] == 0


def test_concat_checksum_tracks_leaf_order_not_parenthesization() -> None:
    leaves = tuple(
        Geometry.create("leaf", params={"index": index})
        for index in range(3)
    )
    left = (leaves[0] + leaves[1]) + leaves[2]
    right = leaves[0] + (leaves[1] + leaves[2])
    reordered = leaves[1] + (leaves[0] + leaves[2])

    assert canonical_checksum(left) == canonical_checksum(right)
    assert canonical_checksum(left) != canonical_checksum(reordered)


def test_renderer_checksum_is_independent_of_performance_counters() -> None:
    static_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "static"},
        0,
    )
    animated_state = runner._setup_animated_renderer(
        {"polylines": 10, "frames": 4, "topology": "animated"},
        0,
    )

    static = runner._workload_animated_renderer(static_state)
    animated = runner._workload_animated_renderer(animated_state)

    assert static.metrics["index_builds"] != animated.metrics["index_builds"]
    assert canonical_checksum(static.value) == canonical_checksum(animated.value)
    assert static.metrics["full_vertex_upload_bytes"] > 0
    assert static.metrics["vertex_only_upload_bytes"] > 0


def test_case_source_hash_includes_transitive_fixture_source(tmp_path: Path) -> None:
    support = tmp_path / "fixture.py"
    support.write_text("VALUE = 1\n", encoding="utf-8")

    def implementation() -> None:
        return None

    first = make_case_spec(
        case_id="case",
        version=1,
        label="case",
        category="test",
        suite="test",
        fixture="fixture",
        parameters={},
        seed=0,
        implementation=implementation,
        support_source_files=(support,),
    )
    support.write_text("VALUE = 2\n", encoding="utf-8")
    second = make_case_spec(
        case_id="case",
        version=1,
        label="case",
        category="test",
        suite="test",
        fixture="fixture",
        parameters={},
        seed=0,
        implementation=implementation,
        support_source_files=(support,),
    )

    assert first.source_sha256 != second.source_sha256
    assert first.compatibility_key != second.compatibility_key


def test_environment_fingerprint_uses_effective_child_overrides() -> None:
    fingerprint = collect_environment_fingerprint(
        environment_overrides={
            "PYTHONHASHSEED": "0",
            "NUMBA_CACHE_DIR": "<isolated-empty>",
        }
    )

    assert fingerprint.values["environment"]["PYTHONHASHSEED"] == "0"
    assert (
        fingerprint.values["environment"]["NUMBA_CACHE_DIR"]
        == "<isolated-empty>"
    )


def test_source_identity_hashes_untracked_files_from_repository_root(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    nested = repository / "src" / "package"
    nested.mkdir(parents=True)
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Grafix Test",
            "-c",
            "user.email=grafix@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=repository,
        check=True,
    )
    untracked = repository / "outside-nested.txt"
    untracked.write_text("first\n", encoding="utf-8")
    first = collect_source_identity(root=nested)
    untracked.write_text("second\n", encoding="utf-8")
    second = collect_source_identity(root=nested)

    assert first.dirty is True
    assert second.dirty is True
    assert first.diff_sha256 != second.diff_sha256
