# `displace` の gradient を「中央ピーク（center）」へ拡張する計画（案A）

作成日: 2026-01-26

## 背景 / 問題

- `src/grafix/core/effects/displace.py` の gradient は bbox 正規化座標 `t∈[0,1]` に対する一次（単調）で、現状は「片側を強く/弱く」はできるが「中央だけ強くして両端を弱く」は表現できない。
- 要望: bbox の **x 中央のみ / y 中央のみ / z 中央のみ** を、3 成分で独立に調整したい（中央に“窓”を作りたい）。

## ゴール

- `displace` に **新規パラメータを最小 1 つだけ**追加し、既存の `amplitude_gradient` / `frequency_gradient` を再利用して「中央ピーク」を作れるようにする。
- 既定挙動は現状維持（破壊的変更を避ける）：新パラメータの default は現行と同じ挙動になる。
- 実装はシンプルに保ち、互換ラッパー/シムは作らない。

## 方針（案A）

### 追加パラメータ

- `gradient_profile: choice("linear", "center")`（default `"linear"`）
  - `"linear"`: 現状の計算式（そのまま）
  - `"center"`: 中央ピーク（左右対称）な計算式

### 中央ピーク（center）仕様案

以下は 1 軸（x/y/z 共通）の記述。`t` は bbox 正規化座標、`c` は中心（`0.5 + gradient_center_offset`）。

1. 中心からの距離（左右対称）を作る:
   - `d = 2 * abs(t - c)`（中心=0、端=1 の目安）
2. 既存の勾配係数 `g`（`amplitude_gradient` or `frequency_gradient` の各成分）で増減する:
   - `raw = 1 - g * d`
3. 既存の下限・上限と同じ流れで整形（従来と同じ）:
   - `raw = max(0, raw)`
   - `factor = min_gradient_factor + (1 - min_gradient_factor) * raw`
   - `factor = min(factor, max_gradient_factor)`

直感的な例（`c=0.5`、`min=0.0` のとき）:

- `g=+1`: 中心 `raw=1`、端 `raw=0`（中心だけ残る）
- `g=+0.5`: 中心 `raw=1`、端 `raw=0.5`（中心が相対的に強い）
- `g=-1`: 中心 `raw=1`、端 `raw=2`（端が強い）

この仕様だと `g` の符号で「中心ピーク / 端ピーク」を反転できる。なお `raw>1` が出るのは主に `g<0` のときで、その場合 `max_gradient_factor` が効く。

## 変更箇所（予定）

- `src/grafix/core/effects/displace.py`
  - `displace_meta` に `gradient_profile` を追加
  - `displace(..., gradient_profile="linear")` を追加し、docstring を更新
  - `@njit` 関数へは `str` を渡しづらいので、`gradient_profile` は **int mode（0=linear, 1=center）** に変換して渡す
  - 勾配適用部（`fx_raw/fy_raw/fz_raw` と `freq_fx_raw/...`）を mode で分岐
- `tests/core/effects/test_displace.py`
  - `"center"` の振る舞いを最小の回帰テストで追加

## 実装手順（チェックリスト）

- [ ] 1. `displace_meta` に `gradient_profile` を追加（`ParamMeta(kind="choice", choices=("linear","center"))`）
- [ ] 2. `displace()` に `gradient_profile: str = "linear"` を追加し、docstring へ仕様を追記
- [ ] 3. `gradient_profile` を mode int に変換（未知値は `"linear"` 扱い）
- [ ] 4. `_apply_noise_to_coords(..., gradient_profile_mode: int, ...)` を追加（numba 対応）
- [ ] 5. 勾配係数の計算を mode で分岐
  - [ ] `"linear"`: 現状の `raw = 1 + g*(t-c)` を保持
  - [ ] `"center"`: 上記の `d = 2*abs(t-c)` → `raw = 1 - g*d` を適用
- [ ] 6. テスト追加（中心ピークの最小保証）
  - [ ] `spatial_freq=(0,0,0)` と `amplitude=(A,0,0)` を使い、ノイズを全点で一定にして「係数だけ」の差を検証
  - [ ] `gradient_profile="center", amplitude_gradient=(1,0,0), min_gradient_factor=0.0` で、bbox x 端の点は不変・中心点は変位することを確認
  - [ ] 既定（省略）と `gradient_profile="linear"` が一致することの確認（互換性）
- [ ] 7. 最小テスト実行
  - [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`
- [ ] 8. スタブ再生成
  - [ ] `PYTHONPATH=src python -m grafix stub`
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`

## 要確認（あなたに決めてほしい点）

1. パラメータ名は `gradient_profile`（"linear"/"center"）で OK？；OK
2. `"center"` の式は上記（三角形 `u`）で OK？（他の候補: ガウス風、smoothstep など）
3. `g` の符号で「中心ピーク/端ピーク」を反転できる仕様は便利？ それとも `abs(g)` 固定で中心ピーク専用にする？；反転もほしい。
4. UI レンジ（既存の `amplitude_gradient/frequency_gradient: -4..4`）は据え置きで OK？（center では `g=1` が “端=0” の目安になる想定）；おすすめが他にあればそれで。
