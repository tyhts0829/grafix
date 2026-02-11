# Grafix Artist Guide

このファイルは `grafix-art-loop-artist` に向けた、Grafixスケッチ実装用の最小ガイド。

## ハードルール

- `sketch.py` で `from grafix.core.realized_geometry import RealizedGeometry` を import しない。
- custom `@primitive` / `@effect` のユーザー関数 I/O は `(coords, offsets)` タプルにする（`coords` は shape `(N,3)` のみ）。
- custom `@primitive` / `@effect` は「定義だけ」ではなく、実際の描画パスで必ず使う。
- 出力は `variant_dir` 配下のみ。`/tmp` や `sketch/agent_loop` 外へ書かない。
- 既存 run の `sketch.py` 丸写しや、テンプレート使い回しでの量産をしない。

## 実装の基本形

```python
from __future__ import annotations

import numpy as np

from grafix import E, G, L, effect, primitive, run

CANVAS = (148, 210)

@primitive
def my_source(*, n: int = 12) -> tuple[np.ndarray, np.ndarray]:
    # 低レベル配列の手組みより、既存 primitive/effect の再利用を優先する。
    from grafix.core.primitives.grid import grid as _grid

    return _grid(nx=max(2, n), ny=max(2, n), center=(74.0, 105.0, 0.0), scale=120.0)


@effect
def my_transform(
    g: tuple[np.ndarray, np.ndarray],
    *,
    amount: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    from grafix.core.effects.rotate import rotate as _rotate

    return _rotate(g, rotation=(0.0, 0.0, 20.0 * float(amount)))


def draw(t: float):
    g = G.my_source(n=16)
    g = E.my_transform(amount=0.25)(g)

    base_layer = L("base").layer(g, color=(0.0, 0.0, 0.0), thickness=0.001)
    accent_layer = L("accent").layer(
        E.rotate(rotation=(0.0, 0.0, 10.0))(g),
        color=(0.1, 0.35, 0.8),
        thickness=0.001,
    )
    return base_layer + accent_layer


if __name__ == "__main__":
    run(draw, canvas_size=CANVAS, render_scale=5)
```

## Layer での color / thickness 指定

- 単一レイヤ: `L("name").layer(geometry, color=(r,g,b), thickness=0.001)`
- 複数レイヤ: 上記を複数作成して `list[Layer]` を返す
- `color` は `0..1` の RGB タプル
- `thickness` は正の値のみ。0.005以下とする。
- `color` / `thickness` を省略した場合は、`run(...)` / `export(...)` の既定値が使われる

## Built-in Primitives（1行説明）

- `asemic`: 擬似文字（asemic）の文章をポリライン列として生成する。
- `grid`: グリッド（縦線 nx 本 + 横線 ny 本）を生成する。
- `line`: 正規化済み引数から線分を生成する。
- `lissajous`: リサージュ曲線を 1 本の開ポリラインとして生成する。
- `lsystem`: L-system を展開し、枝分かれした線（開ポリライン列）を生成する。
- `polygon`: 正多角形の閉ポリラインを生成する。
- `polyhedron`: 多面体を面ポリライン列として生成する。
- `sphere`: 球のワイヤーフレームをポリライン列として生成する。
- `text`: フォントアウトラインからテキストのポリライン列を生成する。
- `torus`: トーラスのワイヤーフレーム（子午線+緯線）を生成する。

## Built-in Effects（1行説明）

- `affine`: スケール→回転→平行移動を適用する（合成アフィン変換）。
- `bold`: 入力を複製して太線風にする。
- `buffer`: Shapely の buffer を用いて輪郭を生成する。
- `clip`: XY 平面へ整列した上で、閉曲線マスクで線分列をクリップする。
- `collapse`: 線分を細分化してノイズで崩す（非接続）。
- `dash`: 連続線を破線に変換する。
- `displace`: 3D Perlin ノイズで頂点を変位する。
- `drop`: 線や面を条件で間引く。
- `extrude`: 指定方向に押し出し、複製線と側面エッジを生成する。
- `fill`: 閉領域をハッチングで塗りつぶす。
- `growth`: マスク内で差分成長を行い、襞のような閉曲線群を生成する。
- `highpass`: ポリライン列を highpass（高周波強調）する。
- `isocontour`: 閉曲線群から等高線（等値線）を複数レベル抽出して出力する。
- `lowpass`: ポリライン列を低域通過（ローパス）して滑らかにする。
- `metaball`: 閉曲線群をメタボール的に接続し、輪郭（外周＋穴）を生成する。
- `mirror`: XY 平面でのミラー複製を行う。
- `mirror3d`: 3D 放射状ミラー（azimuth / polyhedral）。
- `partition`: 偶奇規則の平面領域を Voronoi 分割し、閉ループ群を返す。
- `pixelate`: ポリラインをグリッド上の階段線へ変換する（XY）。
- `quantize`: 頂点座標を各軸のステップ幅で量子化する（XYZ）。
- `reaction_diffusion`: 閉曲線マスク内で反応拡散を走らせ、線として出力する。
- `relax`: 線分ネットワークをグラフとして弾性緩和する。
- `repeat`: 入力ジオメトリを複製して、規則的な配列を作る。
- `rotate`: 回転（auto_center / pivot 対応、degree 入力）。
- `scale`: スケール変換を適用（auto_center 対応）。
- `subdivide`: 中点挿入で線を細分化する。
- `translate`: 平行移動（XYZ のオフセット加算）。
- `trim`: ポリライン列を正規化弧長の区間でトリムする。
- `twist`: 位置に応じて軸回りにねじる（中心付近は 0）。
- `warp`: マスク距離場で、入力線を lens/attract 変形する。
- `weave`: 入力閉曲線からウェブ状の線分ネットワークを生成する。
- `wobble`: 各頂点へサイン波由来の変位を加える。

## primitive/effect の引数の調査は以下のツールを利用せよ

- docs 系 MCP サーバ `grafix-art-loop-grafix-docs`
  - tool: `art_loop.get_op_docstrings`
  - 用途: 指定 primitive/effect の docstring 取得（要素技法の再探索コスト削減）
