# Grafix Project Quick Map

このファイルは、grafix-art-loop 実行時の「最初に読む地図」。
全体探索の前に、まずここを参照する。

## 目的

- 毎回 `rg --files` で全体を掘らず、必要箇所へ最短で到達する。
- role skills が共通の参照順で動けるようにする。

## 最短参照順（Art Loop）

1. `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
2. `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md`
3. `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
4. `.agents/skills/grafix-art-loop-orchestrator/references/contact_sheet_spec.md`（contact sheet 生成時）
5. `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
6. `.agents/skills/grafix-art-loop-artist/SKILL.md`
7. `.agents/skills/grafix-art-loop-critic/SKILL.md`
8. `README.md`（Grafix 全体の基本）
9. `architecture.md`（設計の背景が必要な場合のみ）

## 主要ディレクトリ（最小）

- `src/grafix/`: Grafix 本体
- `sketch/`: 実験スケッチ
- `sketch/agent_loop/runs/`: Art Loop の成果物
- `.agents/skills/grafix-art-loop-*/`: role ごとの運用ルール
- `.agents/skills/grafix-art-loop-orchestrator/references/`: JSON 型と運用参照
- `.agents/skills/grafix-art-loop-orchestrator/scripts/`: contact sheet などの機械処理ツール
