# Grafix Art Loop: skills 改善計画（Run末尾の改善提案 + 調査コスト削減）

作成日: 2026-02-08
ステータス: 提案（未実装）

## 目的（今回の主眼）

- 作品生成 run の最後に、コーディングエージェント自身が「現状 skills の改善点」を構造化 JSON で必ず出す。
- 毎回の Grafix / プロジェクト調査（全体探索）を減らすため、skills 側に事前知識を集約する。

## 背景（`grafix_art_loop.md` の要点）

- 「不足情報だけ追加」は入力肥大化を招くため、`missing` と `redundant` を同時回収する必要がある。
- 回収は自由作文ではなく、根拠付き・件数上限付き JSON に固定するべき。
- 回収結果は散文で残さず、`constraints` / `design_tokens` / `variation_axes` / `next_iteration_directives` へ圧縮反映するべき。

## DoD（完了条件）

- 各 run の終了時に `run_summary/skill_improvement_report.json` が保存される。
- `skill_improvement_report.json` に「skills改善提案」と「調査コスト削減提案」が根拠付きで含まれる。
- 改善提案は件数上限（推奨 3、最大 5）と優先度を持つ。
- `/.agents/skills/grafix-art-loop*` が、まず読む参照資料を持ち、不要な全体探索を避ける規約を持つ。
- 既存規約（`design_tokens.*` leaf path、出力境界、directive 最大 3件）と矛盾しない。

## 対象ファイル

- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md`（新規）

## 非対象（今回やらない）

- 依存追加を伴う自動評価器（CLIP など）。
- `.agents/skills/grafix-art-loop-orchestrator/scripts/` 再導入。
- `sketch/agent_loop` 以外への保存方針変更。

## 実装タスク（チェックリスト）

### 1) スキーマ拡張（最優先）

- [ ] `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` に `SkillImprovementReport` を追加する。
- [ ] `SkillImprovementReport` の最小構造を定義する。
  - `improvements[]`: `priority` / `skill` / `problem` / `evidence` / `proposed_change` / `target_files` / `expected_impact`
  - `discovery_cost[]`: `lookup` / `why_needed` / `how_to_preload`
  - `redundant_info[]`: `item` / `reason` / `suggested_rewrite`
  - `decisions_to_persist[]`: `decision` / `value` / `where_to_store`
- [ ] `improvements[]` は推奨 3 件、最大 5 件に制限する。
- [ ] `evidence` は run 内生成物（`Artifact` / `critique` / ログ）への参照必須にする。

### 2) run末尾レポートの必須化（orchestrator）

- [ ] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` に、最終ステップとして `skill_improvement_report.json` 生成を追加する。
- [ ] 保存先を `sketch/agent_loop/runs/<run_id>/run_summary/skill_improvement_report.json` に固定する。
- [ ] 「作品批評」ではなく「skills改善提案」を最低 1 件は出す規約を追加する（該当なしなら理由を明記）。
- [ ] 改善提案は必ず具体的な変更先ファイル（`SKILL.md`/`references/*.md`）を指す規約にする。

### 3) critic側の棚卸し強化（改善点抽出の中核）

- [ ] `.agents/skills/grafix-art-loop-critic/SKILL.md` に、批評結果とは別に「skill運用上の不足/冗長」を抽出する規約を追加する。
- [ ] `missing` 系項目に `evidence` 必須を明記し、「一般論の要求」を禁止する。
- [ ] `next_iteration_directives` と混同しないよう、`artifact改善` と `skill改善` を明確に分離する。

### 4) 調査コスト削減の知識パック作成（references）

- [ ] `project_quick_map.md` を新規作成し、最小限のプロジェクト地図（主要ディレクトリ、触るべきファイル順）を記述する。
- [ ] `grafix_usage_playbook.md` を新規作成し、Grafix 主要コマンド（list/export）と典型エラー対処の最小手順を記述する。
- [ ] 2ファイルは「先に読む前提」にし、毎回の横断探索を減らす設計にする。

### 5) ideaman / artist の接続更新

- [ ] `.agents/skills/grafix-art-loop-ideaman/SKILL.md` に、`decisions_to_persist` 反映規約を追加する。
- [ ] `.agents/skills/grafix-art-loop-artist/SKILL.md` に、`artist_summary` へ「不明点の仮定」を短文で残す規約を追加する。
- [ ] critic が `evidence` を取りやすいよう、参照元（`artist_summary` / `stdout_ref` / `stderr_ref`）を明記する。

### 6) 整合確認

- [ ] `SkillImprovementReport` キー名を5つの skills で統一する。
- [ ] `design_tokens.*` leaf path ルールと競合しないことを確認する。
- [ ] 既存の出力境界（`sketch/agent_loop/runs/<run_id>/` のみ）を維持する。

## 受け入れテスト（運用確認）

- [ ] 1 run 実行後、`run_summary/skill_improvement_report.json` が生成されることを確認する。
- [ ] レポート内 `improvements[]` が具体ファイルを指していることを確認する。
- [ ] レポート内 `discovery_cost[]` が「次回どこに事前記載すれば探索が減るか」を示すことを確認する。
- [ ] 次回入力で `redundant_info` 項目が削減されることを確認する。

## 要確認（実装前に決める項目）

- [ ] `skill_improvement_report.json` を毎 run 必須にするか（推奨: 必須）。
- [ ] `improvements[]` 件数上限を 3 にするか 5 にするか。
- [ ] 「改善提案なし」を許可する条件（例: 根拠不足時のみ）を設けるか。

## 実装順序（推奨）

1. `schemas.md` へ `SkillImprovementReport` を追加
2. `orchestrator` へ run末尾レポート生成フローを追加
3. `critic` を更新して改善点抽出の根拠要件を固定
4. `references` 2ファイルを追加して調査コストを先回り吸収
5. `ideaman` / `artist` を接続して整合確認
