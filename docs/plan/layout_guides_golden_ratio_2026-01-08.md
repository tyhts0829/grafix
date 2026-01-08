# どこで: Grafix リポジトリ（`layout_guides` の機能追加計画）。

# 何を: `layout_guides` に「比率ベースのレイアウトガイド」を追加し、黄金比/銀比などの貴金属比（metallic means）を選べるようにする。

# なぜ: “2 本線の φ グリッド” だけに寄せず、複数の代表的手法（分割線・矩形分割など）を同一 preset で切り替えられるようにするため。

# `layout_guides` 比率ガイド（貴金属比）: 実装チェックリスト

## ゴール

- `sketch/presets/layout_guides.py` に「比率から作るガイド」を追加できる。
- 黄金比だけでなく、銀比/青銅比などの貴金属比を選択できる。
- “黄金比は縦 2 本 + 横 2 本だけ？”問題を避け、複数のガイド手法を用意する。

## 非ゴール（今回やらない）

- スパイラル曲線そのもの（円弧/ベジェ）を描く（primitive が無いので後回し）。
- ガイド線のスタイル API（太さ/色/破線など）。Layer 側で調整する。

## 設計方針（汎用化の芯）

- “比率（ratio）” と “作り方（guide_type）” を分離する。
  - ratio を変えても同じ手法で描ける（例: 分割線は黄金比でも銀比でも同じ）。
  - 手法を増やしても ratio 選択 UI は増えない。
- `guide_type` ごとに最小のパラメータだけ使う（未使用値は無視）。
- `square` は現状維持（繰り返しで軽い）。

## 公開 API（案）

- 既存（継続）
  - `pattern: choice`（後方互換の都合で残す。意味は “ガイドの作り方” に寄せる）
  - `cell_size: float`（`square` のみ）
  - `offset: vec3`（全パターン共通）
- 追加（比率/貴金属比）
  - `ratio_source: choice` = `"metallic" | "custom"`
  - `metallic_n: int`（1=黄金比, 2=銀比, 3=青銅比, ...）
  - `custom_ratio: float`（`ratio_source="custom"` のとき使用）
- 追加（ガイド共通）
  - `axes: choice` = `"both" | "vertical" | "horizontal"`
  - `border: bool`
- 追加（手法別）
  - `levels: int`（再帰/段数。`square` では未使用）
  - `corner: choice` = `"tl" | "tr" | "br" | "bl"`（分割の開始位置。矩形分割系で使用）
  - `clockwise: bool`（矩形分割系で使用）

## パターン仕様（案）

### `pattern="square"`（既存）

- 既存どおり（正方形グリッド）。
- `axes` に応じて縦/横を出し分けできるようにする（repeat が 2 回なので分岐は単純）。

### `pattern="ratio_lines"`（分割線 / グリッド的）

- “2 本線だけ” で終わらせないため、段数 `levels` を持たせる。
  - `levels=1`: もっとも基本（例: 黄金比なら 0.382/0.618）
  - `levels>=2`: 左右（または上下）の区画に対して同じ比率分割を再適用し、線を増やす
    - 実装は「分割対象の区画リスト」を持ち、各区画に対して 1 回分割 → 次段へ、のループで作る
- `axes` によって縦/横の分割線だけ出すこともできる。
- `border=True` のときは外枠 1 周も追加する。

### `pattern="metallic_rectangles"`（矩形分割 / ネスト）

- 貴金属比（metallic means）に特徴的な “正方形のタイル分割” をガイドとして描く。
  - metallic mean: `δ_n = (n + √(n^2 + 4)) / 2`（n=1 黄金, n=2 銀, ...）
  - δ_n 矩形は「n 個の正方形 + 同じ比率の残り矩形」に分割でき、これを繰り返せる。
- 実装は “分割線（矩形境界）” だけ描く（スパイラル曲線は将来）。
- `corner` と `clockwise` で分割の回り方（どの角から詰めるか）を決める。
- `levels` は繰り返し回数（大きいほど細かいタイルになる）。

## 比率の選択（案）

- `ratio_source="metallic"`:
  - `ratio = δ_n`
  - 代表例:
    - n=1: 黄金比 ≒ 1.618
    - n=2: 銀比 ≒ 2.414
    - n=3: 青銅比 ≒ 3.303
- `ratio_source="custom"`:
  - `ratio = custom_ratio`（>1 を想定。<=1 は 1+eps へ丸める）

## 要確認（あなたに確認したい点）

- `pattern` の命名:すべて OK
  - `"ratio_lines"` / `"metallic_rectangles"` で OK？
  - `"square"` はそのまま残す想定で OK？
- まず最初の実装スコープ:同時に入れて
  - `ratio_lines` と `metallic_rectangles` の 2 つを同時に入れて良い？
  - それとも先に `ratio_lines`（黄金/銀…）だけ入れる？
- `levels` の既定値（1 か 2 か）。；2

## 実装チェックリスト

- [ ] `sketch/presets/layout_guides.py` の `meta` を更新（pattern/ratio/共通オプション/levels）
- [ ] `layout_guides()` を内部ヘルパ分割（`_ratio()`, `_border()`, `_ratio_lines()`, `_metallic_rectangles()`）
- [ ] `pattern == "square"` を `axes` に対応させる
- [ ] `pattern == "ratio_lines"` を実装（levels 対応）
- [ ] `pattern == "metallic_rectangles"` を実装（metallic_n + levels + corner/clockwise）
- [ ] 極端な `canvas_size` でも Geometry が空にならないことを軽く確認
- [ ] `python -m compileall` と import 呼び出しで文法/実行時エラーが無いことを確認
