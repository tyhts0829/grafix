# Local Artist Primary Migration Plan

## 目的

- grafix art loop の artist 実行を「ローカル実装が正」である状態に戻す。
- `codex exec` を入れ子起動する child artist 構想を取りやめ、run ごとの失敗要因と複雑さを減らす。
- skill / docs / 実装の説明を、実際の運用に揃える。

## 対象

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py`
- child artist 前提で残っている関連ドキュメント（必要最小限）

## 方針

- artist は「orchestrator 本体がローカルに `sketch.py` を実装し、ローカルで `grafix export` する」流れを正とする。
- `grafix-art-loop-codex-child-artist` MCP サーバと `art_loop.run_codex_artist` 契約は廃止する。
- 外部の `~/.codex/config.toml` はリポジトリ外のため、このタスクでは編集しない。必要なら別途手動整理前提とする。

## アクション

- [x] 現在の child artist 依存箇所を再確認し、削除対象を確定する
- [x] orchestrator skill から child artist MCP 前提の説明を除去し、ローカル artist 実行フローへ書き換える
- [x] `mcp_codex_child_artist_server.py` を削除する
- [x] child artist を前提とした「今後使う前提」の plan / reference を必要最小限で整理する
- [x] 変更後に child artist 参照が意図通り消えているか grep で確認する

## 確認項目

- [x] active な skill / reference から `art_loop.run_codex_artist` 前提が消えている
- [x] `grafix-art-loop-codex-child-artist` サーバ実装がリポジトリ内から除去されている
- [x] orchestrator の説明が「ローカル artist 実装」に揃っている
- [x] リポジトリ外設定を変更していない

## メモ

- `docs/plan/` 内の child artist 関連文書は削除せず、現行では使わない履歴として注記を付けた。
