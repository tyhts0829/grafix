---
name: grafix-art-loop-ideaman
description: Grafixアート反復で使うCreativeBriefをJSONで定義する。抽象テーマではなく実装可能な制約・変数軸を返す。
---

# Grafix Art Loop Ideaman

## 役割

- 毎 round を独立ラウンドとして扱い、それぞれ異なる並列数 V 個の `CreativeBrief` を作る。
- loop 改善には関与しない。`CreativeBrief` は round の入口で固定し、同一 round 内で差分 brief を作らない。
- 過去 round の `critique.json` や画像を使って brief を洗練・改善してはならない。
- orchestrator が `diversity_ledger.json` から導いた `round identity` と `forbidden family` を守り、same-run 内で既出の構図 family を再利用しない。

## 実行ルール

- 出力形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`に従う。
- 出力先の境界は `grafix-art-loop-orchestrator` の規約に従う。
- 過去 round の `CreativeBrief` / `critique` / 画像 / `sketch.py` を参照してはならない。同一 run 内の過去 round も禁止。
- アイデアは多様性を最重要視する。一時 Python などで「毎回同じ brief を返す」ことは、この loop の目的（作品づくり）を壊すので禁止。
- 各 `CreativeBrief` は必ず `design_axes` を持ち、`brief_uniqueness_key` / `topology_key` / `silhouette_key` / `density_key` / `event_key` / `palette_key` を埋める。
- `brief_uniqueness_key` は同一 run 内で一意でなければならない。
- `brief_uniqueness_key` の一意性だけで十分と見なしてはならない。`topology_key` / `silhouette_key` が same-run の既出 family と意味レベルで同じなら違反である。
- 「前回 winner を少し変える」「前回の改善版を作る」「loop 用の小改善 brief を作る」という発想を禁止する。毎回 fresh start で構想する。
- 色・密度・event だけを少し変えて、実質同じ構図 family を別 brief として量産してはならない。少なくとも `topology_key` または `silhouette_key` の意味が明確に別種である必要がある。
- `v` 本の草案を書き終えたら、確定前に必ず self-check を行うこと。
  - same-round 内で `topology_key` / `silhouette_key` が意味的に被っていないか
  - orchestrator が渡した `forbidden family` と意味的に被っていないか
  - `brief_uniqueness_key` だけ変えて同型構図を出していないか
- 上記 self-check で重複が見つかった brief は、そのまま確定せず作り直すこと。
- intentは300文字以上を目安とする。
- contextには、アートのカテゴリ、系譜、実在のアーティスト名といった、方向性を示すことが可能はハイコンテクストな単語を最低3つ書くこと。
