# Grafix Art Loop: GrafixAdapter 統合計画（2026-02-07）

対象:
- `./.codex/skills/grafix-art-loop-orchestrator/scripts/`

目的:
- `run_one_iter.py` の標準レンダリングを `python -m grafix export` に固定し、artist は「コード生成」に集中できるようにする。
- 既存要件どおり、全出力は `sketch/agent_loop` 配下に保存する。

## 実装チェックリスト

### 1) Adapter 追加

- [x] `grafix_adapter.py` を追加
- [x] `GrafixAdapter.render(...)` を実装（`python -m grafix export` 呼び出し）
- [x] `RenderResult` に `stdout/stderr/exit_code/output_path` を保持

### 2) run_one_iter 統合

- [x] artist 成果物が画像未生成でも `code_ref` があれば Adapter でレンダリングする
- [x] `callable_ref` を優先し、未指定時は `code_ref` から `module:draw` を推定する
- [x] canvas は `CreativeBrief.constraints.canvas` を優先、未指定時は `(800, 800)`
- [x] render ログを `variant_dir` に保存する
- [x] レンダリング結果でも `sketch/agent_loop` 配下以外を拒否する

### 3) 仕様更新

- [x] `SKILL.md` に「標準は GrafixAdapter レンダー」を追記
- [x] `references/schemas.md` に `Artifact.callable_ref`（任意）を追記

### 4) 検証

- [x] 構文チェック（`py_compile`）
- [x] `python -m grafix export` を実際に使うスモーク実行（`run_one_iter.py`）
- [x] 出力が `sketch/agent_loop/runs/...` のみであることを確認
