# Art Loop: docstring取得MCPサーバ分離 実装計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 実施済み

## 目的

- `codex exec` 呼び出し役の `mcp_codex_child_artist_server.py` と、docstring 取得ツールを分離する。
- 実行系サーバが docs 依存で不安定化しない構成にする。

## 実装タスク

- [x] 現状確認（`mcp_codex_child_artist_server.py` が docs ツールを持たないこと）
- [x] docs 専用 MCP サーバを新規作成する
  - 追加先: `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_grafix_docs_server.py`
  - 追加 tool: `art_loop.get_op_docstrings`
- [x] `mcp_codex_child_artist_setup.md` から docs ツール記載を外す
- [x] docs サーバ用のセットアップ手順を新規追加する
  - 追加先: `.agents/skills/grafix-art-loop-orchestrator/references/mcp_grafix_docs_setup.md`
- [x] orchestrator SKILL の MCP セクションを2サーバ前提に更新する
- [x] 動作検証
  - [x] docs サーバの構文チェック
  - [x] `art_loop.get_op_docstrings` の `ok/not_found` 挙動確認
  - [x] `tools/list` に想定 tool が出ることを確認

## 完了条件

- [x] child-artist サーバは実行系 tool のみを提供
- [x] docs サーバで `art_loop.get_op_docstrings` が利用可能
- [x] 参照ドキュメントと SKILL の導線が分離後構成と一致
