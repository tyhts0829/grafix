# Grafix Art Loop LLM負荷削減・単純化計画

- 作成日: 2026-07-21
- ステータス: 実装・実制作A/B完了（処理量は達成、品質非劣性は未達）
- 対象: `.agents/skills/grafix-art-loop-*`
- 方針: 破壊的変更を許容し、互換ラッパーや旧形式のshimは作らない

## 目的

- Art Loopの主目的を「良いGrafix作品を少ないLLM処理で作る」に戻す。
- 過去の失敗対策として増えたrole、固定loop、長文JSON、重複ルール、自己監査を削る。
- 現代のLLMが一つの流れで構想・実装・画像確認まで行えることを前提にする。
- 品質担保は長い契約ではなく、少数候補、render成功、画像比較、必要時だけの修正に寄せる。

## 現状診断

### 1. LLM処理が乗算される

現行の必須role処理数の下限は、orchestrator自身の管理処理と失敗時retryを除いても次の通り。

```text
r * (v * l + 2) + 1

v * l : artist
+ 1   : roundごとのideaman
+ 1   : roundごとのcritic
+ 1   : run末尾のskill improvement report
```

- `r=4, v=6, l=2`: 最低57処理
- `r=3, v=3, l=3`: 最低34処理
- `r=1, v=3, l=2`: 最低9処理

`round`は相互に独立し、critic結果を次roundへ渡さない。そのため`r`と`v`は実質的にどちらも独立候補数であり、二階層にする利益が薄い。

### 2. 固定loopが全候補へ同じ費用を掛ける

最新の実run `run_20260717_073505_r1v3l2` では、最終候補3点を得るために完全な`sketch.py`を6本生成している。

- `sketch.py`: 6本、2,086行、69,630 bytes
- run全体: 61ファイル、約14 MB
- 良い初稿にも一律で2回目のloopを掛けており、修正の必要性や改善幅を見ていない

### 3. 作品以外の長文生成が多い

同runでLLMに作成を要求している主な管理JSONは次の通り。

| 種類 | ファイル数 | 合計bytes |
| --- | ---: | ---: |
| `creative_brief.json` | 3 | 6,408 |
| `artist_context.json` | 3 | 2,979 |
| `artifact.json` | 6 | 6,947 |
| `critique.json` | 1 | 10,164 |
| `diversity_ledger.json` | 1 | 1,861 |
| `skill_improvement_report.json` | 1 | 5,227 |
| 合計 | 15 | 33,586 |

特にcriticの`ranking.reason` 20行以上、ideamanの`intent` 300字以上、6種類の`design_axes`は、品質より出力量と契約遵守へ注意を使わせている。

### 4. 静的コンテキストも重複している

- 4個の`SKILL.md`、4個の主要reference、6個のartist profileで636行、36,453 bytesある。
- round間参照禁止、多様性、出力境界、render規則が複数ファイルで反復される。
- `project_quick_map.md`は探索削減用だが、最初に読む文書を7個以上列挙している。
- `grafix_artist_guide.md`は全primitive/effect一覧を持つ一方、CLIの`list`/`describe`も案内しており二重管理になっている。

### 5. 重い処理が品質改善へ閉じていない

- roundごとのcriticはarchive/ranking専用であり、制作へfeedbackしない。
- 毎runの`skill_improvement_report.json`は必須だが、自動的にはskillへ反映されない。
- 最新reportが指摘した`Layer + Layer`の誤例、再export時の`--overwrite`不足、docs MCP待ち停止は、現行guideに残っている。
- `mcp_grafix_docs_server.py`は290行あるが、同等の情報は`python -m grafix describe`で取得できる。
- 各loopでcustom `@primitive`と`@effect`を必須にする規約は、視覚上不要なwrapperや長いコードを誘発する。

## 採用する新モデル

### 基本方針

Art Loopを次の一つの流れへ置き換える。

```text
短い候補案を一括作成
  -> 各候補を1回実装・render
  -> contact sheetを1回比較
  -> winnerを短く選定
  -> 明確な欠点がある場合だけwinnerを最大1回修正
```

登録skillは1個に統合する。ideaman、artist、criticを独立skillとして維持しない。

### パラメータ

- `r / v / l`を廃止する。
- 主パラメータは候補数`n`だけにする。
- 既定値は`n=3`とする。
- 候補を増やしたい場合は`n`を明示的に増やし、自動roundは作らない。
- 固定loop数は持たない。修正は条件付きでwinnerのみ最大1回とする。

### 実行フロー

1. **run初期化**
   - flatなrunディレクトリを機械処理で作る。
   - userのテーマ、canvas、候補数を`run.json`へ保存する。

2. **concept cardの一括作成**
   - orchestratorが`n`候補を同時に構想する。
   - 1候補は`concept`、`composition`、`mark`、`palette`、`seed`だけを持つ。
   - 長文intent、実在作家名の個数要件、6個のdesign keyは廃止する。
   - batch内で`composition`が意味的に異なることだけを一度確認する。

3. **候補制作**
   - 各候補は一つの持続makerが担当し、loopごとに別agentへ作り直さない。
   - makerは`sketch.py`を一度実装し、renderして画像を確認する。
   - syntax/API/render失敗は同じmaker内で最大1回修正する。再失敗時はfailedとして次候補へ進む。
   - 初稿が正常なら、全候補への美的な固定refineは行わない。

4. **一括比較**
   - contact sheetはscriptで一度だけ生成する。
   - `n > 1`の場合だけ、短いfresh judgeでwinnerを選ぶ。
   - judgeの出力はwinnerと1〜3文の理由だけとし、20行批評と7固定評価軸は廃止する。

5. **条件付きrefine**
   - clipping、焦点不明、余白崩れ、線密度破綻のいずれかが明確な場合だけwinnerを最大1回修正する。
   - 同じmakerへ短い具体指示を返し、既存`sketch.py`をpatchする。
   - 修正後の画像を一度確認し、finalへコピーする。

6. **終了**
   - winnerの`sketch.py`、PNG、必要ならSVG、短い選定理由を保存する。
   - skill改善reportは通常runでは作らない。明示的な`audit`要求時、またはworkflow自体が失敗した場合だけ最大3項目を残す。

## 新しい出力構造

```text
sketch/agent_loop/runs/<run_id>/
├── run.json
├── candidates/
│   ├── v01/
│   │   ├── sketch.py
│   │   ├── out.png
│   │   ├── stdout.txt
│   │   └── stderr.txt
│   ├── v02/
│   └── v03/
├── contact_sheet.png
└── final/
    ├── sketch.py
    ├── out.png
    └── out.svg              # 明示要求時だけ
```

- `round_XX`と`loop_ZZ`階層を廃止する。
- `ArtistContext`、loopごとの`Artifact`、`Critique`、`DiversityLedger`を廃止する。
- path、round、loop、callable、statusなど、filesystemやexit codeから分かる情報をLLMに再記述させない。
- `run.json`を唯一の小さな管理JSONとし、concept card、render status、winner、短い理由を集約する。
- 旧runは移行せず、履歴としてそのまま残す。

## 残す品質・安全規約

以下だけをhard ruleとして単一skillに残す。

1. 全出力は現在の`run_dir`配下に置く。
2. Pythonは`/opt/anaconda3/envs/gl5/bin/python`を使う。
3. renderは`PYTHONDONTWRITEBYTECODE=1`と`--overwrite`を使い、exit codeと`out.png`を確認する。
4. Layerの`thickness`は`0 < thickness <= 0.005`とする。
5. `RealizedGeometry`を直接importしない。
6. contact sheetまたは候補画像を必ず画像レベルで確認する。
7. 候補間で構図familyを使い回さない。

custom `@primitive` / `@effect`は任意にする。Grafixの新op探索が目的のrunだけ、明示的に1候補へ要求する。

## skill / reference / scriptの整理

### 新規の正本

```text
.agents/skills/grafix-art-loop/
├── SKILL.md
├── references/
│   └── grafix_quick_guide.md
└── scripts/
    ├── init_run_dir.py
    └── make_contact_sheet.py
```

- `SKILL.md`: 新フロー、hard rule、完了条件だけを記載する。
- `grafix_quick_guide.md`: 正しい最小コード例、tuple I/O、Layerのtuple/list返却、render command、`list`/`describe`だけを記載する。
- 常時読む文書は`SKILL.md`だけとし、quick guideは実装時に必要箇所だけ読む。
- 必須instruction全体は150行または10 KB以下を目標にする。

### 削除するもの

- `.agents/skills/grafix-art-loop-ideaman/`
- `.agents/skills/grafix-art-loop-artist/`
- `.agents/skills/grafix-art-loop-critic/`
- 旧`.agents/skills/grafix-art-loop-orchestrator/`
- `references/schemas.md`
- `references/project_quick_map.md`
- `references/contact_sheet_spec.md`
- `artist_profiles/artist_*.txt`
- `scripts/mcp_grafix_docs_server.py`

旧skill名のshimは作らない。新しい呼び出し名を`grafix-art-loop`へ一本化する。

### 機械処理として残すもの

- `init_run_dir.py`
  - `--n`だけを受け、`candidates/vNN`を作る。
  - round/loop全組合せの事前作成をやめる。
- `make_contact_sheet.py`
  - `candidates/vNN/out.png`を一段で収集する。
  - round/finalの二段モードを廃止する。
  - 通常previewは長辺約2,048 pxとし、無条件8K upscaleをやめる。
- Grafix API調査
  - `python -m grafix list ...`と`python -m grafix describe ...`へ一本化する。
  - 全op一覧のreference複製とdocs MCPを使わない。

## 実装アクション

### Phase 1: 単一skillと最小contract

- [x] `.agents/skills/grafix-art-loop/SKILL.md`を新規作成する
- [x] `r / v / l`を`n`へ置き換え、固定loopを削除する
- [x] concept cardの最小項目を`run.json`内へ定義する
- [x] candidate makerの入力を「concept card + quick guide + 出力先」に限定する
- [x] fresh judgeの出力をwinnerと1〜3文の理由に限定する
- [x] skill auditを通常runの必須工程から外す

### Phase 2: reference削減

- [x] 現行APIに合う最小例を`grafix_quick_guide.md`へ書く
- [x] `Layer + Layer`をやめ、tuple/list返却へ修正する
- [x] render commandへ`PYTHONDONTWRITEBYTECODE=1`と`--overwrite`を固定する
- [x] primitive/effect全件一覧を削除し、CLI `list`/`describe`へ置き換える
- [x] artist profileとcustom op必須規約を削除する

### Phase 3: flatな機械処理

- [x] `init_run_dir.py`を`--n`とflat layoutへ書き換える
- [x] `make_contact_sheet.py`を単一candidate sheetへ書き換える
- [x] 8K化は明示要求時だけにする
- [x] render statusとattempt数を機械的に`run.json`へ反映する
- [x] `run.json`以外のrole間JSONを生成しないことを確認する

### Phase 4: 旧構成の削除

- [x] ideaman / artist / critic / orchestratorの旧skillを削除する
- [x] schemas / quick map / contact sheet spec / artist profilesを削除する
- [x] docs MCP serverを削除する
- [x] activeな参照から旧skill名、`round_XX`、`loop_ZZ`、`r/v/l`を除く
- [x] 過去runと過去計画mdは移行しない

### Phase 5: 検証

- [x] `init_run_dir.py --n 3 --dry-run`でflat layoutだけが出ることを確認する
- [x] 3候補のexportが成功し、各`out.png`が存在することを確認する
- [x] contact sheetが`v01..v03`を数値順に一度だけ収集することを確認する
- [x] 通常runでlong critique、ledger、skill report、loop別sketchが生成されないことを確認する
- [x] `rg`で削除したrole/referenceへのactive参照が残っていないことを確認する
- [x] 対象限定のtest / lintを実行する

## 実施結果（2026-07-21）

- `grafix-art-loop` 1 skillへ統合し、旧4 skillと旧reference、artist profile、docs MCPを削除した。
- 常時instructionは`SKILL.md`、オンデマンドreference、UI metadataの合計で143行、7,898 bytesになった。
- `init_run_dir.py`は`n`候補のflat layoutと初期`run.json`を生成する。
- `make_contact_sheet.py`はflat候補を数値順に一度だけ集約し、既定長辺を2,048 px以下にする。
- 最小3候補を実exportし、各PNGとcontact sheetが生成できることをsmoke testした。
- skill validation、Ruff lint/format、dry-run、不正入力、出力境界、0件エラーを確認した。
- ユーザー確認後、旧方式`run_20260717_073505_r1v3l2`と新方式`run_20260721_220555_n3`を同系統テーマで実制作比較した。
- 独立role処理は9から5へ44.4%減、実測記録範囲のwall timeは約1,570秒から約646秒へ58.9%減となった。
- 候補コードは2,086行から834行へ60.0%減、通常run相当の管理JSONは33,586 bytesから2,211 bytesへ93.4%減となった。
- workflow名を伏せたrefine後の3者比較では、3者全員が旧方式を選択した。平均点は新方式7.03、旧方式8.73、差は-1.70だった。
- よって処理量の目標は達成したが、「新方式が明白に劣らない」という品質条件は未達である。次の変更候補はroleや固定loopの復活ではなく、短い品質下限として主焦点、線の階層、密度差を明示することとする。

## 評価方法

### 処理量

同じ候補数3で、現行`r1v3l2`と新`n=3`を比較する。

- 独立role実行/長いhandoff:
  - 現行下限: 9
  - 新方式: maker 3 + short judge 1 = 4
  - 条件付きwinner refine込み: 最大5
- 必須instruction:
  - 現行: 636行、36,453 bytes
  - 目標: 150行または10 KB以下
- 管理用LLM出力:
  - 現行実績: 33,586 bytes
  - 目標: `run.json`と短い選定理由だけ
- wall time、LLM token、tool call数、render retry数、生成ファイル数も取得可能な範囲で記録する。

### 品質

- 全候補がrender成功すること。
- 少なくとも2候補のsilhouette / composition familyが明確に異なること。
- contact sheetを必ず画像確認すること。
- winnerがclipping、焦点不明、余白崩れ、過密線の重大問題を持たないこと。
- 現行方式と新方式のwinnerをworkflow名を伏せて比較し、新方式が明白に劣らないこと。
- 長時間のA/B art runは実装とは分け、ユーザー確認後に実施した。

## 完了条件

- activeなArt Loop skillが1個だけになる。
- public parameterが候補数`n`だけになる。
- 通常runで各候補の`sketch.py`は1本だけ生成される。
- 全候補への固定refine、20行批評、diversity ledger、毎run自己監査が消える。
- default `n=3`の独立role処理が4、条件付きrefine込みでも5以下になる。
- 出力境界、render成功、線幅、画像確認、候補差という最小品質規約が維持される。
- 小規模比較で処理量が大きく減る。実測では達成した。
- 作品品質が明白に低下しない。実測では未達だった。

## 非目標

- 旧`r/v/l`形式や旧skill名の互換維持
- 過去runディレクトリの変換
- 自動embedding、CLIP、画像類似度クラスタリングの追加
- 新しいMCP serverや別roleの追加
- 失敗するたびにJSON fieldや禁止文を増やすこと

今後、新しいrole、schema、server、必須fieldを追加する場合は、単純な方式より品質または処理量が改善することを小さな比較で示してから採用する。
