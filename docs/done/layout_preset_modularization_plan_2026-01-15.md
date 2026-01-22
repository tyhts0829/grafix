# layout preset: モジュール分割（合成ベース）実装計画（2026-01-15）

どこで: `sketch/presets/layout.py`（現状: 1 preset に多数機能が集中）

何を: レイアウトガイドを **複数の preset（= モジュール）** に分解し、ユーザーが `+` で合成してレイアウトを構成できるようにする。

なぜ:

- 1 つの preset が「grid system / 比率 / オーバーレイ / 枠線 / 密度制御」まで抱えており、UI/実装ともに肥大化したため。
- 「必要な要素だけを足す」構成にして、スケッチ側の意図を明確にしたい。

---

## 0) 事前に決める（あなたの確認が必要）

- 決定: `use_safe_area` は **削除**する（`margin_* = 0` で「safe area を使わない」のと同義になるため）
- [x] `P.layout(...)`（現行）を **削除**して置き換える（破壊的変更）でよい
  - [ ] それとも `layout.py` は残して「最小の束ね役」にする？（ただし “互換シム” にはしない）
- [x] 分解単位（preset 群）は以下でよい
  - [x] `layout_square_grid`
  - [x] `layout_grid_system`（columns/modular/baseline を内包）
  - [x] `layout_golden_ratio`
  - [x] `layout_ratio_lines` / `layout_metallic_rectangles` / `layout_bounds`（追加分も同時に切り出す）
  - [x] `layout_thirds` / `layout_diagonals` / `layout_intersections`（overlay/交点も分割する）
- [x] **共通パラメータ**の最小セットはこれでよい（各モジュールで揃える）
  - [x] `canvas_w`, `canvas_h`
  - [x] `axes`（`"both" | "vertical" | "horizontal"`）
  - [x] `margin_l`, `margin_r`, `margin_t`, `margin_b`
  - [x] `offset`（vec3）
  - [x] `show_center`（True なら target rect の中心線を足す）
- [x] `margin_*` は現状どおり **4 辺別**で維持する（単一 `margin` に簡略化しない）
- [x] `show_center` を「各モジュールが持つ」方針でよい
  - 合成時に重複線が出る可能性があるため、運用上は “どれか 1 つでだけ True” を推奨する想定。
- [x] 既存の `show_intersections`（交点マーカー）は **フラグではなくモジュールとして切り出す**（`layout_intersections`）

---

## 1) 受け入れ条件（完了の定義）

- [x] モジュール（preset）を `+` で合成して使える（例: `P.layout_square_grid(...) + P.layout_golden_ratio(...)`）。
- [x] 各モジュールが共通パラメータ（少なくとも `offset/margin/show_center`）を持つ。
- [x] `sketch/readme/12.py` / `sketch/readme/14.py` が新モジュール構成へ更新される。
- [x] `python -m grafix stub` を再生成し、`PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` が通る。
- [x] `python -m compileall sketch/presets` が通る。

---

## 2) 設計案（公開 API: composable preset 群）

### 合成の基本

- 各モジュールは `Geometry` を返す preset として実装する。
- ユーザーはスケッチ側で `+` して合成する（順序が意味を持つ場合は z/offset で調整）。

例（案）

```py
from grafix import P

g = (
    P.layout_bounds(canvas_w=w, canvas_h=h, show_margin=True, margin_l=10, margin_r=10, margin_t=10, margin_b=10)
    + P.layout_grid_system(canvas_w=w, canvas_h=h, cols=12, gutter_x=4, show_baseline=True)
    + P.layout_golden_ratio(canvas_w=w, canvas_h=h)
)
```

### 共通（rect の決め方）

- `canvas_rect = rect_from_canvas(canvas_w, canvas_h, offset)`
- `safe_rect = inset_rect(canvas_rect, margin_l, margin_r, margin_t, margin_b)`
- `target_rect = safe_rect`（`margin_* = 0` なら `safe_rect == canvas_rect`）
- `margin_* != 0` の場合、`safe_rect` の外枠（margin の外枠）を **自動で追加**する
  - `layout_grid_system` は列/行の境界線が外枠を含むため、追加不要
- `show_center=True` の場合、`target_rect` の中心線を（`axes` に応じて）追加する

### モジュール案（最低 3 つ）

#### A) `layout_square_grid(...)`

- 役割: 正方形グリッド。
- 追加パラメータ: `cell_size`

#### B) `layout_grid_system(...)`

- 役割: typographic grid 用（columns / modular / baseline をまとめる）。
- 追加パラメータ（案）:
  - columns: `cols`, `gutter_x`, `show_column_centers`
  - modular: `rows`, `gutter_y`
  - baseline: `show_baseline`, `baseline_step`, `baseline_offset`
- メモ: columns/modular/baseline をさらに分割する場合は、`layout_columns` / `layout_modular_grid` / `layout_baseline_grid` に分ける。

#### C) `layout_golden_ratio(...)`

- 役割: 黄金比ガイド（0.382/0.618 の分割線）。
- 追加パラメータ（最小）: なし（常に黄金比）または `orientation`（= `axes` で代用）
- メモ: “黄金矩形の分割（タイル境界）” も必要なら `layout_metallic_rectangles(n=1)` として別モジュール化する。

### 追加モジュール（必要なら）

- `layout_bounds(...)`: canvas border / safe area / trim の外周線だけを描く（grid とは分離）
- `layout_ratio_lines(...)`: 任意 ratio の分割線（現 `ratio_lines` の抽出）
- `layout_metallic_rectangles(...)`: metallic mean の矩形分割（現 `metallic_rectangles` の抽出）
- `layout_diagonals(...)` / `layout_thirds(...)`: 定番 overlay を独立化（交点マーカーは今回捨てるなら不要）

---

## 3) 実装方針（最小で美しく）

- `sketch/presets/layout/` を新設し、ここに **小さな preset 群**を置く（1 ファイル 1 役割）。
- 共通処理は `sketch/presets/layout/common.py` に集約する:
  - rect 計算（canvas/safe/trim）
  - axis 判定（vertical/horizontal/both）
  - line 生成ユーティリティ（v/h/diagonal）
  - 共通 meta（同一 key/同一 default/同一レンジ）を提供するヘルパ
- 互換ラッパーは作らない（必要なら呼び出し側を直す）。

---

## 4) 変更箇所（ファイル単位）

- [x] `sketch/presets/layout.py`（削除）
- [x] `sketch/presets/layout/common.py`（新規）
- [x] `sketch/presets/layout/bounds.py`（新規: `layout_bounds`）
- [x] `sketch/presets/layout/square_grid.py`（新規: `layout_square_grid`）
- [x] `sketch/presets/layout/grid_system.py`（新規: `layout_grid_system`）
- [x] `sketch/presets/layout/golden_ratio.py`（新規: `layout_golden_ratio`）
- [x] `sketch/presets/layout/ratio_lines.py`（新規: `layout_ratio_lines`）
- [x] `sketch/presets/layout/metallic_rectangles.py`（新規: `layout_metallic_rectangles`）
- [x] `sketch/presets/layout/thirds.py`（新規: `layout_thirds`）
- [x] `sketch/presets/layout/diagonals.py`（新規: `layout_diagonals`）
- [x] `sketch/presets/layout/intersections.py`（新規: `layout_intersections`）
- [x] `sketch/readme/12.py`（更新）
- [x] `sketch/readme/14.py`（更新）
- [x] `src/grafix/api/__init__.pyi`（stub 再生成）
- [ ] （必要なら）`docs/readme/` や `docs/review/` の参照更新

---

## 5) 実装手順（順序）

- [x] 事前確認: `git status --porcelain` で依頼範囲外の差分/未追跡を把握（触らない）
- [x] `sketch/presets/layout/common.py` を作成（rect/line/meta の共通化）
- [x] `layout_square_grid` を実装
- [x] `layout_golden_ratio` を実装
- [x] `layout_grid_system` を実装
- [x] `layout_bounds` / `layout_ratio_lines` / `layout_metallic_rectangles` / `layout_thirds` / `layout_diagonals` / `layout_intersections` を実装
- [x] 旧 `layout.py` を削除し、呼び出し側（readme スケッチ）を更新
- [x] `python -m compileall sketch/presets`
- [x] `python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
