# 組み込み effect: `E.conformal_map(base)`（共形写像で任意 geometry を曲げる）実装計画（2026-02-19）

作成日: 2026-02-19  
ステータス: 提案（未実装）

## 背景 / 問題

- 現状 `E.warp(base, mask)` は **マスク距離場（SDF）** による **局所変形**で、角度保存（共形性）は保証されない。
- `G.laplace_field_grid(...)` は “共形写像ベースの直交格子” を生成できるが、**任意の geometry（テキストや任意線）を同じ写像で曲げる**手段がない。

## 目的（ゴール）

- 新しい組み込み effect `E.conformal_map(base)` を追加し、入力 geometry の XY を複素数として **解析写像 `z=f(w)`** で変形できるようにする。
- `preset` により少なくとも次を提供する（`G.laplace_field_grid` と同系統の作風に揃える）。
  - `cylinder_uniform`（逆写像: `z^2-(w)z+a^2=0` の外部解選択）
  - `mobius`（`z=(αw+β)/(γw+δ)`）
  - `exp`（`z=exp(k w)`）
- NaN/Inf が出た点・特異点付近は **線を分割して落とす**（全体がクラッシュしない）。

## 非目的（やらない）

- 数値ラプラスソルバ（任意境界、複数障害物など）
- 3D の一般曲面への共形写像（XY 平面の 2D 変換に限定）
- `warp` の置換（用途が異なるため併存）

## 外部仕様（API）

### 使い方

```python
out = E.conformal_map(preset="mobius", ...)(base)
```

### 引数案（最小）

- 共通
  - `preset: str`（`"cylinder_uniform" | "mobius" | "exp"`）
  - `drop_nonfinite: bool = True`（非有限点を落として線分割）
  - `clip: bool = False` + `clip_xmin/xmax/ymin/ymax`（任意。暴走抑制の簡易 AABB クリップ）
- `cylinder_uniform`
  - `a: float`（0 以上。0 のときは退化して `z=w/U`）
  - `U: float`（0 のときは写像が定義できないため **passthrough（入力をそのまま返す）**）
  - `gap: float`（0 以上。`abs(z) < a*(1+gap)` を落とす）
  - `branch: choice = "outer"`（外部解=|z|が大きい方。将来拡張用、初期は outer 固定でも可）
- `mobius`
  - `alpha_re/im, beta_re/im, gamma_re/im, delta_re/im`（complex を UI に載せるため re/im 分割）
  - `det≈0` は ValueError か passthrough のどちらか（初期は ValueError 推奨）
- `exp`
  - `k_re/im`

## アルゴリズム（実装方針）

1. `base: (coords, offsets)` から各 polyline を抽出
2. 点列を `w = x + i y` として複素配列に変換
3. `preset` ごとの写像 `z=f(w)` を適用
4. `mask = isfinite(z)` を作り、`drop_nonfinite=True` の場合は `mask` の連続区間で線を分割
   - `cylinder_uniform` は追加で `abs(z) >= a*(1+gap)` を `mask` に AND
5. （任意）AABB クリップを同様に “点を落として分割” で適用（交点補間はしない）
6. 出力点列は `(x',y',z')` で返す
   - `x',y'` は `z` の実部/虚部
   - `z'` は **入力の z を維持**（2D 変換なので z は触らない）
7. 分割後の polyline リストを `(coords, offsets)` に pack して返す

## 追加/変更するファイル（予定）

- `src/grafix/core/effects/conformal_map.py`（新規）
- `src/grafix/core/builtins.py`（`_BUILTIN_EFFECT_MODULES` に追加）
- `tests/core/effects/test_conformal_map.py`（新規）
- `src/grafix/api/__init__.pyi`（`PYTHONPATH=src python -m grafix stub` で更新）

## テスト方針（最小）

- `preset` 3 種が例外なく動く（`base=G.grid(scale=...)` など簡単な入力で）
- 出力に NaN/Inf が含まれない（`drop_nonfinite=True`）
- `cylinder_uniform` + `gap>0` で `min(hypot(x,y)) >= a*(1+gap)` を満たす
- `a=0` / `U=0` で落ちない（`U=0` は passthrough を確認）

## 実装タスク（チェックリスト）

- [ ] `src/grafix/core/effects/conformal_map.py` を追加（meta + ui_visible）
- [ ] `preset` 3 種の写像を実装（cylinder_uniform/mobius/exp）
- [ ] `split_by_mask`（非有限/半径/clip）で線分割して落とす
- [ ] `src/grafix/core/builtins.py` に effect module を登録
- [ ] `tests/core/effects/test_conformal_map.py` を追加
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_conformal_map.py`
- [ ] `PYTHONPATH=src python -m grafix stub`

## 受け入れ条件（DoD）

- [ ] `E.conformal_map(...)(base)` が動く（3 preset）
- [ ] 非有限点でクラッシュせず、線が分割されて出力される
- [ ] `cylinder_uniform` で `gap` により内側が落ちる
- [ ] `a=0` / `U=0` を入力しても落ちない（仕様通りのフォールバック）
