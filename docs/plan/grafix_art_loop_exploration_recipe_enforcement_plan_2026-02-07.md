# Grafix Art Loop: exploration の多様性強制（primitive/effect をユニーク化）

作成日: 2026-02-07

## 目的

- exploration では **各 variant が異なる primitive** かつ **異なる effect chain** を必ず使う（比較が「パラメータ差」ではなく「構造差」になる）。
- exploitation は従来どおり winner 追従で収束させる。

## DoD（完了条件）

- orchestrator が exploration variant ごとに `exploration_recipe`（`recipe_id` / `primitive_key` / `effect_chain_key`）を `artist_context.json` へ付与する。
- artist が exploration では `exploration_recipe` を厳守し、`Artifact.params.design_tokens_used` に実使用（`recipe_id` / `primitive_key` / `effect_chain_key`）を記録する。
- critic が早期収束を避けるため、`locked_tokens` に `recipe_id` / `primitive_key` / `effect_chain_key` を入れない（少なくとも序盤）。
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` に上記フィールドの仕様が追記される。
- agent-native の反復でも同じ `artist_context.json` が生成される（exploration の多様性を固定する）。

## 実装範囲（触るファイル）

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`

## 実装チェックリスト

### 1) スキーマ拡張（context と token）

- [x] `schemas.md` に `artist_context.json` の追記（`mode` と `exploration_recipe`）。
- [x] `Artifact.params.design_tokens_used` に `recipe_id` / `primitive_key` / `effect_chain_key` を入れる運用を明文化。

### 2) orchestrator（運用ルール）

- [x] `SKILL.md` に exploration recipe（pool/割当/ユニーク制約）を追加。
- [x] （多様性確保のため）exploration variant には baseline/critic_feedback を渡さない運用へ（exploitation は従来通り渡す）。

### 3) artist / critic（skill 指針）

- [x] artist: exploration では `exploration_recipe` 厳守（primitive/effect 両方ユニーク）、記録を必須化。
- [x] critic: `locked_tokens` に recipe 系を入れない（序盤）、多様性不足時は次回 directive で要求。

### 4) 最低限の検証

- [x] `schemas.md` / role skills / orchestrator の記述が矛盾しないことを確認する。
