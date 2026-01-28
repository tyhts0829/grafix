# 新規 effect: Möbius 変換 + Power diagram で「泡っぽい境界線ネットワーク」を生成（仮: E.mobius_power_network）

作成日: 2026-01-28

## ゴール

- `new_effect.md` にある手順のうち、**2) power diagram → 3) Möbius 変換 → 4) ポリライン化**を Grafix の **組み込み effect** として実装する
- 入力の「円群（複数の閉曲線）」から、重複のない **境界線ネットワーク**（黒い曲線）を生成して返す
- 外側の閉曲線を「単位円盤」に正規化した上で、円盤自己同型の Möbius 変換
  - `f(z) = e^{iθ} (z - a) / (1 - conj(a) z)`（|a| < 1）
  - を境界点列へ適用し、直線境界を円弧っぽく歪ませる

## スコープ

- やる:
  - 入力（円群）→ power diagram（Laguerre）→ 境界線 → Möbius 変換 → ポリライン出力
  - プロッタ向けの「密化（サンプリング間隔）」パラメータ提供
- やらない（別タスク）:
  - `new_effect.md` の 1) にある **円のパッキング（Apollonian/Soddy）を自動生成**（円群は外部で用意する前提）

## 追加/変更するもの

- `src/grafix/core/effects/mobius_power_network.py`（新規）
  - `@effect(meta=..., n_inputs=2)`（effects/AGENTS.md の「effects 間依存禁止」を遵守し、`.util` だけ利用）
- `src/grafix/core/builtins.py`
  - `_BUILTIN_EFFECT_MODULES` に追加して自動登録対象にする
- `src/grafix/api/__init__.pyi`
  - `grafix.devtools.generate_stub` の生成結果で更新（テスト `tests/stubs/test_api_stub_sync.py` を通す）
- `tests/core/effects/test_mobius_power_network.py`（新規・最小）

## API 案（仮）

外側（円盤）と、内部の円群（複数リング）を 2 入力で渡す。

```python
net = E.mobius_power_network(
    a=(0.18, 0.08, 0.0),
    theta=0.0,
    sample_pitch=0.5,
    output="network",  # or "both"
)(circles_geom, outer_disk_geom)
```

### meta（Parameter GUI）案

- `a: vec3`（ディスク内パラメータ。z は未使用）
  - UI range: -0.95..0.95（|a|<1 をユーザー側で作りやすくする）
- `theta: float`（回転角 [deg]）
  - UI range: -180..180
- `sample_pitch: float`（出力ポリラインの点間隔 [mm] 目安）
  - UI range: 0.05..5.0
- `output: choice`（出力内容）
  - `"network"`: 境界線ネットワークのみ
  - `"both"`: ネットワーク + 入力円群（同じ Möbius 変換を適用して追加）

## 実装方針（中身）

### 1) 入力の取り決め（2 input）

- `inputs[0]`: 円群（閉曲線の集合 = offsets で複数リングを持つ想定）
- `inputs[1]`: 外側ディスク（閉曲線 1 本を想定。平面推定と正規化に使う）
- どちらも「ほぼ同一平面上」にある前提（非平面は最小限のチェックで素通し/空返し）

### 2) 平面整列（既存 util を利用）

- `inputs[1]` の代表リングから `util.transform_to_xy_plane` で回転 `R` と `z_offset` を取得
- `inputs[0]`/`inputs[1]` の全頂点へ同じ整列を適用して 2D 化（z≈0 を確認）
- 出力は最後に `util.transform_back` で元の平面へ戻す

### 3) 円パラメータ抽出（center, radius）

- 各リング `P = {(x_k, y_k)}` に対して
  - `center = mean(P)`（等角サンプリングの円なら中心に一致）
  - `radius = mean(||P - center||)`（簡易近似）
- 外側ディスクも同様に `(outer_center, outer_radius)` を推定（正規化に使用）

※「完璧な円」前提にして簡潔に（過度に防御しない）。入力が歪むと結果も歪む方針。

### 4) Power diagram（Laguerre）のセル多角形を作る

円 i（中心 `c_i`, 半径 `r_i`）に対して power distance:

- `π_i(x) = ||x - c_i||^2 - r_i^2`

セル i は `π_i(x) <= π_j(x)` を全 j で満たす領域（凸多角形）。
2 円の境界は直線になり、半平面制約:

- `(c_j - c_i) · x <= (||c_j||^2 - r_j^2 - (||c_i||^2 - r_i^2)) / 2`

実装は「大きめの初期ポリゴン（outer の bbox）を半平面で順にクリップ」。
最後に outer_disk で `intersection` してディスク内に収める。

クリップ実装は以下のどちらか（実装時に片方へ寄せる）:

- A) Shapely の Polygon を「半平面を表す巨大四角形」と `intersection`（split より単純）
- B) 2D の Sutherland–Hodgman を自前実装（convex 前提で簡潔・高速）

### 5) 境界線ネットワークの抽出（重複除去）

- `cells` の `boundary` を集めて
  - `unary_union` で重複線分を溶かす
  - `linemerge` で連結してネットワーク化
- 得られた (Multi)LineString を「ポリライン列」に変換する

### 6) 密化（サンプリング）→ Möbius 変換

- 各 LineString を長さ `L` として、`sample_pitch` から点数 `n = ceil(L/pitch) + 1` を決める
- `interpolate`（等距離サンプル）で点列化 → 外側ディスクで正規化して Möbius:
  - `z = ((x-cx)/R) + i((y-cy)/R)`
  - `w = e^{iθ} (z - a) / (1 - conj(a) z)`
  - `x' = cx + R * Re(w)`, `y' = cy + R * Im(w)`
- `|a| >= 1` は分母が危険なので、ここだけは **入力をそのまま返す/空を返す**のどちらかに統一する（実装時に決める）

### 7) 出力 RealizedGeometry 化

- `output="network"`: ネットワークのみを `RealizedGeometry(coords, offsets)` に詰める
- `output="both"`: 入力円群も同じ Möbius を適用して追加（リングはそのまま点列として扱う）
- 2D（z=0）の点列を `transform_back` で元平面へ戻して完成

## テスト（最小）

- 正常系:
  - 3〜7 本の「円っぽい閉曲線」（例: 32-gon）と outer を作って `mobius_power_network([circles, outer], ...)` が **非空**を返す
- 無効入力:
  - `inputs` が不足/空のときは empty か pass-through（方針を実装時に統一してテスト）
- パラメータ:
  - `a=(0,0,0), theta=0` でクラッシュしない（identity 近い）

## 実装手順（チェックリスト）

- [ ] effect 名と I/O（`n_inputs=2` / `output` 仕様）を確定
- [ ] `src/grafix/core/effects/mobius_power_network.py` 追加（module docstring + `@effect(meta=...)`）
- [ ] 平面整列（util） + 円パラメータ抽出
- [ ] power diagram のセル生成（半平面クリップ）
- [ ] 境界線ネットワーク化（unary_union/linemerge）
- [ ] 密化 + Möbius 変換 + RealizedGeometry 詰め
- [ ] `src/grafix/core/builtins.py` へ登録追加
- [ ] `src/grafix/api/__init__.pyi` を generate_stub の結果で更新
- [ ] `tests/core/effects/test_mobius_power_network.py` 追加
- [ ] `PYTHONPATH=src pytest -q`（対象テスト中心で可）

## 追加で確認したい点（決めたい）

- effect 名は `mobius_power_network` で良い？（短くするなら `mobius_power` など）
- 2 input にする？それとも outer をパラメータ（center/radius）にして 1 input にする？
- `|a| >= 1` の扱い: no-op（入力 concat 返し）にするか、empty を返すか
- `output="both"` のとき「円の再構成（円として復元）」まで要る？（まずは点列のまま追加で十分？）

