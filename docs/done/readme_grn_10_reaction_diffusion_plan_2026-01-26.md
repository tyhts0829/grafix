# sketch/readme/grn/10.py: Gray-Scott 反応拡散で「迷路 + 葉脈」線画を作る

作成日: 2026-01-26

## ゴール

- `sketch/readme/grn/10.py` に、Gray-Scott 反応拡散（U,V 2場）から線（ポリライン列）を生成する primitive を実装する
- 出力は **上段: 迷路状（等値線）**、**下段: 脈状（2値化→細線化→中心線）** の 2 ブロック構成にする
- `@primitive` で登録し、`draw(t)` から `G.<name>(...)` として呼べるようにする

## 方針

- 依存追加なし（NumPy のみ）
- 反応拡散は Gray-Scott の標準形（5点/9点近傍ラプラシアン + 反応項）
- 「線化」は以下を両方実装して使い分ける
  - 迷路: V の等値線（Marching Squares → セグメント → ポリライン）
  - 葉脈: V を閾値で 2 値化 → Zhang-Suen thinning（細線化）→ 8近傍グラフをトレースして中心線
- 重い計算は **パラメータでキー化した簡単なキャッシュ** を 10.py 内に置き、GUI 再描画で毎フレーム回さない（実体ジオメトリ自体は `grafix.core.realize.realize_cache` が GeometryId ベースでキャッシュ）

## 仕様（案）

- primitive 名: `gray_scott_lines`
- 引数（最小）:
  - `center=(cx,cy,cz)`, `size=(w,h)`（mm）: 出力範囲
  - `nx, ny`: グリッド解像度
  - `steps`: 反応拡散ステップ数（例: 2000〜6000）
  - `du, dv, feed, kill`: Gray-Scott パラメータ
  - `seed`: 初期撹乱用シード
  - `mode`: `"contour"` / `"skeleton"`（迷路/葉脈で使い分け）
  - `level`: 等値線レベル or 2値化閾値
- `draw(t)` は `G.gray_scott_lines(..., mode="contour")` と `mode="skeleton"` の 2 回呼び出しで構成

## 実装手順（チェックリスト）

- [x] `sketch/readme/grn/10.py` に `@primitive` を追加し、Gray-Scott を NumPy で実装
- [x] Marching Squares で等値線を抽出し、ポリラインに stitch して `RealizedGeometry` 化
- [x] Zhang-Suen thinning で細線化し、スケルトンをポリラインにトレースして `RealizedGeometry` 化
- [x] `draw(t)` を「上段(迷路) + 下段(葉脈) + frame」に組み直す
- [x] 目視用のパラメータ（F/K/steps/level/解像度/サイズ/配置）を 10.py 先頭にまとめる
- [x] primitive 内の二重キャッシュ（RealizeCache と重複）を解消し、field キャッシュのみ残す

## 確認したい点

- 迷路は「等値線 1 本」中心で OK？（複数レベルを重ねる案もあり）
- 下段の葉脈は「細線化中心線」で進めて OK？（負荷が気になれば等値線に寄せる）
- 反応拡散の初期条件は「中央に V の小ブロブ + 微ノイズ」で OK？
