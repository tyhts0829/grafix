# Root export: `effect`/`primitive` を `from grafix import ...` で使えるようにする計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 完了

## 背景 / 問題

- 現状、`@effect` / `@primitive` は `grafix.api` では再エクスポートされているが、ルートの `grafix` からは import できない。
- そのためユーザーコードで `from grafix import G, E` の流れに合わせてデコレータも取り込みたい場合に、import パスが分散する。

## 目的

- `from grafix import effect, primitive` が成立するようにする。
- 既存の `from grafix import G, E, ...` と同じ “入口” に揃える。

## 非目的

- デコレータ実装の仕様変更（registry の挙動変更、互換ラッパー追加など）は行わない。

## 実装タスク（チェックリスト）

### 1) ルート export を追加

- [x] `src/grafix/__init__.py` で `effect` / `primitive` を import して `__all__` に追加する。

### 2) テスト追加（最小）

- [x] `tests/api/test_root_decorator_export.py` を追加し、ルート import できることを検証する（`from grafix import effect, primitive`）。
- [x] `grafix.core.*_registry` の同一オブジェクトであることを `is` で確認する（ラッパー化しない）。

### 3) 検証

- [x] `PYTHONPATH=src pytest -q tests/api/test_root_decorator_export.py` が通る。

## 受け入れ条件（DoD）

- [x] `from grafix import effect, primitive` が成功する。
- [x] `effect` / `primitive` が既存 registry デコレータと同一である（余計な層を増やしていない）。
