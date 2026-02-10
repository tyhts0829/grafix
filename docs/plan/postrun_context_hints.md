# 実行後メモ: コンテキスト節約のために事前にあると便利だった情報

この run (`run_20260208_173938_n4m4_a5`) を回して、毎回の探索で繰り返し参照が必要だった情報を整理。
次回以降は以下を最初から渡すと、探索・確認コストを減らせる。

## 1. primitive/effect の「使える引数だけ」短縮表
- `primitive_key` / `effect_chain_key` のキー一覧だけでなく、主要引数（型・安全レンジ）を1行で持っておく。
- 特に `clip`（2入力必須）、`repeat`（layout差分）、`pixelate/quantize`（step>0 必須）は毎回確認が発生した。

## 2. フォント解決ポリシーの固定
- `text` primitive は環境差で失敗しやすい。
- 既知の使用可能フォント（例: `data/input/font/GoogleSans-Bold.ttf`）を run 開始時に固定で渡すと再試行が減る。

## 3. 評価の最小スコアリングテンプレ
- critic評価軸（構図安定、視線誘導、密度余白、語彙一貫性など）に対する重みを事前固定すると、ranking作成の迷いが減る。
- 例: `構図 0.25 / 誘導 0.20 / 密度余白 0.20 / 語彙 0.15 / 破綻回避 0.10 / 多様性 0.10`

## 4. 前iterationから次iterationへ渡す「要約1枚」
- `winner` 全文ではなく、以下だけの compact JSON があると十分:
  - `locked_tokens`
  - `mutable_tokens`
  - `next_directive_top2`
  - `avoid_patterns`（失敗要因2-3件）

## 5. recipe 使用履歴の機械可読台帳
- `primitive_key + effect_chain_key + custom names` の既使用一覧を1ファイルで持つと、重複監査が簡単。
- 今回は `run_spec.json` と各 `artifact.json` を都度照合したため、やや冗長だった。

## 6. contact sheet 生成仕様の固定
- タイル数、セルサイズ、ラベル形式、最終8kの最小長辺をテンプレ化しておくと、後段調整（1px不足等）が防げる。
- 目安: `target_long_side` は安全側で `>= 7690` を使う。

## 7. 失敗時の即時分岐ルール
- 例: `text` 失敗時は「フォント絶対パスを注入して再実行」を固定ルール化。
- これを run 規約に書いておくと、エラー復旧の文脈説明を短縮できる。

## 8. 出力境界監査のチェックリスト
- 「run配下のみ」「iter contact sheet全件」「最終8k長辺」「Artifact必須キー」の4点を最後に一括確認する定型を事前配布すると、確認手順が短くなる。

