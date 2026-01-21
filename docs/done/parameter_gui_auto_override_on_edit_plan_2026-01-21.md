# parameter_gui: override=False の行を GUI で編集したら override=True にする（実装計画）

作成日: 2026-01-21

## 背景

- `override=False` のとき、GUI で `ui_value` を編集しても resolver が `base` を採用するため効果が出ない（`src/grafix/core/parameters/resolver.py`）。
- 明示 kwargs（`explicit=True`）は初期 `override=False` になりやすく、GUI で触った瞬間に効くのが直感的（`src/grafix/core/parameters/merge_ops.py`）。

## ゴール

- `override=False` のパラメータを parameter_gui で値編集した瞬間に `override` を自動で `True` にし、編集がその場で反映される。

## 非ゴール（今回やらない）

- `override` 概念自体の変更や永続化仕様の変更はしない。
- explicit/implicit follow policy（`src/grafix/core/parameters/merge_ops.py`）や CC 適用優先順位は変えない。
- `ui_min/ui_max` 変更や CC 割当変更「だけ」で `override` を勝手に立てない（必要なら別タスク）。

## 仕様（確認したい / 決める）

- [x] 対象は `ui_value` の変更のみ（slider/入力/choice 等）。`ui_min/ui_max` 変更では立てない。；はい
- [x] `kind=bool` は `override` が無い前提なので対象外（現状通り）。；はい
- [x] `kind=choice` で「choices が変わって `ui_value` が自動丸めされる」ケースは、`override` を自動で立てない（丸めは store へ反映するが `base` 優先は維持）。；はい

## 実装方針（案）

### 案 A: UI 層で auto-enable（推奨）

- 変更箇所: `src/grafix/interactive/parameter_gui/table.py`
- `render_parameter_row_4cols()` の control 列で `changed` を検知したら、`override=False` の場合 `override=True` にする。
- 例外: `kind=bool`、および `kind=choice` の無操作丸め（上記仕様）では立てない。

### 案 B: store_bridge で auto-enable（非推奨）

- 変更箇所: `src/grafix/interactive/parameter_gui/store_bridge.py`
- `after.ui_value != before.ui_value` なら `override=True` を強制する。
- ただし `choice` の無操作丸め等でも発火し得るため、意図せぬ override が起きやすい。

## 実装タスク

- [x] 案 A / 仕様の最終確定
- [x] `src/grafix/interactive/parameter_gui/table.py` に純粋関数 `_should_auto_enable_override(row)` を追加（テスト可能に）
- [x] `render_parameter_row_4cols()` で `ui_value` 変更時に `_should_auto_enable_override(...)` が True なら `override=True` をセット
- [x] 最低限の単体テスト追加（imgui 依存無し）
  - [x] `tests/interactive/parameter_gui/test_parameter_gui_auto_override_on_edit.py` を追加し、kind ごとの挙動を確認
- [x] 既存テストを対象限定で実行: `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_auto_override_on_edit.py`
- [ ] （任意）手動確認: `sketch/main.py` 等で explicit kwargs の param を触って即反映されることを確認

## 影響範囲メモ

- resolver の優先順位は変えない（`override` が `True` になるだけ）。
- follow policy は「既定値から外れた」扱いになり、explicit 変化への追従が止まる可能性があるが、ユーザーが触った扱いとして妥当。
