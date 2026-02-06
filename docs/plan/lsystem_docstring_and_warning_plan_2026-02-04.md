# `G.lsystem` 改善: docstring 充実 + 不正入力は warn & ignore

作成日: 2026-02-04

対象:

- `src/grafix/core/primitives/lsystem.py`（docstring と入力処理）

## 背景 / 目的

- `axiom` と `rules` が「何を意味し、どう書くのか」が分かりにくい。
- GUI 編集中に少しでも不正な文字/記法が入ると例外で落ち、試行錯誤しづらい。
- そこで **使い方を docstring で明確化**しつつ、**不正入力は warning のみで処理継続**する。

## ゴール

- `G.lsystem` の docstring を「概念 + 書式 + 例」で分かるようにする
  - `axiom`（初期文字列）/ `rules`（置換規則）の意味
  - `rules` の記述フォーマット（`A=...` / 改行 / `#` コメント）
  - 使う記号（`F f + - [ ]`）と、`X` 等の「描画しない記号」の扱い
  - 典型例（fractal plant / 回路プリセット / custom の最小例）
- 不正入力は **例外で止めずに** `warnings.warn(...)` を出して無視する
  - `rules` の不正行（`=` 無し / 左辺が 1 文字でない等）
  - プログラム解釈中の不整合（`']'` が余る / `'['` が閉じていない）

## 非ゴール

- ルール編集 UI の導入（GUI 側でのエディタ機能）
- 仕様を増やす（新しい記号や 3D タートルなど）
- 過剰な入力検証（「落ちない」以上のことはしない）

## 追加/変更するもの

- `src/grafix/core/primitives/lsystem.py`
  - docstring を拡充（`axiom/rules` の説明を中心に）
  - `warnings` を使って warn-only にする（ValueError をやめる）
- `tests/core/primitives/test_lsystem.py`
  - `ValueError` 前提のテストを「warning が出て処理継続」へ更新
- `src/grafix/api/__init__.pyi`
  - docstring 変更に追随するため `PYTHONPATH=src python -m grafix stub` を実行して更新

## 実装方針（最小）

### 1) rules parse

- 現状の `_parse_rules_text()` を「不正行は warn してスキップ」に変更
- warn メッセージには行番号と原文（短縮しても良い）を含める

### 2) タートル解釈の bracket 不整合

- `']'` が余る: warn して無視（pop しない）
- `'['` が余る（stack が残る）: warn して残りを無視（例外にしない）

### 3) docstring

- `axiom` と `rules` を「文字列の置換規則」として明示
- `X` のような “描画しないシンボル（変数）” を例示
- `rules` の書式例を複数提示（最小 / plant 例）
- 「未知記号は無視（no-op）」と「不正行/不整合は warning」も明記

## テスト（最小）

- `rules="F"` のような不正行で例外にならず、`UserWarning` が出る
- `axiom="]"`（余剰 bracket）でも例外にならず、warning が出て空（または最小）結果になる

## 実装手順（チェックリスト）

- [x] `lsystem.py` の docstring を拡充
- [x] `_parse_rules_text()` を warn & skip に変更
- [x] タートルの bracket 不整合を warn & ignore に変更
- [x] テストを更新（warning を検証）
- [x] `PYTHONPATH=src python -m grafix stub`
- [x] `PYTHONPATH=src pytest -q tests/core/primitives/test_lsystem.py tests/stubs/test_api_stub_sync.py`
