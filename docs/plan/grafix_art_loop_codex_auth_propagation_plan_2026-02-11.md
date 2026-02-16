# Grafix Art Loop: CODEX_HOME分離時の認証伝搬（401回避）計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 実装中（一部実施）

## 背景 / 問題

- `art_loop.run_codex_artist` の並列実行のため、子プロセス `codex exec` に `CODEX_HOME=variant_dir/.codex_home` を設定した。
- その結果、Codex CLI が通常参照する `~/.codex/auth.json`（デバイス認証/OAuth のトークン）が見えなくなり、初回から `401 Unauthorized`（Missing bearer）で全 variant が失敗し得る。
- 現環境の `~/.codex/auth.json` は `OPENAI_API_KEY=null` で、OAuth トークン（`tokens.access_token` / `refresh_token`）が保存されている。
  - よって「`auth.json` から `OPENAI_API_KEY` を読み取り env 注入」はそのままだと成立しない。

## 目的

- `CODEX_HOME` を variant ごとに分離したまま、`codex exec` が確実に認証できるようにする。
- run 生成物（`variant_dir`）に **秘密情報のコピー**を残さない（少なくとも複製はしない）。
- OAuth トークン更新（refresh）により、並列実行が壊れないようにする。

## 方針（優先順）

### OAuth の場合: auth.json を「複製せず」共有

- `variant_dir/.codex_home/auth.json` を **symlink** で `~/.codex/auth.json` に向ける。
  - 目的: secret の複製を避けつつ、refresh によるトークン更新を単一のストアに集約する。
  - 「コピーで各 variant が同一 refresh_token を持つ」状況を避け、refresh 競合を最小化する。
- 必要なら `config.toml` も symlink して、子プロセスの挙動（モデル等）を親と揃える。

### C) 最終手段: CODEX_HOME 分離をやめる

- `CODEX_HOME` を設定しない（=`~/.codex` をそのまま使う）。
- 401 は解消するが、state/履歴等の分離が崩れるため採用は最後。

## 実装タスク（チェックリスト）

### 0) 現状確認

- [ ] `~/.codex/auth.json` の認証モードを確認する（API key か OAuth か）。
- [ ] `401 Unauthorized: Missing bearer` の再現ログ（`codex_stderr.txt`）を確認する。

### 1) 伝搬ロジック追加（A/B）

- [x] `.agents/skills/grafix-art-loop-orchestrator/scripts/mcp_codex_child_artist_server.py` に「子プロセス起動前の認証準備」を追加する。
- [x] `OPENAI_API_KEY` が無い場合は、`variant_dir/.codex_home/auth.json` を `~/.codex/auth.json`（または親の `CODEX_HOME` 配下）に symlink する。
  - [ ] 既に存在する場合は上書きしない（安全側）。
  - [ ] symlink 不可環境では明確なエラーを返す。
- [ ] （任意）`variant_dir/.codex_home/config.toml` を `~/.codex/config.toml` に symlink する。

### 2) ドキュメント更新

- [ ] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` に「並列実行時の認証前提」を追記する。
  - [ ] 推奨: 事前に `codex login` 済みであること。

### 3) 検証

- [ ] `CODEX_HOME` 分離ありで `v01〜v04` を並列実行し、401 が消えること。
- [ ] 失敗時も `server_queue_ms` などが返り、原因が追えること。

## 受け入れ条件（DoD）

- [ ] `CODEX_HOME=variant_dir/.codex_home` のまま `codex exec` が認証できる（401が出ない）。
- [ ] `variant_dir` に秘密情報の **コピー**が残らない（少なくとも `auth.json` の複製はしない）。
