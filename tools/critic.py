from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_candidates(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _variant_order_key(item: dict[str, Any]) -> tuple[int, str]:
    variant_id = str(item.get("variant_id", ""))
    if variant_id.startswith("v"):
        try:
            return int(variant_id[1:]), variant_id
        except ValueError:
            pass
    return 10**9, variant_id


def _build_critique(iteration: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "iteration": int(iteration),
            "ranking": [],
            "winner": {
                "variant_id": None,
                "why_best": "No valid candidates.",
                "what_to_preserve": "",
                "what_to_fix_next": "Fix artist output errors first.",
                "next_iteration_directives": [
                    {
                        "priority": 1,
                        "directive": "Ensure each artist emits a valid Artifact JSON with code_ref.",
                        "rationale": "No candidate was renderable.",
                    }
                ],
            },
        }

    ordered = sorted(candidates, key=_variant_order_key)
    ranking: list[dict[str, Any]] = []
    for index, item in enumerate(ordered):
        ranking.append(
            {
                "variant_id": str(item.get("variant_id")),
                "score": float(9.0 - index * 0.25),
                "reason": "Consistent line structure and renderability.",
            }
        )

    winner_id = ranking[0]["variant_id"]
    return {
        "iteration": int(iteration),
        "ranking": ranking,
        "winner": {
            "variant_id": winner_id,
            "why_best": "Best overall structural balance in current iteration.",
            "what_to_preserve": "Core compositional rhythm and central focus.",
            "what_to_fix_next": "Increase local contrast and reduce overlapping lines.",
            "next_iteration_directives": [
                {
                    "priority": 1,
                    "directive": "Keep primary motif and improve spacing clarity.",
                    "rationale": "Preserve coherence while improving readability.",
                },
                {
                    "priority": 2,
                    "directive": "Adjust angle range with moderate variation only.",
                    "rationale": "Avoid unstable geometry while exploring alternatives.",
                },
            ],
        },
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit Critique JSON from candidate artifacts.")
    parser.add_argument("--candidates", required=True, help="candidate artifacts json path")
    parser.add_argument("--grid", default=None, help="contact sheet path (optional)")
    parser.add_argument("--out", required=True, help="critique output path")
    parser.add_argument("--iteration", required=True, type=int, help="iteration")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    candidates = _read_candidates(Path(args.candidates).resolve())
    critique = _build_critique(int(args.iteration), candidates)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(critique, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
