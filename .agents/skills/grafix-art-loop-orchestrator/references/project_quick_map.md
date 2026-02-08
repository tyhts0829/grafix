# Grafix Project Quick Map

このファイルは、grafix-art-loop 実行時の「最初に読む地図」。
全体探索の前に、まずここを参照する。

## 目的

- 毎回 `rg --files` で全体を掘らず、必要箇所へ最短で到達する。
- role skills が共通の参照順で動けるようにする。

## 最短参照順（Art Loop）

1. `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
2. `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
3. `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
4. `.agents/skills/grafix-art-loop-artist/SKILL.md`
5. `.agents/skills/grafix-art-loop-critic/SKILL.md`
6. `README.md`（Grafix 全体の基本）
7. `architecture.md`（設計の背景が必要な場合のみ）

## 主要ディレクトリ（最小）

- `src/grafix/`: Grafix 本体
- `sketch/`: 実験スケッチ
- `sketch/agent_loop/runs/`: Art Loop の成果物
- `.agents/skills/grafix-art-loop-*/`: role ごとの運用ルール
- `.agents/skills/grafix-art-loop-orchestrator/references/`: JSON 型と運用参照

## 変更対象の目安

- 受け渡し JSON を変える: `references/schemas.md`
- 反復フローを変える: `orchestrator/SKILL.md`
- brief 生成ルールを変える: `ideaman/SKILL.md`
- 実装/記録ルールを変える: `artist/SKILL.md`
- 評価/指示ルールを変える: `critic/SKILL.md`

## 追加探索が必要な条件

- 上記ファイルに該当キーの定義が無い。
- `python -m grafix list ...` の実結果と references が矛盾する。
- run 失敗の原因が `stdout/stderr` だけでは判定できない。

## 追加探索時のルール

- 調べる対象は最小限（対象ファイルを先に決める）。
- 探索で判明した再利用価値のある情報は、run 末尾で
  `skill_improvement_report.json.discovery_cost` に記録する。
