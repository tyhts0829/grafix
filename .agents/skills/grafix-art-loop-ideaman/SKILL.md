---
name: grafix-art-loop-ideaman
description: Grafixアート反復で使うCreativeBriefをJSONで定義する。抽象テーマではなく実装可能な制約・変数軸を返す。
---

# Grafix Art Loop Ideaman

## 役割

- 初回反復時、それぞれことなる並列数M個の `CreativeBrief` を作る。
- 2回目反復以降は、`critique.json`に基づき、それらの`CreativeBrief`を洗練・改善する。

## 実行ルール

- 出力形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`に従う。
- 出力先の境界は `grafix-art-loop-orchestrator` の規約に従う。
- アイデアは多様性を最重要視する。一時 Python などで「毎回同じ brief を返す」ことは、この loop の目的（作品づくり）を壊すので禁止。
- intentは300文字以上を目安とする。
- contextには、アートのカテゴリ、系譜、実在のアーティスト名といった、方向性を示すことが可能はハイコンテクストな単語を最低3つ書くこと。
