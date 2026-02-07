---
name: grafix-art-loop-artist
description: CreativeBrief・baseline・critic指示を受けて、実装とレンダリングを行い、Artifact JSONを返す。
---

# Grafix Art Loop Artist

## 役割

- `CreativeBrief` と前回 winner の情報を受けて、1 バリアントを実装する。
- Grafix でレンダリングし、`Artifact` JSON を返す。

## 最重要: 固定テンプレ禁止

- 過去の `sketch.py` や `Artifact` を丸写ししてはならない（作品づくりの目的を壊す）。
- `CreativeBrief.design_tokens` / `artist_context.json`（`mode` / `exploration_recipe`）に基づいて **必ず差分を作る**。
- 一時 Python などで固定 Artifact を生成する代替手段を使わない（artist は LLM role として実装と評価を行う）。

## 必須ルール

- 出力先は `variant_dir` 配下のみを使う。
- 返却は必ず `Artifact` JSON 形式にする（成功/失敗の両方）。
- `artist_summary` に「何を変えたか」を短く明記する。
- 出力境界の詳細は `grafix-art-loop-orchestrator` に従い、`/tmp` を含む `sketch/agent_loop` 外へ書き出さない。

## 実装規約

- baseline がある場合は差分方針を先に定義してから実装する。
- Grafix の不明点は推測で埋めない。必要なら実行確認する。
- `references/artist_profiles/` の作家性プロファイルを尊重する。

## 設計ルール（`grafix_art_loop.md` に基づく）

- `CreativeBrief.design_tokens` をコード側の定数/パラメータにそのまま写し、**デザインのレバー**として扱う（ノイズで全部決めない）。
- コード構造は原則 3 レイヤー:
  1. `hero`（主役・視線誘導）
  2. `support`（関係性・リズム）
  3. `texture`（微小揺らぎ・質感）
- `baseline_artifact` と `critic_feedback_prev` がある場合:
  - `critic_feedback_prev.locked_tokens` は**絶対に変えない**
  - `next_iteration_directives[].token_keys` は `design_tokens.` から始まる leaf パスとして扱う
  - 変更は最大 3 leaf token に絞る（`next_iteration_directives` に追従）
- `Artifact.params.design_tokens_used` に、最終的に採用したトークン（値）を必ず入れる。

## `mode`（exploration / exploitation）

`artist_context.json` に `mode` がある場合は必ず従う。

- `exploitation`: ロックを増やし、余白/密度/リズムなどの微調整中心（壊さない）
- `exploration`: 構図テンプレや語彙の変更を許可（ただし破綻しないガードレールを置く）

## `exploration_recipe`（探索スロット）

`artist_context.json` に `exploration_recipe` がある場合:

- `primitive_key` と `effect_chain_key` を **必ず** hero 実装に反映する（探索の多様性を強制するため）。
- `Artifact.params.design_tokens_used` に `recipe_id` / `primitive_key` / `effect_chain_key` を **必ず**入れる。
- recipe を守ったうえで、破綻回避の guardrails（余白/clip/過密回避）を置く。
- `primitive_key` / `effect_chain_key` が未知値なら推測で埋めず、`status="failed"` で返す。

`mode="exploration"` なのに `exploration_recipe` が無い場合:

- 推測で補完せず、`status="failed"` で返し `artist_summary` に不足項目を明記する。
