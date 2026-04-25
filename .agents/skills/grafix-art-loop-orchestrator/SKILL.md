---
name: grafix-art-loop-orchestrator
description: Grafixアート反復（r round・v variant・l loop）を、エージェント直書きで自動実行し、成果物をsketch/agent_loop配下へ保存する。このモードでは計画 md の新規作成は不要とする。
---

# Grafix Art Loop Orchestrator

## 目的

- grafixを用いて、ハイクオリティかつ高多様性なアートをLLM自身で生成する。副産物として生じるprimitiveやeffectをgrafixの新ネタ候補として貯めていく。
- 全 round 終了後、このスキルを改善(ex. コンテキストの無駄消費削減、より多様で高品質なアートを生成)するための`skill_improvement_report.json` 出力。

## パラメータ語義

- `r`: round 数
- `v`: 1 round あたりの variant 数
- `l`: 1 variant が同一 round 内で回す改善 loop 数

## 全体像

1. ideaman: **毎 round を独立ラウンドとして扱い**、その round 専用の新規 `CreativeBrief.json` を `v` 個生成する。過去 round の `brief` / `critique` / 画像 / `sketch.py` は入力に使わない。
2. artist: 1 を基に、各 `round_XX/vYY` で `loop_01..loop_LL` を順に回す。`loop_01` で初稿を実装し、`loop_02..loop_LL` では同一 variant の直前 loop の画像と `sketch.py` を見て改善する。入れ子の Codex 実行は使わない。
3. critic: 2 の **各 variant の最終 loop 出力画像**だけを認識し、当該 round 内での比較批評 `critique.json` を生成する。批評は次 round の入力にしない。

- 上記を 1 round とする。round ごとに、最終 loop 出力をタイル状に並べた `contact_sheet.png` を出力する。
- 全 round 後、`contact_sheet.png` をさらにタイル状に並べた `summary.png` を出力し、合わせて `skill_improvement_report.json` を出力する。

## 実行ルール

- skill 開始直後に `run_id` を作成し、全出力の保存先である `sketch/agent_loop/runs/<run_id>` ディレクトリを生成する。その中に `round_XX/vYY/loop_ZZ` ディレクトリを都度作成する。
- run ディレクトリ生成は機械処理として次を使って固定する（run_id は `run_YYYYMMDD_HHMMSS_r{r}v{v}l{l}` 形式のみ）。
  - `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python .agents/skills/grafix-art-loop-orchestrator/scripts/init_run_dir.py --r <R> --v <V> --l <L> --update-latest`
- orchestrator は run 開始時に `run_summary/diversity_ledger.json` を作成し、同一 run 内で採用済みの構図 family を記録する。
- `diversity_ledger.json` には最低でも `round` / `variant_id` / `brief_uniqueness_key` / `topology_key` / `silhouette_key` / `family_summary` / `forbidden_from_round` を残す。
- **round 間の改善ループを禁止する。**
  - `round_01` の `critique.json` / `CreativeBrief` / 画像 / `sketch.py` を `round_02` へ入力してはならない。
  - winner 継承、改善版生成、前 round の refinement といった発想を使ってはならない。
  - 各 round は「独立した新規探索ラウンド」として扱う。
- round 再参照禁止は「ファイルを読まない」だけでは不十分である。same-run 内で既出の archetype / 構図 family を頭の中で再利用することも禁止する。
- **loop 改善は同一 variant の中だけで許可する。**
  - `round_XX/vYY/loop_02` 以降は、同一 `round_XX/vYY` の直前 loop の `sketch.py` / `Artifact` / 画像だけを参照してよい。
  - 他 variant の loop 出力や、他 round の成果物を loop 改善に使ってはならない。
- 生成の多様性を保つため、以下を遵守すること。
  - 各 variant ごとに作業ディレクトリ（`.../round_XX/vYY/loop_ZZ/`）を切り、`artist` は各 loop の `sketch.py` を独立して実装する。
  - ideaman/artist/critic は **LLM が担う role**であり、その出力はLLMによって直接生成する。つまり、固定 JSON を吐くだけの補助スクリプト（例: `tools/ideaman.py`）での代替禁止。
  - ideaman は各 `CreativeBrief` に `design_axes` を入れ、`brief_uniqueness_key` / `topology_key` / `silhouette_key` / `density_key` / `event_key` / `palette_key` を必ず埋める。
  - 同一 run 内で `brief_uniqueness_key` の重複を禁止する。
  - `brief_uniqueness_key` の一意性だけでは不十分である。`topology_key` / `silhouette_key` が文字列上は異なっても、意味レベルで同じ構図 family なら違反とみなす。
  - orchestrator は「前 round の出来」を根拠に次 round の軸を決めてはならない。round ごとの相違は最初から別種の brief を作ることで担保する。
  - orchestrator は loop 内改善であっても、別 variant の構図や勝敗を流用してはならない。
  - orchestrator は各 round 開始前に `diversity_ledger.json` を見て、既出 family を `forbidden family` として列挙し、その round の共通 identity と合わせて ideaman に渡す。
  - ideaman が返した `v` 本の brief は、確定前に orchestrator が same-round 内および既出 family との意味重複を点検する。`topology_key` / `silhouette_key` が実質同型なら却下して再生成する。
  - round の brief を確定したら、orchestrator は採用された family を `diversity_ledger.json` へ追記する。
- `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m grafix ...` 形式の実行は、`/opt/anaconda3/envs/gl5/bin/python -m grafix ...` に統一。
- contact sheet 生成は創作判断ではなく機械処理として、次を使って固定する。
  - round 用:
    `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python .agents/skills/grafix-art-loop-orchestrator/scripts/make_contact_sheet.py --mode round --round-dir sketch/agent_loop/runs/<run_id>/round_XX`
  - 最終集約用:
    `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python .agents/skills/grafix-art-loop-orchestrator/scripts/make_contact_sheet.py --mode final --run-dir sketch/agent_loop/runs/<run_id>`
- 出力境界
  - 出力（画像・JSON・`sketch.py`・stdout/stderr・診断ファイル・中間ファイル）は **すべて** `sketch/agent_loop/runs/<run_id>/` 配下に保存する。
  - `sketch/agent_loop` 外への出力を禁止する（例: `/tmp`, リポジトリ直下, ホーム配下の任意パス）。
  - `mktemp` の既定ディレクトリ、`tempfile` の既定 `/tmp` を使わない。
  - 一時作業が必要な場合は `sketch/agent_loop/runs/<run_id>/.tmp/` のみ使用する。
- 全 round 後の`skill_improvement_report.json`
  - `improvements` には、実際の run 内 evidence に紐づく改善提案だけを書く。「作品の出来」ではなく「skills 改善」に限定。
  - `discovery_cost` には、今回追加で調べた項目と「次回はどの references に前置きすべきか」を書く。
  - `redundant_info` には、次回入力から削除/要約できる情報のみを書く。
  - `decisions_to_persist` には、次 run で固定適用する決定だけを最小表現で残す。

## Artist 実行

- `artist` はこのセッションの通常のコード編集とコマンド実行で進め、各 `loop_dir` に対して `sketch.py` / `out.png` / `artifact.json` / `stdout.txt` / `stderr.txt` を直接そろえる。
- `loop_01` は brief から初稿を作る。`loop_02..loop_LL` は同一 variant の直前 loop だけを見て改稿する。
- `creative_brief.json` と `artist_context.json` は `variant_dir` に保存し、loop ごとに書き換えない。
- 実装ルール自体は `grafix-art-loop-artist` と `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md` に従う。
- `codex exec` の入れ子起動や、専用の artist MCP サーバは使わない。
- run 配下のログ確認は通常のローカル読取コマンドで行う。

## 参照資料

- round 開始前に、まず次を読む。
  - `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`
  - `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md`
  - `.agents/skills/grafix-art-loop-orchestrator/references/contact_sheet_spec.md`（contact sheet 生成時）
- 上記で足りる情報について、リポジトリ全体の横断探索をしない。
- 追加探索は「不足している具体情報」に限定。`skill_improvement_report.json`に再発防止策を残す。
- primitive/effect レジストリ参照順（CLI優先）
  - 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` /
    `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects` の実行結果を使う。
- フォールバック: 上記が実行不能な場合のみ
  `.agents/skills/grafix-art-loop-orchestrator/references/primitives.txt` /
  `.agents/skills/grafix-art-loop-orchestrator/references/effects.txt` を参照する。

## 独立ラウンド方針

- 各 round は「改善フェーズ」ではなく「別系統の brief を投げるラウンド」。
- `critic` は archive / ranking 用であり、次 round の ideation へ feed しない。
- `artist_context.json` の `critic_feedback_prev` は常に `null` とする。
- loop 内改善で参照してよいのは同一 variant の直前 loop の成果物だけとする。
- diversity は「前回を少し変える」ではなく、「最初から異なる topology / silhouette / density / event / palette を割り当てる」ことで作る。
- diversity guardrail は「過去 round を見ない」ことに加えて、「同一 run で既出の構図 family を再使用しない」ことまで含む。
