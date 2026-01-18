# src_code_improvement_plan_2026-1-14: 1) パラメータ処理の分散 / 関心事混在（実装計画）

対象: `docs/review/src_code_improvement_plan_2026-1-14.md` の「### 1) パラメータ処理の分散 / 関心事混在」  
作成日: 2026-01-18  

## ゴール

- `src/grafix/core/pipeline.py:realize_scene()` から **Layer style の関心事（観測/label/override 適用）** を分離し、読みやすさを上げる。
- `store` が無いコンテキスト（`parameter_context_from_snapshot`）でも、`frame_params` があれば **label/records が失われない** 形にする。
- 描画結果（thickness/color）の意味を変えずに、最小の回帰テストで担保する。

## 非ゴール（今回やらない）

- realize_cache / runtime_config / mp-draw の並列化方針など、1) 以外の改善項目は触らない。
- API（`G/E/L`）の命名や registry 最適化は触らない。

## 実装方針（案）

### 追加する関数（案）

- `src/grafix/core/parameters/layer_style.py` に関数を追加する。
  - 例: `observe_and_apply_layer_style(...) -> tuple[float, tuple[float, float, float]]`
  - 入力（想定）:
    - `layer_site_id: str`
    - `layer_name: str | None`
    - `base_line_thickness: float`
    - `base_line_color_rgb01: tuple[float, float, float]`
    - `explicit_line_thickness: bool`
    - `explicit_line_color: bool`
  - 出力: `thickness, color_rgb01`（override 適用後）

### 関数内の責務（案）

- 観測（records/labels）
  - `current_frame_params()` があれば `layer_style_records(...)` を追加する。
  - `layer_name` があれば:
    - `current_param_store()` があれば `set_label(store, ...)`
    - 無ければ `frame_params.set_label(...)`（あれば）
- override 適用（描画値の上書き）
  - `current_param_store()` がある場合だけ `store.get_state(layer_style_key(...))` を見て、
    `override=True` のとき `ui_value` を採用する（現状ロジックの移植）。

### 呼び出し側（pipeline）の整理（案）

- `src/grafix/core/pipeline.py` は
  - `resolve_layer_style(...)` で base を確定
  - `observe_and_apply_layer_style(...)` に委譲して thickness/color を得る
  - `realize(...)` して `RealizedLayer` を積む
  だけに寄せる（records/labels/state 参照の直書きを消す）。

## テスト方針（最小）

- [ ] `tests/core/test_pipeline.py` に追加
  - [ ] `parameter_context(store)` 下で 2 フレーム実行し、2 フレーム目で override が反映されること
    - 1 フレーム目: 観測で state を作る
    - `update_state_from_ui(...)` で `line_thickness/line_color` を変更
    - 2 フレーム目: `RealizedLayer.thickness/color` が UI 値になっている
  - [ ] `layer.name` が `ParamStore.get_label(LAYER_STYLE_OP, site_id)` に反映されること
- [ ] （任意）`parameter_context_from_snapshot` 下で `frame_params` に label/records が積まれること
  - ※ mp-draw の将来変更（worker 側で realize する等）に備えた、純粋な回帰として扱う。

## 仕様確認（あなたに確認したい）

- [ ] `parameter_recording_muted()`（=`current_param_recording_enabled()==False`）の扱い
  - 案A: **現状維持**（mute 中でも Layer style の観測/label/override 適用は行う）
  - 案B: **API と揃える**（mute 中は Layer style の観測/label/override を行わない）
  - どちらで進めるのが良いですか？

