# effect/primitive/preset: bypass → activate（OFF=バイパス）改修計画（2026-01-18）

目的:

- effect/primitive/preset にあるデコレータ経由の `bypass` を `activate` に改名する。
- `activate=False`（OFF）のときに bypass（no-op/空）になるように挙動を反転する。
- 破壊的変更は許容し、互換ラッパー/シムは作らない。

背景:

- `bypass=True` は「無効化」という意図は伝わるが、GUI のトグルとしては直感が逆（ON が無効）になりやすい。
- `activate=True` を既定にして「ON が有効 / OFF が無効」を揃えるほうが操作感が良い。

非目的:

- 既存スナップショット/保存済みパラメータ（`bypass`）のマイグレーション（壊れてよい）
- `bypass` を受け付け続ける互換挙動（`TypeError: unexpected keyword 'bypass'` でよい）

## 0) 仕様（確定したい点）

- [x] `activate` の既定値は `True` にする（GUI 初期状態が ON）；OK
- [x] effect の bypass 挙動は現状維持:
  - 入力 0: 空 geometry
  - 入力 1: そのまま返す
  - 入力 N: concat して返す
- [x] primitive/preset の bypass 挙動は現状維持（空 geometry を返す）

## 1) 変更仕様（API/挙動）

共通:

- 予約パラメータ名を `bypass` → `activate` に変更する。
- meta への手書きは禁止（予約名なので `meta` に含めたら `ValueError`）。
- 実装関数シグネチャに `activate` を書かせない（デコレータが吸収する）。

effect (`@effect`):

- `activate=False` のとき:
  - `inputs` をそのまま通す（現状の bypass と同じ返り値規約）。
- `activate=True` のとき:
  - 従来通り effect を適用する。

primitive (`@primitive`):

- `activate=False` のとき:
  - 空 `RealizedGeometry` を返す（現状の bypass と同じ）。
- `activate=True` のとき:
  - 従来通り primitive を生成する。

preset (`@preset`):

- `activate=False` のとき:
  - `Geometry.create(op="concat")` を返して終了（現状の bypass と同じ）。
- `activate=True` のとき:
  - 従来通り preset 本体を呼ぶ（本体は mute のまま）。

## 2) 影響範囲（変更対象）

必須（実装）:

- `src/grafix/core/effect_registry.py`（予約名/注入/実行時 pop/既定値）
- `src/grafix/core/primitive_registry.py`（同上）
- `src/grafix/api/preset.py`（reserved/meta/param_order/resolve/早期 return）

必須（追従）:

- `src/grafix/api/__init__.pyi`（自動生成の結果更新）
- `src/grafix/devtools/generate_stub.py`（必要なら。多くは registry の meta/param_order 変更で追従する想定）
- `tests/**`（`bypass` 参照を `activate` に更新、真偽も反転）

任意（作例/ドキュメント）:

- `sketch/**`（`bypass=` を `activate=` に置換）
- `docs/memo/ui_visible.md`（`v.get("bypass")` 等を更新）
- `docs/done/**` は過去ログとして原則そのまま（更新しない）

## 3) 受け入れ条件（完了の定義）

- [x] `activate=False` で effect が no-op になる（入力 0/1/N の期待が満たされる）
- [x] `activate=False` で primitive が空 geometry になる
- [x] `activate=False` で preset が空 geometry になる
- [x] Parameter GUI の並び順が `activate` → 既存順になる（primitive/effect/preset で揃う）
- [x] `PYTHONPATH=src pytest -q` が通る
- [x] `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を更新し、`tests/stubs/test_api_stub_sync.py` が通る

## 4) 実装チェックリスト（手順）

### A) effect/primitive の予約名置換（core）

- [x] `src/grafix/core/effect_registry.py`
  - [x] `meta` に `activate` が含まれていたら `ValueError`
  - [x] meta 注入: `{"activate": ParamMeta(kind="bool"), **meta_norm}`
  - [x] defaults 注入: `{"activate": True, **defaults}`
  - [x] wrapper: `activate = bool(params.pop("activate", True))` / `if not activate: ...`
  - [x] GUI 順序: `("activate", *sig_order)`
- [x] `src/grafix/core/primitive_registry.py`（同様）

### B) preset の予約名置換（api）

- [x] `src/grafix/api/preset.py`
  - [x] `reserved = {"name", "key", "activate"}` に変更
  - [x] `sig.parameters` に `activate` があれば `ValueError`
  - [x] meta 注入: `{"activate": ParamMeta(kind="bool"), **meta_norm}`
  - [x] `param_order=("activate", *sig_order)` に変更
  - [x] wrapper:
    - [x] `activate_explicit = "activate" in kwargs` を保持
    - [x] `activate_base = bool(kwargs.pop("activate", True))`
    - [x] `public_params = {"activate": activate_base, ...}`
    - [x] `explicit_args` に `activate` を反映
    - [x] `activate=False` なら早期 return（空 geometry）

### C) テスト更新（bypass → activate, 値反転）

- [x] `tests/core/test_effect_bypass.py`（ファイル名も `*_activate.py` へ rename 検討）
- [x] `tests/core/test_primitive_bypass.py`（同上）
- [x] `tests/api/test_preset_namespace.py`
- [x] `tests/api/test_component.py`
- [x] `tests/core/parameters/test_label_namespace.py`
- [x] `tests/core/parameters/test_defaults_autopopulate.py`
- [x] `tests/core/parameters/test_default_override_policy.py`
- [x] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
- [x] `tests/devtools/test_generate_stub_p_presets.py`

### D) スタブ再生成

- [x] `PYTHONPATH=src python -m grafix stub` を実行し、`src/grafix/api/__init__.pyi` を更新する
  - [x] 生成物に `activate: bool = ...` が入っている（`bypass` が残っていない）
  - [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`

### E) 作例/メモ更新（任意）

- [x] `rg -n "\\bbypass\\b" sketch docs/memo -S` で残りを確認し、`activate` に置換する
