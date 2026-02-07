from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Could not find repository root (pyproject.toml not found).")


@dataclass(slots=True)
class RenderRequest:
    callable_ref: str
    output_path: Path
    canvas: tuple[int, int] = (800, 800)
    t: float = 0.0
    config_path: Path | None = None
    python_bin: str = "python"
    cwd: Path | None = None
    additional_python_paths: tuple[Path, ...] = ()


@dataclass(slots=True)
class RenderResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    output_path: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.output_path.exists() and self.output_path.stat().st_size > 0


class GrafixAdapter:
    def __init__(self, repo_root: Path | None = None) -> None:
        base = repo_root if repo_root is not None else _find_repo_root(Path.cwd())
        self.repo_root = Path(base).resolve()
        self.src_path = self.repo_root / "src"

    def render(
        self,
        request: RenderRequest,
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> RenderResult:
        out_path = Path(request.output_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        width, height = int(request.canvas[0]), int(request.canvas[1])
        command = [
            str(request.python_bin),
            "-m",
            "grafix",
            "export",
            "--callable",
            str(request.callable_ref),
            "--t",
            str(float(request.t)),
            "--canvas",
            str(width),
            str(height),
            "--out",
            str(out_path),
        ]
        if request.config_path is not None:
            command.extend(["--config", str(Path(request.config_path).resolve())])

        env = os.environ.copy()
        python_paths = [str(self.src_path)]
        for path in request.additional_python_paths:
            python_paths.append(str(Path(path).resolve()))
        existing_pythonpath = env.get("PYTHONPATH")
        merged = os.pathsep.join(python_paths)
        env["PYTHONPATH"] = merged if not existing_pythonpath else f"{merged}{os.pathsep}{existing_pythonpath}"

        result = subprocess.run(
            command,
            cwd=str((request.cwd if request.cwd is not None else self.repo_root).resolve()),
            text=True,
            capture_output=True,
            env=env,
        )

        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path.write_text(result.stdout, encoding="utf-8")
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_path.write_text(result.stderr, encoding="utf-8")

        return RenderResult(
            command=command,
            exit_code=int(result.returncode),
            stdout=result.stdout,
            stderr=result.stderr,
            output_path=out_path,
        )
