# Grafix Art Loop: skills を LLM 主導に戻す（ideaman 固定化の排除）改善計画

作成日: 2026-02-07

## 背景 / 問題

- `ideaman` の出力（`creative_brief.json`）が毎回同じになるケースがあり、作品づくりの目的をスポイルしている。
- 実例として `sketch/agent_loop/runs/<run_id>/tools/ideaman.py` が **固定の JSON を出力する実装**になっている run がある。
  - この場合、`ideaman_stdout.txt` / `creative_brief.json` が同一になるのは仕様どおり（=壊れているのではなく、設計が目的に反している）。
- 今後は `.agents/skills/grafix-art-loop-*` を「LLM が ideaman/artist/critic として振る舞う」前提に寄せ、
  - 固定テンプレを吐くだけの手段（Python での固定生成等）を禁止
  - LLM が毎回 “作る” ための最低限のガードレール（レバーの明確化 / 多様性の担保）
  を skills 側に組み込む。

## ゴール（DoD）

- [x] ideaman が **固定テンプレをコピペせず**、run/iteration のコンテキストを使って `CreativeBrief` を生成する。
- [x] 同一入力でも「毎回同じ」になりにくいよう、ideaman に **多様性のレバー**（composition/vocabulary/palette 等の差）を必須化する。
- [x] `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` の例が “そのままコピペされる” 罠にならない（値はプレースホルダ化 + 注意書き）。
- [x] `.agents/skills/grafix-art-loop-*` を通読して、作品づくりの目的を損ねる「固定化 / 逃げ道 / 責務のねじれ」を潰す。

## 対象ファイル

- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`

（必要なら追加）

- `.agents/skills/grafix-art-loop-ideaman/references/*`（ideaman の “方向性ライブラリ” を切り出す場合）

## 改善方針（シンプル優先）

- **固定 JSON を吐く Python 実装で ideaman を代替しない**（作品づくりの目的に反する）。
- ideaman は「抽象ムード」ではなく **実装レバー（design_tokens）**を作る役に徹する。
- 多様性は「ランダムに散らす」ではなく、**構図テンプレ + 語彙 + パレット + スペーシング**の組み合わせで担保する。
- 過度な検証・防御はしない。代わりに skill 文面で “やるべきこと/やってはいけないこと” を短く固定する。

## 実装タスク（チェックリスト）

### 1) 現状監査（spoiler 探し）

- [x] role/orchestrator の SKILL.md と schemas.md を通読し、次を列挙する
  - 固定テンプレを誘発する記述（具体例が強すぎる、値が固定、出力例が唯一、等）
  - 「LLM が作る」代わりに「コードが固定生成する」逃げ道が残っている箇所
  - 責務のねじれ（誰が brief を生成/更新するか、誰がレンダするか、等）

監査で見つけた spoiler（今回潰したもの）:

- `schemas.md` の例に具体値（数値/色）が含まれており、ideaman がコピペしやすい。
- ideaman `SKILL.md` に「固定テンプレ禁止 / 毎回差を作る」ルールが無く、結果として同一 brief の再生産を止められない。
- orchestrator `SKILL.md` に「ideaman/artist/critic は LLM role（固定 JSON 生成スクリプトで代替しない）」の明記が無いと、`tools/ideaman.py` のような逃げ道が生まれる。
- artist/critic 側も “定型出力” の禁止が弱い（同じ artifact / 同じ批評を返しがち）。

### 2) ideaman を LLM 主導に強化

- [x] ideaman `SKILL.md` に “禁止” を追加
  - 固定テンプレの出力禁止（前回の brief の丸写し、schemas の例の丸写し等）
- [x] ideaman `SKILL.md` に “多様性の最低要件” を追加
  - 例: `composition_template` / `vocabulary.motifs` / `palette` のうち **少なくとも 2 つは毎回変える**
  - `variation_axes` は必ず **token 名を含む**（次の exploration の軸になる）
- [x] ideaman が参照できるコンテキスト（`run_id` / `iteration` / 前回 winner の要点）がある場合は、それを **必ず** brief に反映するルールを追加

### 3) schemas.md の「コピペ罠」除去

- [x] `schemas.md` の例を、値の固定を避けた書き方にする
  - 例: 数値をダミー値ではなく `float` / `int` のプレースホルダに寄せる、または複数例にして “コピペ唯一解” を作らない
- [x] “値は自由だが、レバーとして機能するように決める” 旨を冒頭に明記する

### 4) artist / critic / orchestrator の整合

- [x] orchestrator `SKILL.md` に「role skills の運用ルールは orchestrator に集約する」方針が一貫しているか確認（既に集約済みだが再点検）
- [x] artist/critic の `SKILL.md` に “固定テンプレの丸写し禁止” を最小限追加
- [x] exploration/exploitation と `exploration_recipe` の位置づけが、ideaman の brief と矛盾しないように調整（schemas と SKILL で齟齬が出ないことを確認）

### 5) 受け入れ確認（ローカルでできる範囲）

- [x] `rg` で「固定テンプレ誘発」になりそうな文言が残っていないか確認
- [x] 期待する運用（LLM が ideaman/artist/critic をやる）が SKILL.md 上で読み取れることを確認

## 決定

- [x] schemas.md の例は「プレースホルダ化」を採用（コピペ罠を作らない）
