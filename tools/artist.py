from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_context(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _build_sketch_code(*, seed: int, variant_id: str) -> str:
    return (
        "from __future__ import annotations\n"
        "\n"
        "from grafix.api import G\n"
        "\n"
        "\n"
        "def draw(t: float):\n"
        f"    base_angle = {(seed % 70) + 10:.1f}\n"
        f"    base_length = {(seed % 420) + 260:.1f}\n"
        f"    offset = {(seed % 120) - 60:.1f}\n"
        "    angle = base_angle + t * 45.0\n"
        "    main = G.line(center=(512.0, 512.0, 0.0), length=base_length, angle=angle)\n"
        "    aux = G.line(center=(512.0 + offset, 512.0 - offset, 0.0), length=base_length * 0.72, angle=-angle)\n"
        "    return main + aux\n"
        "\n"
        f"# variant: {variant_id}\n"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit Artifact JSON for one artist variant.")
    parser.add_argument("--context", required=True, help="artist context json path")
    parser.add_argument("--artifact", required=True, help="artifact output path")
    parser.add_argument("--variant-dir", required=True, help="variant working directory")
    parser.add_argument("--variant-id", required=True, help="variant id")
    parser.add_argument("--artist-id", required=True, help="artist id")
    parser.add_argument("--seed", required=True, type=int, help="seed")
    parser.add_argument("--iteration", required=True, type=int, help="iteration")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    variant_dir = Path(args.variant_dir).resolve()
    variant_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = Path(args.artifact).resolve()
    _ = _read_context(Path(args.context).resolve())

    sketch_path = variant_dir / "sketch.py"
    sketch_path.write_text(
        _build_sketch_code(seed=int(args.seed), variant_id=str(args.variant_id)),
        encoding="utf-8",
    )

    artifact: dict[str, Any] = {
        "artist_id": str(args.artist_id),
        "iteration": int(args.iteration),
        "variant_id": str(args.variant_id),
        "status": "success",
        "code_ref": str(sketch_path),
        "callable_ref": "sketch:draw",
        "seed": int(args.seed),
        "params": {
            "mode": "tool-artist",
            "seed": int(args.seed),
        },
        "artist_summary": "Generated sketch.py and delegated rendering to GrafixAdapter.",
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
