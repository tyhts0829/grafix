# core/effects エフェクト名リネーム 実装計画（2026-01-24）

目的: `src/grafix/core/effects/` の命名レビュー結果を受け、曖昧さが強いエフェクト名をより明確な名前へ整理する。

重要:

- **破壊的変更**（既存スケッチ/プリセット/テストが壊れる）を前提とする。
- 互換ラッパー/別名シム（旧名を残す）は **実装しない**。

## 0) 事前確認（あなたの返答が必要）

### 0.1 リネーム対象と新名称（案）

以下の「旧 → 新」で進めてよい？

- [ ] `fill` → `hatch`
- [ ] `partition` → `voronoi`
- [ ] `drop` → `cull`
- [ ] `buffer` → `offset`

※他の effect は今回は変更しない（必要なら追加で提案して下さい）。

### 0.2 ファイル名も揃える

- [ ] 上のリネームに合わせて、`src/grafix/core/effects/<name>.py` も同名へリネームする；これでよい？

## 1) 手順

- [ ] 参照箇所の洗い出し（`E.<name>` / `op="..."` / プリセット / docs）
- [ ] effect 実装のリネーム
  - [ ] ファイル名変更
  - [ ] `@effect` 関数名変更（= 登録名変更）
  - [ ] `__all__` など公開シンボルの更新
- [ ] builtins 登録の更新（`src/grafix/core/builtins.py` の module list）
- [ ] 利用側の更新（スケッチ/テスト/devtools/docs）
- [ ] stub 同期（必要なら `src/grafix/api/__init__.pyi` を更新）
- [ ] 動作確認（最小: `PYTHONPATH=src pytest -q`）

## 2) 受け入れ条件（完了の定義）

- [ ] 新名称で `E.<new>(...)` が使える
- [ ] 旧名称がコードベースに残っていない（参照文字列含む）
- [ ] `PYTHONPATH=src pytest -q` が通る

