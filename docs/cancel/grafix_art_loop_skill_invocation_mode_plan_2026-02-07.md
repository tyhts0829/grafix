# (Cancelled) Grafix Art Loop skill 発動モード変更計画（2026-02-07）

取消日: 2026-02-07  
理由: Option A により `run_loop.py` / `tools/*.py` を廃止し、agent-native に一本化したため（本計画の前提が変わった）。

目的:
- skill 発動時のデフォルトを「agent 直書きループ」に変更する。
- `run_loop.py` / `tools/*.py` は「明示時のみ」の補助モードに下げる。
- この skill 発動時は計画 md 作成を不要とする運用を明記する。

実装対象:
- `./.codex/skills/grafix-art-loop-orchestrator/SKILL.md`
- 必要に応じて role skill（ideaman/artist/critic）の `SKILL.md`

チェックリスト:
- [x] orchestrator の説明を agent-native 優先に変更
- [x] CLI モードは明示実行時のみと明記
- [x] skill 発動時は計画 md 不要と明記
- [x] 自動ループ実行時の保存先（`sketch/agent_loop`）を再明記
