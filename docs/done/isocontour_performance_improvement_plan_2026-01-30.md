# isocontour effect パフォーマンス改善計画（NJIT化 + アルゴリズム見直し）

作成日: 2026-01-30

対象: `src/grafix/core/effects/isocontour.py`（`E.isocontour`）

## 背景（いま重い理由）

`E.isocontour` は大きく分けて

1. 閉曲線群 → SDF グリッド評価（`@njit` 済み）
2. SDF から等値線を抽出（Marching Squares）
3. 線分を stitch してポリライン化

という流れ。

現状のボトルネックは 2〜3 で、特に

- **Python 実装の Marching Squares**（グリッド全セル走査）
- **レベル数ぶん繰り返し走査**（`spacing/max_dist/level_step` によってはレベルが多い）
- **Python の dict/set ベースの stitch**

が重さの主因になっている。

## ゴール

- 大きいグリッド（上限付近）でも現実的な速度にする
- レベル数が増えてもスケールしやすくする
- 既存の出力特性（閉ループ中心、`mode`/`level_step`/`gamma` など）を維持する
- できるだけ **シンプル**に（キャッシュ/グローバル状態は持ち込まない）

## 方針（おすすめ順）

### 方針 1（最優先）: Marching Squares のセル走査を `@njit` 化

狙い: Python の二重 for を消して、セル走査を Numba に寄せる。

ポイント:

- 現状の `_marching_squares_segments` は `dict key_to_xy` へ書き込むため、そのまま `@njit` 化できない
- `@njit` 側は **配列へ書き込む** 形にするのが最短
  - 例: `segments_xy: (max_segments, 4)` に `[x0,y0,x1,y1]` を詰める
  - `max_segments = 2*(nx-1)*(ny-1)`（各セル最大 2 本）
  - 返り値: `(segments_xy[:n],)` のように “本数 n” も返す

期待効果:

- 単純に “セル走査” が速くなるので、レベル 1 回でも重いケースに効く

リスク/注意:

- メモリが増える（大きい grid では `segments_xy` が大きい）
  - float32 化や、2 パス（まず本数だけ数える→必要サイズ確保→詰める）も候補

### 方針 2（優先）: 複数レベル抽出を「1回の等値線抽出」に落とす（周期場の利用）

狙い: “レベル数ぶんの全セル走査” をやめる。

アイデア:

- レベル集合は `SDF = phase + k*spacing`（さらに `level_step` で間引き）
- したがって `spacing_eff = spacing*level_step` として
  - `f = sin(pi * (SDF - phase) / spacing_eff)`
  - `f == 0` の等値線を **1 回** Marching Squares で抜けば、全レベルの束になる

`mode/max_dist` の適用:

- 抽出したい `SDF` 範囲（例: inside は `[-max_dist, 0]`）の外側を “ゼロ交差しない定数” に潰す
  - 例: 範囲外の `f` を `+1` に固定して 0-crossing を消す

期待効果:

- レベル数が多いほど効く（理論的に O(levels) の因子が消える）

注意:

- 0-crossing の等値線は密になるので、stitch の負担が相対的に増える可能性あり

### 方針 3（次点）: stitch を軽量化（まず “キー表現” を見直す）

狙い: Python の `dict[tuple[int,int], ...]` と `set` の負担を減らす。

候補:

- **座標の量子化キーを tuple ではなく int にエンコード**する
  - 例: `(qx,qy)` を 64-bit の 1 つに pack（`(qx<<32) | (qy&0xffffffff)` 等）
  - adjacency の dict key が int になるだけでも軽くなることが多い
- さらに進めるなら、Marching Squares 側で “点” を **グリッドの辺 ID**（edge id）で表現する
  - 共有辺の交点は “同じ edge id” になるので、点の同一性判定が安定する
  - ループの stitch は edge id のグラフとして扱える

### 方針 4（最後）: stitch 自体も `@njit` 化して “2-正則グラフ” を直接トレース

狙い: 2 と 3 が片付いたあと、残ったボトルネックを取りに行く。

実装の方向:

- ノード（点）が基本的に次数 2（閉曲線）になる前提で、
  - `neighbors[node,2]` を配列で持ち
  - 未訪問ノードから辿って loop を構築
  - `coords2d_flat + offsets` を返す

注意:

- 実装はやや重くなるので、方針 1〜3 の結果を見て判断したい

### 追加案: SDF 評価の並列化

現状も `@njit` だが、`parallel=True` + `prange` で “行” を並列化できる余地がある。
（ただし ring 走査と inside 判定が多いので、まずは等値線側の改善優先）

## 進め方（小さく段階導入）

1. Marching Squares を `@njit` で配列出力に変更（まず 1 レベル）
2. 複数レベルを周期場 `sin(...)` で 1 回抽出に置き換え（`level_step` も `spacing_eff` で吸収）
3. stitch のキーを int pack に変更（最小の軽量化）
4. 必要なら stitch を `@njit` 化（neighbors 配列で loop トレース）
5. 最後に SDF 評価の `parallel` を検討

## 検証（軽い指標）

- 同一入力/同一パラメータで「出力が極端に変わっていない」こと（形状の雰囲気）
- おおまかに
  - `grid_pitch` を細かく
  - `max_dist` を大きく
  - `spacing` を小さく（レベル数増）
    で時間がどう変わるかだけ見る

## 実装手順（チェックリスト）

- [x] 方針 1: `@njit` Marching Squares（配列出力）を入れる
- [x] 方針 2: 周期場で “複数レベル→1回抽出” に置き換える
- [x] 方針 3: stitch のキー表現を int pack にする
- [x] （必要なら）方針 4: stitch を `@njit` 化
- [x] （必要なら）SDF 評価の `parallel` を試す
- [x] `tests/core/effects/test_isocontour.py` を通す

## 先に決めたいこと（確認）

- まずは「方針 1 + 方針 2」までを一気にやるで良い？（一番効く）；はい
- 出力は “閉ループのみ” のままで OK？（境界で開いた線は捨てる方針）；はい
