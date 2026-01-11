# 失敗テスト原因調査: `bypass` と layer style meta（2026-01-10）

- どこで: `docs/plan/parameters_test_failures_2026-01-10.md`
- 何を: `pytest -q` で失敗した 6 件の原因と、テスト側の追従方針（改善案）を整理する。
- なぜ: 仕様変更で ParamStore が観測するキーや UI メタ値が変わり、テスト期待値が古くなっているため。

## 失敗サマリ（6 failed / 403 passed）

- `tests/core/parameters/test_default_override_policy.py`
  - `test_implicit_defaults_start_with_override_on`（`polygon` の期待に `bypass` が欠けている）
  - `test_explicit_kwargs_start_with_override_off_for_those_args`（同上）
- `tests/core/parameters/test_defaults_autopopulate.py`
  - `test_polygon_defaults_recorded_when_no_kwargs`（`polygon` の期待に `bypass` が欠けている）
  - `test_meta_dict_spec_is_accepted_for_user_defined_primitive_and_effect`（user-defined primitive の期待に `bypass` が欠けている）
- `tests/core/parameters/test_label_namespace.py`
  - `test_primitive_name_sets_label`（`polygon` の期待に `bypass` が欠けている）
- `tests/core/parameters/test_layer_style_entries.py`
  - `test_layer_style_records_can_be_merged_by_param_store`（`ui_min` の期待が古い）

## 原因 1: `bypass` が meta 付き primitive/effect に自動追加され、ParamStore が観測する

現状の仕様では、`meta` を持つ primitive/effect は **予約引数 `bypass` が先頭に追加**されます。
そのため、kwargs を省略した呼び出し（例: `G.polygon()`）でも `ParamStore` のスナップショットに `bypass` が現れます。

根拠（実装）:

- `src/grafix/core/primitive_registry.py`
  - `meta_with_bypass = {"bypass": ParamMeta(kind="bool"), **meta_norm}`
  - `defaults = {"bypass": False, **defaults}`
- `src/grafix/core/effect_registry.py`
  - `meta_with_bypass = {"bypass": ParamMeta(kind="bool"), **meta_norm}`
  - `defaults = {"bypass": False, **defaults}`
- `src/grafix/api/_param_resolution.py`
  - `base_params = dict(defaults); base_params.update(user_params)`
  - `explicit_args = set(user_params.keys())`（`bypass` を渡さなければ implicit 扱い）

したがって、以下の「期待値が `bypass` を含まない」テストがズレます:

- `polygon` 系:
  - args 集合は `{"bypass", "n_sides", "phase", "center", "scale"}` が自然
  - override ポリシーは `bypass` を渡していない限り implicit なので `override=True` が自然
- user-defined primitive（`@primitive(meta=...)`）も、`meta` がある限り `bypass` が追加される

補足: 同じファイル内で `effect scale` の期待はすでに `{"bypass", ...}` になっており、`polygon` 側だけ追従漏れの状態。

## 原因 2: layer style の `ui_min` が `1e-6` → `1e-4` に変更済み

`src/grafix/core/parameters/layer_style.py` の定数が以下になっています:

- `LAYER_STYLE_THICKNESS_META = ParamMeta(kind="float", ui_min=1e-4, ui_max=1e-2)`

そのため、`tests/core/parameters/test_layer_style_entries.py` の `ui_min == 1e-6` は期待値が古いです。

## 改善案（チェックリスト）

テスト追従（最小）:

- [ ] `tests/core/parameters/test_default_override_policy.py` の期待に `bypass` を追加する
  - `G.polygon()` では `bypass: True` を追加（implicit → override=True のため）
  - `G.polygon(phase=45.0)` でも `bypass: True` を追加（`phase` 以外は implicit）
- [ ] `tests/core/parameters/test_defaults_autopopulate.py`
  - `test_polygon_defaults_recorded_when_no_kwargs` の期待集合に `bypass` を追加
  - `test_meta_dict_spec_is_accepted_for_user_defined_primitive_and_effect` の `primitive_args` 期待に `bypass` を追加
- [ ] `tests/core/parameters/test_label_namespace.py::test_primitive_name_sets_label` の期待集合に `bypass` を追加（ラベル仕様自体は不変）
- [ ] `tests/core/parameters/test_layer_style_entries.py` の `ui_min` 期待を `1e-4` に更新（または `LAYER_STYLE_THICKNESS_META.ui_min` を参照する方針に切替）

将来の追従漏れを減らす案（任意）:

- [ ] 「meta 付きは `bypass` が必ず追加される」ことを 1 テストで明示し、他テストはそれに依存して簡略化する（重複期待の散在を減らす）
- [ ] `bypass` の予約語制約（`meta` に含められない）をテストで固定する（今は実装側で `ValueError`）
- [ ] ドキュメントに「予約引数 `bypass`」の意味（primitive: empty geometry / effect: passthrough）を明記する

動作確認（テスト更新後）:

- [ ] `pytest -q tests/core/parameters/test_default_override_policy.py tests/core/parameters/test_defaults_autopopulate.py tests/core/parameters/test_label_namespace.py tests/core/parameters/test_layer_style_entries.py`

