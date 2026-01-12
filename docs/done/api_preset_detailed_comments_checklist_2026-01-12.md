# どこで: `src/grafix/api/preset.py`。

# 何を: 動作理解のため、処理の意図・責務境界・予約引数・ParamStore/GUI 記録の流れをコメントで補う。

# なぜ: `@preset` の “公開引数だけ GUI に出す/本体は mute” が一見で追えるようにするため。

# `src/grafix/api/preset.py` コメント追加: チェックリスト（2026-01-12）

## ゴール

- `@preset` の処理フローが、ファイル内のコメントだけで追える。
- 予約引数（`name`/`key`/`bypass`）の意味と、`site_id` の作り方が分かる。
- 「公開引数だけ resolve して、本体は mute」になる理由が分かる。

## 非ゴール

- 仕様変更や挙動変更。
- 依存関係の整理やリファクタ。

## 事前確認（あなたに質問）

- [x] 現在ワークツリーに既に差分があります（`src/grafix/api/preset.py` を含む）。この “現状の内容” に対してコメント追加して良い？；はい
  - もし「差分を戻してから（HEAD の状態で）コメント追加」が希望なら、その方針を指示してください（こちらでは無断で巻き戻ししません）。
- [x] コメントは「かなり細かく（段落コメント多め）」で良い？それとも「要点だけ（Why/予約引数/GUI 記録周り中心）」が良い？；要点だけ

## 実施チェックリスト（承認後に実装）

- [x] `src/grafix/api/preset.py` を読み、処理フローを章立て（登録/呼び出し/ラベル/解決/バイパス/mute）する
- [x] 各ステップに「何をしているか」「なぜ必要か」を日本語コメントで追記する
  - [x] `meta` 正規化と予約引数チェックの意図
  - [x] `preset_registry` 登録（`display_op`/`param_order`）の意味
  - [x] `caller_site_id` と `key` で `site_id` を安定化する理由
  - [x] `bypass` の扱い（explicit 判定と GUI 記録）
  - [x] `resolve_params` に渡す `explicit_args` の意味（override/永続化と整合）
  - [x] `parameter_recording_muted()` で本体を包む理由（内部 G/E を公開しない）
- [x] コメントが冗長すぎて読みにくくならないよう、ブロックコメント中心に整理する（行末コメント乱立は避ける）
- [ ] 最小検証
  - [ ] `ruff check src/grafix/api/preset.py`（この環境に `ruff` が入っていないため未実施）
  - [x] `PYTHONPATH=src pytest -q tests/api/test_preset_namespace.py`

## 追加で気づいたら追記すること（提案）

- [ ] `@preset` の最小使用例（`name`/`key`/`bypass` を含む）を docstring に短く追記するか要相談
