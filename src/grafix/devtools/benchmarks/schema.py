"""Benchmark schema v3 の型、統計、厳格な JSON codec。"""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from grafix.core.atomic_write import atomic_write_text_no_clobber
from grafix.devtools.benchmarks import BENCHMARK_SCHEMA_VERSION

_TAIL_MIN_SAMPLES = 20
_CASE_STATUSES = {"ok", "error", "timeout", "skipped", "resource-limit"}
_CHECKSUM_POLICIES = {"exact"}


class BenchmarkSchemaError(ValueError):
    """未対応または不正な benchmark JSON を表す。"""


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """計測対象 source の識別情報。比較互換性とは分離する。"""

    commit: str | None
    dirty: bool | None
    diff_sha256: str | None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentFingerprint:
    """比較に必要な実行環境と、その canonical key。"""

    compatibility_key: str
    values: dict[str, Any]
    unavailable: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunMeta:
    """1 benchmark run に共通する設定。"""

    run_id: str
    created_at: str
    suite: str
    profile: str
    mode: str
    seed: int
    samples: int = 0
    warmup: int = 0
    target_ns: int = 0
    disable_gc: bool = False
    timeout_seconds: float = 0.0
    argv: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """比較可能性を決める benchmark case 定義。"""

    case_id: str
    version: int
    label: str
    category: str
    suite: str
    fixture: str
    parameters: dict[str, Any]
    seed: int
    source_sha256: str
    compatibility_key: str
    checksum_policy: str = "exact"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sample:
    """反復回数を含む未丸めの wall-clock sample。"""

    elapsed_ns: int
    iterations: int

    @property
    def ns_per_iteration(self) -> float:
        return float(self.elapsed_ns) / float(self.iterations)


@dataclass(frozen=True, slots=True)
class SampleStats:
    """raw sample から得た要約。tail は十分な sample 数でのみ持つ。"""

    n: int
    median_ns: float
    mad_ns: float
    min_ns: float
    max_ns: float
    p95_ns: float | None
    p99_ns: float | None


@dataclass(frozen=True, slots=True)
class CaseResult:
    """隔離 process で得た 1 case の結果。"""

    spec: CaseSpec
    status: str
    samples: tuple[Sample, ...] = ()
    stats: SampleStats | None = None
    checksum: str | None = None
    checksum_kind: str | None = None
    setup_rss_bytes: int | None = None
    baseline_rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    peak_rss_delta_bytes: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """schema v3 の top-level benchmark run。"""

    meta: RunMeta
    source: SourceIdentity
    environment: EnvironmentFingerprint
    cases: tuple[CaseResult, ...]
    warnings: tuple[str, ...] = ()
    schema_version: int = BENCHMARK_SCHEMA_VERSION


def summarize_samples(samples: list[Sample] | tuple[Sample, ...]) -> SampleStats:
    """sample を 1 iteration 当たりの ns へ正規化して要約する。"""

    if not samples:
        raise ValueError("samples は 1 件以上必要です")
    values = [sample.ns_per_iteration for sample in samples]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("sample は有限な非負値である必要があります")
    center = float(median(values))
    deviations = [abs(value - center) for value in values]
    ordered = sorted(values)
    with_tail = len(ordered) >= _TAIL_MIN_SAMPLES
    return SampleStats(
        n=len(ordered),
        median_ns=center,
        mad_ns=float(median(deviations)),
        min_ns=float(ordered[0]),
        max_ns=float(ordered[-1]),
        p95_ns=_percentile(ordered, 0.95) if with_tail else None,
        p99_ns=_percentile(ordered, 0.99) if with_tail else None,
    )


def benchmark_run_to_dict(run: BenchmarkRun) -> dict[str, Any]:
    """BenchmarkRun を JSON 化可能な mapping に変換する。"""

    return asdict(run)


def case_result_to_dict(result: CaseResult) -> dict[str, Any]:
    """CaseResult を child protocol 用 mapping に変換する。"""

    return asdict(result)


def case_result_from_dict(payload: object) -> CaseResult:
    """child protocol の CaseResult を厳格に復元する。"""

    result = _decode_case(payload, index=0)
    _validate_case_result(result, where="cases[0]")
    return result


def benchmark_run_from_dict(payload: object) -> BenchmarkRun:
    """未知 field と欠落 field を拒否して BenchmarkRun を復元する。"""

    run = _decode_benchmark_run(payload)
    _validate_run(run)
    return run


def _decode_benchmark_run(payload: object) -> BenchmarkRun:
    """JSON-compatible object を semantic validation 前まで復元する。"""

    root = _mapping(payload, "root")
    if "schema_version" not in root:
        raise BenchmarkSchemaError("root: missing=['schema_version']")
    version = _integer(root["schema_version"], "schema_version")
    if version != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkSchemaError(
            f"unsupported schema_version: {version} "
            f"(expected {BENCHMARK_SCHEMA_VERSION})"
        )
    _keys(
        root,
        required={"schema_version", "meta", "source", "environment", "cases", "warnings"},
        where="root",
    )
    meta = _decode_meta(root["meta"])
    source = _decode_source(root["source"])
    environment = _decode_environment(root["environment"])
    cases_raw = _sequence(root["cases"], "cases")
    warnings_raw = _sequence(root["warnings"], "warnings")
    warnings = tuple(_string(value, f"warnings[{index}]") for index, value in enumerate(warnings_raw))
    cases = tuple(_decode_case(value, index=index) for index, value in enumerate(cases_raw))
    return BenchmarkRun(
        meta=meta,
        source=source,
        environment=environment,
        cases=cases,
        warnings=warnings,
        schema_version=version,
    )


def environment_compatibility_key(
    values: dict[str, Any],
    unavailable: dict[str, str],
) -> str:
    """environment identity の canonical SHA-256 を返す。"""

    return _sha256_json({"values": values, "unavailable": unavailable})


def case_compatibility_key(
    *,
    case_id: str,
    version: int,
    fixture: str,
    parameters: dict[str, Any],
    seed: int,
    source_sha256: str,
    checksum_policy: str = "exact",
) -> str:
    """case identity の canonical SHA-256 を返す。"""

    return _sha256_json(
        {
            "case_id": str(case_id),
            "version": int(version),
            "fixture": str(fixture),
            "parameters": parameters,
            "seed": int(seed),
            "source_sha256": str(source_sha256),
            "checksum_policy": str(checksum_policy),
        }
    )


def write_benchmark_run(path: str | Path, run: BenchmarkRun) -> None:
    """既存 run を上書きせず、JSON を atomic に保存する。"""

    destination = Path(path)
    _validate_run(run)
    try:
        text = (
            json.dumps(
                benchmark_run_to_dict(run),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as exc:
        raise BenchmarkSchemaError(
            f"run contains a non-JSON value: {exc}"
        ) from exc
    try:
        atomic_write_text_no_clobber(destination, text)
    except FileExistsError as exc:
        raise FileExistsError(
            f"benchmark run already exists: {destination}"
        ) from exc


def read_benchmark_run(path: str | Path) -> BenchmarkRun:
    """JSON file から schema v3 run を厳格に読む。"""

    source = Path(path)
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise BenchmarkSchemaError(f"{source}: {type(exc).__name__}: {exc}") from exc
    try:
        return benchmark_run_from_dict(payload)
    except BenchmarkSchemaError as exc:
        raise BenchmarkSchemaError(f"{source}: {exc}") from exc


def _decode_meta(value: object) -> RunMeta:
    obj = _mapping(value, "meta")
    _keys(
        obj,
        required={
            "run_id",
            "created_at",
            "suite",
            "profile",
            "mode",
            "seed",
            "samples",
            "warmup",
            "target_ns",
            "disable_gc",
            "timeout_seconds",
            "argv",
        },
        where="meta",
    )
    argv = _sequence(obj["argv"], "meta.argv")
    return RunMeta(
        run_id=_string(obj["run_id"], "meta.run_id"),
        created_at=_string(obj["created_at"], "meta.created_at"),
        suite=_string(obj["suite"], "meta.suite"),
        profile=_string(obj["profile"], "meta.profile"),
        mode=_string(obj["mode"], "meta.mode"),
        seed=_integer(obj["seed"], "meta.seed"),
        samples=_integer(obj["samples"], "meta.samples"),
        warmup=_integer(obj["warmup"], "meta.warmup"),
        target_ns=_integer(obj["target_ns"], "meta.target_ns"),
        disable_gc=_boolean(obj["disable_gc"], "meta.disable_gc"),
        timeout_seconds=_number(
            obj["timeout_seconds"], "meta.timeout_seconds"
        ),
        argv=tuple(_string(item, f"meta.argv[{index}]") for index, item in enumerate(argv)),
    )


def _decode_source(value: object) -> SourceIdentity:
    obj = _mapping(value, "source")
    _keys(
        obj,
        required={"commit", "dirty", "diff_sha256", "unavailable_reason"},
        where="source",
    )
    return SourceIdentity(
        commit=_optional_string(obj["commit"], "source.commit"),
        dirty=_optional_bool(obj["dirty"], "source.dirty"),
        diff_sha256=_optional_string(obj["diff_sha256"], "source.diff_sha256"),
        unavailable_reason=_optional_string(
            obj["unavailable_reason"], "source.unavailable_reason"
        ),
    )


def _decode_environment(value: object) -> EnvironmentFingerprint:
    obj = _mapping(value, "environment")
    _keys(
        obj,
        required={"compatibility_key", "values", "unavailable"},
        where="environment",
    )
    values = _mapping(obj["values"], "environment.values")
    unavailable = _mapping(obj["unavailable"], "environment.unavailable")
    return EnvironmentFingerprint(
        compatibility_key=_string(
            obj["compatibility_key"], "environment.compatibility_key"
        ),
        values=dict(values),
        unavailable={
            _string(key, "environment.unavailable key"): _string(
                item, f"environment.unavailable.{key}"
            )
            for key, item in unavailable.items()
        },
    )


def _decode_case(value: object, *, index: int) -> CaseResult:
    where = f"cases[{index}]"
    obj = _mapping(value, where)
    _keys(
        obj,
        required={
            "spec",
            "status",
            "samples",
            "stats",
            "checksum",
            "checksum_kind",
            "setup_rss_bytes",
            "baseline_rss_bytes",
            "peak_rss_bytes",
            "peak_rss_delta_bytes",
            "metrics",
            "error",
        },
        where=where,
    )
    samples_raw = _sequence(obj["samples"], f"{where}.samples")
    samples = tuple(
        _decode_sample(item, where=f"{where}.samples[{sample_index}]")
        for sample_index, item in enumerate(samples_raw)
    )
    stats = None if obj["stats"] is None else _decode_stats(obj["stats"], where=f"{where}.stats")
    return CaseResult(
        spec=_decode_spec(obj["spec"], where=f"{where}.spec"),
        status=_string(obj["status"], f"{where}.status"),
        samples=samples,
        stats=stats,
        checksum=_optional_string(obj["checksum"], f"{where}.checksum"),
        checksum_kind=_optional_string(obj["checksum_kind"], f"{where}.checksum_kind"),
        setup_rss_bytes=_optional_integer(
            obj["setup_rss_bytes"], f"{where}.setup_rss_bytes"
        ),
        baseline_rss_bytes=_optional_integer(
            obj["baseline_rss_bytes"], f"{where}.baseline_rss_bytes"
        ),
        peak_rss_bytes=_optional_integer(obj["peak_rss_bytes"], f"{where}.peak_rss_bytes"),
        peak_rss_delta_bytes=_optional_integer(
            obj["peak_rss_delta_bytes"], f"{where}.peak_rss_delta_bytes"
        ),
        metrics=dict(_mapping(obj["metrics"], f"{where}.metrics")),
        error=_optional_string(obj["error"], f"{where}.error"),
    )


def _decode_spec(value: object, *, where: str) -> CaseSpec:
    obj = _mapping(value, where)
    _keys(
        obj,
        required={
            "case_id",
            "version",
            "label",
            "category",
            "suite",
            "fixture",
            "parameters",
            "seed",
            "source_sha256",
            "compatibility_key",
            "checksum_policy",
            "tags",
        },
        where=where,
    )
    tags = _sequence(obj["tags"], f"{where}.tags")
    return CaseSpec(
        case_id=_string(obj["case_id"], f"{where}.case_id"),
        version=_integer(obj["version"], f"{where}.version"),
        label=_string(obj["label"], f"{where}.label"),
        category=_string(obj["category"], f"{where}.category"),
        suite=_string(obj["suite"], f"{where}.suite"),
        fixture=_string(obj["fixture"], f"{where}.fixture"),
        parameters=dict(_mapping(obj["parameters"], f"{where}.parameters")),
        seed=_integer(obj["seed"], f"{where}.seed"),
        source_sha256=_string(obj["source_sha256"], f"{where}.source_sha256"),
        compatibility_key=_string(
            obj["compatibility_key"], f"{where}.compatibility_key"
        ),
        checksum_policy=_string(
            obj["checksum_policy"], f"{where}.checksum_policy"
        ),
        tags=tuple(
            _string(item, f"{where}.tags[{tag_index}]")
            for tag_index, item in enumerate(tags)
        ),
    )


def _decode_sample(value: object, *, where: str) -> Sample:
    obj = _mapping(value, where)
    _keys(obj, required={"elapsed_ns", "iterations"}, where=where)
    elapsed_ns = _integer(obj["elapsed_ns"], f"{where}.elapsed_ns")
    iterations = _integer(obj["iterations"], f"{where}.iterations")
    if elapsed_ns < 0 or iterations < 1:
        raise BenchmarkSchemaError(f"{where}: invalid elapsed_ns/iterations")
    return Sample(elapsed_ns=elapsed_ns, iterations=iterations)


def _decode_stats(value: object, *, where: str) -> SampleStats:
    obj = _mapping(value, where)
    _keys(
        obj,
        required={"n", "median_ns", "mad_ns", "min_ns", "max_ns", "p95_ns", "p99_ns"},
        where=where,
    )
    return SampleStats(
        n=_integer(obj["n"], f"{where}.n"),
        median_ns=_number(obj["median_ns"], f"{where}.median_ns"),
        mad_ns=_number(obj["mad_ns"], f"{where}.mad_ns"),
        min_ns=_number(obj["min_ns"], f"{where}.min_ns"),
        max_ns=_number(obj["max_ns"], f"{where}.max_ns"),
        p95_ns=_optional_number(obj["p95_ns"], f"{where}.p95_ns"),
        p99_ns=_optional_number(obj["p99_ns"], f"{where}.p99_ns"),
    )


def _percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * float(fraction)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower]) * (1.0 - weight) + float(ordered[upper]) * weight


def _validate_run(run: BenchmarkRun) -> None:
    payload = benchmark_run_to_dict(run)
    _validate_json_value(payload, where="root")
    # writer 側も decoder と同じ型規則を通し、「書けたが読めない」JSON を防ぐ。
    _decode_benchmark_run(
        json.loads(
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        )
    )
    if run.schema_version != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkSchemaError(
            f"unsupported schema_version: {run.schema_version} "
            f"(expected {BENCHMARK_SCHEMA_VERSION})"
        )
    meta = run.meta
    if not all(
        (
            meta.run_id,
            meta.created_at,
            meta.suite,
            meta.profile,
            meta.mode,
        )
    ):
        raise BenchmarkSchemaError("meta: identity fields must not be empty")
    if meta.mode not in {"warm", "process-cold", "compile-cold"}:
        raise BenchmarkSchemaError(f"meta.mode: unsupported value {meta.mode!r}")
    if (
        meta.samples < 1
        or meta.warmup < 0
        or meta.target_ns < 0
        or not math.isfinite(meta.timeout_seconds)
        or meta.timeout_seconds <= 0.0
    ):
        raise BenchmarkSchemaError("meta: invalid measurement settings")
    if meta.mode != "warm" and (meta.warmup != 0 or meta.target_ns != 0):
        raise BenchmarkSchemaError(
            "meta: cold mode requires warmup=0 and target_ns=0"
        )

    expected_environment_key = environment_compatibility_key(
        run.environment.values,
        run.environment.unavailable,
    )
    if run.environment.compatibility_key != expected_environment_key:
        raise BenchmarkSchemaError(
            "environment.compatibility_key does not match its identity fields"
        )

    seen_case_ids: set[str] = set()
    for index, result in enumerate(run.cases):
        where = f"cases[{index}]"
        if result.spec.case_id in seen_case_ids:
            raise BenchmarkSchemaError(
                f"{where}.spec.case_id: duplicate {result.spec.case_id!r}"
            )
        seen_case_ids.add(result.spec.case_id)
        if result.spec.seed != meta.seed:
            raise BenchmarkSchemaError(f"{where}.spec.seed differs from meta.seed")
        _validate_case_result(result, where=where)
        if result.status == "ok" and len(result.samples) != meta.samples:
            raise BenchmarkSchemaError(
                f"{where}.samples: count differs from meta.samples"
            )


def _validate_case_result(result: CaseResult, *, where: str) -> None:
    _validate_json_value(case_result_to_dict(result), where=where)
    spec = result.spec
    if (
        not spec.case_id
        or spec.version < 1
        or not spec.label
        or not spec.category
        or not spec.suite
        or not spec.fixture
        or not spec.source_sha256
    ):
        raise BenchmarkSchemaError(f"{where}.spec: invalid identity fields")
    expected_case_key = case_compatibility_key(
        case_id=spec.case_id,
        version=spec.version,
        fixture=spec.fixture,
        parameters=spec.parameters,
        seed=spec.seed,
        source_sha256=spec.source_sha256,
        checksum_policy=spec.checksum_policy,
    )
    if spec.compatibility_key != expected_case_key:
        raise BenchmarkSchemaError(
            f"{where}.spec.compatibility_key does not match its identity fields"
        )
    if spec.checksum_policy not in _CHECKSUM_POLICIES:
        raise BenchmarkSchemaError(
            f"{where}.spec.checksum_policy: unsupported value "
            f"{spec.checksum_policy!r}"
        )
    if result.status not in _CASE_STATUSES:
        raise BenchmarkSchemaError(
            f"{where}.status: unsupported value {result.status!r}"
        )

    rss_values = (
        result.setup_rss_bytes,
        result.baseline_rss_bytes,
        result.peak_rss_bytes,
        result.peak_rss_delta_bytes,
    )
    if any(value is not None and value < 0 for value in rss_values):
        raise BenchmarkSchemaError(f"{where}: RSS fields must be non-negative")

    if result.status != "ok":
        if not result.error:
            raise BenchmarkSchemaError(
                f"{where}.error: non-ok result requires an error"
            )
        if (
            result.samples
            or result.stats is not None
            or result.checksum is not None
            or result.checksum_kind is not None
        ):
            raise BenchmarkSchemaError(
                f"{where}: non-ok result must not contain timing/checksum data"
            )
        return

    if result.error is not None:
        raise BenchmarkSchemaError(f"{where}.error: ok result must not have an error")
    if not result.samples or result.stats is None:
        raise BenchmarkSchemaError(f"{where}: ok result requires samples and stats")
    if not result.checksum or not result.checksum_kind:
        raise BenchmarkSchemaError(f"{where}: ok result requires a checksum")
    expected_stats = summarize_samples(result.samples)
    if result.stats != expected_stats:
        raise BenchmarkSchemaError(f"{where}.stats does not match raw samples")
    if any(value is None for value in rss_values):
        raise BenchmarkSchemaError(f"{where}: ok result requires all RSS fields")
    baseline = result.baseline_rss_bytes
    peak = result.peak_rss_bytes
    delta = result.peak_rss_delta_bytes
    setup = result.setup_rss_bytes
    assert (
        setup is not None
        and baseline is not None
        and peak is not None
        and delta is not None
    )
    if setup > baseline or peak < baseline or delta != peak - baseline:
        raise BenchmarkSchemaError(
            f"{where}: setup/baseline/peak RSS fields are inconsistent"
        )


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_json_value(value: object, *, where: str) -> None:
    """strict JSON で表現できる有限値だけを再帰的に許可する。"""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BenchmarkSchemaError(f"{where}: non-finite number is not allowed")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, where=f"{where}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BenchmarkSchemaError(f"{where}: object keys must be strings")
            _validate_json_value(item, where=f"{where}.{key}")
        return
    raise BenchmarkSchemaError(
        f"{where}: unsupported JSON value {type(value).__name__}"
    )


def _keys(obj: dict[str, Any], *, required: set[str], where: str) -> None:
    actual = set(obj)
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise BenchmarkSchemaError(f"{where}: {', '.join(details)}")


def _mapping(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BenchmarkSchemaError(f"{where}: object is required")
    return value


def _sequence(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchmarkSchemaError(f"{where}: array is required")
    return value


def _string(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise BenchmarkSchemaError(f"{where}: string is required")
    return value


def _optional_string(value: object, where: str) -> str | None:
    return None if value is None else _string(value, where)


def _integer(value: object, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BenchmarkSchemaError(f"{where}: integer is required")
    return value


def _optional_integer(value: object, where: str) -> int | None:
    return None if value is None else _integer(value, where)


def _number(value: object, where: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise BenchmarkSchemaError(f"{where}: number is required")
    result = float(value)
    if not math.isfinite(result):
        raise BenchmarkSchemaError(f"{where}: finite number is required")
    return result


def _optional_number(value: object, where: str) -> float | None:
    return None if value is None else _number(value, where)


def _optional_bool(value: object, where: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise BenchmarkSchemaError(f"{where}: boolean is required")
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _boolean(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise BenchmarkSchemaError(f"{where}: boolean is required")
    return value


__all__ = [
    "BenchmarkRun",
    "BenchmarkSchemaError",
    "CaseResult",
    "CaseSpec",
    "EnvironmentFingerprint",
    "RunMeta",
    "Sample",
    "SampleStats",
    "SourceIdentity",
    "benchmark_run_from_dict",
    "benchmark_run_to_dict",
    "case_result_from_dict",
    "case_result_to_dict",
    "case_compatibility_key",
    "environment_compatibility_key",
    "read_benchmark_run",
    "summarize_samples",
    "write_benchmark_run",
]
