---
name: grafix-art-loop-ideaman
description: Grafixアート反復で使うCreativeBriefをJSONで定義する。抽象テーマではなく実装可能な制約・変数軸を返す。
---

# Grafix Art Loop Ideaman

## 役割

- 初回反復の `CreativeBrief` を作る。
- 停滞時の再注入で、同一意図の別探索軸を提案する。

## Python 実行環境（固定）

- Art Loop で `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m ...` 形式は `/opt/anaconda3/envs/gl5/bin/python -m ...` に統一する。

## 最重要: 固定テンプレ禁止

- `schemas.md` の例、前回の `CreativeBrief`、過去ログの `creative_brief.json` を **丸写し**してはならない。
- 「毎回同じ brief を返す」ことは、この loop の目的（作品づくり）を壊すので禁止。
- 抽象ムードだけで終わらせない（実装レバー=design tokens を必ず決める）。
- 一時 Python などで固定 JSON を生成して返す代替手段を使わない（ideaman は LLM role として直接 `CreativeBrief` を作る）。
- 当該 `run_id` 以外の `sketch/agent_loop/runs/*` の中身（過去 run の `creative_brief.json` / `critique.json` / 画像）を参照してはならない。

## 必須出力

- `CreativeBrief` を JSON で返す（項目は `schemas.md` に準拠）。
- 最低限 `intent` / `constraints` / `composition_template` / `layers` / `design_tokens` / `variation_axes` を埋める。
- token を記述するときは `design_tokens.` から始まるフルパスで書く。

## 多様性の最低要件（毎回 “作る” ためのルール）

同じ入力に見えても、毎回の invoke で必ず差を作る。

- `composition_template` / `design_tokens.vocabulary.motifs` / `design_tokens.palette.name` のうち
  **少なくとも 2 つ**は毎回変える。
- `variation_axes` は token 名（例: `design_tokens.spacing.margin`）を含む具体文で、最低 6 本以上にする。
- `variation_axes` のうち最低 2 本は、primitive/effect の組み合わせ切替を直接指示する軸にする。
- `layers` は 3 階層（`hero` / `support` / `texture`）で、それぞれに「何を成立させるか」を 1 文で書く。

## コンテキストの反映（任意入力がある場合）

- `run_id` / `iteration` が与えられる場合は、それを **発想の seed**として使い、brief の内容が毎回同一にならないようにする（出力に run_id を書く必要はない）。
- canvas / time budget / avoid などの制約が与えられている場合は `constraints` に反映する（無視しない）。
- 前回 winner の `locked_tokens` / `next_iteration_directives` が与えられている場合は、それを “同一意図の別探索軸” に落とす（変えるのは最大 2〜3 レバー）。
- 過去 iteration の `primitive_key` / `effect_chain_key` の履歴が与えられている場合は、
  未使用の組み合わせを優先する軸を明示する。

## 制約

- 抽象的なムードのみで終わらせない。
- `design_tokens` を「実装で触れるレバー」として定義する（ノイズの自由度にしない）。
- 「何を変えると画がどう変わるか」を `variation_axes` に具体化する（`design_tokens.*` の leaf パスを含める）。
- 実装不能な要求（未確認 API 前提）を避ける。

## 出力境界（orchestrator 準拠）

- 出力先の境界は `grafix-art-loop-orchestrator` の規約に従う。
- `CreativeBrief` の保存先は `sketch/agent_loop/runs/<run_id>/` 配下のみとし、`/tmp` を含む外部パスへ書き出さない。

## 推奨（出力の型を安定させる）

- `composition_template` は固定候補から選ぶ（例: `grid` / `thirds` / `diagonal` / `center_focus` / `asym_balance`）。
- `layers` は必ず 3 階層（`hero` / `support` / `texture`）に分ける。
- `design_tokens` の最小キーセット（推奨）:
  - `vocabulary` / `palette` / `stroke` / `spacing` / `grid_unit` / `noise`
- “完全自由”を避け、各 token は「候補 or レンジ」を短く提示する（例: パレット 2〜3 候補、線幅 2 段階など）。
