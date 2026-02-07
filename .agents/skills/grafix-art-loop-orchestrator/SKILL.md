---
name: grafix-art-loop-orchestrator
description: Grafixアート反復（N回・M並列）を、エージェント直書きで自動実行し、成果物をsketch/agent_loop配下へ保存する。
---

# Grafix Art Loop Orchestrator

## 目的

- アイデア生成 → M並列の実装/レンダリング → 批評/選抜 を N 反復で回す。
- 生成物とログを `sketch/agent_loop` 配下に保存し、追跡可能にする。

## デフォルトモード（skill発動時）

- 出力は常に `sketch/agent_loop/runs/<run_id>/...` に保存する。
- エージェント自身が反復ループを回す。
- このモードでは計画 md の新規作成は不要とする。
- ideaman/artist/critic は **LLM が担う role**であり、固定 JSON を吐くだけの補助スクリプト（例: `tools/ideaman.py`）で代替してはならない。
- ideaman/artist/critic を `cat > /tmp/*.py` などの一時 Python 生成で代替してはならない（role はセッション内で LLM が直接実行する）。
- `artist` は variant ごとの作業ディレクトリ（`.../iter_XX/vY/`）に `sketch.py` を生成する。
- レンダリングは `PYTHONPATH=src python -m grafix export` を使い、各 variant の `out.png` を生成する。
- 各反復で contact sheet を作成し、`critique.json`（winner を含む）を保存する。
- `winner_feedback.json` は作らない（winner の正本は常に `critique.json`）。
- M 並列は exploration / exploitation を分けて運用する（序盤は探索寄り → 終盤は収束寄り）。

## 出力境界（最重要）

- 出力（画像・JSON・`sketch.py`・stdout/stderr・診断ファイル・中間ファイル）は **すべて**
  `sketch/agent_loop/runs/<run_id>/` 配下に保存する。
- `sketch/agent_loop` 外への出力を禁止する（例: `/tmp`, リポジトリ直下, ホーム配下の任意パス）。
- `mktemp` の既定ディレクトリ、`tempfile` の既定 `/tmp` を使わない。
- 一時作業が必要な場合は `sketch/agent_loop/runs/<run_id>/.tmp/` のみ使用する。

## exploration / exploitation の配分（`explore_ratio`）

- 目安として、`explore_ratio` を **0.7 → 0.2** に線形減衰させる（iteration の進行に応じて探索を減らす）。
- 各 iteration の M 本のうち `ceil(M * explore_ratio)` 本を exploration にする（ただし exploitation は最低 1 本残す）。
- `artist_context.json` に各 variant の `mode` を必ず入れる（`exploration` / `exploitation`）。
- winner は次 iteration の exploitation にだけ引き継ぐ（exploration は baseline/feedback を原則渡さない）。
- exploitation に渡す `critic_feedback_prev.next_iteration_directives[].token_keys` は
  `design_tokens.` から始まる leaf パスのみを使う。

## exploration の多様性（primitive/effect をユニーク化）

- exploration variant には `artist_context.json` で `exploration_recipe` を必ず付与する。
  - 同一 iteration 内で `primitive_key` と `effect_chain_key` は**重複禁止**（両方ユニーク）。
  - `primitive_key` / `effect_chain_key` は「hero の primitive / hero の effect chain」を指す（support の補助 primitive は可）。
- `primitive_key` / `effect_chain_key` は下記レジストリに存在する値だけを使う（未知キー禁止）。
- exploration では原則 `baseline_artifact` / `critic_feedback_prev` を渡さない（ロックで即収束しないため）。
- artist は recipe を厳守し、`Artifact.params.design_tokens_used` に `recipe_id` / `primitive_key` / `effect_chain_key` を必ず記録する。

### exploration recipe レジストリ（初期版）

- `primitive_key` 候補（`PYTHONPATH=src python -m grafix list primitives` に一致）:
  - `asemic` / `grid` / `line` / `lsystem` / `polygon` / `polyhedron` / `sphere` / `text` / `torus`
- `effect_chain_key` 候補（各 effect 名は `python -m grafix list effects` に一致）:
  - `subdivide_warp`: `subdivide -> warp`
  - `dash_wobble`: `dash -> wobble`
  - `partition_fill`: `partition -> fill`
  - `mirror_displace`: `mirror -> displace`
  - `twist_trim`: `twist -> trim`
  - `repeat_rotate`: `repeat -> rotate`
  - `quantize_pixelate`: `quantize -> pixelate`
  - `clip_lowpass`: `clip -> lowpass`

運用:
- `artist_context.json` を作る前に key を検証し、不一致があればその recipe を破棄して再割当する。
- レジストリはこの `SKILL.md` 内記述で開始し、必要時に別ファイル化する。

## 停滞判定と ideaman 再注入（デフォルト閾値: 2 回連続）

以下のいずれかを満たしたら停滞と判定する:

- winner `variant_id` が 2 iteration 連続で同一
- 最優先 directive（`priority=1`）の `token_keys` が 2 iteration 連続で同一
- `explore_ratio` を下げたのに winner `score` が 2 iteration 連続で改善しない

停滞時の処理:

- ideaman を再呼び出しし、同一 `intent` / `constraints` を維持したまま再注入する。
- 再注入で必ず差し替える軸は `composition_template` と
  `design_tokens.vocabulary.motifs` / `design_tokens.palette.name`（必要なら `colors` も）。
- 1 回の再注入で動かすレバーは 2〜3 個に制限する（過剰な全面刷新を避ける）。

## 自動ループ手順（agent-native）

1. `run_id` を作成し、`sketch/agent_loop/runs/<run_id>/` を作る（必要なら `.tmp/` も同配下に作る）。
2. 反復ごとに `iter_XX/vY/` を作成し、各 variant の `draw(t)` を実装する。
3. 各 `sketch.py` を `python -m grafix export` でレンダリングし、stdout/stderr も `run_dir` 配下へ保存する。
4. 候補を比較し、`critique.json`（winner を含む）を保存する。
5. winner 情報を次反復へ引き継ぐ。

## 実行後チェック（再発防止）

- 当該 run の生成物が `sketch/agent_loop/runs/<run_id>/` 以外に存在しないことを確認する。
- 特に `/tmp` やリポジトリ直下への一時スクリプト生成が無いことを確認する。
- 代表プロンプト（例: `N=3`, `M=12`, `canvas=1024x1024`, `explore_schedule=0.7->0.2`）で同じ境界制約が維持されることを確認する。
