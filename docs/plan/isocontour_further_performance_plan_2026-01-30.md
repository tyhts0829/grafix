# isocontour effect 追加高速化計画（SDF高速化 / edge-id 化）

作成日: 2026-01-30

対象: `src/grafix/core/effects/isocontour.py`（`E.isocontour`）

前提: `docs/plan/isocontour_performance_improvement_plan_2026-01-30.md` で実施した「周期場 + NJIT Marching Squares + stitch の配列化」以降の次段。

## 現状の残ボトルネック（想定）

- **SDF 評価が `O(Ngrid * Nsegments)`**（線分数が増えると支配的）
- 大規模出力時に **交点同一化**（いまは `np.unique(axis=0)`）が効くケースがある

## ゴール

- 大きい入力（多線分 / 大きい bbox / 小さい `grid_pitch`）でも破綻しない速度にする
- 依存追加なし（SciPy など入れない）
- 出力は今と同じく「閉ループのみ」「パラメータの意味を維持」

## 方針 A: SDF を距離変換（EDT）で `O(Ngrid)` に寄せる（本命）

### 概要

閉曲線をグリッドへラスタライズし、

- `inside_mask`（even-odd 充填）
- `boundary_mask`（境界ピクセル）

を作ってから、2D Euclidean Distance Transform（EDT）で **境界までの距離**を求める。

- unsigned distance: `dist = EDT(boundary_mask)`
- signed: `sdf = dist * (+1/-1)`（inside なら負）

### 期待効果

- 線分数にほぼ依存しなくなる（`Nsegments` が重さの主因でなくなる）
- `grid_pitch` が細かいケースでもスケールが読みやすい

### 主要な設計点

#### 1) `inside_mask` の生成（even-odd）

- スキャンライン（行ごと）で交差数 parity を取る
- 既存の inside 判定（点ごとの even-odd）を “画像” へ一括変換する
- `@njit` で書ける（リングの bbox を使って行ごとに候補線分を減らすと良い）

#### 2) `boundary_mask` の生成（線分ラスタライズ）

最低限の精度で OK（距離の精度は `grid_pitch` に依存する前提）として、

- 方式案 A: セル中心に対する “線分距離 < 0.5\*pitch” で境界扱い（精度は高いが重い）
- 方式案 B: 線分をグリッドセルへ DDA/Bresenham 的に走査して通過セルを境界扱い（高速）

まずは B を推奨（速度優先）。

#### 3) 2D EDT の実装（依存なし）

- Felzenszwalb & Huttenlocher の 1D squared distance transform を
  - まず x 方向
  - 次に y 方向
    で 2D 化する（計算量は `O(nx*ny)`）
- 実装は `@njit` で配列処理にする
- 返り値は “ピクセル単位距離” なので `pitch` を掛けて mm 系に戻す

#### 4) `gamma` の扱い

現行は「`dist/max_dist` を `**gamma`」で歪めているので、

- `dist` を求めた後に同じ変換を適用すれば OK

### リスク / 注意

- EDT は “境界のラスタライズ誤差” がそのまま距離誤差になる（特に斜め線）
  - `grid_pitch` を下げれば改善するが計算量も上がる
- 「線分距離の真値」より精度は落ちる可能性がある（表現として許容できるか要確認）

### 導入手順（段階）

- [ ] `inside_mask`（even-odd）を画像で作れるようにする
- [ ] `boundary_mask` を作る（inside の 4近傍差分から生成）
- [ ] EDT（squared distance）を `@njit` で実装し、`sdf` を作る
- [ ] 既存の isocontour と見た目・速度を比較（遅くなったので EDT は採用せず）
- [ ] 許容できない場合は「方針 B（線分ビニング）」へ切替（採用）

## 方針 B: 線分の空間ビニングで平均計算量を下げる（精度重視の代替）

### 概要

グリッド（または粗いタイル）で平面を分割し、各タイルに “近くを通る線分” を登録。
SDF 評価点ごとに “近傍タイル” の線分だけを走査して距離を取る。

### 期待効果

- 形状が広く分散しているほど効く（局所探索になる）
- EDT より距離精度は高い（線分距離は真値）

### 実装の難しさ

- 「タイル→可変長の線分リスト」を `@njit` で扱うための設計が必要
  - 2-pass（count→prefix sum→fill）で CSR 形式にするのが素直

## 方針 C: 交点の “edge-id” 化で `np.unique(axis=0)` を消す（次に効く）

### 概要

Marching Squares の交点は「どのセルのどの辺」かで一意になるため、
座標を量子化→unique する代わりに **辺ID（edge-id）をノードID** として扱う。

例:

- 水平辺: `(j, i)` の上辺（`0 <= j < ny`, `0 <= i < nx-1`）
- 垂直辺: `(j, i)` の右辺（`0 <= j < ny-1`, `0 <= i < nx`）

を 1D index に畳み込んで node id にする。

### 実装プラン

- Marching Squares の fill で、線分端点を `(edge_id_a, edge_id_b)` の int 配列で出す
- `edge_id -> (x,y)` の座標復元用に、各 edge の補間係数 `t` を保持する
  - 方式案 A: `edge_t` 配列（水平/垂直で別）を作って “初回に書き込み”
  - 方式案 B: segment 側に `t_a/t_b` を持つ（重複あり）
- stitch は “node id のグラフ” なので unique が不要になる

### 期待効果

- 出力が大きい場合の `np.unique(axis=0)` コストを消せる
- 同一交点判定がより安定する（量子化誤差の依存が減る）

### 注意

- node id の総数はグリッド辺数（~2*nx*ny）で、配列をフルに持つとメモリが増える
  - “使用された edge のみ compact 化” をどうするか（bool mask + prefix sum 等）

## 計測（最小）

テストとは別に “速度が落ちない” を確認するため、任意で以下を用意する（実装時に判断）:

- 大きめ polygon（例: n_sides=256, scale 大）+ 小さい `grid_pitch` + 大きい `max_dist`
- 時間計測は `time.perf_counter()` 程度で十分

## 実装手順（チェックリスト）

- [ ] 方針 A（EDT）を先に試す（inside/boundary/EDT）
- [ ] 許容できない場合、方針 B（線分ビニング）へ切替
- [ ] 交点 edge-id 化（方針 C）を適用して unique を排除
- [ ] `tests/core/effects/test_isocontour.py` を通す

## 先に決めたいこと（確認）

- SDF 高速化は「EDT（近似）」でまず試して良い？（精度が合わなければビニングへ）；はい
- `grid_pitch` を SDF 精度の正として割り切って良い？（EDT の近似誤差を許容するか）；はい
