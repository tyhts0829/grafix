# Grafix

Grafix is a Python-based creative coding framework for line-based geometry:

- Generate primitives (`G`)
- Chain effects (`E`)
- Real-time interactive rendering (`run`)
- Export for plotter-ready G-code and visuals (SVG/PNG/MP4).

<img src="docs/readme/top_movie.gif" width="1200" alt="Grafix demo" />
<img src="docs/readme/penplot_movie.gif" width="1200" alt="Penplotting" />

<img src="docs/readme/penplot1.JPG" width="800" alt="pen plotter art example" />

## Requirements

- Python >= 3.11
- macOS-first (tested on macOS / Apple Silicon). Other platforms are not officially supported yet.
- Optional external tools:
  - `resvg` for PNG export (`P` key / headless PNG export)
  - `ffmpeg` for MP4 recording (`V` key)

macOS (Homebrew):

```bash
brew install resvg ffmpeg
```

## Installation

```bash
pip install grafix
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

## Core API

- `G`: primitive Geometry factories (`G.polygon(...)`, `G.grid(...)`, ...)
- `E`: effect chain builders (`E.fill(...).rotate(...)`)
- `L`: wrap Geometry into layers (color / thickness) for multi-pen / multi-pass workflows
- `P` / `@preset`: reusable components
- `cc`: read-only MIDI CC snapshot view (`cc[1]` -> 0..1). Midi learn is available to control params.
- `run(draw)`: interactive rendering + Parameter GUI

## Export & shortcuts

When the draw window is focused:

- `S`: save SVG
- `P`: save PNG (requires `resvg`; also saves the underlying SVG)
- `V`: start/stop MP4 recording (requires `ffmpeg`)
- `G`: save G-code
- `Shift+G`: save G-code per layer (when your sketch returns multiple layers)

Outputs are written under `paths.output_dir` (default: `data/output`), under per-kind subdirectories (`svg/`, `png/`, `gcode/`, ...).

## Headless export (PNG)

```bash
python -m grafix export --callable sketch.main:draw --t 0.0
python -m grafix export --callable sketch.main:draw --t 0.0 1.0 2.0 --out-dir data/output
```

With an explicit config file:

```bash
python -m grafix export --config path/to/config.yaml --callable sketch.main:draw --t 0.0
```

If you want to use the API directly, `Export` lives in `grafix.api`:

```python
from grafix.api import Export
```

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
</table>
<!-- END:README_EXAMPLES_GRN -->

## Extending (custom primitives / effects)

You can register your own primitives and effects via decorators:

```python
from grafix.api import effect, primitive


@primitive
def user_prim(*, r=10.0):
    ...


@effect
def user_eff(inputs, *, amount=1.0):
    ...
```

Notes:

- Built-in primitives/effects must provide `meta=...` (enforced).
- For user-defined ops, `meta` is optional. If omitted, parameters are not shown in the Parameter GUI.
- User-defined modules need to be imported once to register the ops.

## Presets (reusable components)

Use `@preset` to register a component, and call it via `P.<name>(...)`:

```python
from grafix import P, preset


@preset(meta={"scale": {"kind": "float", "ui_min": 0.1, "ui_max": 10.0}})
def grid_system_frame(
    *,
    scale: float = 1.0,
    n_rows: int = 5,
    n_cols: int = 8,
    name=None,
    key=None,
):
    ...


P.grid_system_frame()
```

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

Paths support `~` and environment variables like `$HOME`.

To create a project-local config (starting from the packaged defaults):

```bash
mkdir -p .grafix
python -c "from importlib.resources import files; print(files('grafix').joinpath('resource','default_config.yaml').read_text())" > .grafix/config.yaml
$EDITOR .grafix/config.yaml
```

Overlay is a top-level shallow update (no deep merge). If you override `export:`, keep both `export.png` and `export.gcode` blocks
from the packaged defaults.

To autoload user presets from a directory:

```yaml
paths:
  preset_module_dirs:
    - "sketch/presets"
```

To configure G-code export defaults (used when calling `export_gcode(..., params=None)`):

```yaml
export:
  gcode:
    origin: [0.0, 0.0]
    y_down: false
```

To prioritize MIDI device connections when using `midi_port_name="auto"`:

```yaml
midi:
  inputs:
    - port_name: "Grid"
      mode: "14bit"
    - port_name: "TX-6 Bluetooth"
      mode: "7bit"
    - port_name: "auto"
      mode: "7bit"
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
ruff check .
mypy src/grafix
```

See: `architecture.md` and `docs/developer_guide.md`.
