# Grafix Art Loop: skills 改善計画（`grafix_art_loop.md` 指摘対応）

作成日: 2026-02-07
ステータス: 実装進行中（主要項目完了）

## 目的

- `grafix_art_loop.md` の指摘を `.agents/skills/grafix-art-loop*` に反映し、反復ループの停滞要因を最小改修で潰す。
- 「抽象批評」ではなく「次反復の実装差分」に落ちる仕様へ統一する。

## 対象ファイル

- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/references/artist_profiles/artist_*.txt`

## 優先順位（最小改修で効く順）

1. token path の完全統一（schema / ideaman / critic / artist）
2. winner_feedback の仕様固定
3. exploration_recipe の実在キー供給（レジストリ化）
4. artist_profiles への `token_biases` 追加
5. critic 指示の判定可能性強化（Yes/No で判定できる `success_criteria`）
6. 停滞時の ideaman 再注入トリガ追加

## DoD（完了条件）

- token 指定は常に `design_tokens.*` のフルパスかつ leaf パス（例: `design_tokens.spacing.margin`）で統一される。
- `winner_feedback` の扱いが単一仕様に固定され、schema と SKILL 記述の不整合がない。
- exploration の `primitive_key` / `effect_chain_key` は実在キーだけが供給される。
- critic の directive は最大 3 件で、各 `success_criteria` が画像確認で Yes/No 判定できる。
- orchestrator に停滞判定と ideaman 再呼び出し条件が明記される。
- 全 artist profile に `token_biases` と `anti_patterns` が追加される。

## 実装チェックリスト

### 1) token path の完全統一（最優先）

- [x] `schemas.md` の `locked_tokens` / `mutable_tokens` / `token_keys` を「`design_tokens.` から始まる leaf パスのみ許可」に明記する。
- [x] `ideaman/SKILL.md` の多様性条件を `vocabulary.motifs` / `palette` から `design_tokens.vocabulary.motifs` / `design_tokens.palette` へ統一する。
- [x] `critic/SKILL.md` に「`token_keys` は leaf パスのみ。`spacing` のような中間キーは禁止」を追記する。
- [x] `artist/SKILL.md` に「変更可能なのは leaf token 最大 3 本」を追記する。

### 2) winner_feedback 仕様固定

- [x] 方針を一本化する（推奨: `winner_feedback.json` を廃止し、`critique.json` の `winner` を唯一の正とする）。
- [x] `orchestrator/SKILL.md` から重複保存ルールを整理し、保存物を明示する。
- [x] `schemas.md` から `winner_feedback` 相当の曖昧運用を除去または schema 化して明記する。

### 3) exploration_recipe の実在キー供給（レジストリ化）

- [x] orchestrator 側に `primitive_key` / `effect_chain_key` のレジストリ参照ルールを追加する。
- [x] `orchestrator/SKILL.md` の recipe 例を「実在キーのみ」の一覧へ更新する。
- [x] `artist/SKILL.md` に「未知キーは推測で埋めず失敗として返す」を明記する。

### 4) artist_profiles に `token_biases` / `anti_patterns` を追加

- [x] `artist_01.txt` 〜 `artist_06.txt` すべてに `token_biases` を追加する（優先 token path と推奨レンジ）。
- [x] 同ファイルに `anti_patterns` を追加する（避けるべき状態を 2〜5 行）。
- [x] `artist_05.txt`（Color and tone）に、プロッタ実装の翻訳（複数ペン/濃淡/ハッチ密度）を明示する。

### 5) critic 指示の判定可能性強化

- [x] `critic/SKILL.md` に「`success_criteria` は画像観察で Yes/No 判定可能な文のみ」を明記する。
- [x] `critic/SKILL.md` に良い/悪い `success_criteria` の短い対比例を追加する。

### 6) 停滞時の ideaman 再注入トリガ

- [x] `orchestrator/SKILL.md` に停滞条件を追加する（例: 同一 winner 2 回連続、同一 token_keys 2 回連続、改善停滞）。
- [x] 条件成立時は ideaman を再呼び出しし、`composition_template` と `design_tokens.vocabulary/palette` を再注入する運用を明記する。
- [x] 再注入時の変更上限（2〜3 レバー）を定義する。

### 7) 整合確認（ドキュメント横断）

- [x] 5 つの `SKILL.md` と `schemas.md` 間で token 名・JSON キー名・保存物の不整合がないことを確認する。
- [x] `docs/review/grafix_art_loop_skills_review_2026-02-07.md` の指摘に対して、対応済み/未対応を追記できる状態にする。

## 実装開始前の確認事項

- [x] `winner_feedback` は「廃止（`critique.json` に一本化）」で進めてよいか。
- [x] 停滞判定の閾値は「2 回連続」をデフォルトでよいか。
- [x] レジストリは `orchestrator/SKILL.md` 内記述で開始し、別ファイル化は必要時に行う方針でよいか。
