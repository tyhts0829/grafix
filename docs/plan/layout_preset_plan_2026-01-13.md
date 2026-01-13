# どこで: `sketch/presets/layout_guides.py`（→ `sketch/presets/layout.py` に rename 予定）と `src/grafix/api/__init__.pyi`（スタブ再生成）。

# 何を: レイアウト検討用ガイド preset を `P.layout(...)` に刷新し、safe area / margin / columns+gutter / baseline / center・thirds・golden・diagonals 等の定番ガイドを “主ガイド + オーバーレイ” で重ねられるようにする。

# なぜ: `docs/review/layout_guides_review.md` の指摘（「余白規律」「列組」「文字の縦リズム」「即出せる定番」「密度制御」「単一 pattern の限界」）を、複雑化せず実用に寄せるため。

## ゴール

- 1 回の呼び出しで「主ガイド + 代表的オーバーレイ」を重ねられる。
- margin/safe area 内だけに線を出せる（ガイド線が増えすぎない）。
- ratio_lines は任意 ratio に対応し、三分割/黄金分割を即出せる。
- levels を上げても線数が暴発しにくい（密度制御: `min_spacing` / `max_lines`）。

## 非ゴール（今回やらない）

- スパイラル曲線（円弧/ベジェ等）の描画。
- 線スタイル（色/太さ/破線）API（Layer 側で調整）。※必要なら z ずらしのみ。
- ダイナミックシンメトリーの完全版（まずは対角線 + 最低限の reciprocal を検討）。

## 仕様案（公開 API / meta）

### rename（破壊的変更）

- `sketch/presets/layout_guides.py` → `sketch/presets/layout.py`
- preset 関数: `layout_guides(...)` → `layout(...)`（互換シムは作らない）
- 呼び出し側: `P.layout_guides(...)` → `P.layout(...)`

### 基本パラメータ

- `canvas_w`, `canvas_h`, `offset`
- `axes`: `"both" | "vertical" | "horizontal"`
- `base`: `"none" | "square" | "ratio_lines" | "metallic_rectangles" | "columns" | "modular"`
- `levels`: int（`ratio_lines` / `metallic_rectangles`）
- `border`: bool（canvas 外枠）

### safe area / margin / trim

- `margin_l`, `margin_r`, `margin_t`, `margin_b`（float, inset）
- `trim`（float, inset）
- `use_safe_area`: bool（True なら後続のガイド生成の対象 rect を margin 内へ切り替える）
- `show_margin`, `show_trim`: bool（線として表示）

Notes
-----
- bleed は値としては持たず、必要なら `canvas_w/canvas_h` を増やして表現する。
  - 仕上がり（trim）線を見せたい場合は `trim` を使う。

### columns / modular

- `cols`, `rows`（int）
- `gutter_x`, `gutter_y`（float）
- `show_column_centers`: bool（任意）

### baseline

- `show_baseline`: bool
- `baseline_step`: float
- `baseline_offset`: float（safe area 上端からのオフセットを基本にする）

### ratio / overlays

- `ratio`: float（`ratio_lines` 用。三分割などもここで表現）
- `metallic_n`: int（`metallic_rectangles` 用。黄金分割 overlay 用に再利用するかは要確認）
- `show_center`, `show_thirds`, `show_golden`, `show_diagonals`: bool
- `show_intersections`: bool / `mark_size`: float（交点マーカー）

### density / hierarchy（最低限）

- `min_spacing`: float（これ未満の間隔の線は打たない）
- `max_lines`: int（安全弁）
- `minor_z_offset`: float（optional: minor lines の z）

## 実装メモ（構造）

- すべてのガイド生成関数を「対象矩形 rect=(x0, y0, x1, y1)」で受ける。
  - canvas rect = rect_from_canvas + offset
  - safe rect = inset(margins)
  - trim rect = inset(trim)
- `base` で “主ガイド” を 1 つ生成し、overlay bool で必要な線を追加する。

## 実装チェックリスト

### 1) リネームと参照更新

- [ ] `sketch/presets/layout_guides.py` を `sketch/presets/layout.py` に rename
- [ ] preset 関数名を `layout` に変更（`@preset(meta=...)`）
- [ ] `sketch/readme/12.py` と `sketch/readme/14.py` を `P.layout(...)` へ更新
- [ ] stub を再生成して `src/grafix/api/__init__.pyi` の `layout_guides` → `layout` を反映（`python -m grafix stub`）
- [ ] `rg -n "\\blayout_guides\\b"` で残存参照がないことを確認

### 2) パラメータ/メタの再設計

- [ ] `pattern` を `base` に変更（or 維持。後述の要確認）
- [ ] margin/trim/safe_area/overlay の meta を追加
- [ ] columns/modular/baseline の meta を追加
- [ ] 既定値の決定（A5 を想定した “それっぽい” 初期表示）

### 3) safe area と矩形ユーティリティ

- [ ] `_rect_from_canvas(canvas_w, canvas_h, offset)` を追加
- [ ] `_inset_rect(rect, l, r, t, b)` を追加
- [ ] `use_safe_area` のとき、主ガイド/オーバーレイの対象 rect を safe rect に切り替える

### 4) 定番ガイド（オーバーレイ）

- [ ] center（縦/横の中心線）
- [ ] thirds（1/3, 2/3）
- [ ] golden（0.382, 0.618：固定 vs `ratio` 派生は要確認）
- [ ] diagonals（四隅を結ぶ 2 本）
- [ ] intersections マーカー（`show_intersections` + `mark_size`）

### 5) margin / trim 表示

- [ ] margin rect を線で描ける
- [ ] trim rect を線で描ける

### 6) columns / modular / baseline

- [ ] columns（`cols + gutter_x`）を rect 内へ計算して境界線を描く
- [ ] modular（`cols x rows + gutter_x/y`）を rect 内へ描く
- [ ] baseline（`baseline_step + baseline_offset`）を rect 内の水平線として描く
- [ ] `axes` と組み合わせて必要な軸だけ描ける

### 7) ratio_lines の任意 ratio 化 + 密度制御

- [ ] `ratio_lines` は `ratio` を使う（metallic_n 依存を外す）
- [ ] `_ratio_positions` に `min_spacing` と `max_lines` を追加し、levels を上げても暴発しにくくする
- [ ] （必要なら）早期終了条件を追加（segment 長が閾値未満なら分割しない）

### 8) 仕上げ（最小の検証）

- [ ] `python -m compileall sketch/presets/layout.py`
- [ ] `PYTHONPATH=src pytest -q tests/stubs/test_g_stub_sync.py`（スタブ同期）
- [ ] 目視: `sketch/readme/12.py` で margins + columns + baseline を重ねて破綻しない

## 要確認（あなたに確認したい点）

- canvas は「外枠（表示/書き出しの最大領域）」扱いで良い？（必要なら canvas を増やして trim=仕上がり線にする）；外枠扱い
- `pattern` → `base` rename は OK？（既存 UI が `pattern` 前提なら同時に更新する）；base へリネームして
- golden overlay の比率指定: 固定(0.382/0.618) vs `ratio` から派生（例: ratio=1.618 → 0.382/0.618）；固定
- columns の表示: 列境界のみ / ガター境界も描く / 中心線も描く；列境界のみ
- デフォルトの `min_spacing` / `max_lines` の値（A5 想定での “気持ち良い” 密度）；A5 想定で気持ちいい密度で。
