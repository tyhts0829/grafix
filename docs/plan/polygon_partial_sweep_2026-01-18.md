# polygon: 部分周回（弦で閉じる）対応プラン（2026-01-18）

## 目的

`src/grafix/core/primitives/polygon.py` の `polygon()` は現在「全周の正多角形（閉ポリライン）」のみ生成する。
これを拡張し、**途中の点まで外周を描画して、始点と終点は弦でつないで閉じる**図形を生成できるようにする。

例: `n_sides` を大きくして円近似にしたとき、円周の一部が欠けた（欠け部分が弦で置き換わる）形になる。

## 仕様案（API）

- `polygon(..., phase=<開始角deg>, sweep=<描画角deg>)`
  - `phase`: 既存どおり開始角（頂点開始角）
  - `sweep`: 描画する周回角度 [deg]
    - `360`（デフォルト）: 現状どおり全周
    - `0 < sweep < 360`: 外周を `sweep` まで進め、最後に始点へ直線で戻して閉じる（弦）

### 角度サンプリング方針（「途中の点まで」を満たす）

`n_sides` は「全周を等分したときの分割数」として扱い、ステップ角 `step = 360 / n_sides` を固定する。
そのうえで `sweep` に対して:

- `0, step, 2*step, ...` と進めて `sweep` を超える直前まで頂点を生成
- `sweep` が `step` の整数倍でない場合は、**最終点として `sweep` 角の点を追加**（辺の途中の点になり得る）
- 最後に「始点を終端に複製」して閉じる（この閉じる線分が弦になる）

## 受け入れ条件

- `polygon(n_sides=128, sweep=300)` のようなケースで「円弧 + 弦」で閉じた形になる
- 出力 `coords` は先頭点=末尾点で閉じている（現状仕様を維持）
- `sweep=360` は今の polygon と同じ点列（点数・位置）になる

## 作業手順（チェックリスト）

- [x] 追加パラメータ名を確定（`sweep` で良いか、`arc`/`theta`/`portion` 等にするか）
- [x] `src/grafix/core/primitives/polygon.py` に `sweep` を追加し、メタ情報（UI slider）も追加
- [x] `sweep` 実装（整数ステップ + 端点補間 + 弦でクローズ）を入れる
- [x] テスト追加（例: `tests/core/test_pipeline.py` or 新規テスト）  
      - `sweep=360` の点数が `n_sides + 1` であること  
      - `sweep<360` のとき `coords[0] == coords[-1]` で閉じること  
      - `sweep` が `step` 非整数倍でも終点が `sweep` 角になっていること
- [x] 型/スタブ生成が前提なら追従（該当があれば）し、必要なテストを通す

## 実行コマンド案

- `PYTHONPATH=src pytest -q tests/core/test_pipeline.py`
- （必要なら）`PYTHONPATH=src pytest -q`
