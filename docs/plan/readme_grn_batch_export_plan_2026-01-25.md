# sketch/readme/grn を一括エクスポートして README examples を更新する

作成日: 2026-01-25

## ゴール

- `sketch/readme/grn` 配下のスケッチ群（`1.py`, `2.py`, ...）をまとめて export し、`a5_frame` 改訂時に examples を一括更新できるようにする
- 出力は既存の運用に合わせて以下を更新する
  - `data/output/svg/readme/grn/<n>_148x210.svg`
  - `data/output/png/readme/grn/<n>_1184x1680.png`（`export.png.scale=8.0` 前提）
- export 後に README 反映まで 1 回で回せる導線を用意する（`docs/readme/grn/*.png` 更新 + `README.md` の Examples ブロック更新）

## 対象（変更するもの）

- `src/grafix/devtools/`（一括 export スクリプトを新規追加）
- （スクリプト実行により更新される想定）
  - `data/output/svg/readme/grn/`
  - `data/output/png/readme/grn/`
  - `docs/readme/grn/`
  - `README.md` の `<!-- BEGIN:README_EXAMPLES_GRN -->` ブロック

## 仕様（案）

### 実行インターフェース（devtools の方針）

- `argparse` は使わない
- 変えたいパラメータ（列挙ルール、t、上書き可否など）はモジュール冒頭の `Parameters` セクションに定数として置く
  - 既存の `src/grafix/devtools/prepare_readme_examples_grn.py` と揃える

### 入力スケッチの列挙規則

- 対象: `sketch/readme/grn/*.py`
- `^\d+\.py$` のみ採用（`template.py` などは除外）
- 数字で昇順ソートして処理（1,2,3,...）

### スケッチの読み込み方法

- `importlib.util.spec_from_file_location()` でファイルパスからロードする
  - 理由: `1.py` のような「数字のモジュール名」は通常 import できないため

### export パラメータ

- `t`: 0.0 固定（必要なら将来 `EXPORT_T` をスケッチ側で上書きできる設計にする）
- `canvas_size`: 各スケッチの `CANVAS_WIDTH`, `CANVAS_HEIGHT` から取得（A5: 148×210）
- スタイル既定値はスケッチの `run(...)` と揃える
  - `background_color=(1,1,1)`
  - `line_color=(0,0,0)`
  - `line_thickness=0.001`

### 出力パス

- SVG:
  - `grafix.core.output_paths.output_path_for_draw(kind="svg", ext="svg", canvas_size=(w,h))`
  - 例: `data/output/svg/readme/grn/1_148x210.svg`
- PNG:
  - `grafix.export.image.default_png_output_path(draw, canvas_size=(w,h))`
  - 例: `data/output/png/readme/grn/1_1184x1680.png`

### PNG 生成方法

- 既存のディレクトリ構成を保つため、`Export(..., fmt="svg")` で SVG を先に生成し、その SVG を `resvg` で PNG にラスタライズする
  - `grafix.export.image.rasterize_svg_to_png(..., output_size=png_output_size(canvas_size))`
- 依存:
  - `resvg`（PNG 生成に必要）
  - `sips`（README 用縮小に必要。`prepare_readme_examples_grn.py` が使用）

### README の examples 更新

- export 完了後に `src/grafix/devtools/prepare_readme_examples_grn.py` を呼び、次を自動更新する
  - `docs/readme/grn/<n>.png`（長辺 600px、などの既定設定に従う）
  - `README.md` の BEGIN/END ブロック

## 実装手順（チェックリスト）

- [ ] 既存スケッチ群の前提確認（全て `draw(t)` と `CANVAS_WIDTH/HEIGHT` を持つか）
- [x] 一括 export スクリプト追加: `src/grafix/devtools/refresh_readme_grn.py`
  - [x] 入力列挙（`^\\d+\\.py$` のみ、数字順）
  - [x] 各スケッチをファイルパス import → `draw` / `CANVAS_*` を取得
  - [x] SVG 出力（`output_path_for_draw(kind="svg", ...)`）
  - [x] PNG 出力（SVG → `resvg` で生成、`default_png_output_path(...)` の場所へ）
  - [x] export 後に `prepare_readme_examples_grn.main()` を呼んで README 反映まで一括更新（ON/OFF は定数で制御）
- [ ] 手元で実行して `data/output/*` と `docs/readme/grn` と `README.md` が更新されることを確認

## 確認したい点

- export 対象は「数字ファイルのみ」で OK？（`template.py` は除外）；はい
- `t=0.0` 固定で OK？（将来必要ならスケッチ側に `EXPORT_T` を追加する運用）；はい
- 1 回のコマンドで README まで更新する（batch export → prepare_readme_examples）方針で OK？；はい
