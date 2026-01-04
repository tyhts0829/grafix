# どこで: Grafix リポジトリ（設計メモ / 実装チェックリスト）。

# 何を: `src/grafix/core/effects/collapse.py` に「空間座標 (x,y,z) に応じて、subdivisions で生成される各サブセグメントにかかる崩し量を傾斜させる」機能を追加する。

# なぜ: 画面/モデル空間の一方向に向かって崩しを強めたり弱めたりして、構図・視線誘導・素材感のコントロールをしたいため（`partition` の `site_density_*` と同じ発想）。

# collapse spatial gradient: 実装改善計画

## ゴール

- `E.collapse()` に x/y/z 方向の傾斜（base + slope）を導入し、位置によって崩し量を連続的に変えられる。
- デフォルト引数では既存挙動と一致する（既存テストがそのまま通る）。
- 勾配の作り方は `partition` / `drop` と同系（正規化座標 `t∈[-1,+1]`、`clamp`、OR 合成）で揃える。
- 出力形式は現状維持（サブセグメントは 2 点の独立ポリライン、非接続）。
- `src/grafix/core/effects/` の方針（モジュール間依存なし）を維持し、`collapse.py` 単体で完結させる。

## 非ゴール（今回やらない）

- 乱数 seed のパラメータ化（現状は決定的で固定 seed）。
- 出力の接続性を変える（部分的に「繋げる」など）。
- `subdivisions` 自体を局所的に変えて出力本数を変動させる（必要なら別案として検討）。

## 仕様（案A: 崩し量マスク = intensity 乗算、推奨）

### 追加パラメータ（案）

- `intensity_mask_base: tuple[float, float, float] = (1.0, 1.0, 1.0)`
  - bbox 中心（正規化座標 `t=0`）でのマスク値（軸別、0..1）。
- `intensity_mask_slope: tuple[float, float, float] = (0.0, 0.0, 0.0)`
  - 正規化座標 `t∈[-1,+1]` に対するマスク勾配（軸別、-1..+1）。
- `auto_center: bool = True`
  - True のとき `pivot` を無視し、入力 bbox 中心を pivot として使う（`partition` と同じ）。
- `pivot: tuple[float, float, float] = (0.0, 0.0, 0.0)`
  - `auto_center=False` のときの pivot（ワールド座標）。

`collapse_meta` 追加（UI レンジ案）

- `intensity_mask_base`: `ParamMeta(kind="vec3", ui_min=0.0, ui_max=1.0)`
- `intensity_mask_slope`: `ParamMeta(kind="vec3", ui_min=-1.0, ui_max=1.0)`
- `auto_center`: `ParamMeta(kind="bool")`
- `pivot`: `ParamMeta(kind="vec3", ui_min=-100.0, ui_max=100.0)`

### マスク計算（partition/drop と同系）

1. bbox から `pivot3` と `inv_extent3` を決める。
   - `pivot3 = bbox_center`（`auto_center=True`）または `pivot`。
   - `extent3 = (max-min)/2`、`inv_extent3[k] = 0 if extent<eps else 1/extent`。
2. サブセグメントの変位前 midpoint `m` を計算する（`m=(p0+p1)/2`）。
3. 正規化座標 `t = clip((m - pivot3) * inv_extent3, -1..+1)`。
4. 軸別マスク `p_axis = clamp(base_axis + slope_axis * t_axis, 0..1)`。
5. 合成マスク `p_eff = 1 - (1-p_x)(1-p_y)(1-p_z)`（OR のイメージ、`partition/drop` と同じ）。
6. `intensity_eff = intensity * p_eff` を、そのサブセグメントの崩し量として使う。

### 期待される見た目/性質

- `p_eff=0` の領域は「崩し量 0」だが、出力は非接続サブセグメントのまま（線は分割される）。
- `p_eff` が増えるほどサブセグメントの平行移動量（崩し量）が大きくなる。

## 代替案（案B: subdivisions の局所変化）

- `p_eff` に応じて `divisions_eff = round(subdivisions * p_eff)` のように「サブセグメント数」を変える。
- 長所: 「分割そのもの」が傾斜し、密度感が分かりやすい。
- 短所: 出力配列サイズが位置依存になり、現状の 2 パス事前確保（`_collapse_count`）を作り直す必要がある。
- 判断: まず案A（intensity 乗算）で最小実装→必要なら案Bを別タスクで追加。

## 仕様（事前確認したい点）

- [ ] まずは案A（intensity 乗算）で良いか。案B（局所 subdivisions）まで要るか。
- [ ] マスク合成は OR 合成（`partition/drop` と同じ）で良いか。それとも `max` / `avg` の方が直感的か。
- [ ] `auto_center/pivot` を `collapse` にも追加して良いか（`partition` と揃える想定）。

## 実装チェックリスト（進捗）

- [ ] `src/grafix/core/effects/collapse.py` の API 拡張
  - [ ] `collapse_meta` に `intensity_mask_*`, `auto_center`, `pivot` を追加
  - [ ] `collapse()` の引数・docstring を更新（NumPy スタイル、日本語の事実記述）
  - [ ] bbox/pivot/extent の計算を `collapse()` に追加し、Numba へ渡す
  - [ ] `_collapse_njit_fill()` に midpoint→mask→`intensity_eff` の計算を追加
  - [ ] デフォルト引数で既存挙動と一致することを確認
- [ ] テスト追加/更新
  - [ ] `tests/core/effects/test_collapse.py` に「x 勾配でサブセグメントごとに崩し量が変わる」テストを追加
  - [ ] `auto_center=False` + `pivot` の影響を確認するテストを追加（必要なら）
- [ ] 型スタブ同期
  - [ ] `python -m tools.gen_g_stubs` で `src/grafix/api/__init__.pyi` を更新
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] Lint/型/テスト（対象限定で実行）
  - [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_collapse.py`
  - [ ] `ruff check src/grafix/core/effects/collapse.py tests/core/effects/test_collapse.py`
  - [ ] `mypy src/grafix`

## 追加で気づいた点（提案）

- `collapse` は現状 seed 固定で「再現性優先」なので、今回の傾斜も乱数の消費順序を崩さない形（常に同数の乱数を消費し、強度だけ変える）だと扱いやすい。
- 「崩し量 0 でも分割はされる」点が気になる場合、将来的に `split_when_intensity_zero: bool` のような別パラメータで制御する余地はある（今回はスコープ外）。
