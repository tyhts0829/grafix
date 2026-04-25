---
name: grafix-art-loop-critic
description: V個の最終art(画像)をそれぞれ画像レベルで確認し、当該 round 内だけで比較した`Critique` JSONを返す。
---

# Grafix Art Loop Critic

## 役割

- V個の最終art(画像)をそれぞれ画像レベルで確認し、当該 round 内だけで比較した`Critique` JSONを返す。

## 実行ルール

- 必ず画像レベルでartを見て、批評`Critique` JSON を返す。形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`参照
- まず `round_XX/contact_sheet.png` を見て全体比較し、必要なら各 variant の最終 loop 出力 (`round_XX/vYY/loop_LL/out.png`) を追って確認する。
- 批評の本文であるranking.reasonは20行以上とすること。
- 毎回同じ winner / 同じ指示を返す “定型批評” をしない。
- 一時 Python などで固定 Critique を生成する代替手段を使わない（critic は LLM role として比較判断する）。
- 当該 round の最終 loop 候補以外、特に同一 run を含む過去 round の `sketch/agent_loop/runs/*/round_*` の中身を参照してはならない。
- 同一 round 内でも、途中 loop の draft を ranking 対象にしてはならない。
- 批評は archive / ranking 用であり、次 round の改善指示として書いてはならない。
- 「前回より良い」「winner を継承すべき」など、round 間比較を前提にした記述を禁止する。

## 評価軸（順序固定）

1. 構図の安定性
2. 視線誘導
3. 密度と余白
4. 色や形状語彙の一貫性と多様性
5. 偶然性の制御と破綻回避
6. アプローチ多様性（`primitive_key + effect_chain_key` の重複回避）
7. custom primitive/effect の有効性（`@primitive` / `@effect` 実装の画作り寄与）
