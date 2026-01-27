# headless export の PNG 背景色を ParamStore の style から解決する

作成日: 2026-01-27

## ゴール

- `src/grafix/devtools/refresh_readme_grn.py` 実行時に、`docs/readme/grn/*.png` が「真っ白/真っ黒」になるケースを潰す
  - 具体例: `sketch/readme/grn/11.py` のように **線が白**・**背景が黒** のスタイルを ParamStore が保持している場合、PNG 背景も黒になる
- `python -m grafix export`（= `src/grafix/devtools/export_frame.py` → `grafix.api.Export`）でも同じ規則で PNG 背景を決める
- 既存方針（SVG を正、PNG は `resvg --background ...` で生成）を維持する
  - SVG に背景矩形を埋め込まない（透明背景のまま）

## 背景 / 問題の整理

- `refresh_readme_grn.py` は export 時の既定スタイルを固定値（白背景・黒線）で渡している
- しかし Export は ParamStore をロードして **線色（layer_style）を override で白にできる**ため、結果として「白線 + 白背景」になり PNG が真っ白になる
- 欲しい挙動は「ParamStore の `__style__/__global__/background_color`（override=True）を PNG 背景に反映する」こと

## 対象（変更するもの）

- `src/grafix/api/export.py`
  - Export の `background_color` を ParamStore の style 解決結果で上書きして PNG 生成に渡す
  - ついでに `global_line_color/global_thickness` も同様に解決し、LayerStyleDefaults に反映する（interactive と同じ整合性）
- `src/grafix/devtools/refresh_readme_grn.py`
  - `resvg --background` に渡す背景色を、ParamStore style の解決結果から決める
- `src/grafix/interactive/runtime/style_resolver.py`（必要なら移動/再配置）
  - headless 側でも使うため、配置を core に寄せるか、現状のまま再利用するかを決める
- テスト
  - `tests/interactive/runtime/test_style_resolver.py`（移動した場合は import 更新）
  - `tests/api/` などに Export の背景色適用を確認する小テストを追加（外部 `resvg` を呼ばない形）

## 仕様（案）

### style の解決規則（interactive と同一）

- base 値は Export 呼び出し側が渡した以下を用いる
  - `base_background_color_rgb01`（Export の `background_color`）
  - `base_global_line_color_rgb01`（Export の `line_color`）
  - `base_global_thickness`（Export の `line_thickness`）
- ParamStore の `style_key(...)` に state があり `override=True` のときだけ `ui_value` を採用する
  - RGB は `RGB255 <-> RGB01` 変換を挟む
- style key が未初期化でも必ず解決できるよう、`ensure_style_entries()` 相当で meta/state を作る
  - ただし headless export は ParamStore を **保存しない**（ファイル更新はしない）

### PNG 背景の適用箇所

- `Export(fmt="png"/"image")` の場合
  - `export_image(..., background_color=resolved_bg)` へ渡す
- `refresh_readme_grn.py` の場合（SVG → resvg の手動ラスタライズ）
  - `rasterize_svg_to_png(..., background_color_rgb01=resolved_bg)` へ渡す

## 実装手順（チェックリスト）

- [ ] `StyleResolver` の置き場所を決める
  - 案A（最小）: `grafix.interactive.runtime.style_resolver.StyleResolver` を headless 側でも直接 import
  - 案B（整理）: `StyleResolver` を `src/grafix/core/`（または `src/grafix/core/parameters/`）へ移動し、interactive/export の両方から参照
- [ ] `src/grafix/api/export.py` を更新
  - [ ] ParamStore をロード後、style を解決して `LayerStyleDefaults`（色/線幅）を確定
  - [ ] PNG 生成時に解決済み背景色を `export_image` へ渡す
  - [ ] `Export` インスタンスから「解決済み背景色」を参照できるようにする（`refresh_readme_grn.py` が使う）
- [ ] `src/grafix/devtools/refresh_readme_grn.py` を更新
  - [ ] `Export(...)` を変数に保持し、解決済み背景色を `rasterize_svg_to_png` に渡す
  - [ ] `BACKGROUND_COLOR` は「base 値」として残す（ParamStore が無い場合の既定）
- [ ] テスト追加/更新
  - [ ] `StyleResolver` を移動した場合、既存テストの import を更新
  - [ ] `Export` が `export_image` に渡す `background_color` を style 解決結果にしていることを確認するテストを追加
    - `pytest` の monkeypatch で `grafix.api.export.export_image` を差し替え、引数を検証（`resvg` は呼ばない）
- [ ] 手元確認
  - [ ] `PYTHONPATH=src pytest -q`（少なくとも追加/変更したテスト）
  - [ ] `PYTHONPATH=src python src/grafix/devtools/refresh_readme_grn.py` を実行し、`docs/readme/grn/11.png` が真っ白でなくなること

## 確認したい点

- SVG に背景矩形を埋め込まず、PNG の `resvg --background` だけで背景を制御する方針で OK？；はい
- `StyleResolver` の移動（案B）をしても OK？（破壊的変更を許容する前提）；はい
