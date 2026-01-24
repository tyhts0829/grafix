# parameter_gui: snippet の Copy ボタンでポップアップを閉じる計画（2026-01-24）

目的:

- parameter_gui の snippet（Code ポップアップ）で `Copy` ボタンを押したら、その場でポップアップを閉じる。
  - `Close` ボタンは残す。

背景 / 現状:

- `src/grafix/interactive/parameter_gui/table.py` の Code ポップアップは `Close` / `Copy` ボタンを持つ。
- 現状は `Copy` がクリップボードへコピーするだけで、ポップアップは開いたまま。

## 0) 事前に決める（あなたの確認が必要）

- [x] `Copy` ボタン押下で「クリップボードへコピー → `imgui.close_current_popup()`」まで行う（要求通り）
- [x] `Close` ボタンは残す（要求通り）
- [x] テキスト欄フォーカス中の `Cmd/Ctrl+C` は「コピーのみ」で閉じない（現状維持でよい？）

## 1) 変更後の仕様（挙動の約束）

- Code ポップアップ内の `Copy` ボタン押下で:
  - `imgui.set_clipboard_text(_SNIPPET_POPUP_TEXT)` を実行
  - 続けて `imgui.close_current_popup()` を実行
- `Close` ボタンの挙動は現状のまま（押すと閉じる）。

## 2) 方針（実装案）

- `src/grafix/interactive/parameter_gui/table.py` の Code ポップアップ描画部で、`if imgui.button("Copy"):` の分岐に `imgui.close_current_popup()` を追加する。
- 必要なら、`Copy` で閉じるフレームに `set_keyboard_focus_here()` が走らないよう `Copy` 押下時に `_SNIPPET_POPUP_FOCUS_NEXT = False` を同時に落とす（シンプルに済むなら不要）。

## 3) 変更箇所（ファイル単位）

- [x] `src/grafix/interactive/parameter_gui/table.py`

## 4) 手順（実装順）

- [x] 事前確認: `git status --porcelain` を見て、依頼範囲外の差分は触らない
- [x] `table.py`: `Copy` ボタン押下時に `close_current_popup()` を呼ぶ
- [x] 最小確認:（任意）関連テスト/静的チェックを実行
- [ ] 手動確認: GUI 上で `Copy` を押すと閉じることを確認

## 5) 実行コマンド（ローカル確認）

- [x] （任意）`PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_snippet.py`
- [x] （任意）`ruff check src/grafix/interactive/parameter_gui/table.py`
- [ ] （任意）`mypy src/grafix/interactive/parameter_gui`

## 6) 手動確認（実機）

- [ ] parameter_gui を起動し、任意のグループで Code ポップアップを開く
- [ ] `Copy` を押す → クリップボードに入る＆ポップアップが閉じる
- [ ] `Close` を押す → ポップアップが閉じる（従来通り）
