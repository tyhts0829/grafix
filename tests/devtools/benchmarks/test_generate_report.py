from __future__ import annotations

import json
from pathlib import Path

from grafix.devtools.benchmarks.report import (
    load_runs,
    render_report_html,
    write_report,
)
from grafix.devtools.benchmarks.schema import (
    BenchmarkRun,
    CaseResult,
    CaseSpec,
    EnvironmentFingerprint,
    RunMeta,
    Sample,
    SourceIdentity,
    case_compatibility_key,
    environment_compatibility_key,
    summarize_samples,
    write_benchmark_run,
)


def _write_valid_run(
    runs_dir: Path,
    *,
    warnings: tuple[str, ...] = (),
) -> None:
    spec = CaseSpec(
        case_id="system.example",
        version=1,
        label="System example",
        category="system",
        suite="pipeline",
        fixture="fixture",
        parameters={},
        seed=0,
        source_sha256="source",
        compatibility_key=case_compatibility_key(
            case_id="system.example",
            version=1,
            fixture="fixture",
            parameters={},
            seed=0,
            source_sha256="source",
        ),
    )
    sample = Sample(elapsed_ns=1_250_000, iterations=1)
    run = BenchmarkRun(
        meta=RunMeta(
            run_id="valid",
            created_at="2026-07-17T00:00:00+00:00",
            suite="pipeline",
            profile="short",
            mode="warm",
            seed=0,
            samples=1,
            warmup=0,
            target_ns=0,
            timeout_seconds=120.0,
        ),
        source=SourceIdentity(commit="abcdef", dirty=False, diff_sha256=""),
        environment=EnvironmentFingerprint(
            compatibility_key=environment_compatibility_key({}, {}),
            values={},
        ),
        cases=(
            CaseResult(
                spec=spec,
                status="ok",
                samples=(sample,),
                stats=summarize_samples([sample]),
                checksum="checksum",
                checksum_kind="exact",
                setup_rss_bytes=1 * 1024 * 1024,
                baseline_rss_bytes=1 * 1024 * 1024,
                peak_rss_bytes=3 * 1024 * 1024,
                peak_rss_delta_bytes=2 * 1024 * 1024,
            ),
        ),
        warnings=warnings,
    )
    write_benchmark_run(runs_dir / "valid.json", run)


def test_report_keeps_broken_and_unsupported_runs_as_warnings(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_valid_run(runs_dir)
    (runs_dir / "broken.json").write_text("{broken", encoding="utf-8")
    (runs_dir / "v2.json").write_text(
        json.dumps({"schema_version": 2}),
        encoding="utf-8",
    )

    loaded = load_runs(runs_dir)
    assert len(loaded.runs) == 1
    assert len(loaded.warnings) == 2
    assert any("broken.json" in warning for warning in loaded.warnings)
    assert any("v2.json" in warning for warning in loaded.warnings)

    html = render_report_html(loaded)
    assert "System example" in html
    assert "system.example" in html
    assert "1.250000" in html
    assert "2.00" in html
    assert "cdn" not in html.lower()
    assert "broken.json" in html

    report_path, warnings_path, written = write_report(tmp_path)
    assert written == loaded
    assert report_path.is_file()
    assert warnings_path.is_file()
    warning_payload = json.loads(warnings_path.read_text(encoding="utf-8"))
    assert warning_payload["valid_runs"] == 1
    assert warning_payload["warning_count"] == 2


def test_report_includes_warnings_from_valid_runs(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_valid_run(runs_dir, warnings=("system.example: skipped",))

    loaded = load_runs(runs_dir)

    assert len(loaded.runs) == 1
    assert len(loaded.warnings) == 1
    assert "system.example: skipped" in loaded.warnings[0]
