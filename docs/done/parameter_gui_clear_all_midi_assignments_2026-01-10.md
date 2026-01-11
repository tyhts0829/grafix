# Parameter GUI: 全 MIDI アサイン一括クリア（2026-01-10）チェックリスト

目的: Parameter GUI に「全 MIDI アサインをクリア」ボタンを 1 つ追加し、押下で **全パラメータの `cc_key`（MIDI CC 割当）だけ**を解除する。解除後も、**MIDI により制御されていた値は解除時点の値で保持**する（値がジャンプしない）。

## 背景

- 現状は行単位で CC 割当/解除できるが、全解除を一括で行う導線がない。
- `cc_key` を外すと resolver の経路が変わるため、解除時に値が元へ戻る（ジャンプ）問題があり、行解除は「解除時点の effective を `ui_value` に焼き込む」方針で解決済み（`store_bridge._apply_updated_rows_to_store()`）。
- 一括解除でも同じ「焼き込み」を確実に通し、**アサインだけ消えて値は維持**を満たしたい。

## 0) 事前確認（採用）

- [x] クリア対象の範囲: **ParamStore 内の全キー**（GUI 非表示グループも含めて `cc_key` を全解除）
- [x] `runtime.last_effective_by_key` が無いキー: **bake をスキップして `cc_key` のみ外す**
- [x] ボタン文言/配置: 上部（スクロール外）に `Clear MIDI Assigns`

## 1) 受け入れ条件（完了の定義）

- [x] ボタン押下で、対象範囲の全パラメータについて `state.cc_key is None` になる
- [x] 解除前に MIDI で動いていたパラメータが、解除直後に **値ジャンプしない**
- [x] 解除後は MIDI CC 入力で値が変化しない（= 割当が消えている）
- [x] MIDI learn 中だった場合は解除時に learn がキャンセルされる（意図せぬ即時再割当を防ぐ）
- [x] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_cc_unassign_bake.py`
- [x] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_clear_all_midi_assignments.py`

## 2) 実装方針（採用案）

- 既存の「CC 解除時 bake」ロジック（`src/grafix/interactive/parameter_gui/store_bridge.py:_apply_updated_rows_to_store()`）を再利用する。
- 一括解除は「全行の `cc_key -> None`」という更新を作り、同じ差分適用経路で store へ反映する。
  - これにより scalar/vec3 の解除判定・bake 条件・`override=True` への切替が一元化される。
- learn 状態は GUI 側（`MidiLearnState`）でクリアする。

## 3) 変更箇所（ファイル単位）

- [x] `src/grafix/interactive/parameter_gui/gui.py`
  - ボタン追加（テーブルの上、monitor bar の下など）
  - クリック時に「全解除」処理を呼ぶ
  - learn 中なら `MidiLearnState` をキャンセル
- [x] `src/grafix/interactive/parameter_gui/store_bridge.py`
  - 一括解除ユーティリティを追加（例: `clear_all_midi_assignments(store) -> bool`）
    - `snapshot` 作成（0) の決定に従い `store_snapshot()` か `store_snapshot_for_gui()`）
    - `rows_before = rows_from_snapshot(snapshot)`
    - `rows_after = cc_key を None にした rows`
    - `_apply_updated_rows_to_store(...)` を呼ぶ（bake を通す）
    - 変更があったかを返す（GUI の `changed` に合成する）
- [x] `tests/interactive/parameter_gui/test_parameter_gui_clear_all_midi_assignments.py`（新規）
  - 複数キーに `cc_key` がある状態を作り、一括解除で
    - 全 `cc_key` が `None`
    - `last_effective_by_key` があるキーは `ui_value` が bake され `override=True`
  - 0) の「effective が無いキー」方針に応じた追加アサート

## 4) 手順（実装順）

- [x] 0) の事前確認を確定（対象範囲 / effective 無しの扱い / ボタン文言）
- [x] `store_bridge.py` に一括解除関数を追加（テストから先に呼べる形）
- [x] テスト追加（新規ファイル）→ 期待仕様が満たせることを固定
- [x] `gui.py` にボタンを追加し、押下で一括解除 + learn キャンセル
- [x] 対象テストを実行して最小確認

## 5) 手動確認（実機）

- [ ] Parameter GUI を起動
- [ ] いくつかのパラメータに CC learn で割当 → CC を動かして値が変わることを確認
- [ ] 「全 MIDI アサインをクリア」ボタンを押す
- [ ] 押下直後に値がジャンプしないことを確認
- [ ] 以後 CC を動かしても値が変わらないことを確認（割当解除）

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] 全解除を「戻せる」必要があるか（現状は undo 基盤が無いので、必要なら別途設計）
