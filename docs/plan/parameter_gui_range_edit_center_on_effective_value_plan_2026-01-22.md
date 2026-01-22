# parameter_gui: `R`+MIDI で ui_min/ui_max を「現在の有効値中心」で拡縮する計画（2026-01-22）

目的:

- Parameter GUI で `R` キー押下中に MIDI CC を回したとき、ui_min/ui_max の拡縮が「現在の有効なパラメータ値」を中心に行われるようにする。

背景 / 現状:

- 現状の range edit は `src/grafix/interactive/parameter_gui/gui.py` の `_maybe_apply_range_edit_by_midi()` で行われ、`R/E/T` キーの押下状態に応じて ui_min/ui_max を更新している。
- しかし、レンジ編集の中心が「現在の有効値（resolver が採用した値）」に追従せず、**“今の値を基準にレンジを広げたい/狭めたい”** 操作が直感的になりにくい。

## 0) 事前に決める（あなたの確認が必要）

- [ ] `R` の挙動は「レンジ拡縮（centered）」に変更する（従来の “両端同量シフト” は廃止でよい）；はい
- [ ] `delta` の符号と拡縮の対応（例: `delta>0` で拡大 / `delta<0` で縮小）；それで。
- [ ] vec3 の中心値は「回した CC に対応する成分の effective」を採用する（x/y/z のうち、入力 CC が一致する成分）；はい

## 1) 変更後の仕様（挙動の約束）

- `R` 押下 + CC Δ入力で対象行の `ui_min/ui_max` を更新する。
- 対象:
  - `state.cc_key` が入力 CC を含む（CC learn 済み）
  - `kind in {"float", "int", "vec3"}`
  - `meta.ui_min` / `meta.ui_max` が両方とも存在する
- 中心値（center）の決定:
  - 可能なら `store._runtime_ref().last_effective_by_key[key]`（直近フレームの effective）を採用
  - 無い場合は `state.ui_value` へフォールバック
  - `kind=="vec3"` は上記のうち「対応成分」を center として採用
- 更新後レンジは center を中点として対称になる（概ね `ui_min_new + ui_max_new == 2*center`）。

## 2) 方針（実装案）

- `src/grafix/interactive/parameter_gui/range_edit.py` に「中心値を受け取ってレンジを拡縮する純粋関数」を追加する。
  - 例: `apply_range_zoom_around_value(kind, ui_min, ui_max, *, center, delta, sensitivity=...)`
  - 既存の `apply_range_shift()`（min/max 調整用途）は必要なら温存する。
- `src/grafix/interactive/parameter_gui/gui.py` の `_maybe_apply_range_edit_by_midi()` を変更し、`R` 押下時は:
  - center を算出（effective → ui_value の順で採用）
  - 新関数で `ui_min/ui_max` を更新
- vec3 の成分選択（CC→component index）ロジックは、可能なら小さく切り出してテスト可能に保つ。

## 3) 変更箇所（ファイル単位）

- [ ] `src/grafix/interactive/parameter_gui/range_edit.py`
- [ ] `src/grafix/interactive/parameter_gui/gui.py`
- [ ] `tests/interactive/parameter_gui/test_parameter_gui_range_edit.py`

## 4) 手順（実装順）

- [ ] 事前確認: `git status --porcelain` を見て、依頼範囲外の差分は触らない
- [ ] range_edit: zoom 純粋関数 + unit test を追加
- [ ] gui: `R` の経路を「effective を中心にした拡縮」へ差し替え（vec3 成分対応を含む）
- [ ] 最小確認: 対象テストを実行
- [ ] 任意: `mypy` / `ruff`（対象ディレクトリのみ）

## 5) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_range_edit.py`
- [ ] （任意）`mypy src/grafix/interactive/parameter_gui`
- [ ] （任意）`ruff check src/grafix/interactive/parameter_gui tests/interactive/parameter_gui`

## 6) 手動確認（実機）

- [ ] parameter_gui を起動し、対象パラメータへ CC learn
- [ ] 値がレンジ端に寄った状態で `R`+ノブ回転 → レンジ中心が現在の有効値へ来る（左右対称）
- [ ] float/int/vec3 で破綻しない（vec3 は回した成分の値を中心に拡縮される）
