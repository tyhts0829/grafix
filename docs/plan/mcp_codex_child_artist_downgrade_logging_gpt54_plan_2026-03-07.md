# MCP Codex Child Artist Downgrade Logging / GPT-5.4 Plan

> 注: この調査は nested child artist 廃止判断の根拠として残す。現行運用は [local_artist_primary_migration_plan_2026-03-07.md](local_artist_primary_migration_plan_2026-03-07.md) に従う。

## 目的

- child artist の失敗時に、起動環境の `CODEX_*` 系情報と実際の起動引数を run 配下へ残し、sandbox downgrade 条件を事後に確定できるようにする。
- child artist の起動モデルを `gpt-5.4` に固定し、ログ上でも確認できるようにする。

## 対象

- `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py`

## アクション

- [x] child 起動前に、run 配下へ保存してよい診断情報の範囲を整理する
- [x] child 用 `codex` 起動引数へ `gpt-5.4` 指定を追加する
- [x] child 起動前に `CODEX_*` / `TMP*` / `HOME` / `PWD` / `SHELL` などの診断情報と起動コマンドを `variant_dir` 配下へ保存する
- [x] child 失敗時に、診断ファイルへの参照がレスポンス payload から追えるようにする
- [x] 既存の成功/失敗フローを壊していないか、最低限の静的確認を行う

## 確認項目

- [x] 診断情報の保存先が `variant_dir` 配下に限定されている
- [x] `auth.json` など機微情報の実体はコピーせず、必要ならパスや存在有無だけを記録する
- [x] child ログで `model: gpt-5.4` を確認できる
- [x] 失敗時に `sandbox: ...` と `CODEX_*` 系情報を同じ variant から回収できる
