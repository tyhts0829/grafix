# Primitive: bypass 引数を decorator で自動追加（effect と同様）チェックリスト（2026-01-08）

目的: primitive でも effect と同様に `bypass: bool` を **`@primitive` デコレータ機能**として自動追加し、GUI/スタブ/実行時の挙動を揃える。

背景:

- effect は `@effect` で `bypass` が自動追加され、`bypass=True` で入力を素通しできる。
- primitive は `@primitive` に `bypass` 自動追加が無く、GUI/スタブ/実行時の体験が非対称。

非目的:

- 互換ラッパー/シムの追加（このリポジトリ方針に従い作らない）
- `bypass` 以外の引数仕様変更
- 既存 primitive 実装の設計見直し（必要最小限の変更に留める）

## 0) 事前に決める（あなたの確認が必要）

- [x] `bypass=True` の primitive は **空ジオメトリ**を返す（`concat_realized_geometries()` 相当）でよい；はい
  - 理由: primitive は入力を持たないため「素通し」の意味が無く、空にするのが最も単純
- [x] `bypass` は **予約引数**として扱い、`meta` への明示指定は禁止でよい（effect と同様に `ValueError`）；はい
- [x] `meta=None` の primitive（将来の外部/プラグイン想定）については effect と同様に扱う:；はい
  - [x] 実行時は `bypass` を受け取れる（wrapper が `bypass` を pop する）
  - [x] ただし `meta/defaults/param_order` には追加しない（GUI/スタブ対象外）

## 1) 受け入れ条件（完了の定義）

- [x] `G.<primitive>(bypass=True, ...)` が例外なく動作し、realize 結果が空ジオメトリになる
- [x] parameter GUI の並び順が `bypass` → 既存の signature 順になる（primitive でも effect と揃う）
- [x] `tools/gen_g_stubs.py` の生成結果に primitive の `bypass: bool = ...` が含まれる
- [x] テストが通る:
  - [x] `PYTHONPATH=src pytest -q tests/core/test_primitive_bypass.py`（新規）
  - [x] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
  - [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `ruff check .`（この環境に ruff が無く実行できない）
- [x] `mypy src/grafix`

## 2) 実装方針（最小）

### A) `@primitive` に `bypass` を自動注入する

- 対象: `src/grafix/core/primitive_registry.py`
- 変更内容:
  - [x] `meta` に `bypass` が含まれていたら `ValueError`（予約引数）
  - [x] `meta` がある場合のみ:
    - [x] `meta_with_bypass = {"bypass": ParamMeta(kind="bool"), **meta_norm}` を登録する
    - [x] `defaults = {"bypass": False, **defaults_from_signature}` を登録する
    - [x] `param_order = ("bypass", *sig_order)` を登録する（GUI の並び順）
  - [x] wrapper 内で `bypass = bool(params.pop("bypass", False))` を処理し、
    - [x] `bypass=True` の場合は空ジオメトリを返す（`concat_realized_geometries()`）
    - [x] `bypass=False` の場合は従来通り `f(**params)`

### B) スタブ生成の更新

- 対象: `src/grafix/api/__init__.pyi`（自動生成結果）
- 手順:
  - [x] `python -m tools.gen_g_stubs` を実行して更新する
  - [x] `tests/stubs/test_api_stub_sync.py` が通ることを確認する

### C) テスト追加/更新

- [x] `tests/core/test_primitive_bypass.py` を追加（effect の bypass テストと同程度）
  - [x] `G.polygon(bypass=True)` が空ジオメトリになること
  - [x] `G.polygon()` は空ではないこと（対照）
- [x] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py` を更新
  - [x] primitive の表示順に `bypass` が先頭に来るケースを追加（または既存テストを置換）

## 3) 変更箇所（ファイル単位）

- [x] `src/grafix/core/primitive_registry.py`
- [x] `tests/core/test_primitive_bypass.py`（新規）
- [x] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
- [x] `src/grafix/api/__init__.pyi`（`tools/gen_g_stubs.py` により再生成）

## 4) 実装手順（順序）

- [x] 事前確認: `git status --porcelain` で依頼範囲外の差分/未追跡を把握（触らない）
- [x] 0. の事前決定を確定
- [x] `src/grafix/core/primitive_registry.py` を実装
- [x] テスト追加/更新（primitive bypass + param order）
- [x] `python -m tools.gen_g_stubs` で `src/grafix/api/__init__.pyi` を再生成
- [x] 対象テストを実行して確認
- [ ] `ruff check .` / `mypy src/grafix`（mypy は実行済み / ruff は未導入）

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] `bypass` の説明文をスタブ docstring に明示したいか（現状は meta hint 由来で `bypass: bool` 程度になる）
- [ ] `ruff check .` を必須にするなら、開発環境に ruff を導入する（例: `pip install -e ".[dev]"`）
