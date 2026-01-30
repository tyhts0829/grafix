# 組み込み effect: `E.warp(base, mask)`（mode: lens / attract）

作成日: 2026-01-30

## 背景 / 目的

- 現状は `E.lens(base, lens_mask)` と `E.sdf_attract(base, mask)` が **近い用途（mask/SDF 由来の変形）**で分散している。
- Grafix の仕様として **multi-input effect はチェーン先頭にしか置けない**ため、同じ mask を使って「lens → attract（またはその逆）」の連続適用がしづらい。
- そこで 1 つの組み込み effect に統合し、`mode` トグルで挙動を切り替える。

## ゴール

- 新しい組み込み effect `E.warp(base, mask)` を追加する（multi-input, `n_inputs=2`）
- `mode` により次を切り替える
  - `mode="lens"`: 現行 `E.lens` 相当（kind/strength/profile/band/inside_only 等）
  - `mode="attract"`: 現行 `E.sdf_attract` 相当（strength/bias/snap_band/falloff 等）
- `show_mask` トグルで **mask を出力に含める**（位置が分かる）
- 破壊的変更 OK: `E.lens` と `E.sdf_attract` は削除し、互換ラッパーは作らない

## 非ゴール

- lens と attract を “同一呼び出しで連続適用” する複合モード（必要なら後で検討）
- 3D の非平面入力を無理に扱う（2D 前提を維持）

## 追加/変更するもの

- `src/grafix/core/effects/warp.py`（新規）
  - `@effect(meta=..., n_inputs=2)` で登録
  - effects 間依存禁止のため、`grafix.core.effects.util` のみ参照（`transform_to_xy_plane` / `transform_back`）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` を `warp` に更新（`lens` / `sdf_attract` を除去）
- 型スタブ更新
  - `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
- テスト
  - `tests/core/effects/test_warp.py`（新規）
  - 既存 `test_lens.py` / `test_sdf_attract.py` を置き換え（または削除）
- 削除
  - `src/grafix/core/effects/lens.py` を削除
  - `src/grafix/core/effects/sdf_attract.py` を削除

## API 案

### lens モード

```python
out = E.warp(
    mode="lens",
    kind="scale",          # "scale" | "rotate" | "shear" | "swirl"
    strength=1.0,
    profile="band",        # "band" | "ramp"
    band=20.0,
    inside_only=True,
    auto_center=True,
    pivot=(0.0, 0.0, 0.0),
    scale=1.4,
    angle=30.0,
    shear=(0.2, 0.0, 0.0),
    show_mask=True,
    keep_original=False,
)(base, mask)
```

### attract モード

```python
out = E.warp(
    mode="attract",
    strength=0.8,     # -1..+1（負で反発）
    bias=0.0,         # 目標の signed distance（0=境界）
    snap_band=30.0,   # |d-bias| がこれより大きい点は不変（0 なら無制限）
    falloff=12.0,     # 近いほど強い（0 ならフラット）
    show_mask=True,
    keep_original=False,
)(base, mask)
```

## meta（Parameter GUI）案

- 共通
  - `mode: choice`（`"lens" | "attract"`）
  - `strength: float`（ui: -1..+1 でも良いが、lens は 0..2 の需要もある → 最終決定）
  - `show_mask: bool`
  - `keep_original: bool`
- lens 専用（`mode=="lens"` のとき表示）
  - `kind: choice`（`"scale" | "rotate" | "shear" | "swirl"`）
  - `profile: choice`（`"band" | "ramp"`）
  - `band: float`（mm, ui: 0..200）
  - `inside_only: bool`
  - `auto_center: bool`
  - `pivot: vec3`（`auto_center=False` のときのみ）
  - `scale: float`（`kind=="scale"` のときのみ）
  - `angle: float`（`kind in {"rotate","swirl"}` のときのみ）
  - `shear: vec3`（`kind=="shear"` のときのみ）
- attract 専用（`mode=="attract"` のとき表示）
  - `bias: float`（mm, ui: -50..+50）
  - `snap_band: float`（mm, ui: 0..200）
  - `falloff: float`（mm, ui: 0..200）

## 実装方針（中身）

### 共通処理（mask 基準）

- `mask` から代表リングを 1 本選び、`transform_to_xy_plane(rep)` で平面整列（base/mask とも同じ姿勢へ）
- Z ずれが大きい（非平面）なら **base をそのまま返し、必要なら `show_mask` だけ付けて返す**
- mask から閉曲線リングだけ抽出（先頭=末尾、auto close threshold あり）
- even-odd（奇偶）で内外判定する前提を維持

### SDF 評価（Numba）

- `warp.py` 内にリングの pack と Numba 実装を持つ（effects 間依存を避ける）
- lens / attract の両方で必要なので、点列に対して以下を返す関数を用意する
  - `d(p)`（signed distance）
  - attract 用に、最近点 `q` も追跡し、外向き法線 `g` を作れるようにする（`g = sign(d)*(p-q)/|p-q|`）

### `mode="lens"`

- 現行 `E.lens` の実装を `warp.py` に移植（挙動維持）
- `band/profile/inside_only` でブレンド係数を作り、`kind` の座標変換へ lerp

### `mode="attract"`

- `d, g` からディスプレイスを計算
  - `delta = bias - d(p)`
  - `w`:
    - `snap_band > 0` なら `abs(delta) > snap_band` を `w=0`
    - `falloff > 0` なら `w = exp(-abs(delta)/falloff)`、`falloff==0` なら `w=1`
  - `p' = p + strength * w * delta * g`

### 出力合成

- 変形後 `out` をベースに、トグルで順に append する
  - `keep_original=True` なら `base` を追加
  - `show_mask=True` なら `mask` を追加
- 連結は `concat_realized_geometries(...)` を使用

## テスト（最小）

- 共通
  - `E.warp()(a)` が `TypeError`（arity）
  - `show_mask=True` が no-op ケースでも mask を含む
- lens モード
  - 旧 `test_lens.py` 相当（inside が動き outside が動かない、keep_original など）
- attract モード
  - mask を大きい多角形（半径がほぼ既知）にし、x 軸上の 2 点（内側/外側）を含む線を用意
  - `mode="attract"` で **内側点は外向きへ、外側点は内向きへ** 動くことを確認（x が増える/減る）

## 実装手順（チェックリスト）

- [ ] `src/grafix/core/effects/warp.py` を追加
- [ ] `mode` 切替 + `ui_visible` を実装
- [ ] 共通: 平面整列 / リング抽出 / SDF（+最近点）評価
- [ ] lens: 現行 `lens` のロジックを移植
- [ ] attract: 現行 `sdf_attract` のロジックを移植
- [ ] `show_mask` / `keep_original` の出力合成を統一
- [ ] `src/grafix/core/builtins.py` を更新（`warp` を追加、`lens` / `sdf_attract` を除去）
- [ ] 旧モジュール/テストを削除（互換ラッパー無し）
- [ ] `tests/core/effects/test_warp.py` を追加
- [ ] `PYTHONPATH=src python -m grafix stub`
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_warp.py`

## 追加で決めること（統合時の微調整）

- `strength` の UI レンジ（lens は 0..2、attract は -1..+1）をどう折り合うか
- `show_mask` と `keep_original` の出力順序（デバッグ時に見やすい順）

