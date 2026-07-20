<!--
どこで: `docs/plan/adaptive_choice_widget_implementation_plan_2026-07-20.md`。
何を: Parameter GUI の choice を、利用可能幅と候補数に応じて radio / combo へ切り替える実装手順を定義する。
なぜ: choice 候補が control 列からはみ出す問題を、metadata schema を増やさず一貫した UI で解消するため。
-->

# Adaptive choice widget 実装計画

- 作成日: 2026-07-20
- 状態: **完了**
- 対象:
  - `src/grafix/interactive/parameter_gui/widgets.py`
  - choice widget / selector target の GUI tests
- 前提:
  - 現在の未コミット差分は selector 実装の成果物として維持し、巻き戻さない。
  - `ParamMeta`、codec、stub の schema は増やさない。

## 1. 目的

`ParamMeta(kind="choice")` の候補を常に横一列の radio button として描画すると、
候補数やラベル長によって Parameter GUI の control 列からはみ出す。

choice の値契約は変えず、表示だけを次の adaptive widget にする。

1. 少数かつ現在の列幅へ収まる場合: inline radio
2. 収まらない場合: combo
3. 候補が多い場合: popup 内検索付き combo

## 2. UI 契約

### 2.1 Radio / combo の自動選択

- radio は候補数が 4 件以下の場合だけ候補にする。
- `imgui.get_content_region_available_width()` または互換 API から control cell の幅を取得する。
- `imgui.calc_text_size()` と行高から radio indicator、label、item spacing の必要幅を見積もる。
- 必要幅が利用可能幅以下なら radio、それ以外は combo にする。
- 幅取得 API が無い場合は 4 件以下を radio、5 件以上を combo とする。
- `begin_combo` 自体が無い古い backend/test double だけは、機能を失わないよう radio に戻す。
- selector の `target` は catalog が増減するため、候補数にかかわらず combo を維持する。

### 2.2 検索付き combo

- 候補が 8 件以上の場合だけ popup 先頭へ filter input を表示する。
- filter は空白区切り AND、case-insensitive とする。
- 一致候補が無い場合は `No match` を表示する。
- filter は `(op, site_id, arg)` 単位の一時 UI state とし、ParamStore へ永続化しない。
- 値を選択したら filter を空へ戻す。
- popup は `COMBO_HEIGHT_LARGE` を使って高さを制限し、既存 scroll 挙動を使う。
  table row 自体は縦長にしない。

### 2.3 値・override 契約

- valid な現在値は radio/combo の切替で変更しない。
- 通常 choice の choices 外値は、既存契約どおり先頭候補へ丸める。
- selector target の catalog から消えた値は、既存契約どおり
  `"<value> (unavailable)"` と表示し、明示選択まで変更しない。
- combo を開閉しただけでは `changed=False` とする。
- 候補の明示選択時だけ選択値を返し、table 側の既存 override 自動有効化規則を使う。

## 3. 実装アクション

- [x] ユーザーが本計画を承認した。
- [x] 利用可能幅を backend 互換で取得する小さな helper を追加する。
- [x] radio に必要な描画幅を現在の font scale から見積もる純粋判定を追加する。
- [x] choice label 用の AND filter helper と一時 filter state を追加する。
- [x] 現在の `widget_choice_radio` を adaptive choice widget へ整理する。
- [x] radio 描画と combo 描画を小さな内部関数へ分離する。
- [x] selector target 専用分岐を共通 combo 経路へ統合する。
- [x] public `ParamMeta` や persistence schema を変更していないことを確認する。

## 4. テスト

- [x] 少数・短い候補が十分な幅で radio になる。
- [x] 同じ候補が狭い幅では combo になる。
- [x] 少数でも長い label は combo になる。
- [x] 5 件以上は十分な幅でも combo になる。
- [x] UI scale が変わっても text/frame/available の同比率なら判定が変わらない。
- [x] 8 件以上では filter input が表示され、AND/case-insensitive で絞り込める。
- [x] filter 0 件時に `No match` を表示する。
- [x] combo の開閉だけでは値を変更しない。
- [x] combo 選択が正しい値と `changed=True` を返す。
- [x] 通常 choice の既存 choices 外値丸めを維持する。
- [x] selector の removed target を暗黙変更せず、明示選択で復旧できる。
- [x] 既存の selector GUI / auto-override tests を通す。

## 5. 検証

- [x] choice / selector / Parameter GUI focused tests
- [x] full pytest
- [x] 変更対象 Ruff
- [x] `mypy src/grafix`
- [x] `git diff --check`
- [x] 実 Parameter GUI で、広幅 radio・狭幅 combo・検索付き大量候補を目視確認する。

検証結果:

- adaptive choice 専用 tests: `18 passed`
- choice / selector / Parameter GUI focused tests: `64 passed`
- full pytest: `2177 passed, 2 skipped`
- mypy: `Success: no issues found in 228 source files`
- Ruff（変更対象）: passed
- `git diff --check`: passed
- 実 GUI:
  - 幅 1100 px で `G.sphere` の 3〜4 候補が inline radio になることを確認した。
  - 幅 760 px で同じ候補が combo へ切り替わり、列外へはみ出さないことを確認した。
  - `G.polyhedron.kind` の 20 候補で検索欄と scroll を確認した。
  - `snub left` の AND 検索、明示選択、選択後の filter clear を確認した。

## 6. 完了条件

- choice が control 列からはみ出さない。
- 少数候補では radio の即時性を維持する。
- 多数候補は検索可能で、table row の高さを常時増やさない。
- selector target の stale catalog 復旧契約を壊さない。
- metadata / persistence / public API を複雑化しない。
