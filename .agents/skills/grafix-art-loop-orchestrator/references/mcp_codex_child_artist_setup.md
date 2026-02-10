# MCP: Codex CLI 子エージェント（artist）起動

目的: art loop の `artist` を、MCP tool 呼び出し 1 回で実行する。

この MCP サーバは、内部で `codex exec` を起動し、PROMPT 先頭で `$grafix-art-loop-artist` を指定して 1-shot 実行する。

## 追加される tools

- `art_loop.run_codex_artist`
- `art_loop.read_text_tail`

## 登録例（Codex CLI）

リポジトリ直下で:

```bash
codex mcp add grafix-art-loop-codex-child-artist -- \
  python .agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py
```

確認:

```bash
codex mcp list
```

