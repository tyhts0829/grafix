# 7bit_rel の仮想 CC 値同期（既存へジャンプ）チェックリスト（2026-01-04）

目的: `midi_mode="7bit_rel"`（相対 CC）でも、同じ CC を複数パラメータへ割り当てたときに値が同期して操作できるようにする。

- 既にその CC に「仮想値」が存在する場合、**新しく割り当てたパラメータは既存の仮想値へジャンプ**する（即座に同期）。
- 以後は Δ 入力が来るたびに **仮想値を更新し、同一 CC 割当の全パラメータへ同じ値を書き戻す**（差分が残らない）。
- 相対 CC の操作感（`ui_min/ui_max` 非依存）を維持する。

関連: `docs/plan/midi_relative_cc_rotary_encoder_2026-01-02.md`（相対 CC 基本対応 + プッシュの粗密切替）。

背景:

- 現状の `7bit_rel` は「各パラメータの現在 `ui_value` に Δ を加算」しているため、
  同じ CC に複数のパラメータを割り当てても **割当時点の差分がそのまま残る**。
- `7bit/14bit`（ポテンショメータ前提）は「CC の現在値（absolute）」があるため、
  別のパラメータに割り当て直しても **現在 CC 値へ同期（ジャンプ）する**のが便利だった。

方針（採用案）:

- `7bit_rel` でも CC 番号ごとに **仮想値（virtual）** を保持する。
  - この仮想値は 0..1 正規化ではなく、**`ui_value` の値域（= nudge の単位）**として扱う（min/max 非依存を維持するため）。
- Δ を受け取ったら、まず仮想値を更新し、その後 **同じ CC を持つ全パラメータへ同一値を適用**する。
- `cc_key` 変更（割当/解除）時:
  - **追加された CC** に仮想値があれば、その仮想値へ `ui_value` をジャンプ（`override=True`）。
  - 追加された CC に仮想値が無ければ、当該パラメータの現在値を仮想値として seed する（以後の基準になる）。

対象（v1）:

- rel の制御対象: `kind in {"int", "float", "vec3"}`
  - vec3 は成分ごと（`cc_key=(cc_x, cc_y, cc_z)`）に CC を割当できるため、仮想値も CC 番号ごとに保持する（= 1 CC = 1 成分値）。
- Note On/Off（押し込み）による粗密切替は既存仕様を踏襲（未押下 n 倍 / 押下 1 倍）。

非目的（v1 ではやらない）:

- CC ごとの「相対/絶対混在」設定の一般化
- Note 番号と CC 番号の任意マッピング（v1 は note==cc 固定）
- float/int/vec3 以外（choice/rgb など）の相対制御
- soft takeover / pickup

## 0) 事前に決める（あなたの確認が必要）

- [x] 同期方針: **既存の仮想値へジャンプ**（新規割当側の値で上書きしない）
- [ ] 同一 CC に複数 kind が混在した場合の扱い
  - 案A: 禁止（kind 不一致は同期対象外、ログのみ）
  - 案B: 許容（仮想値は float として保持し、int は round/cast で追従）
- [ ] 同一 CC に複数パラメータが割り当たった場合の `nudge_step` の扱い
  - 案A: 「最初に seed したパラメータの step」を CC の step として固定（以後は無視）
  - 案B: 「最小 step」を採用（粗さより破綻回避）

## 1) 受け入れ条件（完了の定義）

- [ ] `midi_mode="7bit"` / `"14bit"` の挙動が維持される
- [ ] `midi_mode="7bit_rel"` で、同一 CC に割当された複数パラメータが同期して動く（差分が残らない）
- [ ] `7bit_rel` で「既存の仮想値がある CC に新規割当」した場合、そのパラメータが既存仮想値へジャンプする
- [ ] jump は `override=True` として反映され、見た目/解決値に即座に効く
- [ ] `ui_min/ui_max` を変えても 1 step の増減量が変わらない（min/max 非依存）
- [ ] vec3 は成分ごとに同期できる（同じ CC の成分は同値へ揃う）
- [ ] `PYTHONPATH=src pytest -q tests/core/parameters/test_relative_cc_ops.py`
- [ ] `PYTHONPATH=src pytest -q tests/interactive/midi/test_midi_controller.py`

## 2) 実装（設計メモ）

- 仮想値の保持場所
  - [ ] `ParamStoreRuntime` に以下を追加（永続化しない）
    - `rel_cc_virtual_value_by_cc: dict[int, object]`
    - `rel_cc_virtual_step_by_cc: dict[int, float]`（または object）
    - （必要なら）`rel_cc_virtual_kind_by_cc: dict[int, str]`

- Δ 適用（同期込み）
  - [ ] `apply_relative_cc_deltas_to_store()` を「CC 単位」に変更する
    - 入力: `deltas: dict[int, int]`
    - 1) CC ごとに対象キー集合を集める
      - scalar: `state.cc_key == cc`
      - vec3: `state.cc_key` の各成分が `cc` に一致するキー（成分 index も保持）
    - 2) `rel_cc_virtual_*` から仮想値/step を取得（無ければ seed）
    - 3) `virtual += delta * step` で仮想値更新（int/float の扱いは 0) の決定に従う）
    - 4) 同一 CC の対象パラメータへ新しい仮想値を適用（vec3 は該当成分のみ更新）
    - 5) 適用した key は `override=True`

- CC 割当時のジャンプ
  - [ ] Parameter GUI の store 反映処理で「CC の追加」を検出し、jump/seed を行う
    - scalar: `cc_key: int`
    - vec3: `(a,b,c)` の各成分ごとに追加 CC を判定
  - [ ] 追加 CC に仮想値がある場合:
    - `ui_value` を仮想値へジャンプ（vec3 は該当成分のみ）
    - `override=True`
  - [ ] 追加 CC に仮想値が無い場合:
    - 現在の `ui_value`（/成分）を仮想値として seed する

## 3) 仕様（挙動の約束）

- [ ] 仮想値は `ui_value` の値域として扱い、`ui_min/ui_max` は参照しない
- [ ] 仮想値は CC 番号ごとに 1 つ（vec3 は「成分 CC」単位なので同じ）
- [ ] 新規割当は「既存仮想値へジャンプ」（仮想値が無ければ seed）
- [ ] 同一 CC に割当されたパラメータは、Δ 適用後に同値へ揃う（型/丸めは 0) の決定に従う）

## 4) 変更箇所（ファイル単位）

- [ ] `src/grafix/core/parameters/runtime.py`（rel 用 runtime state 追加）
- [ ] `src/grafix/core/parameters/relative_cc_ops.py`（同期ロジック + 仮想値更新）
- [ ] `src/grafix/interactive/parameter_gui/store_bridge.py`（CC 追加時のジャンプ/seed）
- [ ] `tests/core/parameters/test_relative_cc_ops.py`（同期 + ジャンプのテスト追加）

## 5) 手順（実装順）

- [ ] `ParamStoreRuntime` に rel 用 state を追加
- [ ] `apply_relative_cc_deltas_to_store()` を CC 単位へ組み替え（仮想値を更新し全員へ適用）
- [ ] store_bridge で cc_key 追加時に jump/seed を実装（vec3 も含む）
- [ ] テスト追加（同期・ジャンプ・vec3 成分）
- [ ] 最小確認: 対象テストを実行

## 6) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src pytest -q tests/core/parameters/test_relative_cc_ops.py`
- [ ] `PYTHONPATH=src pytest -q tests/interactive/midi/test_midi_controller.py`

## 7) 手動確認（実機）

- [ ] `run(..., midi_mode="7bit_rel")` で起動
- [ ] CC learn で A を CC7 に割当 → 回して A を調整（仮想値ができる）
- [ ] B を同じ CC7 に割当 → B が A の仮想値へジャンプして同期する
- [ ] CC7 を回すと A/B が差分なく一緒に動く
- [ ] vec3 の 1 成分だけ同じ CC に割当 → その成分のみ同期する

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] 「同一 CC に複数 kind 混在」を実際に使うか（使うなら 0) の案を早めに確定する）
