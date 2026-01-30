# 組み込み effect: SDF レンズ（E.sdf_lens）

作成日: 2026-01-30  
元アイデア: `docs/plan/sdf_stripes_effect_plan_2026-01-29.md` の「アイデア I」

## ゴール

- `E.sdf_lens(base, lens)` として使える **組み込み effect** を追加する
  - 入力: `inputs[0]` = 任意の線（開/閉ポリライン列）, `inputs[1]` = レンズ形状（閉曲線群。複数リング可）
  - 出力: `inputs[0]` を **レンズ領域（SDF 由来）で局所変形**したポリライン列（頂点数/offsets は維持）
- **境界で連続**（`d=0` で変形量 0）で、クリップ境界のような不連続を出さない
- 2D 前提（任意平面は `transform_to_xy_plane` で整列して処理）で、非平面入力は無理に扱わない

## 追加/変更するもの

- `src/grafix/core/effects/sdf_lens.py`（新規）
  - `@effect(meta=..., n_inputs=2)` で登録
  - effects 間依存禁止のため、`grafix.core.effects.util`（`transform_to_xy_plane` / `transform_back`）のみ参照
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に追加して自動登録対象にする
- 型スタブ更新
  - `src/grafix/devtools/generate_stub.py` の生成結果で `src/grafix/api/__init__.pyi` を更新
- `tests/core/effects/test_sdf_lens.py`（新規・最小）

## API 案（MVP）

```python
out = E.sdf_lens(
    activate=True,
    kind="scale",          # "scale" | "rotate" | "shear" | "swirl"
    strength=1.0,          # 0..1（必要なら 2 以上も許可）
    profile="band",        # "band"（境界付近だけ）| "ramp"（内側へ向かって増える）
    band=20.0,             # mm（0 でハード）
    inside_only=True,      # True: d<0 のみ / False: d の符号を無視して両側
    auto_center=True,      # True: lens bbox center / False: pivot
    pivot=(0.0, 0.0, 0.0),
    scale=1.4,             # kind=="scale" のときのみ使用
    angle=30.0,            # kind in {"rotate","swirl"} のとき使用 [deg]
    shear=(0.2, 0.0, 0.0), # kind=="shear" のとき使用（x,y を使用、z は無視）
    keep_original=False,
)(base_geom, lens_geom)
```

## meta（Parameter GUI）案

- `kind: choice`（`"scale" | "rotate" | "shear" | "swirl"`）
- `strength: float`（ui: 0..1 or 0..2）
- `profile: choice`（`"band" | "ramp"`）
- `band: float`（mm, ui: 0..200）
- `inside_only: bool`
- `auto_center: bool`
- `pivot: vec3`（ui: -100..+100, `auto_center=False` のときのみ表示）
- `scale: float`（ui: 0.5..3.0, `kind=="scale"` のときのみ表示）
- `angle: float`（deg, ui: -180..+180, `kind in {"rotate","swirl"}` のときのみ表示）
- `shear: vec3`（ui: -1..+1, `kind=="shear"` のときのみ表示）
- `keep_original: bool`

## 実装方針（中身）

### 1) 入力と平面整列（lens 基準）

- `inputs[1]`（lens）から「代表リング」を 1 本選ぶ（`offsets` 区間で 3 点以上あるもの）
- `transform_to_xy_plane(rep)` で回転行列 `R` と `z_offset` を得る
- base/lens の `coords` を同じ `R/z_offset` で XY 平面へ整列
- Z ずれが大きい（非平面）場合は base をそのまま返す（`clip` / `isocontour` と同様の最小限方針）

### 2) lens リング抽出（XY）

- 整列済み lens の各ポリラインについて
  - 端点が近ければ閉じる（固定しきい値 or `auto_close_threshold` をローカル定数で持つ）
  - 「先頭点=末尾点」になるものだけをリングとして採用（開曲線は捨てる）
- リング群は even-odd（奇偶）で 1 つの領域として扱う（外周＋穴／ネストも OK）

### 3) base 各点の SDF 評価（Numba）

- 目的: base の各頂点 `p=(x,y)` について `d(p)`（signed distance: inside negative / outside positive）を得る
- 実装:
  - `isocontour` の実装に寄せて「リング群を Numba 用に平坦化」
    - `ring_vertices: (M,2)`, `ring_offsets`, `ring_mins/maxs`
  - `@njit(cache=True)` で `_evaluate_sdf_points(...) -> d` を実装
    - 全線分への最短距離（ユークリッド）
    - even-odd（奇偶）で inside を決めて `d = +/-dist`
    - `x < x_int` の厳密不等号で「境界上は outside 扱い」へ寄せる（`isocontour` と合わせる）

### 4) 変形の適用（境界で連続）

- 重みの考え方:
  - 基本は「`d=0`（境界）で変形量 0」になるように、**ブレンド係数を 0 に落とす**
  - `band` は距離の正規化に使う（`band=0` は hard）
- 正規化距離 `t`:
  - `inside_only=True`:
    - `d >= 0` は `w=0`
    - `d < 0` のみ `t = clamp((-d)/band, 0..1)`（`band=0` なら `t=1` 固定）
  - `inside_only=False`:
    - `t = clamp(abs(d)/band, 0..1)`（`band=0` なら `t=1` 固定）
- `profile`:
  - `"ramp"`: `w = smoothstep(t)`（境界→内側へ単調増加）
  - `"band"`: `w = 4 * smoothstep(t) * (1 - smoothstep(t))`（境界付近だけ・中心は弱い）
    - 0..1 の範囲に収まるように 4 倍して正規化（最大が 1）
- 変形の適用（2D）:
  - `p2` に対して `p2_t = T(p2)` を計算し、`p2' = lerp(p2, p2_t, strength*w)` を出力
  - Z は 0 のまま（XY のみを動かす）→ 最後に `transform_back(..., R, z_offset)` で元の平面へ戻す

### 5) 変換 `T`（kind）

- 共通: `center c` を定義し、`v = p2 - c` で局所化してから変形する
  - `auto_center=True`: lens リング群の AABB center（`(mins+maxs)/2`）
  - `auto_center=False`: `pivot`（XY のみ使用）
- `kind="scale"`:
  - `p2_t = c + scale * v`（uniform）
- `kind="rotate"`:
  - `p2_t = c + R(angle_deg) @ v`
- `kind="shear"`:
  - `p2_t = c + [[1, shx],[shy, 1]] @ v`（`shear=(shx,shy,_)`）
- `kind="swirl"`:
  - まず `r = ||v||` とし、`angle_eff = angle_deg * (r / r_ref)`（`r_ref` は lens bbox の半径相当）
  - `p2_t = c + R(angle_eff) @ v`
  - （ポイント）この `swirl` 自体は `w` ブレンドが 0 なので境界で連続になる

## テスト（最小）

- `test_sdf_lens_requires_two_inputs`:
  - `E.sdf_lens()(a)` が `TypeError`（arity の既存仕様に合わせる）
- `test_sdf_lens_noop_when_lens_has_no_valid_rings`:
  - lens が開曲線しか持たない → base が不変（`coords/offsets` 一致）
- `test_sdf_lens_deforms_points_inside_and_keeps_outside`:
  - base に「レンズ内の点」と「レンズ外の点」を含む折れ線を用意
  - `kind="scale"` で、内側点は動く／外側点はほぼ不変
- `test_sdf_lens_preserves_offsets`:
  - 出力 `offsets` が base と同一
- `test_sdf_lens_restores_pose_from_rotated_plane`（余力があれば）:
  - base/lens を同一平面で回転＋Z オフセット → 出力も同じ平面に戻る
- `test_sdf_lens_keep_original_appends`（余力があれば）:
  - `keep_original=True` で `coords/offsets` が増える

## 実装手順（チェックリスト）

- [x] `src/grafix/core/effects/sdf_lens.py` を追加（effects/AGENTS.md を遵守）
- [x] `@effect(meta=..., n_inputs=2)` で登録（`ui_visible` で kind ごとに表示制御）
- [x] lens 基準で平面整列（util 使用）＋ planarity 最小チェック
- [x] lens リング抽出（閉曲線のみ採用）
- [x] Numba で `signed distance` を点列に対して評価
- [x] `profile/band/inside_only` に従って weight を計算し、`kind` で変形を適用
- [x] `src/grafix/core/builtins.py` にモジュール追加
- [x] `src/grafix/api/__init__.pyi` を生成結果で更新
- [x] `tests/core/effects/test_sdf_lens.py` を追加
- [x] `PYTHONPATH=src pytest -q`（対象テストでも可）

## 決定（実装済み）

- `profile` デフォルトは `"band"`
- `inside_only=False` は `|d|` ベースの距離で評価
- `kind` は v1 で 4 種（scale/rotate/shear/swirl）すべて入れる
- `auto_center=True` の中心は lens AABB center を採用

## 追加で確認したい点

- `profile` のデフォルトは `"band"`（境界付近だけ）で良い？それとも `"ramp"`（内側で強い）が良い？
- `inside_only=False` の挙動は「d の絶対値で band を作り、レンズ外側にも同様に効く」で良い？
- v1 で `kind` は 4 種（scale/rotate/shear/swirl）全部入れる？まず 2 種（例: scale + swirl）に絞る？
- `auto_center=True` の center は AABB center で十分？（重心が欲しい？）
