from __future__ import annotations

import subprocess
from pathlib import Path


from grafix.devtools.benchmarks.environment import (
    collect_environment_fingerprint,
    collect_source_identity,
)


def test_environment_fingerprint_uses_effective_child_overrides() -> None:
    fingerprint = collect_environment_fingerprint(
        environment_overrides={
            "PYTHONHASHSEED": "0",
            "NUMBA_CACHE_DIR": "<isolated-empty>",
        }
    )

    assert fingerprint.values["environment"]["PYTHONHASHSEED"] == "0"
    assert fingerprint.values["environment"]["NUMBA_CACHE_DIR"] == "<isolated-empty>"


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
