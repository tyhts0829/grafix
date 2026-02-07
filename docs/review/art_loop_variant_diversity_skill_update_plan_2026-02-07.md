# Art Loop Variant Diversity Skill 更新計画（2026-02-07）

## 目的

- 1つの共通実装をパラメータだけ変えて量産する運用を禁止する。
- variant / iteration ごとに、primitive と effect の組み合わせを変えた実装を必須化する。

## 対象ファイル

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`

## 実装アクション（チェックリスト）

- [x] `orchestrator` に「共通テンプレ量産禁止」と「variant 独立実装必須」を追記する。
  - `shared.py` や単一テンプレートを基にしたパラメータ差分量産を禁止。
  - variant ごとに `sketch.py` で異なるアプローチ（primitive/effect の組）を実装することを必須化。
  - 同一 run 内で同一の `primitive_key + effect_chain_key` の再利用を禁止。
- [x] `artist` に「パラメータ差分のみの実装禁止」を追記する。
  - 各 variant が独立した hero 実装を持つことを必須化。
  - 「同一コード + 定数変更のみ」を禁止する。
- [x] `critic` に多様性判定の強制を追記する。
  - 実質同一アプローチ（primitive/effect 同一や変化乏しい候補群）を減点対象にする。
  - 次反復 directive で実装アプローチ差分の再導入を要求できるようにする。
- [x] `ideaman` に iteration 単位のアプローチ差分指示を追記する。
  - `variation_axes` へ primitive/effect の切替軸を明示することを必須化。
- [x] `rg` で追記の反映を確認する。
- [x] 本計画ファイルのチェックリストを完了状態に更新する。

## 完了条件

- 対象 4 ファイルに、量産禁止と variant / iteration 差分必須の規約が反映されていること。
- 本ファイルのチェックリストが完了状態になっていること。
