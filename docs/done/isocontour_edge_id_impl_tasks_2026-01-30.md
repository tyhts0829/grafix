# isocontour 方針C（edge-id 化）実装タスク分解

作成日: 2026-01-30  
対象: `src/grafix/core/effects/isocontour.py`（`E.isocontour`）

## 目的

- Marching Squares の交点を座標で扱わず **edge-id（セル辺ID）** として扱う。
- `np.unique(axis=0)`（座標スナップ＋同一化）を撤去し、大規模出力時のコストを削る。
- 出力は「閉ループのみ」を維持する。

## 実装チェックリスト

### 1) edge-id の定義

- [x] 水平辺ID `h_id(j,i)=j*(nx-1)+i`（`0<=j<ny, 0<=i<nx-1`）
- [x] 垂直辺ID `v_id(j,i)=h_count + j*nx + i`（`0<=j<ny-1, 0<=i<nx`）

### 2) Marching Squares の出力を edge-id 化

- [x] `count` を edge-id 前提へ更新（ロジックは現状維持）
- [x] `fill` を edge-id 前提へ更新し、(edge_a, edge_b) を列挙する
- [x] 交点位置復元のため、edge ごとの補間係数 `t` を格納する（水平/垂直で配列を分ける）

### 3) stitch の edge-id 化

- [x] 大域 edge-id を「使用 edge のみ」へ compact 化する（bool mask + prefix sum）
- [x] 既存のサイクル抽出（次数 2 のみ）を再利用して閉ループを得る
- [x] edge-id と `t` から `(x,y)` を復元して loop 座標列を作る
- [x] 旧実装（座標スナップ＋`np.unique(axis=0)`）を撤去する

### 4) 検証

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_isocontour.py` が通る
