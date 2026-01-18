# 改善タスク: 3) mp-draw の重複計算 + 複雑さ（2026-01-18）

対象: `docs/review/src_code_improvement_plan_2026-1-14.md` の「3) mp-draw の重複計算 + 複雑さ」（実装計画 D）

## 目的

- mp-draw の責務（worker: `draw(t)` + `normalize_scene()` / main: `realize_scene()`）を誤解しづらくする
- `SceneRunner.run()` の mp 経路を読みやすくし、複雑さを局所化する

## 対象範囲

- `src/grafix/interactive/runtime/mp_draw.py`
- `src/grafix/interactive/runtime/scene_runner.py`
- （必要なら）関連ドキュメント

## 非対象（やらない）

- `realize_scene()` の並列化（設計変更が大きい）
- 互換ラッパー/シム追加
- 大きなログ基盤・設定項目の増設

## 作業手順（チェックして進める）

- [x] `mp_draw.py` のモジュールドキュメントに「worker は draw/normalize まで。realize は main」を明示する
- [x] `SceneRunner.run()` を sync 経路 / mp 経路に分割し、「draw（取得）→ realize」の 2 段をコード構造で表現する
- [x] mp 経路で `records/labels` を merge する位置（= main 側でバッファへ反映する）をコメントで明確化する
- [ ] （任意・要確認）デバッグ観測を最小追加する（例: dropped task 数、last_error の保持など）※回答: No
- [x] `PYTHONPATH=src pytest -q` で回帰確認する
- [x] `docs/review/src_code_improvement_plan_2026-1-14.md` の D を完了チェックする（反映状況を残す）

## 確認したいこと

- （任意項目）デバッグ観測の追加は必要ですか？必要なら「どの情報が欲しいか」を先に決めたいです。※回答: No
