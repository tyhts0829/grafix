# isocontour effect 追加高速化（実装タスク分解）

作成日: 2026-01-30  
対象計画: `docs/plan/isocontour_further_performance_plan_2026-01-30.md`

## 前提（確認済み）

- SDF 高速化は「EDT（近似）」を先に試す（精度が合わなければビニングへ切替）: **はい**
- `grid_pitch` を SDF 精度の正として割り切る（EDT の近似誤差を許容）: **はい**

## 目的

- `E.isocontour` のボトルネック（SDF 評価 `O(Ngrid*Nsegments)` / `np.unique(axis=0)`）を解消する。
- 依存追加なし（SciPy 等なし）。
- 出力仕様（閉ループのみ / パラメータ意味）を維持する。

## 実装チェックリスト

### 0) 現状把握

- [x] 既存 `src/grafix/core/effects/isocontour.py` の SDF/抽出/縫合の流れを確認する
- [x] `tests/core/effects/test_isocontour.py` の期待を確認する

### 1) 方針 A: EDT SDF（本命）

#### inside_mask（even-odd）

- [x] グリッド行（y）ごとに交点 x を列挙→ソート→区間塗りつぶしで `inside_mask` を作る（`@njit`）
- [x] リング AABB で「その行で交差し得ないリング」をスキップして軽くする

#### boundary_mask

- [x] `inside_mask` の 4近傍差分から `boundary_mask` を作る（1px 程度で良い）

#### EDT（2D）

- [x] Felzenszwalb & Huttenlocher の 1D squared distance transform を `@njit` 実装する
- [x] x 方向→y 方向の 2-pass で 2D EDT にする（計算量 `O(nx*ny)`）
- [x] `pitch` を掛けて距離をスケールへ戻し、inside で符号を反転して `sdf` を得る
- [x] `gamma` の距離歪みを既存と同じ式で適用する

### 2) 方針 C: 交点 edge-id 化（unique 排除）

- [x] Marching Squares の交点を「セル辺ID（edge-id）」として列挙する（座標ではなく int のペア）
- [x] `edge-id -> (x,y)` 復元（`t` を保持）方式を決めて実装する
- [x] stitch は「node id グラフ」前提で組み立て、`np.unique(axis=0)` を撤去する

### 3) 検証

- [x] `tests/core/effects/test_isocontour.py` が通る
- [ ] 目視で極端なケース（大きい polygon / 小さい `grid_pitch`）が破綻しないことを確認する（任意）

## 方針 B（線分ビニング）について

EDT の精度が表現として許容できない場合のみ、別 PR/別タスクとして `docs/plan/isocontour_segment_binning_plan_2026-01-30.md` を実装する。
