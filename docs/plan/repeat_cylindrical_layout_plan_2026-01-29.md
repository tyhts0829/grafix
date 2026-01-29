# repeat effect: 配置レイアウトを「直交座標 / 円柱座標」から選べるようにする改善計画

作成日: 2026-01-29

## 背景 / 課題

- 現状の `repeat`（`src/grafix/core/effects/repeat.py`）は、コピーごとの平行移動を **XYZ（直交座標）** の終点 `offset` に向かって補間して適用する。
  - そのため「グリッド/直線状」の配置は作りやすい。
- 追加したいのは「回転方向に並べる」配置であり、ここで言う回転は **ジオメトリ自体の回転**ではなく **配置（平行移動）の座標系**の話。
  - イメージ: 配置ベクトルを **円柱座標 (r, θ, z)** で指定し、`repeat` がそれを **XYZ に変換**して並べる。

## ゴール

- `repeat` に配置レイアウト（座標系）を追加し、直交（cartesian）に加えて円柱（cylindrical）配置を選べる。
- njit カーネルの形は維持し、コピーごとの平行移動ベクトル計算だけを `layout` 分岐で差し替える。
- Parameter GUI / stub / テストで仕様を固定する（最小 1 ケース）。

## スコープ

- やる:
  - `repeat` に `layout` を追加して、`offset` を直交/円柱で解釈切替する
  - 「円周に並べる」用途を作りやすくするため、開始点も指定できるようにする（後述の `offset_start`）
  - docstring / stub / テスト更新
- やらない（今回は見送り）:
  - いきなり任意軸の円柱座標（3D の任意方向軸）まで対応（必要なら第 2 段）
  - `scale` / `rotation_step` の開始点指定（必要なら別タスク）

## 提案仕様（API 案）

### 新パラメータ

- `layout: {"cartesian","cylindrical"} = "cartesian"`
- `offset_start: vec3 = (0,0,0)`（新規）
- `offset: vec3 = (0,0,0)`（既存。実質 `offset_end`）

### 解釈

#### `layout="cartesian"`（現状の延長）

- `offset_start` と `offset` を XYZ の「開始/終点オフセット [mm]」として扱い、
  `t_offset` で線形補間してコピーごとの平行移動ベクトル `Δ` を作る:
  - `Δ(t) = lerp(offset_start, offset_end, t_offset)`
  - 既存挙動は `offset_start=(0,0,0)` により維持

#### `layout="cylindrical"`（今回追加したいもの）

- `offset_start` と `offset` を (r, theta_deg, z) の「開始/終点」として扱い、補間してから XYZ に変換して `Δ` を作る:
  - `r(t) = lerp(r0, r1, t_offset)` [mm]
  - `theta(t) = lerp(theta0, theta1, t_offset)` [deg]（内部で rad に変換）
  - `z(t) = lerp(z0, z1, t_offset)` [mm]
  - `Δ(t) = ( r(t)*cos(theta), r(t)*sin(theta), z(t) )`

ポイント:

- `r0=r1` にすれば「一定半径の円周」になり、`theta0..theta1` で回転配置が作れる。
- `r0!=r1` にすれば「螺旋（半径が変わる）」配置になる。
- ジオメトリの向きは `rotation_step`（既存）で別途制御できる（= 配置と回転を分離）。

### 既存パラメータとの関係

- `curve` / `cumulative_offset` は `t_offset` に効くので、円柱配置でも「密度を前半/後半へ寄せる」ができる（仕様として維持）。
- `auto_center/pivot` はこれまで通りスケール/回転の中心に使う。配置（Δ）は「コピー全体に加算される平行移動」なので、直交/円柱どちらも破綻しない。

## 実装方針（中身）

### 1) meta / signature / docstring

- `repeat_meta` に追加:
  - `layout: ParamMeta(kind="choice", choices=("cartesian","cylindrical"))`
  - `offset_start: ParamMeta(kind="vec3", ...)`
- `repeat()` に `layout` と `offset_start` を追加
- docstring を更新:
  - `layout` によって `offset_start/offset` の意味が変わること（cartesian: XYZ / cylindrical: r,θ,z）を明記

### 2) njit カーネル

現状はコピーごとに `ox,oy,oz` を計算して最後に `+ (ox,oy,oz)` をしているので、
その部分を下記に置換する（擬似コード）:

- `offset_vec = lerp(offset_start, offset_end, t_offset)`（まずは 3 成分を補間）
- `if layout == "cartesian": (ox,oy,oz) = offset_vec`
- `if layout == "cylindrical":`
  - `r = offset_vec[0]`
  - `theta = deg2rad(offset_vec[1])`
  - `z = offset_vec[2]`
  - `ox = r*cos(theta); oy = r*sin(theta); oz = z`

`layout` は njit 内で branch してもいいが、分岐コストが気になるなら「layout ごとに 2 カーネル」でも良い。
（ただしまずはシンプル優先で分岐で十分）

## テスト（最小）

- `tests/core/effects/test_repeat.py` に追加（例）:
  - 入力: x 軸上の 2 点ポリライン（既存の `repeat_test_line_0_1` が使える）
  - `layout="cylindrical"`, `auto_center=False`, `pivot=(0,0,0)`
  - `count=2`, `offset_start=(10, 0, 0)`, `offset=(10, 180, 0)` のとき
    - コピー 0 の平行移動 = (10,0,0)
    - コピー 1 の平行移動 = (0,10,0)（θ=90°）
    - コピー 2 の平行移動 = (-10,0,0)（θ=180°）
  - 上記の期待位置へ並ぶことを `np.testing.assert_allclose` で確認

## 実装手順（チェックリスト）

- [ ] `layout` の値名（`cartesian/cylindrical` で良いか）を確定; grid/cylindricalで。
- [ ] `offset_start` を入れる（円周配置のため必須と判断）
- [ ] `src/grafix/core/effects/repeat.py` を更新（meta / signature / docstring / njit）
- [ ] `tests/core/effects/test_repeat.py` に円柱配置テストを追加
- [ ] stub 更新（`src/grafix/api/__init__.pyi`）
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_repeat.py` を実行

## 確認したい点（あなたに質問）

- 円柱配置の軸は「ワールド Z 固定」でまず十分？（必要なら第 2 段で `axis: vec3` を追加する）；はい
- `offset_start` を入れる方針で良い？（入れないと「一定半径の円周」を作りにくい）；はい
  追加要望: もし、layoutによって使わないパラメータが出る場合は、docs/memo/ui_visible.mdに従って隠すようにして。
