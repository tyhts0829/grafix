# Grafix Art Loop: CLI モード廃止（Option A）実装改善計画

作成日: 2026-02-07

## 背景 / 課題

現状の `.agents/skills/grafix-art-loop-*` は、作品制作ループを

- skill 発動（agent-native / チャット内で反復を回す）
- Python スクリプト実行（`scripts/run_loop.py` 等の CLI）

の **二重インターフェース**で提供している。

本来の目的は「grafix を用いた作品づくりをマルチエージェントにさせて自動化（skills による運用）」なので、
CLI 経路は分岐・保守コスト・混乱源になりやすく、不要機能として廃止する。

同時に、role skills（ideaman/artist/critic）の `SKILL.md` に分散している
「skill 発動中は計画 md 不要」のような **運用ルール**を orchestrator 側へ集約し、読み手の迷いを減らす。

---

## 方針（Option A）

- `.agents/skills/grafix-art-loop-orchestrator/scripts/` を **削除**し、CLI モードを廃止する。
- `tools/ideaman.py` / `tools/artist.py` / `tools/critic.py` も削除し、「Python 実行でトリガーできる入口」を repo から無くす。
- orchestrator の `SKILL.md` を「agent-native ループ」前提の仕様に寄せ、CLI の説明・例・プレースホルダを消す。
- `references/schemas.md` は「skills 間受け渡し JSON 仕様」として残し、scripts 依存の説明を外す。
- role skills 側は「役割と入出力」に集中させ、共通運用ルール（計画 md 等）は orchestrator に集約する。

非ゴール:

- CLI の代替ツールを `tools/` として作り直す（必要なら別計画）。
- 互換ラッパー/シムで旧 CLI を温存する（破壊的変更 OK の方針に従い、残さない）。

---

## 受け入れ条件（DoD）

- [x] `.agents/skills/grafix-art-loop-orchestrator/` 配下に、実行可能な CLI スクリプトが存在しない（`scripts/` が無い）。
- [x] orchestrator の `SKILL.md` に CLI 利用の記述が無い（`run_loop.py` / `run_one_iter.py` 等が登場しない）。
- [x] `tools/ideaman.py` / `tools/artist.py` / `tools/critic.py` が存在しない。
- [x] `references/schemas.md` の冒頭が「skills の JSON 仕様」で統一され、scripts を前提にしない。
- [x] role skills の `SKILL.md` から「計画 md 不要」など共通運用ルールを削除し、orchestrator `SKILL.md` に集約されている。
- [x] `rg -n "run_loop\\.py|run_one_iter\\.py|GrafixAdapter|make_contact_sheet" docs .agents` が “意図した箇所だけ” に収束している（plan/review/cancel を除き実運用から排除）。

---

## 実装チェックリスト

### 0) 事前確認（影響範囲を確定）

- [x] `rg -n "grafix-art-loop-orchestrator/scripts|run_loop\\.py|run_one_iter\\.py" -S .` で参照箇所を列挙する
- [x] 参照が `.agents/skills` 外（`docs/` や `tools/`）にある場合は、今回の変更でどう扱うか（更新/取消/据え置き）を決める

### 1) orchestrator の仕様整理（agent-native のみ）

- [x] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` の CLI 節を削除する
- [x] 代わりに「agent-native 反復手順（保存先・成果物・ログ）」を 1 か所に整理する
- [x] **運用ルールの集約**: 「この skill 発動中は計画 md の新規作成は不要」を orchestrator にのみ置く
  - role skills 側には “運用ルールは orchestrator に従う” 程度の短い参照だけ残す（残す場合）

### 2) role skills の運用記述を整理（分散排除）

- [x] `.agents/skills/grafix-art-loop-ideaman/SKILL.md` から「skill発動時の運用（計画 md 不要）」を削除
- [x] `.agents/skills/grafix-art-loop-artist/SKILL.md` から同様の運用記述を削除
- [x] `.agents/skills/grafix-art-loop-critic/SKILL.md` から同様の運用記述を削除
- [x] role 側に残すのは「役割・必須出力・制約・実装規約」のみ（運用は orchestrator へ）

### 3) JSON スキーマ参照の整理（scripts 前提を外す）

- [x] `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` 冒頭文を「skills 間 JSON 仕様」に修正
- [x] scripts 由来の文言（`run_one_iter.py` / `run_loop.py` を前提にした説明）があれば削除/置換

### 4) CLI 実装の削除（破壊的変更）

- [x] `.agents/skills/grafix-art-loop-orchestrator/scripts/` を削除
  - `run_loop.py`
  - `run_one_iter.py`
  - `grafix_adapter.py`
  - `make_contact_sheet.py`
- [x] `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` の「実装ファイル」節が残っていれば削除

### 4.5) `tools/` の削除（破壊的変更）

- [x] `tools/ideaman.py` を削除
- [x] `tools/artist.py` を削除
- [x] `tools/critic.py` を削除

### 5) 関連ドキュメントの更新/整理（混乱防止）

- [x] `docs/plan/` 内で CLI 前提の計画を洗い出し、方針 A と矛盾するものは更新 or 取消（`docs/cancel/` へ移動）する
  - 例: `docs/cancel/grafix_art_loop_skill_plan_2026-02-06.md`（`.codex/skills` と scripts 前提）
  - 例: `docs/cancel/grafix_art_loop_grafix_adapter_plan_2026-02-07.md`（scripts 前提）
  - 例: `docs/cancel/grafix_art_loop_agent_tools_plan_2026-02-07.md`（`run_loop.py` 実行前提）
- [x] 現行運用に関わる場所（`.agents/` / `docs/plan/`）から `.codex/skills/...` 参照を排除する（歴史文書は `docs/cancel/` に退避）

### 6) 最低限の整合性チェック

- [x] `git status --porcelain` で変更範囲が計画どおりに限定されていること
- [x] `rg` で削除したはずの CLI 名称が残っていないこと

---

## 要確認（実装着手前に確認したいこと）

- （決定: 2026-02-07）CLI 廃止により、手元の既存ワークフロー（長時間バッチ実行など）が壊れても問題ない
- （決定: 2026-02-07）`tools/ideaman.py` / `tools/artist.py` / `tools/critic.py` も削除する
