from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from run_one_iter import IterationRunConfig, LOOP_ROOT, make_run_id, run_iteration


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run N iterations of Grafix art loop.")
    parser.add_argument("--n", type=int, default=8, help="number of iterations")
    parser.add_argument("--m", type=int, default=6, help="variants per iteration")
    parser.add_argument("--run-id", default=None, help="run id")
    parser.add_argument("--workers", type=int, default=0, help="parallel workers (0 -> m)")
    parser.add_argument("--max-attempts", type=int, default=2, help="max retries per variant")
    parser.add_argument("--grafix-python", default="python", help="python command used for `python -m grafix export`")
    parser.add_argument("--render-t", type=float, default=0.0, help="default t passed to grafix export")
    parser.add_argument(
        "--canvas",
        nargs=2,
        type=int,
        default=(800, 800),
        metavar=("W", "H"),
        help="default canvas for grafix export",
    )
    parser.add_argument("--grafix-config", default=None, help="optional config path for grafix export")
    parser.add_argument("--ideaman-cmd", required=True, help="ideaman command template")
    parser.add_argument("--artist-cmd", required=True, help="artist command template")
    parser.add_argument("--critic-cmd", required=True, help="critic command template")
    parser.add_argument(
        "--artist-profile-dir",
        default=".codex/skills/grafix-art-loop-artist/references/artist_profiles",
        help="artist profile directory",
    )
    parser.add_argument(
        "--refresh-brief-every",
        type=int,
        default=0,
        help="regenerate brief every K iterations (0 disables)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.n <= 0:
        raise ValueError("n must be positive")
    if args.m <= 0:
        raise ValueError("m must be positive")

    run_id = args.run_id if args.run_id else make_run_id()
    loop_root = LOOP_ROOT.resolve()
    loop_root.mkdir(parents=True, exist_ok=True)
    run_dir = loop_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    creative_brief_path: Path | None = None
    baseline_artifact_path: Path | None = None
    critic_feedback_path: Path | None = None

    history: list[dict[str, Any]] = []

    for iteration in range(1, args.n + 1):
        refresh = args.refresh_brief_every > 0 and iteration > 1 and (iteration - 1) % args.refresh_brief_every == 0
        use_ideaman = iteration == 1 or refresh

        config = IterationRunConfig(
            run_id=str(run_id),
            iteration=iteration,
            m=int(args.m),
            ideaman_cmd=args.ideaman_cmd if use_ideaman else None,
            artist_cmd=args.artist_cmd,
            critic_cmd=args.critic_cmd,
            creative_brief_path=None if use_ideaman else creative_brief_path,
            baseline_artifact_path=baseline_artifact_path,
            critic_feedback_path=critic_feedback_path,
            artist_profile_dir=Path(args.artist_profile_dir),
            workers=int(args.workers),
            max_attempts=max(1, int(args.max_attempts)),
            grafix_python_bin=str(args.grafix_python),
            default_render_t=float(args.render_t),
            default_canvas=(int(args.canvas[0]), int(args.canvas[1])),
            grafix_config_path=None if args.grafix_config is None else Path(args.grafix_config),
        )

        manifest = run_iteration(config)
        history.append(manifest)

        creative_brief_path = Path(manifest["creative_brief_path"])
        winner_artifact = manifest.get("winner_artifact_path")
        winner_feedback = manifest.get("winner_feedback_path")
        baseline_artifact_path = Path(winner_artifact) if winner_artifact else baseline_artifact_path
        critic_feedback_path = Path(winner_feedback) if winner_feedback else critic_feedback_path

        _write_json(run_dir / "loop_progress.json", {"run_id": run_id, "completed_iterations": iteration, "history": history})

    summary = {
        "run_id": run_id,
        "loop_root": str(loop_root),
        "run_dir": str(run_dir.resolve()),
        "iterations": history,
        "final_winner_artifact_path": history[-1].get("winner_artifact_path") if history else None,
    }
    _write_json(run_dir / "loop_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
