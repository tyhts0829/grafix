# `displace` の gradient を「円形/楕円（radial）」マスクへ拡張する計画

作成日: 2026-01-27

## 背景 / 問題

- 以前の「center（軸ごとの三角窓）」は、x/y/z を独立に窓化していたため、ノイズが乗る領域が **矩形（箱）** っぽく見える。
- 期待する見た目は「中央からの距離」で落ちる **円形（2D）/球形（3D）** のスポット。

## ゴール

- bbox 正規化座標の **中心からの距離** で勾配係数を作り、ノイズが乗る領域を円形（楕円）にできるようにする。
- `amplitude_gradient` / `frequency_gradient` の **符号で反転（中心が強い ↔ 外側が強い）** できる。
- 既定挙動は現状維持（`gradient_profile` の default は従来の `"linear"`）。

## 方針（改）

### 追加パラメータ

- `gradient_profile: choice("linear", "radial")`（default `"linear"`）
  - `"linear"`: 現状の `raw = 1 + g * (t - c)`（片側が強くなる）
  - `"radial"`: 中心からの距離で変化（円形/楕円）
- `gradient_radius: vec3`（default `(0.5, 0.5, 0.5)`）
  - bbox 正規化座標での「半径」（各軸別）。
  - `x=y` にすると 2D では円形、`x!=y` で楕円、`z` も使うと 3D では楕円体になる。

※ `gradient_radius` は `"radial"` のときだけ使い、`"linear"` では無視する。

### radial の式（仕様案）

`tx,ty,tz` は bbox 正規化座標（現状どおり）。`c=(0.5+gradient_center_offset)`。

1. 正規化距離（楕円体の半径 1 が境界の目安）:
   - `dx = (tx - cx) / rx`
   - `dy = (ty - cy) / ry`
   - `dz = (tz - cz) / rz`
   - `d = sqrt(dx*dx + dy*dy + dz*dz)`
2. 勾配係数（軸ごとに符号を保持して反転可能）:
   - 振幅: `raw_a_i = 1 - g_a_i * d`（`g_a_i` は `amplitude_gradient` の各成分）
   - 周波数: `raw_f_i = 1 - g_f_i * d`（`g_f_i` は `frequency_gradient` の各成分）
3. 以降は従来と同じ整形:
   - `raw = max(0, raw)`
   - `factor = min_gradient_factor + (1 - min_gradient_factor) * raw`
   - `factor = min(factor, max_gradient_factor)`

直感（`min=0` のとき）:

- `g=+1` なら `d=1` で 0（中心スポット）
- `g=-1` なら外側ほど増える（ビネット反転）

### UI レンジ案

- `amplitude_gradient` / `frequency_gradient` の UI レンジは **据え置き（-4..4）**でよい。
  - `"radial"` では `g=1` が「半径 1 で 0」なので調整もしやすい。
- `gradient_radius` は UI を `0.05..1.0` くらいにすると触りやすい（default 0.5）。
  - 実装側は `rx,ry,rz` が極小の場合だけ最小値へ丸めてゼロ除算を避ける（最小限のクランプ）。

## 変更箇所（予定）

- `src/grafix/core/effects/displace.py`
  - `displace_meta` に `gradient_profile` と `gradient_radius` を追加
  - `displace()` に同引数を追加し、docstring に `"radial"` の意味を書き足す
  - `@njit` へは `str` を渡さず、`gradient_profile_mode: int`（0=linear, 1=radial）を渡す
  - `"radial"` では `d` を 1 回計算して、振幅/周波数の係数へ流用する
- `tests/core/effects/test_displace.py`
  - `"radial"` の形状が「矩形」にならないことを点で検証する（後述）
- `src/grafix/api/__init__.pyi`
  - `python -m grafix stub` で自動更新（手編集しない）

## テスト方針（最小）

`spatial_freq=(0,0,0)` にしてノイズを全点で一定にし、係数差だけで判定する。

- 形状テスト（円形の証拠）:
  - bbox が正方形になる点集合を用意（例: (0,0), (10,10) を含む）
  - `"radial"`, `gradient_radius=(0.5,0.5,1.0)`、`amplitude_gradient=(1,0,0)`、`min=0`
  - 同じ x 偏りでも y が大きい点（角寄り）の方が `d` が大きく、変位が小さく（or 0 で）なることを確認
    - 例: (9,5) は動くが (9,9) は動かない、のように比較できる
- 反転テスト:
  - `amplitude_gradient` の符号を反転して、中心より外側の方が係数が大きい方向に変わることを確認
- 互換テスト:
  - 既定（省略）と `gradient_profile="linear"` が一致すること

## 実装手順（チェックリスト）

- [x] 1. `displace_meta` に `gradient_profile` / `gradient_radius` を追加
- [x] 2. `displace()` のシグネチャと docstring を更新
- [x] 3. `gradient_profile_mode` を int 化して `@njit` 側へ渡す
- [x] 4. `"radial"` の距離 `d` を追加し、係数計算へ接続
- [x] 5. テスト追加（形状 / 反転 / 互換）
- [x] 6. スタブ再生成と同期テスト
  - [x] `PYTHONPATH=src python -m grafix stub`
  - [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] 7. 対象テスト実行
  - [x] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`

## 要確認（あなたに決めてほしい点）

1. `gradient_profile` の選択肢名は `"radial"` で OK？（`"circle"` の方が良い等ある？）；OK
2. `gradient_radius` を「bbox 正規化半径（0.5 で辺に接する）」として良い？；OK
3. `"radial"` の距離計算は 3D（x,y,z）で良い？（2D 作業が主なら z を無視するモードが欲しい？）；OK。z無視モードいらない
