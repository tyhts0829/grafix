# 組み込み effect: SDF等高線彫刻（Isocontour Engraving）（`E.isocontour`）実装計画

作成日: 2026-01-29

対象アイデア: `docs/plan/sdf_stripes_effect_plan_2026-01-29.md` の「アイデア A」

## ゴール

- 閉曲線群（外周＋穴）から SDF を作り、複数レベルの等高線を **線（ポリライン列）として出力**する組み込み effect を追加する
- 出力はペンプロット向けに「線密度がコントロールしやすい」こと（`spacing/max_dist/mode` を軸にする）
- 入力が 3D でも「ほぼ平面」であれば XY へ整列して処理し、元の姿勢に戻す

## 非ゴール（今回やらない）

- 厳密なメディアルアクシス、shadow ray-march、smooth union bridges 等（別アイデア）
- 入力が大きく非平面のときの補正（その場合は空 or 入力そのまま、のどちらかに寄せる）

## API 案（確定したい）

```python
lines = E.isocontour(
    activate=True,
    spacing=2.0,
    phase=0.0,
    max_dist=30.0,
    mode="inside",        # "inside" | "outside" | "both"
    grid_pitch=0.5,
    gamma=1.0,
    level_step=1,         # n 本に 1 本（1=全部、2=半分、3=1/3...）
    auto_close_threshold=1e-3,
    keep_original=False,
)(mask_geom)
```

## 追加/変更するもの

- `src/grafix/core/effects/isocontour.py`（新規）
- `src/grafix/core/builtins.py`（`_BUILTIN_EFFECT_MODULES` へ追加）
- （必要なら）`src/grafix/api/__init__.pyi`（公開 API）
- `tests/core/effects/test_isocontour.py`（最小）

## パラメータ / meta 方針

- UI でまず触りたいのは `spacing / phase / max_dist / mode / grid_pitch` の 5 つ
- `gamma` は “距離の見え方” を一発で変えられるので UI に出す
- `level_step` は v1 から入れる（決定論的に線密度を落とせる）

## 実装方針（段取り）

### 1) 入力整形

- `inputs` が空なら空ジオメトリ
- `inputs[0]` が空なら空ジオメトリ
- `activate=False` の挙動は既存 effect と同様に入力を返す

### 2) 平面整列（XY）

- 代表リング（3 点以上）を 1 本選び、`transform_to_xy_plane` で回転行列 `R` と `z_offset` を得る
- 入力全体を `R/z_offset` で整列し、Z ずれが大きい場合は処理を打ち切る（v1 は保守的で OK）

### 3) リング抽出（閉曲線のみ）

- `auto_close_threshold` 以内なら自動で閉じる
- 閉じていないポリラインは無視
- inside 判定は even-odd（穴/外周の向きは見ない）

### 4) SDF グリッド設計

- bbox を取り、`max_dist` と `grid_pitch` を考慮して評価領域を拡張する（等高線が途切れにくい余白）
- グリッドは `grid_pitch` 間隔の等間隔サンプル（float64 で評価→出力は float32）

### 5) SDF 評価

- 各グリッド点で
  - `distance = min(distance_to_segment)`（全境界線分の最短距離）
  - `inside = even_odd(point_in_polygon)`（複数リングの parity）
  - `sdf = -distance if inside else +distance`
- まずは `metaball.py` と同程度の手法（Numba + bbox 早期判定）に寄せる

### 6) 距離の変換（表情づけ）

- `gamma` による非線形: `sdf' = sign(sdf) * |sdf|**gamma`（候補）
- v1 は `smooth_k` なしで開始する（先に “等高線の束が出る” を最短で作る）

### 7) 等高線レベル生成

- `spacing/phase/max_dist/mode` からレベル配列を作る（inside/outside/both）
- `level_step > 1` のとき、`n 本に 1 本` でレベルを間引いて密度を落とす

### 8) 等高線抽出 → ポリライン化

- Marching Squares で線分集合を作る
- 線分を stitch してループ（または開曲線）へまとめる
- `min_points`（最低点数）等の簡単なクリーンアップを入れるかは要検討

### 9) 3D へ戻す / 出力合成

- 抽出した 2D 線を 3D(z=0) 化し、`transform_back` で元の姿勢へ戻す
- `keep_original=True` なら入力も出力に含める（連結するだけの素朴な合成で OK）

## テスト（最小）

- `G.polygon(...)` など単純な閉曲線で非空の出力が得られる
- 空入力で空
- `activate=False` で入力がそのまま返る
- `mode` の切替で出力が極端に壊れない（inside/outside/both の smoke）

## 実装手順（チェックリスト）

- [x] effect 名/シグネチャを決める（`isocontour`）
- [x] `src/grafix/core/effects/isocontour.py` を追加
- [x] meta を定義し `@effect(meta=..., n_inputs=1)` で登録
- [x] 平面整列 → リング抽出 → SDF 評価（v1）
- [x] レベル生成（mode/spacing/phase/max_dist）
- [x] Marching Squares → stitch → RealizedGeometry 化
- [x] `keep_original` 合成
- [x] `src/grafix/core/builtins.py` に追加
- [ ] （必要なら）`src/grafix/api/__init__.pyi` 更新
- [x] `tests/core/effects/test_isocontour.py` 追加
- [x] `PYTHONPATH=src pytest -q`（対象テストで可）

## 決定事項

- effect 名: `isocontour`（接頭辞なし）
- レベル間引き: `level_step`（n 本に 1 本）
- v1 方針: `smooth_k` なし
