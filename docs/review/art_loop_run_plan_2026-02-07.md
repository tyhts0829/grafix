# Art Loop 実行計画（2026-02-07）

対象パラメータ:
- N=3
- M=12
- canvas=1024x1024
- explore_schedule=0.7->0.2
- 出力先固定: `sketch/agent_loop`

## チェックリスト

- [ ] run_id を採番し、`sketch/agent_loop/runs/<run_id>/` を作成する
- [ ] Ideaman role で初回 `creative_brief.json` を作成する（固定テンプレを使わない）
- [ ] iteration 1 の 12 variant を作成する
- [ ] exploration / exploitation 本数を算出し、各 `artist_context.json` に mode を入れる
- [ ] exploration variant に重複なし `exploration_recipe`（primitive/effect）を割り当てる
- [ ] 各 variant の `sketch.py` を artist role で実装する
- [ ] `/opt/anaconda3/envs/gl5/bin/python -m grafix export` で `out.png` を生成する
- [ ] 各 variant の `artifact.json` を保存する（成功/失敗含む）
- [ ] contact sheet を作成する
- [ ] Critic role で全候補を評価し `critique.json` を保存する（winner/locking/directives 必須）
- [ ] iteration 2, 3 で winner 引き継ぎと explore_ratio 線形減衰を適用する
- [ ] 停滞判定に該当した場合は ideaman を再注入する（同一意図で 2-3 レバーのみ変更）
- [ ] 出力境界チェックを実行する（`sketch/agent_loop/runs/<run_id>/` 外への生成がないこと）
- [ ] 完了報告として run の成果物パスと winner 推移を共有する
