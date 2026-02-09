# Grafix Art Loop runディレクトリ生成ツール実装計画（2026-02-09）

作成日: 2026-02-09  
ステータス: 提案（未実装）

## 背景

- Art Loop の出力は `sketch/agent_loop/runs/<run_id>/...` 配下に集約する。
- run のたびに手で `run_id` を決めてディレクトリを掘るのは機械作業であり、ミス（出力境界逸脱、命名揺れ、iter/vディレクトリ欠損）の温床になる。
- 現状、run 名が複数パターン混在している（例: `run_YYYYMMDD_HHMMSS_*`, `run_YYYYMMDD_001`, suffix にテーマ名等）。
- `sketch/agent_loop/runs/.latest_run_id` / `.last_run_id` が存在する（運用メモとして活用できるが、skill 本体から参照されているわけではない）。

## 目的

- run 生成を「固定 I/F のスクリプト 1 本」で再現可能にする。
- 生成される run 配下のディレクトリ構造を固定し、後続処理（artist/critic/contact_sheet）からの参照を安定化する。

## 非目的

- ideaman/artist/critic の role をツールに置換しない。
- run の中身（JSON 生成、レンダリング、contact sheet）までは本ツールの責務に含めない。
- 既存 run のリネームや移行はしない（新規 run の生成に限定）。

## 現状観測（代表例）

- run ルート: `sketch/agent_loop/runs/run_20260209_214538_n4m8_a5/`
  - `.tmp/`
  - `iter_01/ ... iter_04/`
    - `v01/ ... v08/`（または `v1 ... v8` の run も存在）
  - `run_summary/`

## 実装対象（予定）

- `.agents/skills/grafix-art-loop-orchestrator/scripts/init_run_dir.py`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`（標準コマンド追記）
- （任意）`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`（run 配下メタの追加が必要なら）

## 仕様案（スクリプト I/F）

### CLI 引数

- `--n <int>`: iteration 数（例: `4`）
- `--m <int>`: variant 数（例: `8`）
- `--run-id <str>`: run_id を直接指定（指定時も `run_YYYYMMDD_HHMMSS_n{n}m{m}` 形式に制限する）
- `--root <path>`: 生成先 root（既定 `sketch/agent_loop/runs`）
- `--dry-run`: 生成せずに、作成予定のパス一覧だけ出力
- （任意）`--update-latest`: `.latest_run_id` / `.last_run_id` を更新する

### run_id 生成規則（案）

- 既定:
  - `run_YYYYMMDD_HHMMSS_n{n}m{m}` のみに固定する（attempt/tag suffix は使わない）
- 例:
  - `run_20260209_214538_n4m8`
  - `run_20260209_231500_n8m12`

### 生成するディレクトリ（案）

- `<root>/<run_id>/`
- `<root>/<run_id>/.tmp/`（一時作業用。常に作る）
- `<root>/<run_id>/run_summary/`（最終成果物置き場。常に作る）
- `<root>/<run_id>/iter_XX/`（`XX=01..N` を作る）
- `<root>/<run_id>/iter_XX/vYY/`（`YY=01..M` を作る。zero pad は `M` 桁数に合わせる）

## 実装タスク（チェックリスト）

### 1) 仕様確定

- [ ] run_id 生成規則を確定する（`run_YYYYMMDD_HHMMSS_n{n}m{m}` のみに固定）。
- [ ] variant ディレクトリ名を確定する（`v1` か `v01` か。新規 run は `vYY` を推奨）。
- [ ] `.latest_run_id` / `.last_run_id` を更新するかを決める（更新するなら opt-in を推奨）。

### 2) スクリプト実装

- [ ] `init_run_dir.py` を追加する。
- [ ] `--dry-run` を実装する（mkdir せず計画表示のみ）。
- [ ] 実行結果として `run_id` と `run_dir` を 1 行で出力する（後続から拾いやすくする）。
- [ ] 出力先が `sketch/agent_loop/runs` 配下であることを前提にし、境界逸脱を避ける（必要最小の検証に留める）。
- [ ] `--update-latest` 指定時のみ `.latest_run_id` / `.last_run_id` を更新する。

### 3) skills への接続

- [ ] orchestrator の `SKILL.md` に run 作成の標準コマンドを追記する。
- [ ] 生成後の run ルート配下以外に出力しない運用（`.tmp` も run 配下）を再掲する。

### 4) 検証

- [ ] `--dry-run` で作成予定パスが期待どおり出ること。
- [ ] 実生成して、`iter_01..iter_N` と `vYY` が揃うこと。
- [ ] 生成物が `sketch/agent_loop/runs/<run_id>/` 配下に限定されること。
- [ ] `--update-latest` 指定時のみ `.latest_run_id` が更新されること。

## 受け入れ条件（DoD）

- [ ] `init_run_dir.py` だけで run ディレクトリ骨格が生成できる。
- [ ] run_id が一定の規則で生成され、run 間で揺れない。
- [ ] 新規 run の variant ディレクトリ命名が固定される（推奨: `vYY`）。
- [ ] `--dry-run` があり、危険な mkdir が先に見える。

## 実装開始前確認

- [ ] この計画で実装に進めてよいか、ユーザー承認を得る。
