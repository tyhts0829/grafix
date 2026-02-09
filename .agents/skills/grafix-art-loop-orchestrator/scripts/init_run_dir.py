#!/usr/bin/env python3
"""Art loop の run ディレクトリ骨格を生成する補助 CLI。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^run_(\d{8})_(\d{6})_n(\d+)m(\d+)$")
DEFAULT_ROOT = Path("sketch/agent_loop/runs")


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    run_dir: Path
    n: int
    m: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize a grafix art-loop run directory skeleton.")
    parser.add_argument("--n", type=int, required=True, help="Number of iterations (N).")
    parser.add_argument("--m", type=int, required=True, help="Number of variants per iteration (M).")
    parser.add_argument("--run-id", type=str, help="Explicit run_id (must match run_YYYYMMDD_HHMMSS_n{n}m{m}).")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Runs root directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned paths without creating them.")
    parser.add_argument(
        "--update-latest",
        action="store_true",
        help="Update .latest_run_id/.last_run_id under runs root (opt-in).",
    )
    return parser.parse_args()


def validate_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive (got {value})")


def normalize_root(root: Path) -> Path:
    allowed = DEFAULT_ROOT.resolve()
    resolved = root.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"--root must be under {DEFAULT_ROOT} (got {root})") from exc
    return resolved


def generate_run_id(n: int, m: int, now: datetime) -> str:
    ts = now.strftime("%Y%m%d_%H%M%S")
    return f"run_{ts}_n{n}m{m}"


def validate_run_id(run_id: str, *, n: int, m: int) -> None:
    matched = RUN_ID_PATTERN.match(run_id)
    if not matched:
        raise ValueError(
            "run_id must match run_YYYYMMDD_HHMMSS_n{n}m{m} "
            f"(got {run_id!r}, example: run_20260209_214538_n4m8)"
        )
    n_in_id = int(matched.group(3))
    m_in_id = int(matched.group(4))
    if n_in_id != n or m_in_id != m:
        raise ValueError(f"run_id encodes n/m that differ from args (run_id: n={n_in_id}, m={m_in_id})")


def build_run_spec(args: argparse.Namespace) -> RunSpec:
    validate_positive("n", args.n)
    validate_positive("m", args.m)

    root = normalize_root(args.root)
    run_id = args.run_id or generate_run_id(args.n, args.m, datetime.now())
    validate_run_id(run_id, n=args.n, m=args.m)
    run_dir = root / run_id
    return RunSpec(run_id=run_id, run_dir=run_dir, n=args.n, m=args.m)


def variant_width(m: int) -> int:
    return max(2, len(str(m)))


def planned_dirs(spec: RunSpec) -> list[Path]:
    width = variant_width(spec.m)
    paths: list[Path] = []
    paths.append(spec.run_dir)
    paths.append(spec.run_dir / ".tmp")
    paths.append(spec.run_dir / "run_summary")
    for iter_idx in range(1, spec.n + 1):
        iter_dir = spec.run_dir / f"iter_{iter_idx:02d}"
        paths.append(iter_dir)
        for var_idx in range(1, spec.m + 1):
            paths.append(iter_dir / f"v{var_idx:0{width}d}")
    return paths


def update_latest_files(root: Path, run_id: str) -> None:
    latest_path = root / ".latest_run_id"
    last_path = root / ".last_run_id"
    previous = latest_path.read_text(encoding="utf-8").strip() if latest_path.exists() else ""
    if previous:
        last_path.write_text(previous + "\n", encoding="utf-8")
    latest_path.write_text(run_id + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    try:
        spec = build_run_spec(args)
        paths = planned_dirs(spec)

        print(f"run_id={spec.run_id} run_dir={spec.run_dir}")
        for path in paths:
            print(path)

        if args.dry_run:
            return 0

        if spec.run_dir.exists():
            raise ValueError(f"run_dir already exists: {spec.run_dir}")

        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

        if args.update_latest:
            update_latest_files(spec.run_dir.parent, spec.run_id)

        print("status=ok")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

