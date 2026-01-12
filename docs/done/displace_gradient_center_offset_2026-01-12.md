# displace: gradient 中心オフセット導入チェックリスト（2026-01-12）

目的: `src/grafix/core/effects/displace.py` の `amplitude_gradient` / `frequency_gradient` における「計算上の中心座標（現状 0.5 固定）」をオフセットできるパラメータを追加する。

背景:

- 現状の勾配は、bbox 正規化座標 `t∈[0,1]` を用い `t-0.5` を中心として係数を計算している。
- グラデーションの“中心（= 係数 1.0 付近）”を任意位置へずらしたい。

非目的:

- 既存の `amplitude_gradient` / `frequency_gradient` の意味・数式自体の刷新
- 互換ラッパー/シムの追加（不要）

## 0) 事前に決める（あなたの確認が必要）

- [x] 新パラメータ名: `gradient_center_offset`
- [x] オフセット座標系: bbox 正規化座標（単位なし、各軸別 `Vec3`）
  - [x] `pivot = 0.5 + offset`
  - [x] 既存式 `t - 0.5` を `t - pivot` に置換
- [x] GUI 範囲: `ui_min=-1.0`, `ui_max=1.0`
- [x] クリップ方針: クリップしない（`pivot` を `[0,1]` に制限しない）

## 1) 受け入れ条件（完了の定義）

- [x] `E.displace(..., gradient_center_offset=(0,0,0))` が省略時と同一の結果になる
- [x] `amplitude_gradient!=0` または `frequency_gradient!=0` のとき、`gradient_center_offset` を変えると出力座標が変化する
- [x] `amplitude_gradient==(0,0,0)` かつ `frequency_gradient==(0,0,0)` のとき、`gradient_center_offset` を変えても出力が変化しない
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`
- [x] スタブ再生成後に `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `mypy src/grafix`
- [ ] `ruff check .`（環境に ruff がある場合）

## 2) 仕様案（API/パラメータ）

- effect シグネチャ（案）
  - `displace(..., amplitude_gradient=(...), frequency_gradient=(...), gradient_center_offset=(0,0,0), min_gradient_factor=..., max_gradient_factor=..., t=...)`
- `gradient_center_offset : Vec3`（新規）
  - bbox 正規化座標 `t∈[0,1]` の“中心”をずらすためのオフセット（各軸別）
  - 実装上の中心: `pivot = 0.5 + offset`
  - 置換する式:
    - 旧: `1 + g * (t - 0.5)`
    - 新: `1 + g * (t - (0.5 + offset))`

## 3) 実装チェックリスト（ファイル単位）

- [x] `src/grafix/core/effects/displace.py`
  - [x] `displace_meta` に `gradient_center_offset` を追加（`kind="vec3"`）
  - [x] `displace(...)` の引数へ `gradient_center_offset` を追加（default `(0.0,0.0,0.0)`）
  - [x] Docstring に `gradient_center_offset` を追加（日本語、事実記述）
  - [x] `_apply_noise_to_coords(...)` へ `gradient_center_offset` を渡す
  - [x] `_apply_noise_to_coords(...)` 内で `tx/ty/tz` の中心を `0.5` → `0.5+offset` に置換
    - [x] `has_freq_grad == False` ブランチの `fx_raw/fy_raw/fz_raw`
    - [x] `has_freq_grad == True` ブランチの `amp_*` と `freq_*` の両方
  - [x] 既存のクランプ（`GX/FGX`、`min/max_gradient_factor`）は踏襲しつつ、追加実装は最小限に留める
- [x] スタブ再生成（手編集しない）
  - [x] `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新
  - [x] `displace` の API シグネチャ/Docstring に `gradient_center_offset` が反映されること
- [x] `tests/core/effects/test_displace.py`
  - [x] 新規テスト: `gradient_center_offset` により出力が変わる（勾配あり）
  - [x] 新規テスト: `gradient_center_offset` を変えても出力が変わらない（勾配なし）
  - [x] 新規テスト: `gradient_center_offset=(0,0,0)` が省略時と一致する（`E.displace` 経由）

## 4) 実行コマンド（ローカル確認）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`
- [x] `PYTHONPATH=src python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `mypy src/grafix`
- [ ] `ruff check .`（任意）

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] オフセットの符号感（「+X で中心が右に動く」など）を GUI 用に短い説明として Docstring に入れるか
- [ ] `displace` の勾配計算が分岐で重複しているため、将来は共通化できるが（今回は変更しない）
- [x] `tests/stubs/test_api_stub_sync.py` と整合させるため、スタブ生成は `python -m grafix stub` を正とする（`tools/gen_g_stubs.py` はヘッダ行が異なる）
