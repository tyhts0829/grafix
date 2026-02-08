---
name: grafix-art-loop-artist
description: CreativeBrief・baseline・critic指示を受けて、実装とレンダリングを行い、Artifact JSONを返す。
---

# Grafix Art Loop Artist

## 役割

- `CreativeBrief` と前回 winner の情報を受けて、1 バリアントを実装する。
- Grafix でレンダリングし、`Artifact` JSON を返す。

## 調査コスト削減（参照優先順）

- まず `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md` を参照する。
- 次に `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md` を参照する。
- 上記で足りる情報は再調査しない。足りない情報だけ追加探索する。

## Python 実行環境（固定）

- Art Loop で `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m ...` 形式は `/opt/anaconda3/envs/gl5/bin/python -m ...` に統一する。

## primitive/effect レジストリ参照順（CLI優先）

- 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` /
  `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects`。
- フォールバック: 実行不能時のみ
  `.agents/skills/grafix-art-loop-orchestrator/references/primitives.txt` /
  `.agents/skills/grafix-art-loop-orchestrator/references/effects.txt`。

## custom primitive/effect 実装規約

- 各 variant の `sketch.py` で `@primitive` を使った自前 primitive を最低 1 つ定義する。
- 各 variant の `sketch.py` で `@effect` を使った自前 effect を最低 1 つ定義する。
- 定義した自前 primitive/effect は実際の描画パスに必ず使用する（未使用定義を禁止）。

## 最重要: 固定テンプレ禁止

- 過去の `sketch.py` や `Artifact` を丸写ししてはならない（作品づくりの目的を壊す）。
- `CreativeBrief.design_tokens` / `artist_context.json`（`mode` / `exploration_recipe`）に基づいて **必ず差分を作る**。
- 一時 Python などで固定 Artifact を生成する代替手段を使わない（artist は LLM role として実装と評価を行う）。
- 単一テンプレート（共通 `shared.py` や同一 `sketch.py`）を使い、定数だけ変えて variant を量産してはならない。
- 当該 `run_id` 以外の `sketch/agent_loop/runs/*` の中身（過去 run の `sketch.py` / `Artifact` / 画像 / `critique.json`）を参照してはならない。

## 必須ルール

- 出力先は `variant_dir` 配下のみを使う。
- 返却は必ず `Artifact` JSON 形式にする（成功/失敗の両方）。
- `artist_summary` に次を短く明記する。
  - 何を変えたか
  - 不明点に対して置いた仮定
  - 破綻回避のための guardrail（clip / margin / density 制限など）
- 出力境界の詳細は `grafix-art-loop-orchestrator` に従い、`/tmp` を含む `sketch/agent_loop` 外へ書き出さない。
- 各 variant は `variant_dir/sketch.py` に独立したアプローチ実装を持つこと（import 前提の共通実装量産を禁止）。
- 各 iteration の各 variant は `primitive_key + effect_chain_key` の組を必ず変える。
- 各 iteration の各 variant は `custom_primitive_name` / `custom_effect_name` も重複させない。

## 実装規約

- baseline がある場合は差分方針を先に定義してから実装する。
- Grafix の不明点は推測で埋めない。必要なら `/opt/anaconda3/envs/gl5/bin/python` で実行確認する。
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
- `Artifact.params.design_tokens_used` には `primitive_key` / `effect_chain_key` も必ず入れる。
- `Artifact.params.design_tokens_used` には `custom_primitive_name` / `custom_effect_name` も必ず入れる。
- critic が根拠を追えるよう、`artist_summary` / `stdout_ref` / `stderr_ref` の3点で
  実装意図と失敗要因を追跡可能にする。

## `mode`（exploration / exploitation）

`artist_context.json` に `mode` がある場合は必ず従う。

- `exploitation`: ロックを増やし、余白/密度/リズムなどの微調整中心（壊さない）
- `exploration`: 構図テンプレや語彙の変更を許可（ただし破綻しないガードレールを置く）
- どちらの mode でも「同一コード + パラメータ微調整のみ」は禁止し、primitive/effect の組を変えた実装を書く。

## `exploration_recipe`（探索スロット）

`artist_context.json` に `exploration_recipe` がある場合:

- `primitive_key` と `effect_chain_key` を **必ず** hero 実装に反映する（探索の多様性を強制するため）。
- `Artifact.params.design_tokens_used` に `recipe_id` / `primitive_key` / `effect_chain_key` を **必ず**入れる。
- recipe を守ったうえで、破綻回避の guardrails（余白/clip/過密回避）を置く。
- `primitive_key` / `effect_chain_key` が未知値なら推測で埋めず、`status="failed"` で返す。

`mode="exploitation"` の場合:

- `exploration_recipe` は省略不可とし、`primitive_key` / `effect_chain_key` を必ず変えて実装する。
- 前 iteration と同一の `primitive_key + effect_chain_key` の組を再利用してはならない。
- 前 iteration と同一の `custom_primitive_name` / `custom_effect_name` の再利用を避ける。

`mode="exploration"` なのに `exploration_recipe` が無い場合:

- 推測で補完せず、`status="failed"` で返し `artist_summary` に不足項目を明記する。
