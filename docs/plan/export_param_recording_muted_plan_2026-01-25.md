# headless Export で `name=` を許容する（param 記録ミュート）計画

作成日: 2026-01-25

## 背景 / 問題

`python src/grafix/devtools/refresh_readme_grn.py` のようなヘッドレス export で、
スケッチが `G(name="...")` / `E(name="...")` を使っていると以下で落ちる。

- エラー: `ParamStore が利用できないコンテキストで name 指定は使えません`
- 原因:
  - `name=` は Parameter GUI 向けのラベル記録で、`parameter_context` によって `ParamStore` / `FrameParams` が用意されている前提
  - headless export（`Export`）はそのコンテキストを作らずに `draw(t)` を評価するため、ラベル保存先が無く例外になる

## ゴール

- headless export 経路でも `G(name=...)` / `E(name=...)` を使ったスケッチが落ちない
- `name=` は export では「無視（記録しない）」でよい
- 既存の interactive `run(...)` / Parameter GUI の挙動は変えない

## 方針（1案: param 記録をミュートする）

`Export` が `draw(t)` を呼ぶ直前〜終了までを `parameter_recording_muted()` で包む。

- 期待効果:
  - `set_api_label(...)` は `current_param_recording_enabled()==False` で早期 return し、例外にならない
  - export 中に ParamStore/FrameParams を用意する必要がない（最小変更）

注意:

- param 解決（`resolve_params`）も無効化されるため、量子化や frame record は行われない。
  - ただし export では GUI 用の record は不要で、今回の readme/grn の数値精度（概ね 1e-3 単位）なら出力差は出にくい想定。

## 変更箇所（予定）

- `src/grafix/api/export.py`
  - `realize_scene(draw, t, defaults)` の呼び出しを `parameter_recording_muted()` で包む
  - 追加 import: `from grafix.core.parameters.context import parameter_recording_muted`

## 実装手順（チェックリスト）

- [x] `Export.__init__` の `realize_scene(...)` 呼び出しを `parameter_recording_muted()` で包む
- [x] 最小動作確認:
  - [x] `G(name=...)` を含むスケッチを headless export しても例外にならない
- [ ] 既存導線の確認（任意）:
  - [ ] `python -m grafix export ...` が従来通り動く

## 代替案（参考）

- `parameter_context_from_snapshot(...)` で `FrameParams` を用意しつつ store は持たない（ラベル保存先だけ作る）
  - 記録/量子化を維持できるが、今回の目的（落ちないこと）には過剰になり得るため今回は採用しない
