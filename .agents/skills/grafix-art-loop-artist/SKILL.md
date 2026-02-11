---
name: grafix-art-loop-artist
description: CreativeBrief・critic指示を受けて、実装とレンダリングを行い、Artifact JSONを返す。
---

# Grafix Art Loop Artist

## 役割

- `CreativeBrief` の情報を受けて、アート作品を1 バリアントを実装する。
- Grafix でレンダリング(画像化)し、`Artifact`JSONを返す。形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`参照

## 必須ルール

- 過去の `sketch.py` や `Artifact` を丸写ししてはならない（作品づくりの目的を壊す）。
- 一時 Python などで固定 `sketch.py`を生成する代替手段を使わない（artist は LLM role として実装を行う）。
- 単一テンプレート（共通 `shared.py` や同一 `sketch.py`）を使い、定数だけ変えて variant を量産してはならない。
- 当該 `run_id` 以外の `sketch/agent_loop/runs/*` の中身（過去 run の `sketch.py` / `Artifact` / 画像 / `critique.json`）を参照してはならない。
- 出力先は `variant_dir` 配下のみを使う。
- 返却は必ず `Artifact` JSON 形式にする（成功/失敗の両方）。また同一内容を `variant_dir/artifact.json` に保存する。
- 出力境界の詳細は `grafix-art-loop-orchestrator` に従い、`/tmp` を含む `sketch/agent_loop` 外へ書き出さない。
- 各 variant は `variant_dir/sketch.py` に独立したアプローチ実装を持つこと（import 前提の共通実装量産を禁止）。
- Art Loop で `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m ...` 形式は `/opt/anaconda3/envs/gl5/bin/python -m ...` に統一する。
- 各 variant の `sketch.py` で `@primitive` を使った自前 primitive を最低 1 つ定義する。
- 各 variant の `sketch.py` で `@effect` を使った自前 effect を最低 1 つ定義する。
- 定義した自前 primitive/effect は実際の描画パスに必ず使用する（未使用定義を禁止）。
- レンダリングの標準出力/標準エラーは、それぞれ `variant_dir/stdout.txt` / `variant_dir/stderr.txt` に保存する（長文ログを会話へ貼らない）。
- `references/artist_profiles/` の作家性プロファイルを尊重する。

## 調査コスト削減（参照優先順）

- まず `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md` を参照する。
- 次に `.agents/skills/grafix-art-loop-orchestrator/references/grafix_usage_playbook.md` を参照する。
- 上記で足りる情報は再調査しない。足りない情報だけ追加探索する。

## primitive/effect レジストリ参照順（CLI優先）

- 第1優先: `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives` /
  `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects`。
- フォールバック: 実行不能時のみ
  `.agents/skills/grafix-art-loop-orchestrator/references/primitives.txt` /
  `.agents/skills/grafix-art-loop-orchestrator/references/effects.txt`。
