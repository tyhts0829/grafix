# Parameter GUI snippet に `name=` を出す（Layer / Preset）: 実装計画（2026-01-20）

## 背景 / 課題

現在、Parameter GUI の snippet は primitive/effect については raw label がある場合のみ `name=` を復元できるようにした。
同様に、

- `L(..., name=...)` による Layer 名（Layer style のグループラベル）
- `P.<preset>(..., name=...)` による preset 呼び出しの表示名（グループラベル）

も snippet 経由でコードへ戻せると、実装変更→再調整のループが改善する。

## 結論（変更規模）

大きな変更は不要。いずれも ParamStore の snapshot が `(op, site_id)` 単位の `label` を保持しているため、
既存の「raw label を snippet に渡す」配線を拡張すればよい。

## ゴール

- **Layer style（`__layer_style__`）**: raw label がある site のみ、style snippet の layer dict に `name='...'` を含める。
  - 例: `dict(name='outline', color=(...), thickness=...)`
- **Preset（`P.<name>(...)`）**: raw label が「既定ラベル（= display_op）」と異なる場合のみ、snippet に `name='...'` を含める。
  - 例: `P.layout_grid_system(..., name='Grid')`

## Non-goals（今回やらない）

- preset の `key=` 復元（`site_id` 文字列からの逆算など）。
- GUI 表示用の dedup 名（`name#1` など）をコードへ書き戻す。
- `site_id` 生成方式の変更（source 位置化 / 明示 id 導入など）。

## 方針（設計）

### 1) raw label の定義

- `store_snapshot_for_gui()` が返す snapshot の `label` を raw label とみなす。
- 空文字（`strip()` が空）や `None` は無視する。

### 2) Layer style: `name=` の出し方

- style ブロックの layer style 出力（`snippet.py` の style 分岐）で、
  - `raw_label_by_site[(LAYER_STYLE_OP, site_id)]` がある場合だけ `name=...` を dict に追加する。
- 既存の `layer_style_name_by_site_id` は表示名用途（フォールバック `"layer"` が入る）なので、
  snippet の `name` 判定には **raw_label_by_site を使う**。

### 3) Preset: `name=` の出し方

- preset ブロック出力で、raw label がある場合でも常に `name=` を出すとノイズになる（既定で label が付く仕様のため）。
- そこで `name=` を出す条件を:
  - `raw_label != preset_registry.get_display_op(op)`（= 既定ラベルと異なる）とする。

## 変更範囲（想定ファイル）

- `src/grafix/interactive/parameter_gui/store_bridge.py`
  - `raw_label_by_site` の収集対象を `LAYER_STYLE_OP` と `preset_registry` にも拡張する。
- `src/grafix/interactive/parameter_gui/snippet.py`
  - style ブロック: layer dict に `name=` を条件付きで追加
  - preset ブロック: `name=` を条件付きで kwargs に追加
- `tests/interactive/parameter_gui/test_parameter_gui_snippet.py`
  - style（layer dict）: raw label あり/なしで `name=` が出る/出ない
  - preset: raw label が display_op と異なる時だけ `name=` が出る

## 実装タスク（チェックリスト）

- [x] `store_bridge.py` で `raw_label_by_site` に以下を追加
  - [x] `(LAYER_STYLE_OP, site_id) -> label`
  - [x] `(preset_op, site_id) -> label`（`op in preset_registry` のもの）
- [x] `snippet.py` の style 分岐を修正
  - [x] layer style dict に `name=` を追加（raw label がある場合のみ）
- [x] `snippet.py` の preset 分岐を修正
  - [x] `raw_label != display_op` の場合のみ `name=` を kwargs に含める
- [x] テスト追加（`test_parameter_gui_snippet.py`）
  - [x] layer style: raw label あり→ `name=` あり / raw label なし→ `name=` なし
  - [x] preset: raw label が display_op と同じ→ `name=` なし / 異なる→ `name=` あり
- [x] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_snippet.py` を実行

## 受け入れ条件（Definition of Done）

- 既存の snippet テストがすべて通り、新規テストも通る。
- Layer/preset で `name=` が勝手に増えない（raw label / 既定差分の条件を満たす場合のみ出る）。
