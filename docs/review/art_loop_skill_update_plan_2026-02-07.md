# Art Loop Skills 更新計画（2026-02-07）

## 目的

- `grafix-art-loop-orchestrator` に、意図しない「既存ランナー探索」を防ぐ禁止事項を追加する。
- Art Loop 関連 skill に、Python 実行時は `/opt/anaconda3/envs/gl5/bin/python` を使う規約を追加する。

## 対象ファイル

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`

## 実装アクション（チェックリスト）

- [x] `orchestrator` に禁止事項を追記する。
  - `run_loop.py` / `run_one_iter.py` など既存ランナー探索を禁止。
  - 依存判断目的の横断調査を禁止。
  - 開始直後に `run_id` 作成 -> `iter_01` 開始を明示。
- [x] 4 つの Art Loop skill すべてに Python 実行パス規約を追記する。
  - `python` 実行は `/opt/anaconda3/envs/gl5/bin/python` を使用。
  - `python -m grafix ...` などの例示コマンドも同パス基準に統一。
- [x] 追記内容を `rg` で再確認する（対象 4 ファイル）。
- [x] この計画ファイルのチェックを完了状態に更新する。

## 完了条件

- 上記 4 ファイルに追記が反映され、禁止事項と Python パス規約が明示されていること。
- 本ファイルのチェックリストが完了状態になっていること。
