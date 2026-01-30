# 組み込み effect: SDF シャドウキャストハッチ（E.sdf_shadow_hatch）

作成日: 2026-01-30

元アイデア: `docs/plan/sdf_stripes_effect_plan_2026-01-29.md` の **アイデア M**。

## ゴール

- `E.sdf_shadow_hatch(mask)` として使える **組み込み effect** を追加する
  - 入力: `inputs[0]` = 閉曲線マスク（外周＋穴、複数リング可）
  - 出力: 影領域にのみ生成されたハッチ（開ポリライン列）
- 2D 前提（3D 入力は `transform_to_xy_plane` で近似的に XY へ整列して処理）で、非平面入力は無理に扱わない
- SDF を「距離場としての ray marching」に使い、**複雑形状でも一貫して動く**こと

## 追加/変更するもの

- `src/grafix/core/effects/sdf_shadow_hatch.py`（新規）
  - `@effect(meta=..., n_inputs=1)` で登録
  - `src/grafix/core/effects/AGENTS.md` を遵守（effect 間 import しない / util は可）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に追加して自動登録対象にする
- 型スタブ更新
  - `src/grafix/devtools/generate_stub.py` の生成結果で `src/grafix/api/__init__.pyi` を更新
- `tests/core/effects/test_sdf_shadow_hatch.py`（新規・最小）

## API 案

```python
out = E.sdf_shadow_hatch(
    activate=True,
    light_angle=45.0,     # [deg] 入射方向（0=+X 方向へ進む光）
    shadow_steps=64,      # レイマーチのステップ数
    softness=8.0,         # 0 でハードシャドウ、>0 でソフト寄り
    shadow_threshold=0.5, # 0..1（ソフトシャドウを二値化する閾値）
    hatch_angle=30.0,     # [deg] ハッチ方向
    hatch_spacing=2.0,    # [mm] ハッチ間隔
    band=80.0,            # [mm] |SDF| の外側レンジ上限（0 で無制限）
    grid_pitch=0.5,       # [mm] SDF/シャドウの評価グリッド
    auto_close_threshold=1e-3,
    keep_original=False,
)(mask_geom)
```

### `light_angle` の取り決め（案）

- `light_dir = (cos(theta), sin(theta))` を「光が進む方向」とする（`theta = deg2rad(light_angle)`）
- ある点 `p` が照らされるかの判定は、`p` から **逆向き** `-light_dir`（光源の方向）へレイマーチして遮蔽物（SDF<0）に当たるかどうかで決める
  - 当たる → 影（shadow=1）
  - 当たらない → 明（shadow=0）

## meta（Parameter GUI）案

- `light_angle: float`（0..360, default 45）
- `shadow_steps: int`（8..256, default 64）
- `softness: float`（0..50, default 8）
- `shadow_threshold: float`（0..1, default 0.5）
- `hatch_angle: float`（0..180, default 30）
- `hatch_spacing: float`（0.2..20, default 2）
- `band: float`（0..300, default 80）
- `grid_pitch: float`（0.1..5, default 0.5）
- `auto_close_threshold: float`（0..5, default 1e-3）
- `keep_original: bool`

## 実装方針（中身）

### 1) 入力と平面整列（mask 基準）

- `inputs[0]`（mask）から「代表リング」を 1 本選ぶ（`offsets` 区間で 3 点以上あるもの）
- `transform_to_xy_plane(rep)` で回転行列 `R` と `z_offset` を得る
- mask の `coords` を `R/z_offset` で XY 平面へ整列
- どれだけ Z=0 から外れているかを見て、平面性が崩れている場合は空を返す（`isocontour` の方針に寄せる）

### 2) 閉曲線（リング）抽出（XY）

- 整列済み mask の各ポリラインについて
  - 端点が十分近ければ閉じる（`auto_close_threshold`）
  - 「先頭点=末尾点」になったものだけをリングとして採用
- リングは even-odd の XOR 合成で扱う（外周＋穴、ネストも含む）

### 3) SDF グリッドの作成（Numba）

- `isocontour` と同等の「リング群を平坦な配列にする」形式で Numba に渡す
  - `ring_vertices: (M,2) float64`
  - `ring_offsets: (n_rings+1,) int32`
  - `ring_mins/maxs: (n_rings,2) float64`
- 評価範囲はリング AABB を基準に
  - ハッチ領域 `band` と
  - レイマーチの“逃げ”のための余白（固定で `margin = 2*band + 10*grid_pitch` など）
  を足して作る
- `grid_pitch` で一様グリッド `xs, ys` を作り、`sdf[j,i]` を Numba で評価する
  - 距離: 全線分への最短距離
  - 符号: even-odd（リング内外の XOR）
- グリッド点数が巨大化する場合は空を返す（`isocontour` の `MAX_GRID_POINTS` 相当の上限を置く）

### 4) SDF の bilinear サンプラ（Numba）

- レイマーチ・ハッチ判定で SDF を頻繁に引くので、`sdf_grid` を bilinear で引ける関数を用意する
  - 入力: `sdf_grid, x0, y0, pitch, nx, ny, x, y`
  - 出力: `d(x,y)`（float）
- 範囲外の参照は「範囲外に出た」扱いとして呼び出し元で break できるように、bool 返し（`in_bounds`）にしても良い

### 5) シャドウ場（0..1）の評価（Numba）

- 各グリッド点 `p=(x,y)` について、影係数 `shadow` を計算して `shadow_grid` を作る
- まず候補点を絞る:
  - `d = sdf(p)`
  - `d <= 0`（内側）→ shadow=0（ここはハッチ対象外）
  - `band > 0` かつ `d > band` → shadow=0（遠すぎるので描かない）
- レイマーチ（ハードシャドウ）:
  - `dir = -light_dir`
  - `t = pitch` から開始して、`pos = p + dir * t` の SDF をサンプル
  - `SDF(pos) < 0` に入ったら遮蔽ヒット → shadow=1
  - 何も当たらずグリッド外へ出たら → shadow=0
  - `t += max(SDF(pos), pitch)` で前進（最小ステップは `pitch`）
- ソフトシャドウ（MVP は “ソフトを二値化” まで）:
  - Quilez 系の近似をそのまま 2D に適用して `lit_factor` を 0..1 で得る
    - `lit = min(lit, softness * sdf(pos) / t)` を更新していく（`softness<=0` はハード扱い）
    - `shadow = 1 - clamp(lit, 0, 1)`
  - 最終的には `shadow_threshold` で二値化してハッチ領域を得る（shadow>=threshold を影）
    - “濃淡”までやる場合は v2 で（確率的に線を落とす / spacing を局所変化させる）

### 6) 影領域のハッチ線分生成

- 方針: **ポリゴン化せず**、`shadow_grid` を直接スキャンして線分を作る（最小実装）
- `hatch_angle` を打ち消す回転（`-hatch_angle`）を作り、作業座標でハッチが水平になるようにする
  - 回転中心は評価 bbox の中心（または mask の重心）に固定する
  - bbox 四隅を作業座標へ回し、`min_x..max_x, min_y..max_y` を得る
- `y=min_y..max_y` を `hatch_spacing` 間隔で走査
  - 各 `y` について `x=min_x..max_x` を `sample_pitch`（基本は `grid_pitch`）でサンプル
  - 各サンプル点を世界座標へ戻し、`shadow_grid` を bilinear で評価
  - `shadow >= threshold` を満たす区間（連続 run）を `[x_a, x_b]` として線分化
  - 作業座標の線分を world へ回転し、3D（z=0）にして `transform_back` で元の平面へ戻す
- `keep_original=True` なら、最後に入力 mask の各ポリラインをそのまま出力へ足す

## テスト（最小）

- 正常系:
  - `mask = G.polygon(n_sides=64, scale=50)` を用意
  - `realize(E.sdf_shadow_hatch(light_angle=0, hatch_spacing=3, grid_pitch=1, band=80)(mask))` が
    - `coords` が空でない
    - `coords[:,2]` がほぼ 0（平面入力の基本ケース）
- `activate=False`:
  - wrapper 仕様通り「入力がそのまま返る」ことを確認
- 空入力:
  - `G.polygon(activate=False)` を渡すと空を返す

## 実装手順（チェックリスト）

- [ ] `src/grafix/core/effects/sdf_shadow_hatch.py` を追加（effects/AGENTS.md を遵守）
- [ ] `@effect(meta=..., n_inputs=1)` で登録（meta に `activate` は入れない）
- [ ] mask 基準で平面整列（util 使用）＋ planarity 最小チェック
- [ ] mask からリング抽出（閉曲線のみ採用）
- [ ] Numba で SDF グリッド評価
- [ ] Numba で bilinear サンプラ
- [ ] Numba で shadow_grid（ray marching）
- [ ] shadow_grid をスキャンしてハッチ線分生成（回転→水平スキャン→逆回転）
- [ ] `src/grafix/core/builtins.py` にモジュール追加
- [ ] `src/grafix/api/__init__.pyi` を生成結果で更新
- [ ] `tests/core/effects/test_sdf_shadow_hatch.py` を追加
- [ ] `PYTHONPATH=src pytest -q`（対象テストでも可）

## 追加で確認したい点

- `light_angle` の向き（入射方向 vs “光源の方向”）はこの取り決めで OK？
- `band` は「SDF の外側距離でクリップ（0..band）」で良い？（影をもっと伸ばしたいなら `shadow_length` を別 param で足す）
- v1 は **二値の影 + 一様ハッチ**で進め、濃淡（dither/spacing 変化）は v2 に回す方針で良い？
