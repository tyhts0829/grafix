# G-code export: face 単位の最適化（塗り順の均一化）Plan

日付: 2026-02-14

## 背景 / 問題

`src/grafix/export/gcode.py` の `optimize_travel` は、**レイヤ内の全 stroke をまとめて** `_order_strokes_in_layer()`（貪欲 nearest）で並べ替える。

その結果:

- `effects.fill` が「face（外周+穴のグループ）ごとに」生成したハッチ線分が **face を跨いで混ざる**
- 同一 face 内でも、生成順（スキャン順）と異なる順序で描かれて **塗りの均一感が落ちる**
- `bridge_draw_distance` により、face 間が近いと **別 face を線で繋いでしまう**可能性がある（意図しない線）

## ゴール

- **face ごと**に stroke 並び替え（最適化）を閉じる: face A の塗りが途中で face B に飛ばない
- `effects.fill` の “塗り線の生成順（隣接線の連なり）” をできるだけ壊さず、見た目を均一化する
- 決定性（同一入力 -> 同一出力）を維持する
- 実装はシンプルに保ち、過度に防御的にしない

## 非ゴール

- レイヤ全体の厳密 TSP 最適化
- 3rd-party 依存追加
- “face” を完全に幾何学的に復元する（メタデータ無しでの完璧な所属推定）

## 現状把握（どこが混ざるか）

- `export_gcode()` 内で `strokes: list[_Stroke]` をレイヤ全体で収集
- `ordered = _order_strokes_in_layer(strokes, ...)` により **polyline/face 構造を無視して**並べ替え
- `bridge_draw_distance` の判定も **ordered 全体**に対して行われ、face の境界を考慮しない

## 変更方針（提案）

### 1) “face グループ” を導入し、グループ内だけ最適化する

`effects.fill` の出力は（remove_boundary=False の場合）概ね次の順:

1. その face の境界リング（頂点数>=3 のポリラインが複数: outer + holes）
2. その face の塗り線（主に 2 点ポリラインの列）
3. 次の face の境界リング...

この構造を利用し、G-code 側で以下の **face ブロック**を作る:

- `face_block` = 先頭に 1 個以上の「リング候補ポリライン（頂点数>=3）」を含み、その後に続く非リングポリライン群を含む連続区間
- 次のリング候補が現れたら、新しい `face_block` を開始する

この `face_block` ごとに:

- stroke の順序最適化（または最適化の一部）を実施
- `bridge_draw_distance` の状態（`current_end_q`）は block 境界でリセットし、**face 間ブリッジを禁止**する

注意/制約:

- `fill(remove_boundary=True)` だとリングが無いので、この検出は効かない
  - このケースを重視するなら「face_id を出力に埋め込む」など、上流からの情報伝搬が必要

### 2) 並び替えの粒度: “塗り線の均一感” 優先に寄せる

最小の変更としては、face_block 内で既存 `_order_strokes_in_layer()` を適用するだけでも「face を跨ぐ混ざり」は止まる。

ただし “塗りの均一感” を強く守るなら、塗り線（主に 2 点線分）は:

- 入力順（= fill の生成順: スキャン順）を基本にし
- 必要なら「反転（boustrophedon）」だけ許可して travel を減らす

という設計が自然。

提案する段階的アプローチ:

- Phase A（まず効くやつ）: face_block で分割し、block 内だけ既存貪欲を回す
- Phase B（見た目優先）: block 内の “塗り線っぽい stroke” は **順序固定 + 反転だけ最適化** に切り替える

“塗り線っぽい” の暫定判定（過度にやりすぎない）:

- 元 polyline の頂点数が 2（=線分）であるものを塗り線とみなす
- それ以外（>=3）は境界/輪郭寄りとして入力順固定（もしくは別扱い）

## 実装タスク（チェックリスト）

- [x] `src/grafix/export/gcode.py` に “face_block” 分割の小さなヘルパーを追加する
- [x] stroke 生成時に `block_id` を付与し、`block_id` ごとに `ordered` を作る（block 順は入力順で固定）
- [x] `bridge_draw_distance` の `current_end_q` を block 境界で `None` に戻し、face 間ブリッジを発生させない
- [x] Phase A: block 内の ordering を既存 `_order_strokes_in_layer()` で行う（まずは挙動確認）
- [ ] Phase B: “塗り線（2点ポリライン）” については順序を固定し、`allow_reverse` による反転選択だけを行う（必要なら）
- [x] `tests/export/test_gcode.py` に「face を跨いで stroke が混ざらない」ことのテストを追加する
- [x] `PYTHONPATH=src pytest -q tests/export/test_gcode.py` で確認する

## テスト設計（案）

1. 入力として 2 face を作る
   - 各 face: リング（>=3点）+ 複数の 2点線分（塗り線）
2. `optimize_travel=True` でも、出力の `; stroke polyline ...` コメント列が
   - face A の polyline 群 -> face B の polyline 群
     という **連続ブロック**になることを検証する
3. `bridge_draw_distance` を十分大きくしても、face A 終了から face B 開始の間に
   - pen up（`G1 Z...`）が入る（=ブリッジしない）
     を検証する

## 仕様の確認ポイント（ユーザー確認が欲しい点）

1. “face” の定義
   - `fill` の「外周+穴グループ」を face として扱う想定で良いか；はい
2. `fill(remove_boundary=True)` を使う運用はあるか；あるけど、その場合はユーザー側で最適化offにする運用にするから気にしないでいい。
   - ある場合、G-code 側だけで face を復元するのは難しいので、上流から “face_id” を伝搬する設計に寄せたい
3. 境界と塗りの順序
   - いまの `fill` は “境界 -> 塗り” だが、G-code 最適化後もこの順序を必ず維持したいか；いいえ。どちらでもいい。
