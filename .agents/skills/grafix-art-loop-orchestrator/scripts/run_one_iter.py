from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import subprocess
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from grafix_adapter import GrafixAdapter, RenderRequest
from make_contact_sheet import create_contact_sheet

LOOP_ROOT = Path("sketch/agent_loop")


def make_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    nonce = random.randint(1000, 9999)
    return f"{stamp}-{nonce}"


@dataclass(slots=True)
class IterationRunConfig:
    run_id: str
    iteration: int
    m: int
    ideaman_cmd: str | None
    artist_cmd: str
    critic_cmd: str
    creative_brief_path: Path | None = None
    baseline_artifact_path: Path | None = None
    critic_feedback_path: Path | None = None
    artist_profile_dir: Path | None = None
    workers: int = 0
    max_attempts: int = 2
    grafix_python_bin: str = "python"
    default_render_t: float = 0.0
    default_canvas: tuple[int, int] = (800, 800)
    grafix_config_path: Path | None = None


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Could not find repository root (pyproject.toml not found).")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_command(command: str, *, cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GRAFIX_AGENT_LOOP_ROOT"] = str(LOOP_ROOT.resolve())
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=env,
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return result


def _fill_template(template: str, mapping: dict[str, Any]) -> str:
    command = str(template)
    for key, value in mapping.items():
        command = command.replace("{" + str(key) + "}", str(value))
    return command


def _normalize_brief(raw: Any) -> dict[str, Any]:
    brief = raw if isinstance(raw, dict) else {}
    constraints = brief.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    canvas = constraints.get("canvas", "unknown")
    time_budget = constraints.get("time_budget_sec", 30)
    avoid = constraints.get("avoid", [])
    if not isinstance(avoid, list):
        avoid = []

    return {
        "title": str(brief.get("title", "Untitled Loop")),
        "intent": str(brief.get("intent", "")),
        "constraints": {
            "canvas": canvas,
            "time_budget_sec": int(time_budget),
            "avoid": [str(item) for item in avoid],
        },
        "variation_axes": [str(item) for item in brief.get("variation_axes", []) if isinstance(item, (str, int, float))],
        "aesthetic_targets": str(brief.get("aesthetic_targets", "")),
    }


def _resolve_ref(ref: str | None, variant_dir: Path) -> str | None:
    if ref is None:
        return None
    ref_path = Path(str(ref))
    if not ref_path.is_absolute():
        ref_path = (variant_dir / ref_path).resolve()
    return str(ref_path)


def _is_under_loop_root(path: str | None, loop_root: Path) -> bool:
    if path is None:
        return False
    try:
        Path(path).resolve().relative_to(loop_root.resolve())
        return True
    except ValueError:
        return False


def _validate_image(path: str | None) -> tuple[bool, str]:
    if path is None:
        return False, "image_ref is null"
    image_path = Path(path)
    if not image_path.exists():
        return False, "image file does not exist"
    if image_path.stat().st_size <= 0:
        return False, "image file size is zero"
    try:
        with Image.open(image_path) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid image: {exc}"
    return True, ""


def _fallback_brief(iteration: int) -> dict[str, Any]:
    return {
        "title": f"Auto Brief Iteration {iteration}",
        "intent": "Create a coherent geometric composition and improve the selected winner.",
        "constraints": {
            "canvas": "unknown",
            "time_budget_sec": 30,
            "avoid": ["broken geometry", "empty output"],
        },
        "variation_axes": ["composition", "density", "line rhythm"],
        "aesthetic_targets": "clear focal hierarchy and controlled negative space",
    }


def _fallback_critique(iteration: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranking: list[dict[str, Any]] = []
    for index, artifact in enumerate(candidates):
        ranking.append(
            {
                "variant_id": str(artifact.get("variant_id", "")),
                "score": float(max(0.0, 9.0 - index * 0.5)),
                "reason": "fallback ranking",
            }
        )
    winner_variant = ranking[0]["variant_id"] if ranking else None
    return {
        "iteration": int(iteration),
        "ranking": ranking,
        "winner": {
            "variant_id": winner_variant,
            "why_best": "fallback winner",
            "what_to_preserve": "coherence",
            "what_to_fix_next": "add stronger contrast",
            "next_iteration_directives": [
                {
                    "priority": 1,
                    "directive": "improve composition contrast",
                    "rationale": "fallback directive",
                }
            ],
        },
    }


def _canvas_from_brief(brief: dict[str, Any], fallback: tuple[int, int]) -> tuple[int, int]:
    constraints = brief.get("constraints")
    if isinstance(constraints, dict):
        canvas = constraints.get("canvas")
        if isinstance(canvas, dict):
            width = canvas.get("w")
            height = canvas.get("h")
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                return int(width), int(height)
        if isinstance(canvas, (list, tuple)) and len(canvas) == 2:
            width, height = canvas[0], canvas[1]
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                return int(width), int(height)
    return int(fallback[0]), int(fallback[1])


def _infer_callable_ref(code_path: Path, variant_dir: Path, *, attr: str = "draw") -> str | None:
    code = code_path.resolve()
    root = variant_dir.resolve()
    try:
        rel = code.relative_to(root)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    module = ".".join(rel.with_suffix("").parts)
    if not module:
        return None
    return f"{module}:{attr}"


def _coerce_float(value: Any, fallback: float) -> float:
    if value is None:
        return float(fallback)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _coerce_canvas(value: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    if isinstance(value, dict):
        width = value.get("w")
        height = value.get("h")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return int(width), int(height)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        width, height = value[0], value[1]
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return int(width), int(height)
    return int(fallback[0]), int(fallback[1])


def _normalize_artifact(
    raw: Any,
    *,
    loop_root: Path,
    variant_dir: Path,
    artist_id: str,
    variant_id: str,
    iteration: int,
    seed: int,
    stdout_ref: Path,
    stderr_ref: Path,
) -> dict[str, Any]:
    artifact = raw if isinstance(raw, dict) else {}
    status = str(artifact.get("status", "success"))
    if status not in {"success", "failed"}:
        status = "failed"

    code_ref = _resolve_ref(artifact.get("code_ref"), variant_dir)
    image_ref = _resolve_ref(artifact.get("image_ref"), variant_dir)
    if code_ref is not None and not _is_under_loop_root(code_ref, loop_root):
        status = "failed"
        code_ref = None
    if image_ref is not None and not _is_under_loop_root(image_ref, loop_root):
        status = "failed"
        image_ref = None

    params = artifact.get("params", {})
    if not isinstance(params, dict):
        params = {}

    return {
        "artist_id": str(artifact.get("artist_id", artist_id)),
        "iteration": int(artifact.get("iteration", iteration)),
        "variant_id": str(artifact.get("variant_id", variant_id)),
        "status": status,
        "code_ref": code_ref,
        "image_ref": image_ref,
        "seed": int(artifact.get("seed", seed)),
        "params": params,
        "stdout_ref": str(stdout_ref.resolve()),
        "stderr_ref": str(stderr_ref.resolve()),
        "artist_summary": str(artifact.get("artist_summary", "")),
        "callable_ref": None if artifact.get("callable_ref") in {None, ""} else str(artifact.get("callable_ref")),
        "render_t": artifact.get("render_t"),
        "render_canvas": artifact.get("render_canvas"),
    }


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not Path(path).exists():
        return None
    data = _read_json(Path(path))
    if isinstance(data, dict):
        return data
    return None


def _render_with_grafix_adapter(
    *,
    artifact: dict[str, Any],
    brief: dict[str, Any],
    variant_dir: Path,
    loop_root: Path,
    repo_root: Path,
    adapter: GrafixAdapter,
    attempt: int,
    config: IterationRunConfig,
) -> dict[str, Any]:
    if artifact.get("status") != "success":
        return artifact

    image_ok, _ = _validate_image(artifact.get("image_ref"))
    if image_ok:
        return artifact

    code_ref = artifact.get("code_ref")
    if not isinstance(code_ref, str) or not code_ref:
        artifact["status"] = "failed"
        artifact["artist_summary"] = f"{artifact.get('artist_summary', '')} | code_ref is required for grafix export".strip(" |")
        return artifact

    code_path = Path(code_ref).resolve()
    if not code_path.exists():
        artifact["status"] = "failed"
        artifact["artist_summary"] = f"{artifact.get('artist_summary', '')} | code_ref does not exist".strip(" |")
        return artifact

    callable_ref = artifact.get("callable_ref")
    if not isinstance(callable_ref, str) or not callable_ref.strip():
        callable_ref = _infer_callable_ref(code_path, variant_dir, attr="draw")
    if not callable_ref:
        artifact["status"] = "failed"
        artifact["artist_summary"] = f"{artifact.get('artist_summary', '')} | callable_ref could not be inferred".strip(" |")
        return artifact

    brief_canvas = _canvas_from_brief(brief, config.default_canvas)
    requested_canvas = _coerce_canvas(artifact.get("render_canvas"), brief_canvas)
    render_t = _coerce_float(artifact.get("render_t"), config.default_render_t)

    existing_image = artifact.get("image_ref")
    output_path = Path(existing_image).resolve() if isinstance(existing_image, str) and existing_image else variant_dir / "out.png"
    output_path = output_path.resolve()
    if not _is_under_loop_root(str(output_path), loop_root):
        artifact["status"] = "failed"
        artifact["artist_summary"] = f"{artifact.get('artist_summary', '')} | image_ref must be under sketch/agent_loop".strip(" |")
        return artifact

    render_stdout_path = variant_dir / f"render_stdout_attempt_{attempt}.txt"
    render_stderr_path = variant_dir / f"render_stderr_attempt_{attempt}.txt"
    render_result = adapter.render(
        RenderRequest(
            callable_ref=str(callable_ref),
            output_path=output_path,
            canvas=requested_canvas,
            t=render_t,
            config_path=config.grafix_config_path,
            python_bin=config.grafix_python_bin,
            cwd=repo_root,
            additional_python_paths=(variant_dir,),
        ),
        stdout_path=render_stdout_path,
        stderr_path=render_stderr_path,
    )

    artifact["callable_ref"] = str(callable_ref)
    artifact["render_t"] = float(render_t)
    artifact["render_canvas"] = [int(requested_canvas[0]), int(requested_canvas[1])]
    artifact["render_command"] = render_result.command
    artifact["render_exit_code"] = int(render_result.exit_code)
    artifact["render_stdout_ref"] = str(render_stdout_path.resolve())
    artifact["render_stderr_ref"] = str(render_stderr_path.resolve())

    if render_result.ok:
        artifact["image_ref"] = str(render_result.output_path.resolve())
        artifact["status"] = "success"
        return artifact

    artifact["status"] = "failed"
    error_summary = render_result.stderr.strip().splitlines()
    first_line = error_summary[0] if error_summary else "grafix export failed"
    artifact["artist_summary"] = f"{artifact.get('artist_summary', '')} | {first_line}".strip(" |")
    return artifact


def run_iteration(config: IterationRunConfig) -> dict[str, Any]:
    if config.m <= 0:
        raise ValueError("m must be positive")
    if config.max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if config.default_canvas[0] <= 0 or config.default_canvas[1] <= 0:
        raise ValueError("default canvas must be positive")

    repo_root = _find_repo_root(Path.cwd())
    adapter = GrafixAdapter(repo_root=repo_root)
    loop_root = LOOP_ROOT.resolve()
    loop_root.mkdir(parents=True, exist_ok=True)

    run_dir = loop_root / "runs" / config.run_id
    iter_dir = run_dir / f"iter_{config.iteration:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    baseline = _load_optional_json(config.baseline_artifact_path)
    critic_feedback = _load_optional_json(config.critic_feedback_path)

    creative_brief_path = iter_dir / "creative_brief.json"
    if config.creative_brief_path is not None:
        creative_brief = _normalize_brief(_read_json(Path(config.creative_brief_path)))
        _write_json(creative_brief_path, creative_brief)
    else:
        if config.ideaman_cmd is None:
            raise ValueError("creative_brief_path or ideaman_cmd is required")
        ideaman_context = {
            "run_id": config.run_id,
            "iteration": config.iteration,
            "loop_root": str(loop_root),
        }
        ideaman_context_path = iter_dir / "ideaman_context.json"
        _write_json(ideaman_context_path, ideaman_context)
        ideaman_stdout = iter_dir / "ideaman_stdout.txt"
        ideaman_stderr = iter_dir / "ideaman_stderr.txt"
        ideaman_cmd = _fill_template(
            config.ideaman_cmd,
            {
                "run_id": config.run_id,
                "iteration": config.iteration,
                "repo_root": repo_root,
                "loop_root": loop_root,
                "brief": creative_brief_path,
                "context": ideaman_context_path,
            },
        )
        _run_command(ideaman_cmd, cwd=iter_dir, stdout_path=ideaman_stdout, stderr_path=ideaman_stderr)
        if creative_brief_path.exists():
            creative_brief = _normalize_brief(_read_json(creative_brief_path))
            _write_json(creative_brief_path, creative_brief)
        else:
            creative_brief = _fallback_brief(config.iteration)
            _write_json(creative_brief_path, creative_brief)

    profile_dir = config.artist_profile_dir
    if profile_dir is None:
        profile_dir = Path(".codex/skills/grafix-art-loop-artist/references/artist_profiles")

    iteration_context = {
        "run_id": config.run_id,
        "iteration": config.iteration,
        "creative_brief": creative_brief,
        "baseline_artifact": baseline,
        "critic_feedback_prev": critic_feedback,
    }
    _write_json(iter_dir / "iteration_context.json", iteration_context)

    def run_variant(variant_index: int) -> dict[str, Any]:
        variant_id = f"v{variant_index}"
        artist_id = f"artist-{variant_index:02d}"
        variant_dir = iter_dir / variant_id
        variant_dir.mkdir(parents=True, exist_ok=True)

        profile_path = profile_dir / f"artist_{variant_index:02d}.txt"
        profile_text = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
        variant_context = dict(iteration_context)
        variant_context["variant_id"] = variant_id
        variant_context["artist_id"] = artist_id
        variant_context["artist_profile"] = profile_text

        context_path = variant_dir / "artist_context.json"
        artifact_path = variant_dir / "artifact.json"
        _write_json(context_path, variant_context)

        fallback_seed = random.Random(f"{config.run_id}-{config.iteration}-{variant_id}").randint(1, 2**31 - 1)
        final_artifact = {
            "artist_id": artist_id,
            "iteration": config.iteration,
            "variant_id": variant_id,
            "status": "failed",
            "code_ref": None,
            "image_ref": None,
            "seed": fallback_seed,
            "params": {},
            "stdout_ref": None,
            "stderr_ref": None,
            "artist_summary": "artist command did not return artifact",
        }

        for attempt in range(1, config.max_attempts + 1):
            seed = fallback_seed + attempt - 1
            stdout_path = variant_dir / f"stdout_attempt_{attempt}.txt"
            stderr_path = variant_dir / f"stderr_attempt_{attempt}.txt"
            command = _fill_template(
                config.artist_cmd,
                {
                    "run_id": config.run_id,
                    "iteration": config.iteration,
                    "repo_root": repo_root,
                    "loop_root": loop_root,
                    "variant_id": variant_id,
                    "artist_id": artist_id,
                    "variant_dir": variant_dir,
                    "artifact": artifact_path,
                    "context": context_path,
                    "brief": creative_brief_path,
                    "baseline": "" if config.baseline_artifact_path is None else Path(config.baseline_artifact_path),
                    "feedback": "" if config.critic_feedback_path is None else Path(config.critic_feedback_path),
                    "seed": seed,
                    "attempt": attempt,
                    "profile": profile_path if profile_path.exists() else "",
                },
            )
            result = _run_command(command, cwd=variant_dir, stdout_path=stdout_path, stderr_path=stderr_path)
            raw_artifact = _read_json(artifact_path) if artifact_path.exists() else {}
            normalized = _normalize_artifact(
                raw_artifact,
                loop_root=loop_root,
                variant_dir=variant_dir,
                artist_id=artist_id,
                variant_id=variant_id,
                iteration=config.iteration,
                seed=seed,
                stdout_ref=stdout_path,
                stderr_ref=stderr_path,
            )
            normalized["command_exit_code"] = int(result.returncode)
            normalized["attempt"] = attempt

            normalized = _render_with_grafix_adapter(
                artifact=normalized,
                brief=creative_brief,
                variant_dir=variant_dir,
                loop_root=loop_root,
                repo_root=repo_root,
                adapter=adapter,
                attempt=attempt,
                config=config,
            )
            image_ok, image_error = _validate_image(normalized.get("image_ref"))
            if normalized["status"] == "success" and image_ok:
                final_artifact = normalized
                break

            normalized["status"] = "failed"
            if image_error:
                normalized["artist_summary"] = f"{normalized.get('artist_summary', '')} | {image_error}".strip(" |")
            final_artifact = normalized

        _write_json(artifact_path, final_artifact)
        return final_artifact

    worker_count = config.m if config.workers <= 0 else min(config.workers, config.m)
    artifacts: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(run_variant, index): index for index in range(1, config.m + 1)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                artifacts.append(future.result())
            except Exception as exc:  # noqa: BLE001
                variant_id = f"v{index}"
                artist_id = f"artist-{index:02d}"
                variant_dir = iter_dir / variant_id
                variant_dir.mkdir(parents=True, exist_ok=True)
                stdout_path = variant_dir / "stdout_exception.txt"
                stderr_path = variant_dir / "stderr_exception.txt"
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text(traceback.format_exc(), encoding="utf-8")
                fallback = {
                    "artist_id": artist_id,
                    "iteration": config.iteration,
                    "variant_id": variant_id,
                    "status": "failed",
                    "code_ref": None,
                    "image_ref": None,
                    "seed": None,
                    "params": {},
                    "stdout_ref": str(stdout_path.resolve()),
                    "stderr_ref": str(stderr_path.resolve()),
                    "artist_summary": f"exception: {exc}",
                }
                _write_json(variant_dir / "artifact.json", fallback)
                artifacts.append(fallback)

    artifacts.sort(key=lambda item: str(item.get("variant_id", "")))
    _write_json(iter_dir / "artifacts.json", artifacts)

    valid_artifacts = [artifact for artifact in artifacts if artifact.get("status") == "success"]
    candidates_path = iter_dir / "candidates.json"
    _write_json(candidates_path, valid_artifacts)

    contact_sheet_path = iter_dir / "contact_sheet.png"
    if valid_artifacts:
        images = [Path(str(artifact["image_ref"])) for artifact in valid_artifacts if artifact.get("image_ref")]
        if images:
            create_contact_sheet(images, contact_sheet_path, columns=min(4, max(1, config.m)))

    critique_path = iter_dir / "critique.json"
    critic_context_path = iter_dir / "critic_context.json"
    _write_json(
        critic_context_path,
        {
            "run_id": config.run_id,
            "iteration": config.iteration,
            "creative_brief": creative_brief,
            "candidates_path": str(candidates_path.resolve()),
            "contact_sheet_path": str(contact_sheet_path.resolve()) if contact_sheet_path.exists() else None,
        },
    )
    critic_stdout = iter_dir / "critic_stdout.txt"
    critic_stderr = iter_dir / "critic_stderr.txt"

    critique: dict[str, Any]
    if valid_artifacts:
        critic_cmd = _fill_template(
            config.critic_cmd,
                {
                    "run_id": config.run_id,
                    "iteration": config.iteration,
                    "repo_root": repo_root,
                    "loop_root": loop_root,
                    "candidates": candidates_path,
                    "grid": contact_sheet_path if contact_sheet_path.exists() else "",
                    "critique": critique_path,
                    "context": critic_context_path,
            },
        )
        _run_command(critic_cmd, cwd=iter_dir, stdout_path=critic_stdout, stderr_path=critic_stderr)
        critique = _read_json(critique_path) if critique_path.exists() else _fallback_critique(config.iteration, valid_artifacts)
    else:
        critic_stdout.write_text("", encoding="utf-8")
        critic_stderr.write_text("No valid artifacts to critique.", encoding="utf-8")
        critique = _fallback_critique(config.iteration, valid_artifacts)

    if not isinstance(critique, dict):
        critique = _fallback_critique(config.iteration, valid_artifacts)
    winner_info = critique.get("winner")
    if not isinstance(winner_info, dict):
        winner_info = {}

    winner_variant_id = winner_info.get("variant_id")
    winner: dict[str, Any] | None = None
    if winner_variant_id is not None:
        for artifact in valid_artifacts:
            if artifact.get("variant_id") == winner_variant_id:
                winner = artifact
                break
    if winner is None and valid_artifacts:
        winner = valid_artifacts[0]
        winner_info["variant_id"] = winner.get("variant_id")
    critique["winner"] = winner_info
    critique["iteration"] = int(config.iteration)

    _write_json(critique_path, critique)
    winner_feedback_path = iter_dir / "winner_feedback.json"
    _write_json(winner_feedback_path, winner_info)

    manifest = {
        "run_id": config.run_id,
        "iteration": config.iteration,
        "loop_root": str(loop_root),
        "iter_dir": str(iter_dir.resolve()),
        "creative_brief_path": str(creative_brief_path.resolve()),
        "artifacts_path": str((iter_dir / "artifacts.json").resolve()),
        "candidates_path": str(candidates_path.resolve()),
        "contact_sheet_path": str(contact_sheet_path.resolve()) if contact_sheet_path.exists() else None,
        "critique_path": str(critique_path.resolve()),
        "winner_artifact_path": None if winner is None else str((iter_dir / winner["variant_id"] / "artifact.json").resolve()),
        "winner_feedback_path": str(winner_feedback_path.resolve()),
        "valid_count": len(valid_artifacts),
        "total_count": len(artifacts),
    }
    _write_json(iter_dir / "manifest.json", manifest)
    return manifest


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one iteration of Grafix art loop.")
    parser.add_argument("--run-id", default=None, help="run id")
    parser.add_argument("--iteration", type=int, default=1, help="iteration index")
    parser.add_argument("--m", type=int, default=6, help="number of artist variants")
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
    parser.add_argument("--ideaman-cmd", default=None, help="ideaman command template")
    parser.add_argument("--artist-cmd", required=True, help="artist command template")
    parser.add_argument("--critic-cmd", required=True, help="critic command template")
    parser.add_argument("--creative-brief", default=None, help="existing brief json path")
    parser.add_argument("--baseline-artifact", default=None, help="baseline artifact json path")
    parser.add_argument("--critic-feedback", default=None, help="previous winner feedback json path")
    parser.add_argument(
        "--artist-profile-dir",
        default=".codex/skills/grafix-art-loop-artist/references/artist_profiles",
        help="artist profile directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_id = args.run_id if args.run_id else make_run_id()
    config = IterationRunConfig(
        run_id=str(run_id),
        iteration=int(args.iteration),
        m=int(args.m),
        ideaman_cmd=args.ideaman_cmd,
        artist_cmd=args.artist_cmd,
        critic_cmd=args.critic_cmd,
        creative_brief_path=None if args.creative_brief is None else Path(args.creative_brief),
        baseline_artifact_path=None if args.baseline_artifact is None else Path(args.baseline_artifact),
        critic_feedback_path=None if args.critic_feedback is None else Path(args.critic_feedback),
        artist_profile_dir=None if args.artist_profile_dir is None else Path(args.artist_profile_dir),
        workers=int(args.workers),
        max_attempts=max(1, int(args.max_attempts)),
        grafix_python_bin=str(args.grafix_python),
        default_render_t=float(args.render_t),
        default_canvas=(int(args.canvas[0]), int(args.canvas[1])),
        grafix_config_path=None if args.grafix_config is None else Path(args.grafix_config),
    )
    manifest = run_iteration(config)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
