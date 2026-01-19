# pytest 失敗: polygon の `sweep` 追加に伴う parameters 系テスト更新プラン（2026-01-19）

## 1. 現象（失敗内容）

以下のテストが、`polygon` の引数一覧に **`sweep` が追加された**ことで失敗している。

- `tests/core/parameters/test_default_override_policy.py`
  - `test_implicit_defaults_start_with_override_on`
  - `test_explicit_kwargs_start_with_override_off_for_those_args`
- `tests/core/parameters/test_defaults_autopopulate.py`
  - `test_polygon_defaults_recorded_when_no_kwargs`
- `tests/core/parameters/test_label_namespace.py`
  - `test_primitive_name_sets_label`

失敗差分はいずれも共通で、期待値に無い `sweep` が snapshot に含まれている（`Left contains 1 more item: {'sweep': True}`）。

## 2. 原因（調査結果）

`polygon` プリミティブに **`sweep: float = 360.0`** が追加され、メタ情報にも `sweep` が含まれているため、`ParamStore` が `polygon` のデフォルト引数として `sweep` を記録するようになった。

- 実装: `src/grafix/core/primitives/polygon.py` に `sweep` 引数と `polygon_meta["sweep"]` が存在する
- 直近の設計・意図: `docs/plan/polygon_partial_sweep_2026-01-18.md`（部分周回対応で `sweep` を導入）

一方で、parameters 系テストは `polygon` の引数集合を「`activate, n_sides, phase, center, scale`」のまま固定で期待しており、**仕様変更（引数追加）に追従できていない**。

## 3. 修正方針

実装側は `sweep` を正式なパラメータとして扱っているため、ここでは **テスト側の期待値を更新**して整合させる。

- `polygon` の引数集合に `sweep` を追加
- override policy の期待値にも `sweep` を追加
  - 省略時（デフォルト）は `override=True`
  - 明示指定した引数は `override=False`（既存の `phase` と同様）

## 4. 作業手順（チェックリスト）

- [x] 対象テストのみで失敗を再現する  
      `PYTHONPATH=src pytest -q tests/core/parameters/test_default_override_policy.py tests/core/parameters/test_defaults_autopopulate.py tests/core/parameters/test_label_namespace.py`
- [x] 期待値更新（`sweep` 追加）
  - [x] `tests/core/parameters/test_default_override_policy.py` の dict に `"sweep": True` を追加
  - [x] `tests/core/parameters/test_defaults_autopopulate.py` の set に `"sweep"` を追加
  - [x] `tests/core/parameters/test_label_namespace.py` の set に `"sweep"` を追加
- [x] （任意だが推奨）`sweep` を明示指定した場合の override が `False` になるテストを追加  
      例: `G.polygon(sweep=180.0)` を 1 ケース追加
- [x] 上記 3 ファイルのテストを再実行して緑化
- [ ] 必要なら全体実行で回帰確認  
      `PYTHONPATH=src pytest -q`

## 5. 完了条件

- ここで挙げた 4 つの failing test がすべて通る
- `polygon` のパラメータ一覧・override policy の期待値が、現行 API（`sweep` 含む）と一致している
