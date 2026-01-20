# Parameter GUI snippet に `name=` を出す（raw label のみ）: 実装計画（2026-01-20）

## 背景 / 課題

- `G(name="...")` / `E(name="...")` のラベルは、`site_id` が揺れたときの reconcile（旧→新の値引き継ぎ）に強いヒントになる。
- しかし現状の Parameter GUI の snippet 出力は、その `name` 情報をコードに戻せないため、
  「ラベルを付ける運用」をしても snippet 経由だとラベルが欠落してしまう。

## ゴール

- snippet が **ユーザーが明示的に付けたラベル（raw label）を検出できる場合のみ**、
  そのブロックの呼び出しを `G(name=...).<op>(...)` / `E(name=...).<op>(...)` の形で出力する。
- GUI 表示用の dedup（`name#1` など）や自動名（`text#2` など）は **コードに書き戻さない**。

## Non-goals（今回やらない）

- `site_id` 生成方式の変更（source位置化や明示 key 導入など）。
- reconcile アルゴリズムの改善。
- preset の reserved 引数（`name` / `key`）を snippet に含める対応。

## 方針（設計）

- raw label は `store_snapshot_for_gui()` の snapshot が持つ `label`（`(op, site_id)` 単位）を「真」とする。
- snippet は `GroupBlock.header`（表示名）ではなく、**raw label（永続化される label）**から `name=` を生成する。
- 既存 API を壊さないため、追加引数はすべて `None` デフォルトの **optional kwargs** とする。

## 変更範囲（想定ファイル）

- `src/grafix/interactive/parameter_gui/store_bridge.py`
  - snapshot から `raw_label_by_site: dict[tuple[str, str], str]` を構築して `render_parameter_table()` に渡す。
- `src/grafix/interactive/parameter_gui/table.py`
  - `render_parameter_table(..., raw_label_by_site=...)` を受け取り、`snippet_for_block()` 呼び出しへ渡す。
- `src/grafix/interactive/parameter_gui/snippet.py`
  - `snippet_for_block(..., raw_label_by_site=...)` を受け取り、
    - primitive: `G(name=<raw label>).<op>(...)`（raw label がある時だけ）
    - effect_chain: `E(name=<raw label>).<op>(...)...`（raw label がある時だけ）
    を出力する。
- `tests/interactive/parameter_gui/test_parameter_gui_snippet.py`
  - raw label あり/なしで出力が変わることを追加テストする。

## 実装タスク（チェックリスト）

- [x] `store_bridge.py` で `raw_label_by_site` を作る（`label is not None` かつ `strip()` が空でない場合のみ）
- [x] `table.py` で `render_parameter_table` に `raw_label_by_site: Mapping[tuple[str, str], str] | None = None` を追加し、snippet 呼び出しへ渡す
- [x] `snippet.py` で `raw_label_by_site` を使って `G(name=...)` / `E(name=...)` を条件付きで出力する
- [x] `test_parameter_gui_snippet.py` に以下を追加する
  - [x] primitive ブロック: raw label があると `G(name=...)` が出る / 無いと出ない
  - [x] effect_chain ブロック: raw label があると `E(name=...)` が出る / 無いと出ない
- [x] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_snippet.py` を実行して確認する

## 受け入れ条件（Definition of Done）

- 既存の snippet テストが通り、新規テストも通る。
- raw label が無いブロックの snippet は現状と同等（`name=` を勝手に増やさない）。
- raw label があるブロックの snippet は `G(name=...)` / `E(name=...)` を含む。
