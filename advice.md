codex の skills って他の skills を呼び出せる？

---

結論から言うと、Codex の skills には「skill の中から別 skill をサブルーチンとして確実に呼び出す」ための専用機構（依存関係宣言や `import` 的なもの）は基本的にありません。Codex が skill を有効化する経路は、ユーザーがプロンプトで `$skill-name` を明示するか、タスクが description に合致すると Codex が判断して暗黙に使うかの 2 通りです。([OpenAI Developers][1])

ただし「他の skill を組み合わせて使う」こと自体は可能で、実務上は“呼び出し”というより「同一プロンプトで複数 skill を同時に有効化する」形になります。Codex は、呼び出された（invoked）skills の全文指示と、その skill 内に同梱された参照物を読み込みます（invoked “skills” と複数形で書かれています）。([OpenAI Developers][1]) なので、例えば CLI で最初から

`$skill-a $skill-b これこれをやって`

のように併記してしまうのが、意図どおりに“合成”する一番堅い方法です（暗黙選択に賭けない）。

再利用という観点では、skills は起動時に name/description しかコンテキストに入りません（本文は明示的に invoke されたときだけ入る）という設計なので、skill A の中で skill B の本文を当然の前提にするのはズレやすいです。([OpenAI Developers][2]) 代わりに、共通化したいものは「別 skill を呼ぶ」よりも、(1) 複数 skill を同時 invoke する、(2) 共通の薄い“オーケストレータ skill”を作って必要な規約をそこに集約する、(3) 共通のチェックリストやテンプレは各 skill の `references/` や `assets/` に置く／共通スクリプトは repo 側に置いて各 skill の `scripts/` から使う、の方が運用が安定します。skills には scripts や templates / references を同梱する前提も明示されています。([OpenAI Developers][2])

[1]: https://developers.openai.com/codex/skills/ "Agent Skills"
[2]: https://developers.openai.com/codex/skills/create-skill/ "Create skills"

---

インタラクティブなクリエーティブコーディングライブラリを書いてて、エージェントに作品を書いてほしい。 primitive や effect 関数がたくさんあるから、skills をうまく使いたい。 作品の書かせ方は、$grafix-draw-export コンセプトの指示　で行ってる。 どうするのがいいと思う？

---

あなたの状況（primitive/effect が多く、エージェントに「作品」を安定して書かせたい）だと、skills の設計で効くのは「巨大な 1 skill に全部詰める」よりも、「薄いオーケストレータ + 役割で分けた補助 skill を“同時に明示 invoke”する」運用です。Codex の skills は、起動時に入るのは基本的に各 skill の `name` と `description` だけで、本文（指示ボディ）は明示的に invoke したときにだけ入ります。したがって、普段のコンテキストを肥大させずに、必要なときだけ厚い指示を注入する、という分割が素直です。([OpenAI Developers][1])

まず前提として、skill は `SKILL.md`（必須）に加え、`scripts/`・`references/`・`assets/` を同梱できます。設計の肝は「重いもの（API カタログ、テンプレ、用語辞書、作品例、スタイルガイド）を references/assets 側に退避し、SKILL.md 本体は“手順と制約”に寄せて薄く保つ」ことです。([OpenAI Developers][2])

あなたが今やっている `$grafix-draw-export コンセプト指示` は、そのまま“出口”として活かしてよいです。ただし `$grafix-draw-export` に「primitive/effect を網羅的に教える」役を背負わせると、結局コンセプトごとの選択が雑になりやすい。ここは役割を分けて、毎回の作品生成で必要な skill 群をセットで呼ぶ形にした方が再現性が上がります（Codex はプロンプトに `$skill-name` を並べて明示 invoke できます）。([OpenAI Developers][2])

実務的におすすめの分割は次の構造です。`$grafix-draw-export` は「作品を 1 本書き切って export まで持っていく」工程管理だけに寄せ、選定や規約は別 skill に逃がします。

たとえば `.codex/skills/`（リポジトリ配下）に、以下の 3〜4 個を置きます。リポジトリスコープで管理でき、チーム運用にも乗ります（skills の配置場所と優先順位はドキュメントのとおり）。([OpenAI Developers][2])

1. `grafix-api-catalog`（参照特化）
   ここは「多すぎる primitive/effect の索引」を作るための skill です。`references/api.md` に、各 primitive/effect を “タグ付きの短い辞書”として列挙し、最低限「何を生成するか」「入力」「相性のいい effect」「典型パラメータ」「使用例（数行）」だけを書きます。ポイントは、網羅的説明ではなく “検索できる薄いカード”にすることです。これを人手で保守すると破綻するので、`scripts/build_catalog.py` のような Python スクリプトで docstring や型情報から自動生成し、カタログだけ更新できるようにします（スクリプト同梱は想定されている使い方です）。([OpenAI Developers][1])

2. `grafix-compose`（コンセプト → 構成決定）
   ここは「コンセプトを、具体的な構図・レイヤ構成・primitive/effect の最小セットに落とす」ための指示だけを持ちます。重要な制約を明文化してください。たとえば「1 作品あたり primitive は最大 3 種、effect は最大 2 種」「まず静的構図を完成させ、その後にインタラクションを追加」「乱数 seed の扱い」「フレームレート/計算量の上限」などです。skill は小さく・モジュール的に、曖昧さを潰して命令形で書くのが推奨です。([OpenAI Developers][1])

3. `grafix-interact`（インタラクション規約）
   インタラクティブ作品は、ここが曖昧だと破綻します。UI/入力（マウス、MIDI、OSC など）の抽象化レイヤ、パラメータ命名、レンジ、スムージング、状態管理（ステートフルかどうか）、フリーズ/リセットの挙動、といった “作品の骨格”を固定する skill を別立てします。`assets/interaction_template.py` のような雛形を同梱して、エージェントが毎回同じ枠組みで書くようにすると品質が安定します。([OpenAI Developers][1])

4. `grafix-draw-export`（実装・書き切り・エクスポート）
   今の入口 skill は、ここに置く責務を「実装 → 実行確認 →export→ 成果物の配置」のみに絞るのがよいです。`scripts/smoke_render.py` や `scripts/export_all.py` を用意して、最低限の再現性チェック（例外なし、出力ファイル生成、サイズ/背景透明など）を自動で通すようにします。スクリプトは“決定的な処理が必要なときだけ”に留め、基本は指示で寄せるのが推奨です。([OpenAI Developers][1])

使い方としては、「skill の中で別 skill を呼ぶ」発想ではなく、毎回のプロンプトで “セットとして明示 invoke”するのが堅いです。例えば次のように運用します。

```text
$grafix-api-catalog $grafix-compose $grafix-interact $grafix-draw-export
コンセプト: 〜〜（狙い、質感、時間変化、触ったときの反応、出力形式、キャンバスサイズ制約）
```

この形なら、作品ごとに必要な規約と参照が確実に有効化されます（明示 invocation が仕様として用意されています）。([OpenAI Developers][2])

最後に、SKILL.md の設計で外しやすい盲点を一つ挙げると、「description を雑に書く」ことです。Codex はまず `name/description` を見て skill を選ぶので、暗黙トリガを将来使う可能性があるなら、description には“いつ使うか”を具体的に書き、テスト用の例プロンプトも SKILL.md に含めておくのがよいです。([OpenAI Developers][1])

補足として、skill の雛形作成や反復は `$skill-creator` を使うのが早いです。あなたの現状の `$grafix-draw-export` を起点に、上の 3 skill を段階的に増やしていくのが最短です。([OpenAI Developers][2])

[1]: https://developers.openai.com/codex/skills/create-skill/ "Create skills"
[2]: https://developers.openai.com/codex/skills/ "Agent Skills"
