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

- [ ] `bypass=True` の primitive は **空ジオメトリ**を返す（`concat_realized_geometries()` 相当）でよい
  - 理由: primitive は入力を持たないため「素通し」の意味が無く、空にするのが最も単純
- [ ] `bypass` は **予約引数**として扱い、`meta` への明示指定は禁止でよい（effect と同様に `ValueError`）
- [ ] `meta=None` の primitive（将来の外部/プラグイン想定）については effect と同様に扱う:
  - [ ] 実行時は `bypass` を受け取れる（wrapper が `bypass` を pop する）
  - [ ] ただし `meta/defaults/param_order` には追加しない（GUI/スタブ対象外）

## 1) 受け入れ条件（完了の定義）

- [ ] `G.<primitive>(bypass=True, ...)` が例外なく動作し、realize 結果が空ジオメトリになる
- [ ] parameter GUI の並び順が `bypass` → 既存の signature 順になる（primitive でも effect と揃う）
- [ ] `tools/gen_g_stubs.py` の生成結果に primitive の `bypass: bool = ...` が含まれる
- [ ] テストが通る:
  - [ ] `PYTHONPATH=src pytest -q tests/core/test_primitive_bypass.py`（新規）
  - [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] `ruff check .`
- [ ] `mypy src/grafix`

## 2) 実装方針（最小）

### A) `@primitive` に `bypass` を自動注入する

- 対象: `src/grafix/core/primitive_registry.py`
- 変更内容:
  - [ ] `meta` に `bypass` が含まれていたら `ValueError`（予約引数）
  - [ ] `meta` がある場合のみ:
    - [ ] `meta_with_bypass = {"bypass": ParamMeta(kind="bool"), **meta_norm}` を登録する
    - [ ] `defaults = {"bypass": False, **defaults_from_signature}` を登録する
    - [ ] `param_order = ("bypass", *sig_order)` を登録する（GUI の並び順）
  - [ ] wrapper 内で `bypass = bool(params.pop("bypass", False))` を処理し、
    - [ ] `bypass=True` の場合は空ジオメトリを返す（`concat_realized_geometries()`）
    - [ ] `bypass=False` の場合は従来通り `f(**params)`

### B) スタブ生成の更新

- 対象: `src/grafix/api/__init__.pyi`（自動生成結果）
- 手順:
  - [ ] `python -m tools.gen_g_stubs` を実行して更新する
  - [ ] `tests/stubs/test_api_stub_sync.py` が通ることを確認する

### C) テスト追加/更新

- [ ] `tests/core/test_primitive_bypass.py` を追加（effect の bypass テストと同程度）
  - [ ] `G.polygon(bypass=True)` が空ジオメトリになること
  - [ ] `G.polygon()` は空ではないこと（対照）
- [ ] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py` を更新
  - [ ] primitive の表示順に `bypass` が先頭に来るケースを追加（または既存テストを置換）

## 3) 変更箇所（ファイル単位）

- [ ] `src/grafix/core/primitive_registry.py`
- [ ] `tests/core/test_primitive_bypass.py`（新規）
- [ ] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
- [ ] `src/grafix/api/__init__.pyi`（`tools/gen_g_stubs.py` により再生成）

## 4) 実装手順（順序）

- [ ] 事前確認: `git status --porcelain` で依頼範囲外の差分/未追跡を把握（触らない）
- [ ] 0) の事前決定を確定
- [ ] `src/grafix/core/primitive_registry.py` を実装
- [ ] テスト追加/更新（primitive bypass + param order）
- [ ] `python -m tools.gen_g_stubs` で `src/grafix/api/__init__.pyi` を再生成
- [ ] 対象テストを実行して確認
- [ ] `ruff check .` / `mypy src/grafix`

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] `bypass` の説明文をスタブ docstring に明示したいか（現状は meta hint 由来で `bypass: bool` 程度になる）
