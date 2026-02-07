# Grafix Art Loop Manual Session Plan (2026-02-06)

## Scope

- User request: execute art loop manually in this session with `N=3`, `M=4`.
- Do not use `run_loop.py` and do not use `tools/*.py`.
- Use skills: ideaman, artist, critic, orchestrator role.
- Save outputs under `sketch/agent_loop/runs/<run_id>/...`.

## Run Configuration

- [x] Decide `run_id` and create run root directory.
- [x] Set common render command policy:
  - `PYTHONPATH=src python -m grafix export --callable <module:draw> --t 0 --canvas 800 800 --out <out.png>`
- [x] Define variant-to-profile mapping using `references/artist_profiles/*`.

## Iteration 01 (M=4)

- [x] Generate `creative_brief.json` (ideaman output, schema-compliant).
- [x] For each variant `v1..v4`:
  - [x] Create `sketch.py` implementing `draw(t)` in `iter_01/vY/`.
  - [x] Create `artifact.json` (artist output, schema-compliant).
  - [x] Render `out.png` via `python -m grafix export`.
  - [x] Save render logs (`stdout.txt`, `stderr.txt`).
- [x] Build contact sheet `iter_01/contact_sheet.png` from all variant outputs.
- [x] Create `iter_01/critique.json` with ranking, winner, and prioritized next directives.

## Iteration 02 (M=4)

- [x] Use iteration 01 winner as baseline context.
- [x] For each variant `v1..v4`:
  - [x] Create `iter_02/vY/sketch.py` as controlled variation from baseline.
  - [x] Create `iter_02/vY/artifact.json`.
  - [x] Render `iter_02/vY/out.png` and save logs.
- [x] Build `iter_02/contact_sheet.png`.
- [x] Create `iter_02/critique.json` with next directives.

## Iteration 03 (M=4)

- [x] Use iteration 02 winner + directives as baseline context.
- [x] For each variant `v1..v4`:
  - [x] Create `iter_03/vY/sketch.py`.
  - [x] Create `iter_03/vY/artifact.json`.
  - [x] Render `iter_03/vY/out.png` and save logs.
- [x] Build `iter_03/contact_sheet.png`.
- [x] Create `iter_03/critique.json` (final winner included).

## Finalization

- [x] Write `run_summary.json` including per-iteration winners and file references.
- [x] Verify required files exist for all 12 variants (`sketch.py`, `out.png`, `artifact.json`).
- [x] Report completed/remaining checklist items in the session response.
