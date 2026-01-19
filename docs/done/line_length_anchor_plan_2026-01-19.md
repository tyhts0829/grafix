# line primitive: length の基準点（左/中央/右）を選べるようにする（2026-01-19）

## ゴール

- `src/grafix/core/primitives/line.py` の `line()` に、length の伸び方を「中央 / 左基準 / 右基準」から選べる choice 引数を追加する。

## 仕様（案）

### 新規引数

- 引数名: `anchor`（choice）
  - `choices=("center", "left", "right")`

### 既存引数の解釈

- `center`: 基準点（`anchor` の解釈に従う）
- `length`: 線分の長さ（現状維持）
- `angle`: 回転角 [deg]（現状維持、0° で +X 方向）

### 挙動

- `anchor="center"`（デフォルト）
  - 現状通り `center` が線分の中心
  - length を大きくすると両端が等しく伸びる
- `anchor="left"`
  - `center` を「左端（angle 方向の逆側）」として扱う
  - length は +angle 方向にのみ伸びる
- `anchor="right"`
  - `center` を「右端（angle 方向）」として扱う
  - length は -angle 方向にのみ伸びる

## 要確認（未確定点）

- [x] 引数名は `anchor` で問題ないか（要望どおり `choice` という名前にする方が良いか）；OK
- [x] 値の名称は `"center"|"left"|"right"` で問題ないか（`"center"|"start"|"end"` 等にするべきか）:OK

## 実装タスク

- [x] `line()` の既存利用箇所を検索し、追加引数名の衝突がないことを確認する
- [x] `line_meta` に `anchor` の `ParamMeta(kind="choice", choices=(...))` を追加する
- [x] `line()` のシグネチャと docstring を更新する
- [x] `anchor` の値に応じて endpoints を計算する（`center/left/right`）
- [x] `tests/` に各モードの座標が期待通りになるテストを追加/更新する
- [x] `PYTHONPATH=src pytest -q tests/core/primitives/test_line.py` / `tests/stubs/test_api_stub_sync.py` で確認する

## 受け入れ条件

- `anchor="center"` で既存と同一の `coords` が生成される
- `anchor="left"` / `"right"` で length の変更が片側のみの伸長になる
- テストが通る
