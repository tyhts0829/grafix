# どこで: `src/grafix/export/gcode.py`。

# 何を: 動作理解のため、全関数（export 本体 + 内部ヘルパ + ネスト関数）に「細かいコメント」を追加する。

# なぜ: 仕様（紙クリップ / 座標変換 / bed 検証 / travel 最適化 / 近距離ブリッジ描画）が多層で、後から安全に改変するには意図の明文化が必要なため。

# gcode.py: 詳細コメント追加 改善計画（2026-01-10）

## 0. 前提

- 対象ファイル: `src/grafix/export/gcode.py`
- やらないこと:
  - 挙動変更（G-code の内容が変わる修正）
  - 公開 API の変更
  - 依存追加
- コメント方針:
  - 既存の docstring は維持し、必要なら「誤解されやすい点」だけを追記する。
  - 1 関数あたり「概要 2〜6 行 + 重要分岐に 1〜3 行」程度を基本にし、過剰な逐語説明は避ける。
  - 何をしているか（What/How）より「なぜそうしているか（Why/Trade-off）」を優先して書く。

## 1. 現状整理（コメント対象の関数）

- 小物ユーティリティ:
  - `_fmt_float`
  - `_is_inside_rect`
  - `_append_point`
  - `_quantize_xy`
- クリップ:
  - `_clip_segment_to_rect`（Liang–Barsky）
  - `_clip_polyline_to_rect`（線分クリップ→連続区間に分割）
  - `_paper_safe_rect`
- 座標変換/安全:
  - `_canvas_to_machine_xy`
  - `_validate_bed_xy`
- ストローク最適化:
  - `_order_strokes_in_layer`（貪欲 + タイブレーク + 反転）
- export 本体:
  - `export_gcode`
  - `export_gcode` 内のネスト関数: `set_pen_down`, `set_feed`, `move_xy`

## 2. ゴール（受け入れ条件）

- 各関数を上から読んでいけば、仕様の「順序関係」と「適用条件」が迷わず追える。
- 重要な不変条件がコメントで明示される:
  - 距離評価は canvas 座標系（量子化して安定化）
  - bed 検証は “出力座標” のみ
  - レイヤ内のみ並び替え（レイヤ跨ぎはしない）
  - 近距離ブリッジ描画（`bridge_draw_distance`）は「意図的に線を足す」最適化
- 変更前後でテストがすべて通る（コメント追加のみ）。

## 3. 実装チェックリスト（コメント追加の作業手順）

- [x] 1. ファイル先頭に「全体のパイプライン概要（1 画面以内）」を追加
  - [x] クリップ → ストローク化 → 並び替え →（ブリッジ判定）→ G-code 出力 の流れ
  - [x] “決定性” の担保ポイント（丸め/量子化/タイブレーク）
- [x] 2. クリップ系の補足コメントを追加
  - [x] `_clip_segment_to_rect`: 変数 `u1/u2` の意味と eps の意図
  - [x] `_clip_polyline_to_rect`: 分割条件（断絶/紙外へ出る）と、出力が「紙内の連続区間群」になる理由
  - [x] `_paper_safe_rect`: マージン過大のエラー理由
- [x] 3. 座標変換/範囲検証の補足コメントを追加
  - [x] `_canvas_to_machine_xy`: 変換順（Y 反転→origin）と `canvas_height_mm` の意味
  - [x] `_quantize_xy`: “出力値” を正とする（検証も出力も丸め後）
  - [x] `_validate_bed_xy`: 入力ではなく出力座標のみ検証する理由
- [x] 4. ストローク順最適化の補足コメントを追加
  - [x] `_Stroke` のフィールドの役割（`start_q/end_q` は距離比較用の量子化点）
  - [x] `_order_strokes_in_layer`: 先頭固定・貪欲選択・反転判定・タイブレーク規則
- [x] 5. `export_gcode` の補足コメントを追加
  - [x] `set_pen_down` / `set_feed` / `move_xy` の「状態保持の理由」（冗長 G-code 抑制）
  - [x] レイヤ内での stroke 収集→順序決定→出力の境界が分かるコメント
  - [x] `bridge_draw_distance` の注意（“移動距離短縮” ではなく “線を追加” のトレードオフ）
- [x] 6. 検証
  - [x] `mypy src/grafix/export/gcode.py`
  - [x] `PYTHONPATH=src pytest -q tests/export/test_gcode.py`

## 4. 追加で事前確認したいこと

- [x] コメントは「日本語のみ」で統一（既存方針どおり）
- [x] “細かく” の上限: 1 関数あたり 10 行程度を目安
- [ ] メモ: フッタで `z_up + 20` を出力している（既存仕様）。将来の仕様確認ポイント。
