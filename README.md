# Grafix

Grafix is a Python-based creative coding framework for line-based geometry:

- Generate primitives (`G`)
- Chain effects (`E`)
- Real-time interactive rendering (`run`)
- Export plotter-ready G-code
- Export visuals (SVG / PNG / MP4)

<img src="https://raw.githubusercontent.com/tyhts0829/grafix/main/docs/readme/top_movie.gif" width="1200" alt="Grafix demo" />
<img src="https://raw.githubusercontent.com/tyhts0829/grafix/main/docs/readme/penplot_movie.gif" width="1200" alt="Penplotting" />

<img src="https://raw.githubusercontent.com/tyhts0829/grafix/main/docs/readme/penplot1.JPG" width="800" alt="pen plotter art example" />

## Installation

```bash
pip install grafix
```

## Requirements

- Python >= 3.11
- macOS-first (tested on macOS / Apple Silicon).
- Optional external tools:
  - `resvg` for PNG export (`P` key / headless PNG export)
  - `ffmpeg` for MP4 recording (`V` key)

macOS (Homebrew):

```bash
brew install resvg ffmpeg
```

## Quick start

```python
from grafix import E, G, run

CANVAS_SIZE = (148, 210)  # A5 [mm]


def draw(t: float):
    # Coordinates are in canvas units: (0,0)=top-left, +x=right, +y=down.
    # Keyword arguments are discovered at runtime and show up in the Parameter GUI.
    geometry = G.polyhedron()
    effect = E.fill().subdivide().displace().rotate(rotation=(t * 6, t * 5, t * 4))
    return effect(geometry)


if __name__ == "__main__":
    run(draw, canvas_size=CANVAS_SIZE, render_scale=5.0)
```

To run a sketch file with transactional live reload:

```bash
python -m grafix run sketch.py --watch
```

Grafix polls the source mtime without an extra watcher dependency. It loads changed
operations, presets, and `draw(t)` into staging registries, validates them, and only then
swaps the callable and worker generation. A syntax/load error keeps the last-good code,
frame, parameters, and worker alive; the Inspector shows the traceback with Retry/Open.

## Core API

- `G`: primitive Geometry factories (`G.polygon(...)`, `G.grid(...)`, ...)
- `E`: Effect chain builders (`E.fill(...).rotate(...)`)
- `L`: wrap Geometry into Layers (color / thickness) for multi-pen / multi-pass workflows
- `P` / `@preset`: reusable components
- `cc`: MIDI CC(`cc[1]` -> 0..1) to control parameters with physical controllers
- `run(draw)`: interactive rendering + Parameter GUI
- `ResourceBudget`: per-operation vertex/line/byte limits checked before large allocations

`run()` evaluates `draw(t)` in one background worker by default (`n_worker=1`) so the
window stays responsive. Use `n_worker=0` only when synchronous evaluation is required,
or increase the worker count for CPU-heavy `draw(t)` functions. Background evaluation
uses multiprocessing `spawn`, so keep `draw` at module scope and call `run()` behind an
`if __name__ == "__main__":` guard. A background evaluation that exceeds
`evaluation_timeout=5.0` seconds is cancelled by restarting its worker while the last
successful frame stays visible; pass `evaluation_timeout=None` to disable this deadline.
Temporary user-code/effect errors keep the last successful frame visible and appear in
the Parameter GUI monitor bar; fixing the error lets the next successful frame recover
without restarting the application.

The Parameter GUI shows each value's effective `CODE` / `UI` / `MIDI LIVE` /
`MIDI FROZEN` source. Search and structured filters find rows by label, operation,
source, or MIDI CC; favorites, collapsible groups, and the Help pane keep large scenes
navigable. Parameter edits support coalesced Undo/Redo, named variations, deterministic
randomize/lock/morph, and debounced atomic autosave, so it is safe to explore alternatives
and return to an earlier state. Use `Cmd/Ctrl+Z` to undo and `Cmd/Ctrl+Shift+Z` (or
`Ctrl+Y`) to redo while the Parameter GUI is focused.

Closing the Inspector hides it instead of stopping the artwork; `Cmd/Ctrl+I` shows it
again. Preview/Inspector placement, Inspector visibility, and UI scale are saved per
sketch and clamped to the available screens on the next launch.

Use `run(..., resource_budget=ResourceBudget(...))` to tune allocation limits for the
machine or sketch. The defaults apply to code-provided values as well as GUI values.

`G`, `E`, `L`, and `P` accept `key=str|int` as a stable semantic identity when a
parameter group must survive moving its call within the same source file. For repeated
structures, add `instance_key=i` to give each loop/comprehension instance its own group,
or use `shared=True` to intentionally share one semantic group. `instance_key` and
`shared=True` are mutually exclusive. Without these options, Grafix derives a cached
project-relative call-site identity automatically.

## Export & shortcuts

When the draw window is focused:

- `S`: save SVG
- `P`: save PNG (requires `resvg`; its intermediate SVG is private and temporary)
- `V`: start/stop MP4 recording (requires `ffmpeg`)
- `G`: save G-code
- `Shift+G`: save G-code per layer (when your sketch returns multiple Layers)
- `Space`: play/pause the preview timeline
- `Home`: reset preview time to zero
- `Left` / `Right`: step backward/forward by one frame (and pause)
- `[` / `]`: halve/double preview speed (0.125x to 8x)

Outputs are written under `paths.output_dir` (default: `data/output`), under per-kind subdirectories (`svg/`, `png/`, `gcode/`, ...).
Interactive captures never silently overwrite an existing artifact: Grafix reserves an
unused numbered filename and writes a sibling `*.capture.json` manifest containing the
Grafix/source/git/config/parameter snapshot provenance, frame time/quality, output size,
format, and actual artifact paths. Provenance is fixed with the frame in the main process;
the capture worker does not re-read Git, config, or source state.
PNG and G-code shortcuts enqueue an immutable frame snapshot on one bounded background
worker, so a slow export does not stop the preview loop. After the first frame, each
shortcut is bound to the frame visible at keypress and is immediately admitted or rejected
against both request-count and aggregate geometry-byte limits. Accepted jobs keep FIFO
order, repeated captures of the same immutable snapshot share the retained geometry, and
rejections are shown explicitly instead of replacing or silently dropping an older request.
A small intent queue exists only before the first frame is available.

The byte limit is a conservative process-wide estimate: Grafix accounts for the parent
geometry, multiprocessing serialization, and the worker copy. It is a backpressure budget,
not an exact operating-system RSS measurement. Closing the app finalizes an active video
before draining other exports; video finalization and export drain share a bounded deadline,
and unfinished exports are reported as cancelled when that deadline is reached. Recording
uses an explicit pause-on-error policy: a failed scene is not replaced by a duplicated
last-good video frame, and its fixed-FPS clock does not advance. The recording manifest
reports written/dropped/duplicated/error counts and the stop/abort reason.

## Examples

<!-- BEGIN:README_EXAMPLES_GRN -->
<table>
  <tr>
    <td><img src="docs/readme/grn/1.png" width="320" alt="grn 1" /></td>
    <td><img src="docs/readme/grn/2.png" width="320" alt="grn 2" /></td>
    <td><img src="docs/readme/grn/3.png" width="320" alt="grn 3" /></td>
  </tr>
  <tr>
    <td><img src="docs/readme/grn/4.png" width="320" alt="grn 4" /></td>
    <td><img src="docs/readme/grn/5.png" width="320" alt="grn 5" /></td>
    <td><img src="docs/readme/grn/6.png" width="320" alt="grn 6" /></td>
  </tr>
  <tr>
    <td><img src="docs/readme/grn/7.png" width="320" alt="grn 7" /></td>
    <td><img src="docs/readme/grn/8.png" width="320" alt="grn 8" /></td>
    <td><img src="docs/readme/grn/9.png" width="320" alt="grn 9" /></td>
  </tr>
  <tr>
    <td><img src="docs/readme/grn/10.png" width="320" alt="grn 10" /></td>
    <td><img src="docs/readme/grn/11.png" width="320" alt="grn 11" /></td>
    <td><img src="docs/readme/grn/12.png" width="320" alt="grn 12" /></td>
  </tr>
  <tr>
    <td><img src="docs/readme/grn/13.png" width="320" alt="grn 13" /></td>
    <td><img src="docs/readme/grn/14.png" width="320" alt="grn 14" /></td>
    <td><img src="docs/readme/grn/15.png" width="320" alt="grn 15" /></td>
  </tr>
  <tr>
    <td><img src="docs/readme/grn/16.png" width="320" alt="grn 16" /></td>
    <td><img src="docs/readme/grn/17.png" width="320" alt="grn 17" /></td>
    <td><img src="docs/readme/grn/18.png" width="320" alt="grn 18" /></td>
  </tr>
</table>
<!-- END:README_EXAMPLES_GRN -->

## Extending

You can register your own primitives and effects via decorators:

```python
import numpy as np

from grafix import effect, primitive

prim_meta = {"r": {"kind": "float", "ui_min": 1.0, "ui_max": 100.0}}
eff_meta = {"amount": {"kind": "float", "ui_min": 0.0, "ui_max": 2.0}}

@primitive(meta=prim_meta)
def user_prim(*, r=10.0) -> tuple[np.ndarray, np.ndarray]:
    coords = ...  # shape (N, 3)
    offsets = ...  # shape (M+1,)
    return coords, offsets


@effect(meta=eff_meta)
def user_eff(g: tuple[np.ndarray, np.ndarray], *, amount=1.0) -> tuple[np.ndarray, np.ndarray]:
    coords, offsets = g
    coords_out = ...
    return coords_out, offsets
```

Notes:

- Built-in primitives/effects must provide `meta=...` (enforced).
- User-defined primitives/effects use `(coords, offsets)` tuples (`coords` must be shape `(N,3)`).
- For user-defined ops, `meta` is optional. If omitted, parameters are not shown in the Parameter GUI.
- User-defined modules need to be imported once to register the ops.

## Presets (reusable components)

Use `@preset` to register a component, and call it via `P.<name>(...)`:

```python
from grafix import G, P, preset

meta = {
    "n_rows": {"kind": "int", "ui_min": 1, "ui_max": 20},
    "n_cols": {"kind": "int", "ui_min": 1, "ui_max": 20},
}

@preset(meta=meta)
def grid_system_frame(
    *,
    n_rows: int = 5,
    n_cols: int = 8,
    name=None,
    key=None,
):
    return G.grid(
        nx=n_cols,
        ny=n_rows,
        center=(150.0, 150.0, 0.0),
        scale=180.0,
    )


P.grid_system_frame()
```

A preset is a scene component: it must return a `Geometry`, a `Layer`, or a nested
sequence of those values (`SceneItem`). Every preset also accepts the automatically
added `activate` argument. When `activate=False`, Grafix skips the function body and
returns an empty `Geometry` that can be passed through the normal scene pipeline.

For IDE completion of `P.<name>(...)`, regenerate stubs after adding/changing presets:

```bash
python -m grafix stub
```

## Configuration (`config.yaml`)

A `config.yaml` lets you locate external fonts and choose where Grafix writes runtime outputs (`.svg`, `.png`, `.mp4`, `.gcode`).

Grafix starts from the packaged defaults (`grafix/resource/default_config.yaml`) and then overlays user config(s).

Load order (later wins):

1. packaged defaults
2. discovered config (0 or 1 file; first found wins)
3. explicit config path (if provided)

Config search (first found wins):

- `./.grafix/config.yaml` (project-local)
- `~/.config/grafix/config.yaml` (per-user)

You can also pass an explicit config path:

- `run(..., config_path="path/to/config.yaml")`
- `python -m grafix export --config path/to/config.yaml`

Validate or inspect effective values and their source before launching:

```bash
python -m grafix config validate .grafix/config.yaml
python -m grafix config show .grafix/config.yaml
```

Unknown keys and invalid values are rejected with a nearest-key hint. Interactive runs
remain recoverable: an invalid user config falls back to the packaged defaults and emits
an explicit Inspector diagnostic with the source and traceback. The validation CLI stays
strict and exits non-zero instead of applying that fallback.

Paths support `~` and environment variables like `$HOME`. Relative paths in a user
config are resolved from that config file's directory. Therefore paths in
`./.grafix/config.yaml` normally start with `../` when they point into the project root.

To create a project-local config, prefer the no-clobber project initializer:

```bash
python -m grafix init .
```

The packaged defaults are interpreted relative to the process working directory, so do
not copy them verbatim under `.grafix/`. A minimal project-local path overlay looks like:

```yaml
version: 1
paths:
  output_dir: "../data/output"
  sketch_dir: "../sketch"
  preset_module_dirs:
    - "../sketch/presets"
  font_dirs:
    - "../data/input/font"
```

Overlay is recursive for mapping values. For example, overriding only
`export.gcode.travel_feed` keeps the packaged defaults under `export.png` and the other
G-code fields.

To autoload user presets from a directory:

```yaml
paths:
  preset_module_dirs:
    - "../sketch/presets"
```

Useful project/operation CLI entry points:

```bash
python -m grafix init my-project       # no-clobber scaffold
python -m grafix doctor                # GL/resvg/ffmpeg/MIDI/font/output checks
python -m grafix examples list
python -m grafix list
python -m grafix describe primitive circle
python -m grafix stub                  # project-local G/E/P typing
```

## Text-to-Physical art (WIP)

I'm experimenting with a fully autonomous LLM loop that creates Grafix sketches end-to-end from a single prompt.

It iterates through:

- ideate
- implement
- render
- critique
- improve

No human intervention, just continuous iteration and unexpected visual evolution.
The image below was generated by the LLM in this closed loop.

<img src="https://raw.githubusercontent.com/tyhts0829/grafix/main/docs/readme/agent_generated_art.png" width="1200" alt="LLM-generated sketches (work in progress)" />

### Headless export (batch rendering)

The loop uses `python -m grafix export` to render `draw(t)` without opening any window.
The default parameter source is `code`, so headless output never reads a hidden ParamStore
unless you explicitly select `saved`, `recovery`, or a JSON path:

```bash
python -m grafix export --callable sketch.main:draw --t 0.0 --canvas 300 300
python -m grafix export --callable sketch.main:draw --format svg --out art.svg
python -m grafix export --callable sketch.main:draw --format gcode --out plot.gcode
python -m grafix export --callable sketch.main:draw --t 0.0 1.0 2.0 --format png --canvas 300 300 --out-dir data/output
python -m grafix export --callable sketch.main:draw --parameter-source saved --out saved-state.png
python -m grafix export --callable sketch.main:draw --parameter-source data/params.json --out explicit-state.svg
```

With an explicit config file:

```bash
python -m grafix export --config path/to/config.yaml --callable sketch.main:draw --t 0.0 --canvas 300 300
```

Existing artifacts are not overwritten by default. The CLI prints the actual numbered
artifact path and its `*.capture.json` manifest; pass `--overwrite` only when replacing
that generation is intentional.

Render saved named variations as no-clobber thumbnails plus an SVG contact sheet and a
structured partial-failure summary:

```bash
python -m grafix variations \
  --callable sketch.main:draw \
  --parameter-source saved \
  --out-dir data/output/variation-batches
```

Each thumbnail label includes the variation name and seed. A failed variation does not
discard successful siblings; the CLI reports the failed item and exits non-zero.

The direct API separates one final-quality render from capture. `line_thickness=0.001`
means 0.1% of the canvas short side:

```python
from grafix import RenderOptions, export, render

frame = render(
    draw,
    0.0,
    options=RenderOptions(canvas_size=(300, 300), line_thickness=0.001),
    parameter_source="code",
)
result = export(frame, "data/output/art.svg")
print(result.path, result.manifest_path)
```

## Troubleshooting

- `resvg が見つかりません`: install `resvg` and ensure it is on `PATH` (macOS: `brew install resvg`)
- `ffmpeg が見つかりません`: install `ffmpeg` (macOS: `brew install ffmpeg`)

## Development

```bash
# run without installation
PYTHONPATH=src python sketch/main.py

# tests / lint / typecheck
PYTHONPATH=src pytest -q
ruff check src/grafix tests
mypy src/grafix

# short deterministic measurements (fresh process per case)
PYTHONPATH=src python -m grafix benchmark run --suite system --profile smoke
# long measurements are explicit; hosted CI does not use wall time as a hard gate
PYTHONPATH=src python -m grafix benchmark run --suite all --profile long
# generate the offline HTML report from schema v3 run JSON
PYTHONPATH=src python -m grafix benchmark report
```

See: `architecture.md` and `docs/developer_guide.md`.
