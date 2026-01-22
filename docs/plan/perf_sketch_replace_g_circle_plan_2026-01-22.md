# perf_sketch の `G.circle` を既存 primitive に置き換える（2026-01-22）

## ゴール

- `sketch/perf_sketch.py` が「存在しない `G.circle`」に依存せずに動作する。
- 計測用途（many_vertices / upload_skip / cpu_draw）の意図を保ちつつ、既存 primitive の範囲で同等の負荷を生成できる。

## スコープ

- 変更対象: `sketch/perf_sketch.py`
- 非スコープ: `git status` に見えている未依頼差分/未追跡ファイルには触れない

## 作業手順（チェックリスト）

- [x] 1. `perf_sketch.py` 内の `G.circle(...)` 使用箇所を確認（case / 引数 / 意図）
- [x] 2. `G.polygon(...)` 等の既存 primitive へ置換（例: `segments -> n_sides`, `r -> scale=2*r`）
- [x] 3. 環境変数・コメントの説明を実装に合わせて更新（必要なら変数名も整理）
- [x] 4. 最小の動作確認（例: `python -m py_compile sketch/perf_sketch.py`、および `GRAFIX_SKETCH_CASE=many_vertices|cpu_draw|upload_skip` で `draw(0.0)` が例外なく返る）

## 受け入れ条件

- `GRAFIX_SKETCH_CASE=many_vertices` / `cpu_draw` / `upload_skip` で `AttributeError: ... circle` が発生しない
- `sketch/perf_sketch.py` の実行経路で、primitive 未登録エラーが出ない
