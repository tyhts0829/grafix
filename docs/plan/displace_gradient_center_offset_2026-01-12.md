# displace: gradient 中心オフセット導入チェックリスト（2026-01-12）

目的: `src/grafix/core/effects/displace.py` の `amplitude_gradient` / `frequency_gradient` における「計算上の中心座標（現状 0.5 固定）」をオフセットできるパラメータを追加する。

背景:

- 現状の勾配は、bbox 正規化座標 `t∈[0,1]` を用い `t-0.5` を中心として係数を計算している。
- グラデーションの“中心（= 係数 1.0 付近）”を任意位置へずらしたい。

非目的:

- 既存の `amplitude_gradient` / `frequency_gradient` の意味・数式自体の刷新
- 互換ラッパー/シムの追加（不要）

## 0) 事前に決める（あなたの確認が必要）

- [ ] 新パラメータ名（案）
  - 案 A: `gradient_center_offset`（推奨）；こちら
  - 案 B: `gradient_pivot_offset`
- [ ] オフセットの座標系（案）
  - 案 A（推奨）: bbox 正規化座標でのオフセット（単位なし、各軸別 `Vec3`）；こちらで
    - `pivot = 0.5 + offset`
    - 既存式 `t - 0.5` を `t - pivot` に置換
  - 案 B: ワールド座標（mm）での中心指定/オフセット（bbox 正規化が絡み複雑化しやすい）
- [ ] GUI 範囲（案、正規化オフセット前提）
  - [ ] `ui_min=-1.0`, `ui_max=1.0`（シンプル。bbox 外も許容）；こちらで
  - [ ] もしくは `ui_min=-0.5`, `ui_max=0.5`（中心が bbox 内に収まりやすい）
- [ ] クリップ方針（案）
  - [ ] クリップしない（推奨。式がそのまま機能し、実装が単純）；こちらで
  - [ ] `pivot` を `[0,1]` にクリップ（直感的だが仕様が増える）

## 1) 受け入れ条件（完了の定義）

- [ ] `E.displace(gradient_center_offset=(0,0,0))` が従来と同一の結果（少なくともテスト上の挙動）になる
- [ ] `amplitude_gradient!=0` または `frequency_gradient!=0` のとき、`gradient_center_offset` を変えると出力座標が変化する
- [ ] `amplitude_gradient==(0,0,0)` かつ `frequency_gradient==(0,0,0)` のとき、`gradient_center_offset` を変えても出力が変化しない
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`
- [ ] スタブ再生成後に `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `mypy src/grafix`
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

- [ ] `src/grafix/core/effects/displace.py`
  - [ ] `displace_meta` に `gradient_center_offset` を追加（`kind="vec3"`）
  - [ ] `displace(...)` の引数へ `gradient_center_offset` を追加（default `(0.0,0.0,0.0)`）
  - [ ] Docstring に `gradient_center_offset` を追加（日本語、事実記述）
  - [ ] `_apply_noise_to_coords(...)` へ `gradient_center_offset` を渡す
  - [ ] `_apply_noise_to_coords(...)` 内で `tx/ty/tz` の中心を `0.5` → `0.5+offset` に置換
    - 対象箇所（最低限）:
      - `has_freq_grad == False` ブランチの `fx_raw/fy_raw/fz_raw`
      - `has_freq_grad == True` ブランチの `amp_*` と `freq_*` の両方
  - [ ] 既存のクランプ（`GX/FGX`、`min/max_gradient_factor`）は踏襲しつつ、追加実装は最小限に留める
- [ ] `tools/gen_g_stubs.py` 実行（手編集しない）
  - [ ] `python -m tools.gen_g_stubs` で `src/grafix/api/__init__.pyi` を更新
  - [ ] `displace` の API シグネチャ/Docstring に `gradient_center_offset` が反映されること
- [ ] `tests/core/effects/test_displace.py`
  - [ ] 新規テスト: `gradient_center_offset` により出力が変わる（勾配あり）
  - [ ] 新規テスト: `gradient_center_offset` を変えても出力が変わらない（勾配なし）

## 4) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_displace.py`
- [ ] `python -m tools.gen_g_stubs`
- [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `mypy src/grafix`
- [ ] `ruff check .`（任意）

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] オフセットの符号感（「+X で中心が右に動く」など）を GUI 用に短い説明として Docstring に入れるか
- [ ] `displace` の勾配計算が分岐で重複しているため、将来は共通化できるが（今回は変更しない）
