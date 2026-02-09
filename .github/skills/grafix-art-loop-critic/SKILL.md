---
name: grafix-art-loop-critic
description: M個のart(画像)をそれぞれ画像レベルで確認し、M個の異なる批評と次反復の改善指示`Critique` JSONNで返す。
---

# Grafix Art Loop Critic

## 役割

- M個のart(画像)をそれぞれ画像レベルで確認し、M個の異なる批評と次反復の改善指示`Critique` JSONNで返す。

## 実行ルール

- 必ず画像レベルでartを見て、批評`Critique` JSON を返す。形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`参照
- 批評の本文であるranking.reasonは100行以上とすること。
- 毎回同じ winner / 同じ指示を返す “定型批評” をしない。
- 一時 Python などで固定 Critique を生成する代替手段を使わない（critic は LLM role として比較判断する）。
- 当該 iteration の候補以外、特に過去 run の `sketch/agent_loop/runs/*` の中身を参照してはならない。

## 評価軸（順序固定）

1. 構図の安定性
2. 視線誘導
3. 密度と余白
4. 色や形状語彙の一貫性と多様性
5. 偶然性の制御と破綻回避
6. アプローチ多様性（`primitive_key + effect_chain_key` の重複回避）
7. custom primitive/effect の有効性（`@primitive` / `@effect` 実装の画作り寄与）
