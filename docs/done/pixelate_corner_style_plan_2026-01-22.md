# effect: pixelate の角スタイル（corner style）追加チェックリスト（2026-01-22）

目的: `E.pixelate(...)` に「階段の角（折れ方）」を変えるオプションを追加し、同じ入力でも角の見た目（L字の出方）を切り替えられるようにする。

背景:

- 現状の `pixelate` は major axis first（`abs(dx) >= abs(dy)` なら x→y、逆なら y→x）で固定。
- 対角（8-connected の“斜め1手”）を 2 手（水平+垂直）に分解する際、`x→y` と `y→x` のどちらを選ぶかで“角の位置”が 1 マスずれて見た目が変わる。

非目的:

- 角の丸め（フィレット）や面取り（斜めチャンファ）※斜め線を出さない前提のまま
- `pixelate` 以外の effect を増やすこと

## 0) 事前に決める（あなたの確認が必要）

- [x] 新規引数名（案）
  - [x] 案 A: `corner`（短い、推奨）；これで
  - [ ] 案 B: `corner_style`
  - [ ] 案 C: `turn`
- [x] 仕様（案）
  - [x] `corner="auto|xy|yx"` の 3 択にする（最小）；これで
    - [x] `"auto"`: 現状どおり major axis first（既定値）
    - [x] `"xy"`: 対角分解は常に x→y
    - [x] `"yx"`: 対角分解は常に y→x
  - [ ] （追加候補）`"alternate"`: 対角分解ごとに x→y / y→x を交互（今回は入れない想定）

## 1) 受け入れ条件（完了の定義）

- [x] `corner="auto"` のとき、現在と同じ出力（互換）になる
- [x] `corner="xy"` / `corner="yx"` で、同じ入力でも XY の経路が変わる（テスト固定）
- [x] いずれの `corner` でも「水平/垂直のみ」は維持される（既存テストも通る）
- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py` が通る
- [x] `PYTHONPATH=src python -m grafix stub` 後、`PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` が通る

## 2) 変更方針（最小）

- `src/grafix/core/effects/pixelate.py` に `corner: str = "auto"` を追加
- `pixelate_meta` に `corner: ParamMeta(kind="choice", choices=("auto","xy","yx"))` を追加
- 対角分解が発生する分岐（= 1 iteration で x と y が両方動くところ）だけ順序を切り替える
  - `"auto"`: major axis first（現状）
  - `"xy"`: x→y
  - `"yx"`: y→x

## 3) 変更箇所（ファイル単位）

- [x] `src/grafix/core/effects/pixelate.py`
  - [x] 引数/ParamMeta 追加
  - [x] 対角分解の順序を `corner` で切替
- [x] `tests/core/effects/test_pixelate.py`
  - [x] `corner` の違いで出力が変わるケースを追加（y-major の例が分かりやすい）
- [x] `src/grafix/api/__init__.pyi`
  - [x] `PYTHONPATH=src python -m grafix stub` で再生成（手編集しない）

## 4) 実行コマンド（ローカル確認）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `ruff check src/grafix/core/effects/pixelate.py tests/core/effects/test_pixelate.py`
