# Parameter GUI: activate OFF で他パラメータを自動非表示（計画 / 2026-01-30）

## 背景

`ui_visible` によって「いまの状態で効いている引数だけを表示」できるようになったが、最頻出の枝刈りが `activate`。
各 op ごとに `ui_visible` を書かなくても、`activate=False` のときは「他の引数は効かない」ため、デフォルトでまとめて隠せると UX が改善する。

## 目的

- `show_inactive_params` が OFF のとき、同一 group（`(op, site_id)`）の `activate` が OFF なら **`activate` 行以外を非表示** にする。
- `ui_visible` を各 op に書かなくてもこの挙動がデフォルトで働くようにする。
- 非表示は GUI 表示のみ（値・override・MIDI 割当には影響しない）。

## 仕様（案）

- 影響範囲: Parameter GUI の表示マスク計算のみ（`active_mask_for_rows`）。
- 判定単位: group = `(op, site_id)`。
- `show_inactive_params=True` のときは **常に全行表示**（現状維持）。
- `show_inactive_params=False` のとき:
  - group 内に `activate` 行があり、かつ **実効値**（`last_effective_by_key` 優先）が `False` の場合:
    - `activate` 行は表示
    - それ以外の引数行は **すべて非表示**（`ui_visible` ルールより優先）
  - `activate` 行が無い group は現状通り（`ui_visible` ルールがあればそれを評価、無ければ表示）

注:

- `activate` の実効値が非 bool の場合も `bool(value)` で扱う（既存の UI 値辞書と同様の正規化）。
- 例外時の fail-open 方針は維持する（ただし `activate` 自体の判定は例外が出ない形にする）。

## 実装タスク

### 1) 可視マスク計算へ “activate ゲート” を追加

- [x] `src/grafix/interactive/parameter_gui/visibility.py` の `active_mask_for_rows()` を拡張する
  - [x] group ごとの現在値辞書 `values_by_group` から `activate` の on/off を引けるようにする
  - [x] `show_inactive=False` かつ `activate=False` の group は `arg=="activate"` 以外を False にする
  - [x] それ以外は現状の `ui_visible` 評価フローを維持する

### 2) テスト追加

- [x] `tests/interactive/parameter_gui/test_parameter_gui_visibility.py`
  - [x] `activate=False` で “activate 以外が隠れる” を検証
  - [x] `show_inactive=True` なら “activate=False でも全部出る” を検証
  - [x] `activate` 行が存在しない場合は “既存挙動を維持” を検証
  - [x] `last_effective_by_key` を使うケース（実効値が False）も 1 ケース入れる

### 3) ドキュメント更新

- [x] `docs/memo/ui_visible.md` に「`activate=False` はデフォルトで他引数を隠す」旨を追記
  - [x] `Show inactive params` が escape hatch であることも併記

## 動作確認（手動）

- [ ] `python sketch/readme/16.py` を起動し、Parameter GUI で任意の primitive/effect/preset の `activate` を OFF → 他行が消えることを確認
- [ ] `Show inactive params` を ON → 全行が再表示されることを確認

## 受け入れ条件（Definition of Done）

- `activate=False` の group は `activate` 以外が隠れる（show_inactive=False のとき）。
- `Show inactive params` ON で必ず全行に戻る。
- `ui_visible` の既存ルールは `activate=True` のとき従来通り効く。
- 既存テスト + 追加テストが通る。

## 確認してほしい点（要決定）

- [x] preset の予約引数（`name/key` 等）が GUI 行として存在する場合も「全部隠す」に含めてよいか；はい
- [x] `activate` が無い op（style 行など）には当然適用しない、でよいか；はい
