from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_context(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _build_brief(context: dict[str, Any]) -> dict[str, Any]:
    iteration = int(context.get("iteration", 1))
    return {
        "title": f"Agent Loop Iteration {iteration}",
        "intent": "Generate a balanced line composition and refine it iteratively.",
        "constraints": {
            "canvas": {"w": 1024, "h": 1024},
            "time_budget_sec": 30,
            "avoid": ["empty output", "overlapping noise"],
        },
        "variation_axes": [
            "line angle and spacing",
            "focal balance around center",
            "contrast of stroke density",
        ],
        "aesthetic_targets": "clear structure with controlled rhythm and negative space",
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit CreativeBrief JSON for art loop.")
    parser.add_argument("--out", required=True, help="output brief json path")
    parser.add_argument("--context", default=None, help="optional context json path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out_path = Path(args.out).resolve()
    context = _read_context(None if args.context is None else Path(args.context).resolve())
    brief = _build_brief(context)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
