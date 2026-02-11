# 復旧: grafix-art-loop skill の MCP 利用ルール追記

作成日: 2026-02-10  
ステータス: 実施済み

## 目的

誤って差分が消えた `grafix-art-loop` の skill ファイルに、次の2点を復元する。

- orchestrator: MCP 経由の Codex CLI 子エージェントで artist を実行する運用追記
- artist: `variant_dir/artifact.json` と `stdout.txt` / `stderr.txt` 保存ルール追記

## チェックリスト

- [x] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` に MCP 利用セクションを復元する
- [x] `.agents/skills/grafix-art-loop-artist/SKILL.md` に artifact/stdout/stderr 保存ルールを復元する
- [x] 文字列検索で復元を確認する（`MCP（任意）` / `variant_dir/artifact.json`）

