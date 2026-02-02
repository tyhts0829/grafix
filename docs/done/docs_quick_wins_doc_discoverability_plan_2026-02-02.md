<!--
どこで: `docs/plan/docs_quick_wins_doc_discoverability_plan_2026-02-02.md`。
何を: ドキュメント/探索性の「すぐ効く」改善タスクの実行計画。
なぜ: コーディングエージェント/人間が `src/grafix/` を素早く理解し、変更作業に入れるようにするため。
-->

# Plan: ドキュメント/探索性の改善（A, 2026-02-02）

方針: コード変更なし。ドキュメント追加/追記のみ。

## 対象タスク

- [x] `docs/` に「開発者向け入口」1 枚を追加し、読む順番を固定する
  - 追加ファイル: `docs/developer_guide.md`
  - 含める内容:
    - まず読む: `README.md` / `architecture.md`
    - 入口（コード）: `src/grafix/api/*` → `src/grafix/core/pipeline.py` → `src/grafix/core/realize.py`
    - 変更パターン別: primitive/effect/preset/Parameter GUI/Export
    - 関連ツール: `python -m grafix list|stub|export`
- [x] `core/parameters` に “1 ファイルだけ読むならこれ” を明記したミニ README を置く
  - 追加ファイル: `src/grafix/core/parameters/README.md`
  - 含める内容:
    - `store_snapshot -> parameter_context -> resolve_params -> frame_params -> merge` の流れ
    - 主要ファイル/関数へのリンク
- [x] 用語集（Glossary）を追加する
  - 追加ファイル: `docs/glossary.md`
  - 含める用語（最小）:
    - `site_id`, `chain_id`, `ParamSnapshot`, `FrameParamsBuffer`, `explicit_args`
    - それぞれ 1〜2 行 + 参照先（ファイル/関数）
- [x] `python -m grafix` のサブコマンド一覧を `README.md` に追記する
  - 追記場所: `README.md`（短い CLI セクションを追加）
  - 最低限載せる: `list`, `stub`, `export`（可能なら `benchmark` も）

## 完了条件（受け入れ）

- 追加したドキュメントが相互にリンクし、初見で “読む順” と “触るべきファイル” が分かる
- `README.md` から `python -m grafix` の導線が見える
- 変更はドキュメントのみ（`.py` の挙動変更なし）

## 実施結果（作成/更新ファイル）

- `docs/developer_guide.md`（読む順/入口/変更パターン/CLI）
- `src/grafix/core/parameters/README.md`（parameters の最短フロー）
- `docs/glossary.md`（主要用語の定義）
- `README.md`（`python -m grafix` の `stub/export/benchmark` を追記）
