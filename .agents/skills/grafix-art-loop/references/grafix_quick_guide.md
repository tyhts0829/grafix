# Grafix Quick Guide

候補の実装・export時だけ参照する。座標は `(0, 0)` が左上、`+x` が右、`+y` が下。

## 最小sketch

```python
from grafix import E, G, L, run

CANVAS = (300, 300)


def draw(t: float):
    grid = G.grid(nx=18, ny=18, center=(150.0, 150.0, 0.0), scale=180.0)
    turned = E.rotate(rotation=(0.0, 0.0, 18.0 + t))(grid)
    return (
        L("grid").layer(grid, color=(0.08, 0.10, 0.14), thickness=0.0012),
        L("turned").layer(turned, color=(0.75, 0.18, 0.12), thickness=0.0010),
    )


if __name__ == "__main__":
    run(draw, canvas_size=CANVAS, render_scale=3.0)
```

- `G.<name>(...)`でGeometryを作り、`E.<name>(...)(geometry)`で変形する。
- `L("name").layer(...)`は単一Layerを返す。複数Layerはtuple/listで返し、`Layer + Layer`は使わない。
- colorは0..1のRGB tuple、thicknessは `0 < thickness <= 0.005` とする。

## custom operation（必要な場合だけ）

```python
import numpy as np
from grafix import effect, primitive


@primitive
def segment(*, length: float = 100.0) -> tuple[np.ndarray, np.ndarray]:
    coords = np.asarray([(0.0, 0.0, 0.0), (length, 0.0, 0.0)], dtype=np.float32)
    offsets = np.asarray([0, 2], dtype=np.int32)
    return coords, offsets


@effect
def shift_x(
    g: tuple[np.ndarray, np.ndarray], *, dx: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    coords, offsets = g
    moved = coords.copy()
    moved[:, 0] += np.float32(dx)
    return moved, offsets
```

`@primitive` / `@effect` の公開I/Oは常に `(coords, offsets)` tupleにする。`coords`はexact・C-contiguousな有限 `float32 (N,3)`、`offsets`はexact・C-contiguousな `int32 (M+1,)`（先頭0、末尾N、単調非減少）にする。`RealizedGeometry`をimportしない。

## APIを調べる

全operation一覧を文書へ複製せず、現行registryをCLIで調べる。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix describe primitive grid
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix describe effect rotate
```

## PNG export

```bash
RUN_ID=run_YYYYMMDD_HHMMSS_n3
RUN_DIR="sketch/agent_loop/runs/$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export \
  --callable "sketch.agent_loop.runs.${RUN_ID}.candidates.v01.sketch:draw" \
  --t 0.0 --canvas 300 300 --out "$RUN_DIR/candidates/v01/out.png" --overwrite \
  > "$RUN_DIR/candidates/v01/stdout.txt" \
  2> "$RUN_DIR/candidates/v01/stderr.txt"
```

exit code 0と、要求した `out.png` の存在を両方確認する。SVGはfinalで明示要求されたときだけ、`--out "$RUN_DIR/final/out.svg" --overwrite` を使う。
