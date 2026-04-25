# Grafix Art Loop Diversity Guardrails Plan

## 目的

- `round` 間で構図 family が再利用される抜け道を塞ぐ。
- 既存の「round 再参照禁止」「fresh start」「design_axes を埋める」といった原則を、実運用で守らせるための手順に落とす。
- `grafix-art-loop-orchestrator` / `ideaman` / `artist` の role contract に、diversity guardrail を明文化する。

## 背景

- 現状の skill には、以下の原則は書かれている。
  - 過去 round の `CreativeBrief` / `critique` / 画像 / `sketch.py` を参照しない
  - 各 round は独立した新規探索ラウンドとして扱う
  - diversity は最初から異なる `topology / silhouette / density / event / palette` を割り当てることで作る
- ただし、以下は手順化されていない。
  - run 内で使用済みの構図 family を記録する
  - 後続 round でその family を禁止する
  - `topology_key` / `silhouette_key` の意味重複をチェックする
- そのため、過去 round を直接参照していなくても、LLM が頭の中で同系統 archetype を round を跨いで再利用できてしまう。

## この plan で追加する guardrail

1. run 内 family ledger を導入する
2. round 開始前に禁止 family を明示する
3. `design_axes` の意味重複チェックを必須化する

## 追加方針

### 1. family ledger

- orchestrator は `run_summary/diversity_ledger.json` を run 内の機械的な記録先として持つ。
- 各 round 開始前に、過去 round で確定済みの family を ledger から参照する。
- ledger には少なくとも以下を持たせる。
  - `round`
  - `variant_id`
  - `brief_uniqueness_key`
  - `topology_key`
  - `silhouette_key`
  - `family_summary`
  - `forbidden_from_round`

### 2. round ごとの禁止 family

- orchestrator skill に、round 開始時の必須手順として次を追加する。
  - 既存 ledger を読み、当該 run で既出の family を列挙する
  - 今回の round では再使用禁止の family と silhouette を明示する
  - ideaman へ渡す前提として「今回の round の共通 identity」と「禁止 family」を確定する
- ここで言う family は、単なる文字列一致ではなく、構図レベルの類型を指す。
  - 例: `central medallion`, `orbital halo`, `ledger with script band`, `mirrored buttress growth`

### 3. meaning-level 重複チェック

- ideaman skill に、各 round の `v` 本を書き終えたあとに実施する自己点検を追加する。
- チェック対象:
  - 同一 round 内で `topology_key` / `silhouette_key` が意味的に被っていないか
  - 既存 ledger 上の過去 round family と意味的に被っていないか
- 禁止する抜け道:
  - ラベルだけ変えて同じ構図を出す
  - `brief_uniqueness_key` だけ変えて、実質同じ family を出す
  - `palette_key` / `density_key` の差分だけで別作品扱いにする

## 変更対象

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`

必要なら追記候補:

- `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`

## 実装イメージ

### orchestrator に追加する文言

- run 開始時に `diversity_ledger.json` を run_summary 配下へ作る
- 各 round 開始前に ledger を見て「既出 family」と「今回禁止 family」を確定する
- ideaman へ渡す制約に「禁止 family」を含める
- round 完了後に、その round の採用 brief を ledger へ追記する

### ideaman に追加する文言

- fresh start であることに加え、既出 family の再利用を禁止する
- `topology_key` / `silhouette_key` は意味レベルで既存 ledger と重複してはならない
- 各 round の `v` 本を書いたあと、family の意味重複チェックを行ってから確定する

### artist に追加する文言

- `creative_brief.design_axes` は round の family 制約を含むものとして扱う
- もし brief が既出 family に見える場合は、そのまま round を進めず、orchestrator に不整合として返す

### schema に追加する方向

- `SkillImprovementReport.decisions_to_persist` に加え、run 中の diversity guardrail 用として
  `run_summary/diversity_ledger.json` を新規出力として明記する
- 形式は最小限にし、作品評価ではなく family 管理に限定する

## 実装アクション

- [x] orchestrator skill に `diversity_ledger.json` の作成 / 更新手順を追加する
- [x] orchestrator skill に round 開始前の「既出 family 確認」と「禁止 family 明示」を追加する
- [x] ideaman skill に meaning-level 重複チェック手順を追加する
- [x] ideaman skill に `brief_uniqueness_key` だけでなく `topology_key` / `silhouette_key` の非重複責務を明文化する
- [x] artist skill に「brief が既出 family に見える場合はそのまま進めない」旨を追加する
- [x] schemas に `run_summary/diversity_ledger.json` を追加する
- [ ] 必要なら quick map に diversity guardrail の参照順を追記する

## 検証観点

- [x] skill だけ読んだときに、「過去 round を見ない」だけでなく「既出 family を再利用しない」ことが手順として理解できる
- [x] `brief_uniqueness_key` が一意でも、`topology_key` / `silhouette_key` が意味的に同じなら違反だと読める
- [x] round identity と forbidden family を orchestrator が明示する前提が skill に入る
- [x] 追加文言が artist / ideaman / orchestrator 間で矛盾しない

## 実装しないこと

- 作品画像そのものの自動類似判定ロジック
- embedding やクラスタリングのような自動判定スクリプト追加
- 過去 run 全体を横断した family 管理

## 完了条件

- diversity guardrail が「原則」ではなく「run 内の手順」として skill に明記される
- round 再参照禁止の抜け道として archetype 再利用ができないよう、少なくとも運用上は塞がる
- 次回同じ失敗が起きた場合、どの手順を破ったかを skill 上で特定できる
