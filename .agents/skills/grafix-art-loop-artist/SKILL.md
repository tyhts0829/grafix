---
name: grafix-art-loop-artist
description: CreativeBrief と同一 variant の過去 loop 成果物を受けて、実装とレンダリングを行い、Artifact JSONを返す。
---

# Grafix Art Loop Artist

## 役割

- `CreativeBrief` の情報を受けて、1 variant の 1 loop 分の `sketch.py` を実装する。
- `loop_01` では初稿を作り、`loop_02..loop_LL` では同一 variant の直前 loop 成果物だけを見て完成度を高める。
- Grafix でレンダリング(画像化)し、`Artifact`JSONを返す。形式は`.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`参照
- 実装ガイドは`.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md` 参照

## 必須ルール

- Layerのthicknessは必ず0.005以下に設定する。
- 過去の `sketch.py` や `Artifact` を丸写ししてはならない（作品づくりの目的を壊す）。
- 一時 Python などで固定 `sketch.py`を生成する代替手段を使わない（artist は LLM role として実装を行う）。
- 単一テンプレート（共通 `shared.py` や同一 `sketch.py`）を使い、定数だけ変えて variant を量産してはならない。
- 同一 run 内で参照してよいのは、現在作業中の `round_XX/vYY` の直前 loop 成果物だけである。他 variant、他 round、過去 run は参照禁止。
- 出力先は `loop_dir` と `variant_dir` 配下のみを使う。
- 返却は必ず `Artifact` JSON 形式にする（成功/失敗の両方）。また同一内容を `loop_dir/artifact.json` に保存する。
- 出力境界の詳細は `grafix-art-loop-orchestrator` に従い、`/tmp` を含む `sketch/agent_loop` 外へ書き出さない。
- 各 loop は `loop_dir/sketch.py` に実装すること（import 前提の共通実装量産を禁止）。
- Art Loop で `python` 実行が必要な場合は、必ず `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `python -m ...` 形式は `/opt/anaconda3/envs/gl5/bin/python -m ...` に統一する。
- `artist_context.json` に `artist_profile_ref` があれば、そのパスを最優先で読み、無ければ `.agents/skills/grafix-art-loop-artist/references/artist_profiles/` を参照する。
- `creative_brief.json` はその round 専用の独立 brief とみなし、前 round の改善版として扱ってはならない。
- `creative_brief.design_axes`（`topology_key` / `silhouette_key` / `density_key` / `event_key` / `palette_key`）を実際の構図差分として反映すること。
- `topology_key` / `silhouette_key` の差分を、配色や密度だけの差に縮退させてはならない。異なる brief には異なる構図 family を与えること。
- 「安定して描ける既知 archetype」に丸め込んで brief を処理してはならない。same-run の既出 family に似た構図へ寄せて安定化する行為を禁止する。
- 各 loop の `sketch.py` で `@primitive` を使った自前 primitive を最低 1 つ定義する。
- 各 loop の `sketch.py` で `@effect` を使った自前 effect を最低 1 つ定義する。
- 定義した自前 primitive/effect は実際の描画パスに必ず使用する（未使用定義を禁止）。
- 各 loop の `sketch.py` で `from grafix.core.realized_geometry import RealizedGeometry` を import しない。
- レンダリングの標準出力/標準エラーは、それぞれ `loop_dir/stdout.txt` / `loop_dir/stderr.txt` に保存する（長文ログを会話へ貼らない）。
- `read-only` と推測で決めつけて失敗終了してはならない。`loop_dir` 配下への実書き込みを少なくとも一度は試し、その結果で判断する。
- レンダリングは `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export --callable <loop_dir から導く module:draw> --canvas <creative_brief.canvas.w> <creative_brief.canvas.h> --out loop_dir/out.png > loop_dir/stdout.txt 2> loop_dir/stderr.txt` の完全形を使う。
- `artist_context.json` に `prior_loop_artifact_ref` があれば、その参照先は同一 `round_XX/vYY` の直前 loop に限る。
- `.agents/skills/grafix-art-loop-artist/references/artist_profiles/` の作家性プロファイルを尊重する。
