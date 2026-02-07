## 全体所感

この一式は、「反復しても同じ物を吐く」「批評が抽象的で実装に落ちない」「探索が即収束して死ぬ」という典型的な破綻点を、かなり正面から潰せています。特に、成果物を run/iter/variant 単位で保存して追跡可能にする設計、exploration と exploitation を分けて引き継ぎを限定する設計、critic が locked/mutable と最大3本の directive を返す設計は、ループの健全性に直結します。

## いちばん先に直したい不整合

まず、トークンの名前空間がドキュメント間でズレています。schema では `design_tokens.vocabulary.motifs` や `design_tokens.palette` なのに、ideaman 側の多様性条件は `vocabulary.motifs` / `palette` と書いてあり、critic/artist の `locked_tokens` や `token_keys` を機械的に検証しづらくなります。ここは「トークン指定は常にフルパス（例: `design_tokens.spacing.margin`）」に統一した方がよいです。

## Orchestrator の穴

`winner_feedback.json` を保存すると書いてある一方で、そのフォーマットが schema に存在しません。実装側で “なんとなく” の JSON が増えると、後で解析・再利用ができなくなります。`winner_feedback.json` を廃して `critique.json` の winner セクションだけを見れば済むようにするか、逆に winner だけを抜いた schema を追加して固定するのが良いです。

次に、exploration の `primitive_key` / `effect_chain_key` をユニーク化する方針は良いですが、例として挙がっている recipe が Grafix 側に実在する保証がありません。artist 側は「不明点は推測で埋めない」と明記しているので、orchestrator が“実在するキーだけ”を供給する一段（レジストリ or 検証済みリスト）が無いと失敗率が上がります。

## Artist / Critic の改善ポイント

「変更は最大3トークン」は良い制約ですが、何を1トークンと数えるかが曖昧です（`spacing` 全体なのか、`spacing.margin` まで含むのか）。critic の `token_keys` を“葉（leaf）パス”に限定し、artist は「leaf を最大3本まで変更」にすると、ブレが減って収束が速くなります。

また、critic の評価軸は順序固定で妥当ですが、勝者理由と次アクションを厚く書く要求に比べ、`success_criteria` の“判定可能性”が弱いと、結局「良くなった気がする」でループが停滞します。数値化が嫌でも、「余白が呼吸して見える」「主役のシルエットが一撃で読める」「support が規則性を持つが主役を食わない」みたいに、画像を見て Yes/No が切れる文に寄せるのが良いです。

## Ideaman と停滞時の再注入

ideaman に「停滞時の再注入」が書かれているのに、orchestrator 側にトリガ条件が無いので、実装するとたぶん“呼ばれない”ままになります。たとえば「同一 winner が2回続いた」「directive の token_keys が2回連続で同じ」「explore_ratio を下げたのにスコアが改善しない」みたいな条件で、ideaman を再呼び出しして `composition_template` と `vocabulary/palette` の軸を差し替える、と明記すると運用が安定します。

## artist_profiles のレビュー

6つのプロファイルは短くて運用しやすい反面、「どの design_tokens にどう反映するか」が未定義です（PRIORITY/CHANGE_POLICY は方向性で、実装レバーに落ちていない）。ここが薄いと、artist が結局ノイズや思いつきに逃げがちになります。各プロファイルに `token_biases`（推奨レンジや優先する token path）と `anti_patterns`（やってはいけない状態）を2〜5行足すだけで、作品の“人間っぽさ”に寄せる速度が上がります。特に “Color and tone” はペンプロッタ前提だと解釈が割れやすいので、「複数ペン/濃淡/ハッチ密度」でトーンを作る、といった実装上の翻訳を最初から書いておくのが安全です。

---

このレビューを踏まえて最小改修で効く順番は、「(1) token path の完全統一（schema/ideaman/critic/artist）、(2) winner_feedback の仕様固定、(3) exploration_recipe の“実在キー”供給（レジストリ化）、(4) profiles に token_biases 追加」です。ここまで入れると、ループが“改善の仕方を学習する”側に寄って、出力の質が上がりやすくなります。
