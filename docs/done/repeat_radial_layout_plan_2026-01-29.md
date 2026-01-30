# repeat effect: 円形（放射）配置を追加する実装計画（r / θ / 周方向数 / 半径方向数）

作成日: 2026-01-29

## 背景

- `repeat`（`src/grafix/core/effects/repeat.py`）は現状、`offset`（XYZ）で「直交方向の配置（グリッド/直線）」を作るのが得意。
- 追加したいのは、配置座標系を「円形（放射）」へ切り替え、以下の直感的な指定で並べられること:
  - 半径 `r`
  - 回転角 `theta`（開始角）
  - 周方向配置数 `n_theta`
  - 半径方向配置数 `n_radius`

## ゴール

- `repeat` に `layout` を追加し、`layout="grid"`（現状）/ `layout="radial"`（円形配置）を選べる。
- `layout="radial"` で **(r, theta, n_theta, n_radius)** のみで「同心円状の配置」を作れる。
- layout により「使わないパラメータ」は `ui_visible` で GUI から隠す（`docs/memo/ui_visible.md` に従う）。
- 最小のテストを追加して仕様を固定する。

## 非ゴール（今回はやらない）

- 円柱の任意軸（axis 指定）対応（ワールド Z 固定で十分、必要なら第 2 段）。
- 3D の z 方向スタックや、螺旋（z 変化）などの派生機能（必要なら別タスク）。

## API 案（effect 引数）

### 新規追加

- `layout: {"grid","radial"} = "grid"`
- `radius: float = 0.0`（[mm]）
- `theta: float = 0.0`（[deg]。開始角）
- `n_theta: int = 6`（周方向配置数）
- `n_radius: int = 1`（半径方向配置数）

### 既存維持

- `count`, `offset`, `rotation_step`, `scale`, `curve`, `cumulative_*`, `auto_center`, `pivot` は **grid では現状維持**。

## 仕様（radial の配置定義）

### 半径方向（リング）

`n_radius` 本のリングを **中心→外周**に等間隔で置く:

- `n_radius == 1` のとき: 半径列は `[radius]`
- `n_radius >= 2` のとき: 半径列は `linspace(0, radius, n_radius)`
  - ただし **中心リング（r=0）は周方向を 1 本だけ**にして重複を避ける（= 1 コピー）

結果としてコピー数は:

- `total = 1 + (n_radius - 1) * n_theta`（`n_radius >= 2` のとき）
- `total = 1 * n_theta` ではなく、中心の重複を避けるため上記

### 周方向（角度）

外側リング（r>0）の角度は等分:

- `angle(j) = theta + 360 * j / n_theta`（j=0..n_theta-1）

### 座標変換（ワールド Z 固定）

配置の平行移動は XY 平面上で:

- `dx = r * cos(angle)`
- `dy = r * sin(angle)`
- `dz = 0`

※ 配置全体の移動は `E.translate()` を併用する（repeat に中心座標を持たせない）。

## repeat 内の「変換」との関係（radial 時）

`repeat` は「中心移動→スケール→回転→平行移動→中心復帰」を持つため、radial では以下を方針として固定する:

- 平行移動（配置）だけを radial 仕様へ差し替える
- `rotation_step` / `scale` の「補間」は維持し、`t` は **生成されるコピーの順序**で 0→1 に変化させる
  - `t = k / (copies-1)`（k は 0..copies-1 のコピー index）
  - これにより **位相（theta 方向）でも** 回転/スケールが変化する
  - `copies==1` のときは `t=1` とする（単一コピーでも end 値が効く）

※ 以前は「半径 index のみ」案だったが、要望により位相でも変化する仕様へ変更。

## Parameter GUI: ui_visible 方針

`layout` をスイッチにし、使わない行を隠す:

- `layout="grid"` のときに表示:
  - `count`, `offset`, `cumulative_offset`（既存のグリッド配置に必要）
- `layout="radial"` のときに表示:
  - `radius`, `theta`, `n_theta`, `n_radius`
- それ以外（`rotation_step`, `scale`, `curve`, `cumulative_scale`, `cumulative_rotate`, `auto_center`, `pivot`）は基本表示のまま（必要なら第 2 段でさらに整理）

実装は `@effect(meta=..., ui_visible=UI_VISIBLE)` で `arg -> predicate` を登録する。

## 実装方針（コード）

- `src/grafix/core/effects/repeat.py`
  - meta に `layout/radius/theta/n_theta/n_radius` を追加
  - `repeat()` の signature と docstring を更新
  - njit:
    - `layout="grid"` は既存 `_repeat_fill_all` を維持
    - `layout="radial"` 用に `_repeat_fill_radial(...)` を新設（もしくは既存に分岐を追加）
      - ループを (ring_i, j) の二重にするか、フラット index から (ring_i, j) を復元する
      - 中心リングの重複回避（j=0 だけ）を実装

- `src/grafix/api/__init__.pyi`
  - `E.repeat()` の引数へ追加分を反映

## テスト（最小）

- `tests/core/effects/test_repeat.py`
  - `layout="radial"` の配置を 1 ケース固定:
    - `radius=10, theta=0, n_theta=4, n_radius=2` のとき
    - 期待位置が `(0,0) + (10,0) + (0,10) + (-10,0) + (0,-10)` になること（中心 + 外周4点）

## 実装手順（チェックリスト）

- [x] `layout` の値名を確定（`grid/radial`）
- [x] radial のコピー数仕様（中心リングの重複回避）を確定
- [x] radial 時の補間 `t` を確定（コピー順序で 0→1 / 位相でも変化）
- [x] `src/grafix/core/effects/repeat.py` を更新（meta / signature / docstring / ui_visible / njit）
- [x] `tests/core/effects/test_repeat.py` に radial テストを追加
- [x] `src/grafix/api/__init__.pyi` を更新
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_repeat.py` を実行

## 確認したい点（あなたに質問）

- `layout` の値名は `grid/radial` で OK？（`grid/circular` など別案が良ければ合わせる）；はい
- radial の半径分割は `linspace(0, radius, n_radius)` で OK？（`n_radius==1` だけ `[radius]` の特例あり）；はい
- radial 時の `rotation_step/scale` は位相でも step してほしい；はい
