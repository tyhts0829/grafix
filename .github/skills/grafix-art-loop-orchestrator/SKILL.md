---
name: grafix-art-loop-orchestrator
description: Grafixアート反復（N回・M並列）を、エージェント直書きで自動実行し、成果物をsketch/agent_loop配下へ保存する。このモードでは計画 md の新規作成は不要とする。
---

# Grafix Art Loop Orchestrator

## 目的

- grafixを用いて、ハイクオリティなアートをLLM自身で生成する。副産物として生じるprimitiveやeffectをgrafixの新ネタ候補として貯めていく。
- 全イテレーション終了後、このスキルを改善(ex. コンテキストの無駄消費削減、より多様で高品質なアートを生成)するための`skill_improvement_report.json` 出力。

## 全体像

1. ideaman: 初回はアートの核となるアイデア`CreativeBrief.json`をM個生成。criticの批評を受け取った際は、それを踏まえた次反復の改善指示。
2. artist: 1を基に、M体のサブエージェントで完全に独立したM個の`sketch.py`バリアントを実装。レンダリングして画像生成。
3. critic: 2の**出力画像**を認識し、アートとしてのクオリティを批評した`critique.json`を生成。

- 上記を1イテレーションとする。1イテレーションごとに、生成アートをタイル状に並べたcontact_sheet.pngを出力。
- 全イテレーション後、`contact_sheet.png`をさらにタイル状に並べた`summary.png`を出力。合わせて`skill_improvement_report.json`を出力。

## 実行ルール

- skill 開始直後に `run_id` を作成し、全出力の保存先である `sketch/agent_loop/runs/<run_id>`ディレクトリを生成。その中にiter_XXディレクトリを都度作成。
- 生成の多様性を保つため、以下を遵守すること。
  - 各 variant ごとに作業ディレクトリ（`.../iter_XX/vY/`）を切り、`artist` は `sketch.py` を独立して実装（各ファイルでアプローチを分ける）。
  - 各 variant の `sketch.py` で、`@primitive` と `@effect` を使った自前実装を必ず定義し、実際の描画に使う。
  - 当該 `run_id` 以外の `sketch/agent_loop/runs/*` の参照禁止
  - `run_loop.py` / `template_art.py` などのスクリプトによるアイデア・批評・作品バリエーション生成禁止
  - 標準 primitive/effect の組み合わせだけで完結させる実装を禁止。
  - ideaman/artist/critic は **LLM が担う role**であり、その出力はLLMによって直接生成する。つまり、固定 JSON を吐くだけの補助スクリプト（例: `tools/ideaman.py`）での代替禁止。
- レンダリングは `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export` を使い、各 variant の `out.png` を生成する。
- `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m grafix ...` 形式の実行は、`/opt/anaconda3/envs/gl5/bin/python -m grafix ...` に統一。
- 出力境界
  - 出力（画像・JSON・`sketch.py`・stdout/stderr・診断ファイル・中間ファイル）は **すべて** `sketch/agent_loop/runs/<run_id>/` 配下に保存する。
  - `sketch/agent_loop` 外への出力を禁止する（例: `/tmp`, リポジトリ直下, ホーム配下の任意パス）。
  - `mktemp` の既定ディレクトリ、`tempfile` の既定 `/tmp` を使わない。
  - 一時作業が必要な場合は `sketch/agent_loop/runs/<run_id>/.tmp/` のみ使用する。
- 全イテレーション後の`skill_improvement_report.json`
  - `improvements` には、実際の run 内 evidence に紐づく改善提案だけを書く。「作品の出来」ではなく「skills 改善」に限定。
  - `discovery_cost` には、今回追加で調べた項目と「次回はどの references に前置きすべきか」を書く。
  - `redundant_info` には、次回入力から削除/要約できる情報のみを書く。
  - `decisions_to_persist` には、次 run で固定適用する決定だけを最小表現で残す。

## 参照資料

- イテレーション開始前に、まず次を読む。
  - `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`
  - `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md`
- 上記で足りる情報について、リポジトリ全体の横断探索をしない。
- 追加探索は「不足している具体情報」に限定。`skill_improvement_report.json`に再発防止策を残す。
- primitive/effect レジストリ参照順（CLI優先）
  - 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` /
    `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects` の実行結果を使う。
- フォールバック: 上記が実行不能な場合のみ
  `.agents/skills/grafix-art-loop-orchestrator/references/primitives.txt` /
  `.agents/skills/grafix-art-loop-orchestrator/references/effects.txt` を参照する。
