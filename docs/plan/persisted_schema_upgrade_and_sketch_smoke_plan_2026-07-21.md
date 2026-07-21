# 永続スキーマ一括更新・sketch 実行復旧計画（2026-07-21）

作成日: 2026-07-21

基準 HEAD: `0b0e647`

ステータス: **完了**

## 1. 目的

旧形式のローカル永続データを、runtime に旧 decoder、migration shim、互換 fallback を
追加せず、一回限りのデータ変換で現行仕様へ更新する。更新後は、通常保守対象の
`sketch/` entrypoint が保存済みデータ込みで 1 frame 描画できることを確認する。

今回の再現対象は `sketch/readme/top_movie.py` 起動時の
`ParamStore schema_version 3; expected 4` である。

## 2. 事前棚卸し

| schema family | 件数 | 現状 | 最新 | 方針 |
|---|---:|---|---|---|
| ParamStore | 76 | 全件 v3 | v4 | 全件変換 |
| MIDI CC snapshot | 68 | 全件 versionless flat mapping | v1 | 全件変換 |
| WorkspaceState | 11 | 全件 v1 | v1 | 検証のみ |
| runtime config | 2 | 全件 v1 | v1 | 検証のみ |
| capture manifest | 9 | 全件 v3 | v3 | 検証のみ |
| active BenchmarkRun | 1 | v4 | v4 | 検証のみ |

- ParamStore は `data/output/param_store/**/*.json` 75件と
  `.grafix/data/output/param_store/**/*.json` 1件。session recovery 1件を含む。
- MIDI は `data/output/midi/**/*.json` 68件、合計377 CC assignment。
- ParamStore の dry-run 変換は **76/76件成功、decode issue 0**。
- MIDI の dry-run 変換は **68/68件成功**。全 CC/value は現行範囲内。
- `top_movie` は一時変換データを使った非 GUI 1 frame 描画に成功済み。

### 2.1 benchmark legacy の扱い

`data/output/benchmarks/legacy/` の旧 BenchmarkRun 19件
（schema v2 3件、versionless 16件）は、欠落した provenance/checksum/measurement 情報を
捏造せず、historical archive として exact bytes を維持する。これらは active reader や
sketch 起動から参照されず、v4 への正しい更新手段は旧計測の再実行だけである。
custom report JSON 3件も BenchmarkRun schema ではないため変換対象にしない。

## 3. 安全境界

- [x] 作業開始時に `git status --porcelain` を確認した。
- [x] 既存の大規模作業差分を確認し、本作業では巻き戻し・整理しない。
- [x] 全 schema-bearing JSON/YAML を棚卸しした。
- [x] 変換対象144件をメモリ上で事前変換し、現行 parser で検証した。
- [x] 本計画についてユーザー承認を得る。
- [x] write 直前の全件 SHA-256/stat 再照合で、変換中の外部更新がないことを確認した。
- [x] production に旧 schema reader、自動 migration、shim を追加しない。
- [x] invalid/unknown/future schema を推測変換せず、1件でもあれば write 前に全体中止する。
- [x] 原本の mode と mtime_ns を維持し、primary/session recovery の選択順を変えない。

## 4. Phase 1 — 原本固定と全件 preflight

- [x] 144件すべてが通常ファイルであり、対象集合が棚卸し時から変わっていないことを確認する。
- [x] duplicate JSON key、NaN/Infinity、不正 Unicode、未知 field を strict に拒否する。
- [x] 全原本の相対 path、size、mode、mtime_ns、SHA-256 を manifest 化する。
- [x] `/private/tmp/grafix-schema-upgrade-20260721/original/` へ相対 path を保って exact backup する。
- [x] backup の SHA-256 が原本と一致することを確認する。
- [x] commit 直前に原本の SHA-256/stat を再確認し、外部変更があれば全体中止する。

## 5. Phase 2 — ParamStore v3 → v4

- [x] `schema_version` を exact int `4` に更新する。
- [x] `ui.collapsed_headers` の旧文字列 ID を v4 tagged record へ変換する。
  - `style:global` → `{"kind": "style"}`
  - `effect_chain:<id>` → `{"kind": "effect_chain", "chain_id": "<id>"}`
  - `primitive:<op>:<site>` / `preset:<op>:<site>` →
    `{"kind": ..., "op": "<op>", "site_id": "<site>"}`
- [x] operation header は `split(":", 2)` で site ID 内の colon を保持し、曖昧な入力は拒否する。
- [x] state/meta 5,579件、effect step 396件、collapsed header 78件などの意味値・件数を保持する。
- [x] session recovery を含め、現行 decoder で76/76件 issue 0を確認する。
- [x] 現行 encoder による再出力が二回目には byte 差分を生まないことを確認する。

## 6. Phase 3 — MIDI snapshot → schema v1

- [x] 旧 `{cc_string: float}` を
  `{"schema_version": 1, "values": [{"cc": int, "value": float}, ...]}` へ変換する。
- [x] CC は exact decimal `0..127`、value は finite exact float `0.0..1.0` として検証する。
- [x] record は CC 昇順にし、重複を拒否する。
- [x] 空 `{}` 26件も空の v1 payload へ更新する。
- [x] 377 assignment の CC/value が変換前後で一致することを確認する。
- [x] public `load_cc_snapshot()` で68/68件が `status="loaded"` になることを確認する。

## 7. Phase 4 — 原子的な一括置換

- [x] 全変換結果を write 前に現行 pure decoder で再検証する。
- [x] 各 target と同一 directory の private temp file を fsync してから `os.replace()` する。
- [x] file mode と atime_ns/mtime_ns を原本値へ戻す。
- [x] 途中失敗時は backup から置換済み target を復元し、部分更新を残さない。
- [x] 変換後 SHA-256 と変換対象一覧を backup manifest へ記録する。
- [x] repository に one-shot converter を残さない。

## 8. Phase 5 — schema 全件検証

- [x] ParamStore 76件: schema v4、strict decode issue 0、load/recovery 成功。
- [x] MIDI 68件: schema v1、public loader `loaded`、377値一致。
- [x] Workspace 11件: 現行 v1 loader 成功。
- [x] config 2件: 現行 v1 validation 成功。
- [x] capture manifest 9件: 現行 v3 と一致。
- [x] active BenchmarkRun 1件: 現行 v4 reader 成功。
- [x] repository 全体を再走査し、active writable state に旧 schema が残っていないことを確認する。

## 9. Phase 6 — sketch 実行検証

通常保守対象は `agent_loop` の履歴成果物を除く65 Python files。そのうち `draw` と
main guard を持つ実行 entrypoint は52件である。

- [x] 全65 files を副作用なしで構文 compile する。
- [x] 既存 `tests/sketch/test_active_sketch_entrypoints.py` を実行し、52 entrypoint の
  code-state 1 frame 描画と inventory test を通す。
- [x] 52 entrypoint を個別 subprocess で実行し、実際の `run()` 引数から既定 path を計算する。
- [x] persistence 有効な entrypoint は `parameter_source="recovery"` で保存済み ParamStore を読み、
  1 frame を final quality で描画する。
- [x] MIDI/Workspace は各 entrypoint の実際の既定 pathを public loader で preflight する。
- [x] missing file は現行仕様どおり空/default として成功し、旧 schema だけが残らないことを確認する。
- [x] `sketch/readme/top_movie.py` は専用 smoke で ParamStore v4、MIDI v1、Workspace v1 を読み、
  1 frame・1 layer の描画成功を確認する。
- [x] strict API 変更に起因する sketch 本体の失敗が見つかった場合は、互換 layer を作らず
  当該 script を現行 API へ直接更新し、同じ smoke を再実行する。

## 10. Phase 7 — regression と完了記録

- [x] parameters persistence/codec/recovery、MIDI persistence、Workspace の focused tests。
- [x] sketch headless tests。
- [x] `PYTHONPATH=src pytest -q`。
- [x] `mypy src/grafix` と `ruff check src tests tools`。
- [x] `git diff --check`。
- [x] 本計画の全項目を更新し、変換件数、backup path、検証結果、既知 failure を追記する。

## 11. 完了条件

- [x] writable runtime state 144件がすべて現行 schema で strict load できる。
- [x] 既に最新だった schema family も現行 validator で全件成功する。
- [x] 通常保守対象52 entrypointが code-state と saved/recovery-state の双方で描画できる。
- [x] `top_movie.py` の提示された schema error が再現しない。
- [x] runtime へ旧 decoder、migration shim、silent fallback を追加していない。
- [x] 未完了項目と historical benchmark legacy の扱いが明記されている。

## 12. 実施結果

### 12.1 更新

- ParamStore 76件を v3 から v4 へ更新した。
  - state/meta 各5,579件、effect step 396件、collapsed header 78件を保持した。
  - variation は全件空であり、意味値を捏造する変換は発生していない。
  - 唯一の session recovery は primary より新しい `mtime_ns` を exact に維持し、
    `load_param_store_with_recovery()` が `session_recovery` を選択することを確認した。
- MIDI snapshot 68件を versionless mapping から v1 へ更新した。
  - 377 assignment を保持し、空 snapshot 26件も現行の空 payload に更新した。
- Workspace 11件、runtime config 2件、capture manifest 9件、active BenchmarkRun 1件は
  既に現行 version だったため、変更せず現行 validator で再検証した。
- historical BenchmarkRun 19件（versionless 16件、v2 3件）は runtime 非参照の履歴として
  変更せず保持した。
- production code、互換 reader、migration shim、fallback は追加していない。

### 12.2 安全性

- 変換前原本144件を
  `/private/tmp/grafix-schema-upgrade-20260721/original/` に相対 path のまま保存した。
- `/private/tmp/grafix-schema-upgrade-20260721/manifest.json` に原本/変換後の SHA-256、
  size、mode、atime/mtime、schema version、意味件数を記録した。
- 全144件について backup hash、変換後 hash、mode、atime_ns、mtime_ns を再照合した。
- 現行 encoder による再出力は全件 byte-idempotent だった。

### 12.3 検証

- schema 全件検証: 成功。
  - ParamStore 76/76件: v4、decode issue 0。
  - MIDI 68/68件: v1、public loader `loaded`、377値一致。
  - Workspace 11/11件、config 2/2件、capture 9/9件、active benchmark 1/1件: 成功。
- sketch 構文 compile: 65/65 files 成功。
- code-state sketch test: 53 tests passed（52 entrypoint + inventory）。
- saved/recovery-state smoke: 52/52 entrypoint 成功。
  - persistence 有効51件は `parameter_source="recovery"`、無効1件は `"code"`。
  - MIDI は loaded 47件/missing 5件、Workspace は loaded 5件/missing 47件。
  - missing は現行仕様の default 経路で成功した。
- `sketch/readme/top_movie.py`: ParamStore v4、MIDI v1、Workspace v1 を読み、
  final quality 1 frame・1 layer の描画に成功した。
- focused tests: 248 passed。
- full suite: 3,601 passed、失敗0件。既存 multiprocessing resource tracker warning 6件のみ。
- mypy: 240 source files、issue 0。
- Ruff: 全対象成功。
- `git diff --check`: 成功。
