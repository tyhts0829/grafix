# Grafix Art Loop: A実装改善計画（LLM role強制 + 出力境界固定）

作成日: 2026-02-07

## 背景 / 問題

- `"$grafix-art-loop-orchestrator ... N=3 M=12 ..."` 実行時に、`/tmp/run_agent_loop_n3_m12.py` を生成して実行する経路が使われた。
- そのスクリプト内の `make_creative_brief()` が `creative_brief_initial.json` / `creative_brief_used.json` を直接生成しており、role skill（ideaman）の LLM 生成が実質バイパスされていた。
- 作品づくりの目的に対して、固定テンプレ寄りの出力が再発しやすい。
- さらに、`sketch/agent_loop` 外（例: `/tmp`）に実行用ファイルを出力できる状態は、運用境界として不適切。

## 目的

- ideaman / artist / critic を「LLMが担う role」として強制し、固定 JSON 生成スクリプトへの退避経路をなくす。
- 生成物・中間物・一時ファイルを含め、出力先を `sketch/agent_loop` 配下に限定する。

## DoD（完了条件）

- [x] `orchestrator` に「`/tmp` を含む `sketch/agent_loop` 外への出力禁止」が明記される。
- [x] `orchestrator` に「role の代替として固定生成スクリプト（例: 一時 Python）を作らない」が明記される。
- [x] role skills（ideaman/artist/critic）にも出力境界と代替禁止の制約が整合して反映される。
- [x] 実行手順が `sketch/agent_loop/runs/<run_id>/...` だけで完結するように更新される。
- [x] 再発防止の運用チェック（実行後確認手順）が文書化される。

## 対象ファイル（予定）

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `grafix_art_loop.md`（必要なら運用ルールを同期）

## 実装方針

- 入口統制は `orchestrator` に集約する（role側は重複を最小限にして整合のみ持たせる）。
- 「禁止事項」を曖昧語で書かず、パス境界と禁止例を明示する。
- 一時作業が必要な場合も `sketch/agent_loop/runs/<run_id>/.tmp/` のみ許可し、`/tmp`・リポジトリ直下・他ディレクトリは不可にする。
- 失敗時もエラー情報の保存先を `run_dir` 配下に固定する。

## 実装タスク（チェックリスト）

### 1) orchestrator の境界規約を強化

- [x] `SKILL.md` のデフォルトモードに「出力許可ルート: `sketch/agent_loop` のみ」を追加。
- [x] 禁止例として `cat > /tmp/*.py`、`mktemp` 既定ディレクトリ利用、`tempfile` の既定 `/tmp` 利用を明記。
- [x] role 実行の代替として固定生成スクリプトを作る行為を明示的に禁止。

### 2) role skills の整合更新

- [x] ideaman に「`CreativeBrief` は role として生成し、固定テンプレスクリプトで代替しない」を追記。
- [x] artist/critic にも出力先境界（`variant_dir`/`iter_dir`/`run_dir` 配下のみ）を追記。
- [x] 例外規約の重複を避け、詳細規約は orchestrator 参照に寄せる。

### 3) 実行手順の再定義

- [x] 自動ループ手順に「中間ファイルを含む全出力は `sketch/agent_loop/runs/<run_id>/` 配下」を追加。
- [x] 一時作業ディレクトリを使う場合の標準位置（`<run_id>/.tmp/`）を規定。
- [x] 失敗時ログの保存先を run 配下に固定（stdout/stderr/診断JSON）。

### 4) 再発防止チェックを追加

- [x] 実行後チェック項目として「`sketch/agent_loop` 外に新規生成物がない」確認手順を文書化。
- [x] 代表プロンプト（N/M/canvas/explore_schedule 指定）での運用確認観点を明記。

## 受け入れ確認（実装後に実施）

- [ ] role skills を指定した実行で、`creative_brief*.json` が role 生成フローに従って更新される。
- [ ] `sketch/agent_loop/runs/<run_id>/` 以外に当該 run の生成物が存在しない。
- [x] `orchestrator` の文面だけで、禁止経路（`/tmp` 一時スクリプト経由）が読み手に明確に伝わる。
