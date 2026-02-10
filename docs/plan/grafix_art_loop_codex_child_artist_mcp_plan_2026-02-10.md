# Grafix Art Loop: MCP 経由で Codex CLI 子エージェントに artist を任せる計画

作成日: 2026-02-10  
ステータス: 提案（未実装）

## 背景

- `mcp_artist.md` の方針（MCP は「実行・検証・集約」を担い、role の創作判断は LLM に残す / stdio MCP / ツール契約の先行固定 / workspace 分離）を踏まえ、art loop の安定性と反復速度を上げたい。
- 現状の `artist` は「M 体のサブエージェントで独立実装」として設計されているが、運用上は **orchestrator の会話コンテキスト肥大**と **実行手順のブレ**が起きやすい。
- そこで、`grafix-art-loop-artist` を **MCP ツール呼び出し 1 回**に畳み、Codex CLI を別プロセスで起動して「子エージェント（artist role）」に任せる。

## 目的

- orchestrator からは `art_loop.run_codex_artist(variant_dir)` を呼ぶだけで、`variant_dir` 配下に `sketch.py` / `out.png` / `artifact.json` / `stdout.txt` / `stderr.txt` が揃う。
- `artist` の会話ログや長い stdout/stderr を orchestrator 側へ貼らずに済む（返却は短い構造化 JSON に限定）。
- M 並列でも衝突しない（`variant_dir` 分離 + `CODEX_HOME`/`TMPDIR` 分離）。

## 非目的

- ideaman/critic/artist の創作判断を固定スクリプトやテンプレ生成に置換すること（role は LLM のまま）。
- Grafix のレンダリング実行そのものを MCP 化すること（この計画では「Codex CLI 子エージェント起動」が主題）。
- run の出力境界（`sketch/agent_loop/runs/<run_id>/` 配下のみ）を緩めること。

## 方針（`mcp_artist.md` の反映）

- MCP サーバは stdio で起動（Codex/Agents SDK どちらからでも呼べる形）。
- ツール契約（引数・返却 JSON）を先に固定し、ログや巨大データの返却を避ける。
- `variant_dir` を “workspace” とみなし、実行・ログ・成果物を **必ず** `variant_dir` 配下へ閉じ込める。
- 実行環境の不確定要素（`/tmp`、Codex の状態ディレクトリ）を最小化するため、`TMPDIR` と `CODEX_HOME` を `variant_dir` 配下へ向ける。

## ツール契約（案）

### Tool: `art_loop.run_codex_artist`

入力（最小）:

- `variant_dir`: `sketch/agent_loop/runs/<run_id>/iter_XX/vYY`（相対/絶対どちらでもよいが、正規化後に許可パス配下であること）
- `timeout_s`: 例 `900`（デフォルトあり）

前提ファイル（`variant_dir` 内）:

- `artist_context.json`（orchestrator が作成。`schemas.md` の `ArtistContext`）
- `creative_brief.json`（orchestrator が作成。`schemas.md` の `CreativeBrief`）

出力（短い構造化 JSON）:

- `status`: `success|failed`
- `artifact_json_path`: 例 `.../artifact.json`
- `stdout_path` / `stderr_path`
- `elapsed_ms`
- `error_summary`（失敗時のみ、先頭数行）

### Tool: `art_loop.read_text_tail`（任意・必要になったら）

- 入力: `path`, `max_chars`
- 出力: `tail`（LLM に渡すのは必要なときだけ）

## 実装タスク（チェックリスト）

### 0) 仕様確定（先に決める）

- [ ] Codex CLI の **非対話実行**の確定（skill 指定方法 / 1-shot 実行方法 / 終了条件）。
- [ ] Codex CLI 呼び出し時の **作業ディレクトリ**（`cwd`）の確定（原則 `variant_dir`）。
- [ ] 子エージェントが読む入力を `artist_context.json` に一本化するか、追加の「追記指示」を tool 引数に持つか決める（推奨: まずは JSON 一本化）。
- [ ] MCP 実装に `mcp` Python SDK を追加するか決める（依存追加は Ask-first）。

### 1) MCP サーバ（stdio）を追加

- [ ] 配置場所を決める（例: `.agents/mcp_servers/grafix_art_loop_codex_runner/`）。
- [ ] `art_loop.run_codex_artist` を実装する。
- [ ] パス検証（`variant_dir` が `sketch/agent_loop/runs/` 配下であること、`..` 脱出禁止）。
- [ ] `TMPDIR` を `variant_dir/.tmp`、`CODEX_HOME` を `variant_dir/.codex_home` へ固定する。
- [ ] Codex CLI をサブプロセス実行し、`stdout.txt` / `stderr.txt` を `variant_dir` へ保存する。
- [ ] 成功/失敗に関わらず `artifact.json` を `variant_dir` に残す（`schemas.md` の `Artifact` 準拠）。
- [ ] MCP 返却は短い JSON のみにする（ログ全文は返さない）。

### 2) skills 側の接続（artist を MCP 呼び出しへ）

- [ ] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` に「artist は `art_loop.run_codex_artist` を呼ぶ」運用を追記する。
- [ ] `.agents/skills/grafix-art-loop-artist/SKILL.md` に「入力は `variant_dir/artist_context.json`、成果物は `variant_dir` に保存（`artifact.json` を含む）」を明記する。
- [ ] 必要なら `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md` に MCP 呼び出しの最小例を追記する。

### 3) 動作確認（最小スモーク）

- [ ] N=1, M=1 で `variant_dir` に成果物が揃うこと（`out.png`/`artifact.json`/ログ）。
- [ ] N=1, M=4 で衝突しないこと（並列実行時にログ・状態が混ざらない）。
- [ ] `/tmp` を使っていないこと（`TMPDIR` の効き確認）。
- [ ] 失敗時に `error_summary` が短く返り、詳細は `stderr.txt` で追えること。

## 受け入れ条件（DoD）

- [ ] orchestrator から見て artist 実行が「ツール 1 回」に固定され、手順ブレが消える。
- [ ] `variant_dir` 配下に `sketch.py` / `out.png` / `artifact.json` / `stdout.txt` / `stderr.txt` が揃う。
- [ ] MCP の返却が短い構造化 JSON に収まり、会話コンテキストを圧迫しない。
- [ ] M 並列でも `CODEX_HOME`/`TMPDIR` が分離され、状態衝突が起きない。

## 実装前に確認したい点（質問）

- Codex CLI を tool から起動するコマンド形は何を採用しますか？（例: `codex run --skill grafix-art-loop-artist --message ...` のような 1-shot 起動が可能か）
- `mcp` Python SDK の依存追加をしてよいですか？（Yes の場合、`pyproject.toml` に extras で追加する想定）；こちらで入れました。
