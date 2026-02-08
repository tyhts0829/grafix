# Grafix Art Loop: `postrun_context_hints.md` + `art_loop_mcp.md` 対応改善計画

作成日: 2026-02-08
ステータス: 提案（未実装）

## 背景

- `postrun_context_hints.md` で、毎 run で繰り返し調査している情報と運用の抜けが列挙された。
- `art_loop_mcp.md` で、MCP は「創作判断」ではなく「実行・検証・集約」に限定すると有効、という方針が示された。
- 既存の `skills_context_audit` 計画だけでは、引数クイック表・失敗分岐・台帳化・MCP導入境界の定義が不足している。

## 目的

- run の反復で毎回調べる情報を、skills の `references` に先置きして探索コストを削減する。
- run 末尾の改善提案を、次 run の入力にそのまま接続できる最小 JSON に固定する。
- MCP 導入対象を「周辺手続き」に限定し、ideaman/artist/critic の創作判断は LLM role のまま維持する。

## 非目的

- ideaman/artist/critic を固定 JSON 生成ツールへ置換すること。
- 依存追加を伴う重い評価器（CLIP 等）の即時導入。
- `sketch/agent_loop/runs/<run_id>/` 以外への出力拡張。

## 対象ファイル（予定）

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/primitive_effect_args_quickref.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/text_font_policy.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/critic_scoring_template.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/contact_sheet_spec.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/failure_recovery_rules.md`（新規）

## 実装タスク（チェックリスト）

### 1) `postrun_context_hints` の具体化

- [ ] primitive/effect の主要引数・型・安全レンジの 1 行表を `primitive_effect_args_quickref.md` に追加する。
- [ ] `text` primitive のフォント固定ポリシーを `text_font_policy.md` に追加する。
- [ ] critic の最小重みテンプレを `critic_scoring_template.md` に追加する。
- [ ] 前 iteration から次 iteration へ渡す compact handoff JSON 仕様を `schemas.md` に追加する。
- [ ] recipe 使用履歴の機械可読台帳（`recipe_ledger`）仕様を `schemas.md` に追加する。
- [ ] contact sheet 生成仕様（ラベル、セル、長辺閾値 `>=7690`）を `contact_sheet_spec.md` に固定する。
- [ ] 失敗時分岐ルール（例: text 失敗時のフォント絶対パス注入）を `failure_recovery_rules.md` に固定する。
- [ ] 出力境界監査の最終チェックを orchestrator の実行後チェックへ統合する。

### 2) schema と成果物の整備

- [ ] `schemas.md` に `WinnerHandoff` を追加する。
- [ ] `schemas.md` に `RecipeLedger` を追加する。
- [ ] 既存 `SkillImprovementReport` との重複項目を整理し、責務を分離する。
- [ ] run 配下の保存物を次に固定する。
- [ ] `iter_XX/winner_handoff.json`
- [ ] `run_summary/recipe_ledger.json`
- [ ] `run_summary/skill_improvement_report.json`

### 3) skills 接続（調査削減と反映）

- [ ] orchestrator に「新規 references を先読みし、足りない時のみ追加探索」を明記する。
- [ ] critic に「`critic_scoring_template` を既定値として使い、迷いを減らす」を明記する。
- [ ] artist に「`failure_recovery_rules` に沿った即時復旧」を明記する。
- [ ] ideaman に「`winner_handoff` と `decisions_to_persist` の優先反映」を明記する。

### 4) MCP 部分導入計画（仕様化）

- [ ] MCP 化対象を次の周辺手続きに限定する。
- [ ] `list_primitives` / `list_effects`
- [ ] `export_variant`
- [ ] `make_contact_sheet`
- [ ] `make_final_contact_sheet`
- [ ] `audit_output_boundary`
- [ ] `check_uniqueness`
- [ ] `read_log_tail`
- [ ] MCP 応答は短い構造化 JSON（status/path/elapsed/error_summary）に限定する。
- [ ] 詳細ログは `read_log_tail` で遅延取得する方針を明記する。
- [ ] ideaman/artist/critic の生成判断を MCP へ移さない禁止事項を明記する。

### 5) 段階導入

- [ ] Phase A: skills/references/schema だけ更新（この計画の実装範囲）。
- [ ] Phase B: MCP I/F の最小 PoC（実行・検証・集約のみ）を追加。
- [ ] Phase C: run 実績で効果計測し、不要な探索手順を更に削減。

## 受け入れ条件（DoD）

- [ ] run 開始時に参照する資料が固定され、横断探索の回数が減る。
- [ ] run 末尾で `skill_improvement_report.json` に加えて `winner_handoff.json` と `recipe_ledger.json` が揃う。
- [ ] critic の評価迷いが重みテンプレで減り、ranking の根拠が安定する。
- [ ] text 系失敗時の復旧が定型化され、再試行説明が短縮される。
- [ ] MCP 導入範囲が「周辺手続き限定」で明文化され、role 置換が起きない。

## 実装前に決める項目

- [ ] `WinnerHandoff` を `critique.json` 内包にするか、別ファイルにするか。
- [ ] `RecipeLedger` の粒度を iteration 単位にするか variant 単位にするか。
- [ ] critic 重みテンプレを固定値にするか、run ごと override 可能にするか。
- [ ] MCP Phase B の実施タイミングを、次回 run 前にするか run 後にするか。

## 実装順序（推奨）

1. `references` 5ファイルを整備して調査コスト削減の前提を作る。
2. `schemas.md` に `WinnerHandoff` / `RecipeLedger` を追加する。
3. orchestrator/critic/artist/ideaman の接続ルールを更新する。
4. 最後に MCP 部分導入の I/F 仕様を SKILL に追記する。
