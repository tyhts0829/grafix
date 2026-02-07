# `.agents/skills` の grafix-art-loop 系 skills レビュー（2026-02-07）

対象:

- `.agents/skills/grafix-art-loop-ideaman/`
- `.agents/skills/grafix-art-loop-artist/`
- `.agents/skills/grafix-art-loop-critic/`
- `.agents/skills/grafix-art-loop-orchestrator/`

結論（TL;DR）:

- 役割分担（ideaman/artist/critic）と JSON 受け渡し（schemas.md）は分かりやすく、マルチエージェント反復の「最低限の共通言語」として良い。
- 一方で orchestrator が **2つのトリガー経路**（skill 発動時の agent-native ループ / `scripts/run_loop.py` 等の CLI）を持っており、ここが目的（skills による自動化）に対して余計な分岐・保守コスト・混乱源になりやすい。
- 「python ファイルを実行する形でトリガーできるのが不要」なら、**CLI モードを廃止（推奨）**するのが最もシンプル。残すなら「内部デバッグ用途」に封じ込め、skill の表面仕様から切り離すのが現実的。

Update（2026-02-07）:

- Option A を採用し、`.agents/skills/grafix-art-loop-orchestrator/scripts/` と `tools/*.py` を削除した。
- 以降の CLI に関する記述は「当時の観察」として残している（現行では存在しない）。

Update（2026-02-07, skills 改修追記）:

- 対応済み:
  - token path を `design_tokens.*` の leaf パスへ統一（schema / ideaman / artist / critic）。
  - `winner_feedback.json` を廃止し、winner の正本を `critique.json` に一本化。
  - orchestrator に実在キーの recipe レジストリと検証ルールを追加。
  - critic の `success_criteria` を Yes/No 判定可能文へ制約。
  - 停滞判定（2 回連続）と ideaman 再注入トリガを追加。
  - artist profiles に `token_biases` / `anti_patterns` を追加。
- 未対応:
  - なし（このレビュー起点の最小改修範囲）。

---

## 現状の構成と意図（観察）

### Role skills（ideaman / artist / critic）

- 3 role の責務が明確で、出力の必須要件（`CreativeBrief` / `Artifact` / `Critique`）が揃っている。
- critic が `locked_tokens` / `mutable_tokens` / `next_iteration_directives` を返す設計は、「次の実装差分」に落ちる形式なので反復が収束しやすい。
- artist 側に `mode`（exploration / exploitation）と `exploration_recipe` 反映を必須化しているのは、M 並列の「意味」を担保する良いルール。

気になった点:

- role skills の `SKILL.md` に「skill 発動中は計画 md 不要」を明記しているが、例外規約が role 側に分散している。運用ルールは orchestrator 側に集約した方が読み手が迷いにくい（ただし、ここは好み）。

### Orchestrator skill + scripts

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` は「デフォルトは agent-native で反復を回す」ことを明記している。
- それとは別に `.agents/skills/grafix-art-loop-orchestrator/scripts/run_loop.py` / `run_one_iter.py` が CLI として成立しており、`--ideaman-cmd` / `--artist-cmd` / `--critic-cmd` によって外部コマンド（JSON 受け渡し）を回せる。
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` は **scripts と role が受け渡す JSON 仕様**として書かれており、仕様の「正」の参照先が scripts 寄りに見える。

---

## 論点: 「Python 実行でトリガーできる」ことの位置づけ

現状、orchestrator は以下の二重インターフェースになっている:

1. **skill 発動（チャット内）**: エージェントが反復ループを直書きで回し、成果物を `sketch/agent_loop/` に保存する（想定）。
2. **CLI 実行（python）**: `python .agents/skills/grafix-art-loop-orchestrator/scripts/run_loop.py ...` のように、スクリプトが反復ループを回す。

補足: 「トリガーできてしまう」の定義を分けた方が議論が早い。

- **(a) 公式の入口としてサポートしたくない**: `SKILL.md` から CLI 手順を消し、skill から参照しない（＝“存在はしても使わない”）。
- **(b) 物理的に実行できるものを消したい**: ファイル自体を削除する（または実行不能にする）。repo に置く以上、完全に“実行不能”を保証するのは難しいので、基本は削除が一番明快。

この二重性が生みやすい問題:

- **目的の曖昧化**: “skills による自動化” なのか “CLI ツールとしての自動化” なのかが仕様上ブレる。
- **保守コストの増加**: どちらか一方を直すと他方が古くなる（JSON schema、探索/収束ルール、出力ディレクトリ規約など）。
- **運用の混乱**: 「通常は skill」「明示時は CLI」という注釈が増えるほど、チーム内の再現性が落ちる。

逆に CLI を残すことのメリットもある（採用する場合の理由）:

- 長時間/大量反復を **チャット外で安定実行**できる。
- JSON 受け渡しが固定化され、role 実装（`tools/*.py` 等）を差し替えやすい。
- contact sheet 生成など “機械仕事” をコードで確実に行える。

---

## 提案（選択肢）

### A) CLI モード廃止（推奨: 最もシンプル）

狙い:

- 「skills でマルチエージェント作品制作を自動化する」を唯一の入口にして、分岐を消す。

やること（方針レベル）:

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` から CLI の説明・例を削除する（agent-native のみ）。
- `scripts/run_loop.py` / `scripts/run_one_iter.py` / `scripts/grafix_adapter.py` / `scripts/make_contact_sheet.py` を削除（orchestrator の“実装”は skill 側に寄せる）。
- `references/schemas.md` は「skills の受け渡し仕様」として残す（scripts 参照の文言を外す）。

この選択のトレードオフ:

- チャット外での再現実行は弱くなる（必要なら別途、正式な `tools/` として設計し直すのが筋）。

### B) CLI は残すが “skill の表面” から外す（次善）

狙い:

- CLI の実利（再現性・安定実行）を残しつつ、「トリガー経路」を 1 つに見せる。

やること（方針レベル）:

- orchestrator の `SKILL.md` から CLI の使い方を削除（存在を言及しない / “内部ツール” 扱い）。
- `references/schemas.md` は scripts 依存の書き方をやめ、skills の I/O として定義する。
- scripts を残すなら、置き場所を `.agents/skills/.../scripts/` から `tools/` 配下などに移し「開発補助」に明確化する（= “skill の機能” に見えないようにする）。

---

## 追加の改善メモ（軽め）

- `docs/plan/grafix_art_loop_skill_invocation_mode_plan_2026-02-07.md` 内の対象パスが `.codex/skills/...` になっているが、実体は `.agents/skills/...` なので、ドキュメントの参照先は揃えた方がよい（混乱防止）。
- orchestrator scripts は fallback（brief/critique の自動生成など）が多く、「欠けたら fallback」運用になりやすい。リポジトリ方針（過度に防御しない）に寄せるなら、失敗は早めに表出させ、必要な修正をその場で入れる運用の方が合う。
