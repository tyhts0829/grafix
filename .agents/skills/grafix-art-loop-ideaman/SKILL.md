---
name: grafix-art-loop-ideaman
description: Grafixアート反復で使うCreativeBriefをJSONで定義する。抽象テーマではなく実装可能な制約・変数軸を返す。
---

# Grafix Art Loop Ideaman

## 役割

- 初回反復の `CreativeBrief` を作る。
- 停滞時の再注入で、同一意図の別探索軸を提案する。

## skill発動時の運用

- この skill 発動中は計画 md の新規作成は不要。
- 反復実行を止めず、即時に `CreativeBrief` を返す。

## 必須出力

- `CreativeBrief` を JSON で返す（項目は `schemas.md` に準拠）。
- 最低限 `intent` / `constraints` / `variation_axes` を埋める。

## 制約

- 抽象的なムードのみで終わらせない。
- 「何を変えると画がどう変わるか」を `variation_axes` に具体化する。
- 実装不能な要求（未確認 API 前提）を避ける。
