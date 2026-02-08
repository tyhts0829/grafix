---
name: grafix-art-loop-orchestrator
description: Grafixアート反復（N回・M並列）を、エージェント直書きで自動実行し、成果物をsketch/agent_loop配下へ保存する。このモードでは計画 md の新規作成は不要とする。
---

# Grafix Art Loop Orchestrator

## 目的

- アイデア生成 → M並列の実装/レンダリング → 批評/選抜 を N 反復で回す。
- 生成物とログを `sketch/agent_loop` 配下に保存し、追跡可能にする。

## デフォルトモード（skill発動時）

- 出力は常に `sketch/agent_loop/runs/<run_id>/...` に保存する。
- エージェント自身が反復ループを回す。
- `run_loop.py` / `run_one_iter.py` などの既存ランナー探索で実行経路を切り替えてはならない。
- 依存可否の判断を目的とした横断調査（リポジトリ全体のランナー探索）をしてはならない。
- skill 開始直後に `run_id` 作成 -> `iter_01` の variant 作成まで進める（不要な事前探索をしない）。
- 当該 `run_id` 以外の `sketch/agent_loop/runs/*` の中身を参照してはならない（過去 run の画像・JSON・`sketch.py`・ログの参照禁止）。
- `shared.py` などの共通実装を run 配下に置き、同一コードを import してパラメータだけ変える量産を禁止する。
- 各 variant は `variant_dir/sketch.py` に独立実装を書く（各ファイルでアプローチを分ける）。
- 各 variant の `sketch.py` で、`@primitive` と `@effect` を使った自前実装を必ず定義し、実際の描画に使う。
- 標準 primitive/effect の組み合わせだけで完結させる実装を禁止する（自前 primitive/effect を必須化）。
- ideaman/artist/critic は **LLM が担う role**であり、固定 JSON を吐くだけの補助スクリプト（例: `tools/ideaman.py`）で代替してはならない。
- ideaman/artist/critic を `cat > /tmp/*.py` などの一時 Python 生成で代替してはならない（role はセッション内で LLM が直接実行する）。
- `artist` は variant ごとの作業ディレクトリ（`.../iter_XX/vY/`）に `sketch.py` を生成する。
- レンダリングは `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export` を使い、各 variant の `out.png` を生成する。
- 各反復で contact sheet を作成し、`critique.json`（winner を含む）を保存する。
- `winner_feedback.json` は作らない（winner の正本は常に `critique.json`）。
- M 並列は exploration / exploitation を分けて運用する（序盤は探索寄り → 終盤は収束寄り）。

## Python 実行環境（固定）

- Art Loop で `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m grafix ...` 形式の実行は、`/opt/anaconda3/envs/gl5/bin/python -m grafix ...` に統一する。

## primitive/effect レジストリ参照順（CLI優先）

- 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` /
  `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects` の実行結果を使う。
- フォールバック: 上記が実行不能な場合のみ
  `.agents/skills/grafix-art-loop-orchestrator/references/primitives.txt` /
  `.agents/skills/grafix-art-loop-orchestrator/references/effects.txt` を参照する。
- `references/*.txt` はスナップショット扱いとし、CLI 成功時は常に CLI 結果を正とする。

## custom primitive/effect 実装規約

- `primitive_key` / `effect_chain_key` は探索レシピの設計キーとして使い、実装は `@primitive` / `@effect` の自前定義に落とす。
- 各 variant で最低 1 つの自前 primitive と最低 1 つの自前 effect を定義する。
- `custom_primitive_name` / `custom_effect_name` は同一 iteration 内で重複禁止とし、run 全体でも再利用を避ける。
- 監査のため、各 variant の `Artifact.params.design_tokens_used` に
  `custom_primitive_name` / `custom_effect_name` を必ず記録する。

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
- `mode` に関係なく、全 variant で `primitive_key` と `effect_chain_key` の組を必ず割り当てる。
- 同一 run 内で、同一の `primitive_key + effect_chain_key` の組み合わせ再利用を禁止する（iteration 横断）。
- 収束（exploitation）でも「同一コード + 定数調整のみ」は禁止し、primitive/effect の組を変えた別実装にする。

## exploration の多様性（primitive/effect をユニーク化）

- exploration variant には `artist_context.json` で `exploration_recipe` を必ず付与する。
  - 同一 iteration 内で `primitive_key` と `effect_chain_key` は**重複禁止**（両方ユニーク）。
  - `primitive_key` / `effect_chain_key` は「hero の primitive / hero の effect chain」を指す（support の補助 primitive は可）。
- `primitive_key` / `effect_chain_key` は下記レジストリに存在する値だけを使う（未知キー禁止）。
- exploration では原則 `baseline_artifact` / `critic_feedback_prev` を渡さない（ロックで即収束しないため）。
- artist は recipe を厳守し、`Artifact.params.design_tokens_used` に `recipe_id` / `primitive_key` / `effect_chain_key` を必ず記録する。
- exploration に限らず全 variant で `Artifact.params.design_tokens_used` へ
  `primitive_key` / `effect_chain_key` を記録し、再利用監査を可能にする。

### exploration recipe レジストリ（初期版）

- `primitive_key` 候補（`PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` に一致）:
  - `asemic` / `grid` / `line` / `lsystem` / `polygon` / `polyhedron` / `sphere` / `text` / `torus`
- `effect_chain_key` 候補（各 effect 名は `/opt/anaconda3/envs/gl5/bin/python -m grafix list effects` に一致）:
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
- 同一 run で未使用の組を優先し、重複が発生した場合は variant 生成前に再割当する。
- CLI 取得に失敗した場合のみ `references/primitives.txt` / `references/effects.txt` で検証する。

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
3. 各 `sketch.py` を `/opt/anaconda3/envs/gl5/bin/python -m grafix export` でレンダリングし、stdout/stderr も `run_dir` 配下へ保存する。
4. 各 iteration の終了時に、全 variant 画像をタイル状に並べた `iter_XX/contact_sheet.png` を必ず生成する。
5. 候補を比較し、`critique.json`（winner を含む）を保存する。
6. winner 情報を次反復へ引き継ぐ。
7. 最終 iteration 完了後、各 `iter_XX/contact_sheet.png` をさらにタイル状に並べた
   高解像度画像 `run_summary/final_contact_sheet_8k.png`（長辺 7680px 以上）を保存する。

## 実行後チェック（再発防止）

- 当該 run の生成物が `sketch/agent_loop/runs/<run_id>/` 以外に存在しないことを確認する。
- 特に `/tmp` やリポジトリ直下への一時スクリプト生成が無いことを確認する。
- 各 `iter_XX/contact_sheet.png` が存在することを確認する。
- `run_summary/final_contact_sheet_8k.png` が存在し、長辺が 7680px 以上であることを確認する。
- 代表プロンプト（例: `N=3`, `M=12`, `canvas=1024x1024`, `explore_schedule=0.7->0.2`）で同じ境界制約が維持されることを確認する。
