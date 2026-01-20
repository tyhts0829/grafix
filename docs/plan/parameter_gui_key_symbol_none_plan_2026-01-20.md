# parameter_gui のキー入力で `symbol=None` が来て落ちる件（2026-01-20）

## ゴール

- `parameter_gui` で文字入力（IME 含む）を行っても例外で落ちないようにする。

## スコープ

- 変更対象: `src/grafix/interactive/parameter_gui/gui.py`
- 追加テスト: `tests/interactive/parameter_gui/` 配下に最小の回帰テストを追加
- 非スコープ: 既存の未依頼差分（`git status` に見えている別ファイル群）には触れない

## 作業手順（チェックリスト）

- [x] 1. 例外の原因特定（`on_key_release` に `symbol=None` が来て `int(None)` で落ちる）
- [x] 2. `ParameterGUI._on_key_press/_on_key_release` を `None` 安全にする（必要なら ImGui がキーボードを掴んでいる時は無視）
- [x] 3. 回帰テスト追加（`symbol=None` を渡しても落ちないこと）
- [x] 4. 対象テストのみ実行（`PYTHONPATH=src pytest -q tests/interactive/parameter_gui -k key` 等）

## 受け入れ条件

- `parameter_gui` 上でテキスト入力を試しても `TypeError: int() ... NoneType` が出ない
- テストが追加され、ローカルで通る
