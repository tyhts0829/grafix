# 組み込み effect: SDF 吸着/反発ディスプレイス（E.sdf_attract）

作成日: 2026-01-30

## ゴール

- `E.sdf_attract(base, mask)` として使える **組み込み effect** を追加する
  - 入力: `inputs[0]` = 任意の線（開/閉ポリライン列）, `inputs[1]` = 閉曲線マスク（複数リング可）
  - 出力: `inputs[0]` の各頂点を、`inputs[1]` の境界（またはオフセット境界）へ **吸着 / 反発**させたポリライン列
- 形状を「境界に沿わせる」ための土台として、文字・ハッチ・流線の追従に使えること
- 2D 前提（任意平面は `transform_to_xy_plane` で整列して処理）で、非平面入力は無理に扱わない

## 追加/変更するもの

- `src/grafix/core/effects/sdf_attract.py`（新規）
  - `@effect(meta=..., n_inputs=2)` で登録
  - effects 間依存禁止のため、`grafix.core.effects.util`（`transform_to_xy_plane` / `transform_back`）のみ参照
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に追加して自動登録対象にする
- 型スタブ更新
  - `src/grafix/devtools/generate_stub.py` の生成結果で `src/grafix/api/__init__.pyi` を更新
- `tests/core/effects/test_sdf_attract.py`（新規・最小）

## API 案

```python
out = E.sdf_attract(
    activate=True,
    strength=0.8,     # -1..+1（負で反発）
    bias=0.0,         # 目標の signed distance（0 で境界）
    snap_band=30.0,   # |d-bias| がこれより大きい点は不変（0 なら無制限）
    falloff=12.0,     # 近いほど強い（0 ならフラット）
)(base_geom, mask_geom)
```

## meta（Parameter GUI）案

- `strength: float`（-1..+1, default 0.8）
- `bias: float`（mm, default 0.0 / ui: -50..+50）
- `snap_band: float`（mm, default 30.0 / ui: 0..200）
- `falloff: float`（mm, default 12.0 / ui: 0..200）
- （MVP では入れない）`preserve_length: bool`
  - 伸び縮みを抑えたい場合は `E.relax` を後段に置く運用でまず十分かを確認する

## 実装方針（中身）

### 1) 入力と平面整列（mask 基準）

- `inputs[1]`（mask）から「代表リング」を 1 本選ぶ（`offsets` 区間で 3 点以上あるもの）
- `transform_to_xy_plane(rep)` で回転行列 `R` と `z_offset` を得る
- base/mask の `coords` を同じ `R/z_offset` で XY 平面へ整列
- Z ずれが大きい（非平面）場合は base をそのまま返す（`clip` / `isocontour` と同様の最小限方針）

### 2) マスクリング抽出（XY）

- 整列済み mask の各ポリラインについて
  - 端点が十分近ければ閉じる（固定しきい値 or 小さな定数）
  - 「先頭点=末尾点」になるものだけをリングとして採用
- 各リングは
  - `vertices2d: (N,2) float64`（closed）
  - `mins/maxs: (2,) float64`（AABB）
  を持つ

### 3) 点ごとの SDF（signed distance）と外向き法線（∇d 方向）

- 目的: base の各頂点 `p=(x,y)` について
  - `d(p)` = signed distance（inside negative / outside positive, even-odd）
  - `g(p)` = d が増える向きの単位ベクトル（外向き法線）
  を得る
- 実装:
  - isocontour の実装に寄せて「リング群を Numba 用に平坦化」する
    - `ring_vertices: (M,2)`, `ring_offsets`, `ring_mins/maxs`
  - `@njit(cache=True)` で `_evaluate_sdf_points(...) -> (d, gx, gy)` を実装
    - 全線分への最短距離（最近点 `q` も追跡）→ `dist = |p-q|`
    - even-odd（奇偶）で inside を決めて `d = +/-dist`
    - `g` は `sign(d) * (p-q)/dist`（dist=0 のときは 0 ベクトル）
      - hole を含むケースでも「inside が偶奇で決まる」前提ならこの定義で自然に動く

### 4) 変位の適用（吸着/反発）

- 基本式（SDF が理想的なら 1 回で狙いに寄る）:
  - `delta = bias - d(p)`（目標レベルまでの距離）
  - `p' = p + strength * w * delta * g(p)`
- 重み `w`:
  - `snap_band > 0` なら `abs(delta) > snap_band` の点は `w=0`（無変形）
  - `falloff > 0` なら `w = exp(-abs(delta)/falloff)`（距離減衰）
  - `falloff == 0` なら `w = 1`（バンド内フラット）
- 変位は XY のみ、Z は 0 のまま → 最後に `transform_back(..., R, z_offset)` で元の平面へ戻す
- 出力の `offsets` は base と同一（頂点数は変えない）

### 5) （後回し）伸び縮み抑制

- v1 ではまず「吸着の気持ちよさ」を優先し、長さ維持は入れない
- 必要になったら次のどれかで最小実装にする
  - `preserve_length: bool` を追加し、ポリラインごとに 2〜5 回だけ距離拘束（PBD）を回す
  - もしくは「運用で `E.relax` を後段に置く」を推奨し、組み込みは増やさない

## テスト（最小）

- 正常系:
  - `mask = G.polygon(n_sides=64, scale=50)` と、適当な base（数点の折れ線）を用意
  - `realize(E.sdf_attract(strength=1.0, snap_band=200, falloff=0)(base, mask))` が
    - `offsets` を保持しつつ
    - base から座標が変化している（`max(|Δ|) > eps`）
- 無効入力:
  - base が空なら空のまま
  - mask が空 or リングが取れないなら base をそのまま返す
- `activate=False`:
  - wrapper 仕様通り「入力がそのまま返る」ことを確認

## 実装手順（チェックリスト）

- [x] `src/grafix/core/effects/sdf_attract.py` を追加（effects/AGENTS.md を遵守）
- [x] `@effect(meta=..., n_inputs=2)` で登録
- [x] mask 基準で平面整列（util 使用）＋ planarity 最小チェック
- [x] mask リング抽出（閉曲線のみ採用）
- [x] Numba で `signed distance + outward normal` を点列に対して評価
- [x] base へ変位を適用（bias/snap_band/falloff/strength）
- [x] `src/grafix/core/builtins.py` にモジュール追加
- [x] `src/grafix/api/__init__.pyi` を生成結果で更新
- [x] `tests/core/effects/test_sdf_attract.py` を追加
- [x] `PYTHONPATH=src pytest -q`（対象テストでも可）

## 追加で確認したい点

- `strength` は **-1..+1 のスナップ係数**で良い？（mm 強度にしたいなら式を変える）
- `bias` は「目標の signed distance」として良い？（= オフセット境界へ吸着）
- v1 の `preserve_length` は無しで進めて、必要なら後で追加する方針で OK？
