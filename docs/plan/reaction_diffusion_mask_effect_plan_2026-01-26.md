# 組み込み effect: 閉曲線マスク内で Gray-Scott 反応拡散 → 線化（E.reaction_diffusion）

作成日: 2026-01-26

## ゴール

- `E.reaction_diffusion(mask)` として使える **組み込み effect** を追加する
  - 入力: `inputs[0]` = **閉曲線（複数可）** からなるマスクジオメトリ（平面上）
  - 出力: そのマスク領域内だけで Gray-Scott を回して得た V 場を「線」（等値線 or 細線化中心線）に変換したポリライン列
- **`E.clip` を使わず**、「計算中にドメインマスクを適用」して外形が矩形に見えない状態にする
- Parameter GUI で主要パラメータ（F/K/steps/pitch/level/mode 等）を調整できるよう `meta` を付ける

## 追加/変更するもの

- `src/grafix/core/effects/reaction_diffusion.py`（新規）
  - `@effect(meta=..., n_inputs=1)` で登録
  - `util.transform_to_xy_plane` / `util.transform_back` のみ利用（effects 間依存禁止のため）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に追加して自動登録対象にする
- （必要なら）型スタブ
  - `src/grafix/api/__init__.pyi` に `reaction_diffusion` を追記、または `python -m grafix stub` 相当で更新
- `tests/core/effects/test_reaction_diffusion.py`（新規・最小）

## API 案

```python
masked_lines = E.reaction_diffusion(
    activate=True,
    grid_pitch=0.6,
    steps=4500,
    du=0.16, dv=0.08, feed=0.035, kill=0.062, dt=1.0,
    seed=0,
    mode="contour",   # or "skeleton"
    level=0.2,
    thinning_iters=60,
    min_points=16,
    boundary="noflux",  # or "dirichlet"
)(mask_geom)
```

### meta（Parameter GUI）案

- `grid_pitch: float`（mm）: 0.2..2.0
- `steps: int`: 0..10000
- `du,dv: float`: 0..1
- `feed,kill: float`: 0..0.1
- `dt: float`: 0.1..2.0
- `seed: int`: 0..9999
- `mode: choice`: `"contour" | "skeleton"`
- `level: float`: 0..1
- `thinning_iters: int`: 1..200（`mode=="skeleton"` のときのみ表示）
- `min_points: int`: 2..200
- `boundary: choice`: `"noflux" | "dirichlet"`

## 実装方針（中身）

### 1) マスクの平面整列

- `inputs[0]` から「代表リング」を 1 本選ぶ（`offsets` 区間で 3 点以上あるもの）
- `transform_to_xy_plane(rep)` で回転行列 `R` と `z_offset` を得る
- マスク全体の `coords` を同じ `R/z_offset` で XY 平面へ整列
- ここで Z ずれが大きければ（非平面） empty を返す（最小限のチェック）

### 2) マスクのラスタライズ（even-odd）

- 整列済み mask の閉ポリライン列を「リング列」として取得（閉じていなければ閉じる/無視）
- bbox を取り、`grid_pitch` で 2D グリッドを作る（`nx,ny` は bbox から自動算出）
- `domain_mask[ny,nx]` を **even-odd ルール**で塗りつぶす
  - 実装は「スキャンライン交差数（XOR）」で、NumPy/Numba で書ける形にする
  - （pyclipper/shapely の point-in-polygon は呼び出し回数が多くなりやすいので避ける）

### 3) Gray-Scott（ドメインマスク付き）

- `u,v` を float32 で確保（外側は固定: `u=1, v=0`）
- 初期条件:
  - マスク内に微ノイズ（±0.01）＋中心に小ブロブ（パラメータ化するかは後で判断）
- `@njit(cache=True)` の `_gray_scott_simulate_masked(u,v,mask,...)` を実装
  - 更新は `mask==True` のセルのみ
  - Laplacian の近傍がマスク外のとき
    - `boundary="noflux"`: 近傍値を自セル値に置換（法線方向の勾配ゼロ）
    - `boundary="dirichlet"`: 近傍値を外側固定値（u=1,v=0）にする

### 4) 線化（clip なし）

- `mode="contour"`:
  - `V` をそのまま Marching Squares → セグメント → stitch → polyline 化
  - ただし `mask==False` を 0（もしくは `-1`）にして、等値線が外へ出ないようにする
- `mode="skeleton"`:
  - `binary = (V >= level) & mask`
  - Zhang-Suen thinning（NumPy で十分）→ スケルトン点を 8 近傍でトレース → polyline 化
- 生成した 2D 点列を 3D(z=0) にし、`transform_back(..., R, z_offset)` で元の平面へ戻す

## テスト（最小）

- 正常系:
  - `mask = G.polygon(n_sides=64, center=(0,0,0), scale=50)` を与えて `realize(E.reaction_diffusion(...)(mask))` が非空になる
- 無効入力:
  - 空ジオメトリ入力で empty を返す
- `activate=False`:
  - effect wrapper の挙動として入力がそのまま返る（現行仕様に合わせる）

## 実装手順（チェックリスト）

- [ ] `src/grafix/core/effects/reaction_diffusion.py` を追加（effects/AGENTS.md を遵守）
- [ ] `@effect(meta=..., n_inputs=1)` で登録
- [ ] マスク整列（util 使用）＋ラスタライズ（even-odd）
- [ ] Gray-Scott masked（`@njit(cache=True)`）
- [ ] contour / skeleton の線化
- [ ] `src/grafix/core/builtins.py` にモジュール追加
- [ ] （必要なら）`src/grafix/api/__init__.pyi` 更新
- [ ] `tests/core/effects/test_reaction_diffusion.py` 追加
- [ ] `PYTHONPATH=src pytest -q`（対象テストのみでも可）

## 追加で確認したい点

- `grid_pitch` ベースで解像度自動算出で OK？（`nx/ny` 固定にしたい需要があれば切替を検討）
- 初期条件は「中心ブロブ + ノイズ」で固定で OK？（マスク形状由来の seed を入れたいなら第2入力に拡張）
- デフォルトの `boundary` は `"noflux"` で良い？（境界に模様が乗りやすい）

