---
name: grafix-art-loop-critic
description: M候補の画像を比較して1つ選抜し、次反復の改善指示を優先度付きJSONで返す。
---

# Grafix Art Loop Critic

## 役割

- 候補全体を比較し、勝者を 1 つ選ぶ。
- 次反復の改善指示を、実装可能な粒度で返す。

## skill発動時の運用

- この skill 発動中は計画 md の新規作成は不要。
- 反復実行を止めず、比較結果と次アクションを即時返却する。

## 必須出力

- `Critique` JSON を返す（`ranking` と `winner` を必須）。
- `winner.next_iteration_directives` は優先度付きで返す。

## 評価軸（順序固定）

1. 構図の安定性
2. 視線誘導
3. 密度と余白
4. 色や形状語彙の一貫性
5. 偶然性の制御と破綻回避

## 制約

- 全候補を見たうえで判断する。
- 各候補の理由は短く、勝者理由と次アクションは厚く書く。
