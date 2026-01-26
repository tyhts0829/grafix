# README examples（grn）ツール整理 + ParamStore を反映した headless export 改善計画

作成日: 2026-01-25

## 背景 / 現状の痛み

現在、README の examples（grn）更新は主に 2 つの devtools に分かれている。

- `src/grafix/devtools/refresh_readme_grn.py`
  - スケッチ（`sketch/readme/grn/*.py`）から `data/output/{svg,png}/readme/grn` を生成し、最後に `prepare_readme_examples_grn` を呼ぶ
- `src/grafix/devtools/prepare_readme_examples_grn.py`
  - `data/output/png/readme/grn` を `docs/readme/grn` に縮小保存し、`README.md` の Examples ブロックを更新する

この構成は「生成（ソース→原本）」と「整形（原本→README用アセット）」で責務が分かれていて筋は良いが、ユーザー体験としては:

- 似たツールが複数あり、設定（定数）が分散する
- どこで画像サイズが決まるのかが一見分かりにくい（`export.png.scale` vs `sips -Z`）

さらに、headless export の文脈では ParamStore が効かず、スケッチ上で明示されていないパラメータが無視される問題がある。

- 例: `G.polygon()` の省略引数を GUI で調整して `data/output/param_store/.../*.json` に保存しても、headless export では反映されない
- 原因（概略）:
  - parameter 解決（`resolve_params`）は `parameter_context` 内の snapshot を前提としている
  - headless export がその文脈を作らない（/ あるいは param 記録ミュートで解決自体を回避する）ため、保存済み値が適用されない

## ゴール

- README の examples 更新を「迷わない導線」に整理する（入口と設定の所在が明確）
- `refresh_readme_grn` の通常実行では **ParamStore の保存値を反映した状態**で画像出力できる
  - スケッチ上で省略されたパラメータも、保存済みの GUI 値を使う
- `argparse` は使わず、調整用パラメータはモジュール冒頭の定数に寄せる（既存方針）

## 提案する整理（設計案）

### 案A（おすすめ）: “入口を 1 つ” に寄せ、内部は 2 フェーズのまま維持

- 新しい 1 ファイルを canonical にする（例: `src/grafix/devtools/refresh_readme_examples_grn.py`）
  - 冒頭の `Parameters` で export/prepare の両方を制御
  - `main()` が以下の 2 フェーズを順に実行
    1) `sketch/readme/grn` → `data/output/{svg,png}/readme/grn`（原本生成）
    2) `data/output/png/readme/grn` → `docs/readme/grn` + `README.md` 更新（README用整形）
- 既存の 2 ファイルは役割が被るので、どちらか（または両方）を削除して混乱源を減らす
  - 互換ラッパーは作らず、使い方を 1 本化する

### 案B: 共通ユーティリティだけ切り出して 2 ファイルは残す

- `src/grafix/devtools/readme_grn_pipeline.py` のような共通モジュールへ
  - ルート探索、列挙ルール、依存チェック、丸め（6 で割り切れる枚数）などを集約
- `export_*` と `prepare_*` は薄い呼び出し側だけにして差をなくす

## ParamStore 反映（headless export の改善案）

### 目的

- `ParamStore` に保存された UI 値（override など）を export 時に適用し、interactive 実行と同等の出力に寄せる

### アプローチ

headless export で `draw(t)` を評価する部分を **ParamStore を持つ parameter context** で包む。

- `grafix.core.parameters.persistence.default_param_store_path(draw)` でパス決定
- `load_param_store(path)` でロード（無ければ空ストア）
- `with parameter_context(store):` で `draw(t)` を評価する
  - これにより `resolve_params` が snapshot を参照できる
  - `G(name=...)` / `E(name=...)` の label 記録も保存先があり安全
  - Layer style の override（line_color/thickness）も store 経由で適用できる

### 実装する場所（候補）

- 候補1: `src/grafix/api/export.py`（`Export` の内部で context を張る）
  - `python -m grafix export ...` 等も含めて一貫して “保存値を反映” できる
  - ただし export の意味（コードのみ vs 保存値含む）を明確にする必要がある
    - 例: `use_param_store=True/False` のようなフラグを Export の kw-only 引数にする
- 候補2: `refresh_readme_grn`（バッチ専用に context を張る）
  - 変更影響が局所的だが、別導線（`python -m grafix export`）との一貫性は落ちる

方針としては、ツール整理（案A）とセットで **入口側（refresh スクリプト）で明示**するのが分かりやすい。

## 実装手順（チェックリスト）

### 1) 整理方針の確定

- [x] 方針: 案B寄り（2 フェーズ維持。入口は `refresh_readme_grn.py` に寄せる）
- [x] canonical な実行コマンド: `PYTHONPATH=src python src/grafix/devtools/refresh_readme_grn.py`

### 2) devtools の再編

- [x] `refresh_readme_grn.py` が `prepare_readme_examples_grn.py` を呼ぶ導線を既定で使う（1 回で更新）
- [x] 両スクリプトの docstring に「目的 / 役割分担」を明記する
- [ ] （今回は採用しない: 案A）新規: `src/grafix/devtools/refresh_readme_examples_grn.py`
  - [ ] `Parameters` を 1 箇所に集約（export/prepare 両方）
  - [ ] export フェーズ（スケッチ→data/output）を内包
  - [ ] prepare フェーズ（data/output→docs/readme + README更新）を内包
- [ ] （今回は採用しない: 案A）既存の `prepare_readme_examples_grn.py` / `refresh_readme_grn.py` を整理（削除 or 役割縮小）

### 3) ParamStore を反映した export の導入

- [x] 候補1（おすすめ寄り）: `Export` を `parameter_context(load_param_store(default_param_store_path(draw)))` で包む
  - [x] `Export` の既定挙動として ParamStore を反映（`run_id` も kw-only で指定可能）
- [ ] 候補2: refresh/batch 側で `parameter_context` を張ってから `Export` を呼ぶ

### 4) 検証

- [ ] `sketch/readme/grn/1.py` などで「コードに明示していない引数」を GUI で変更→ParamStore に保存
- [ ] headless refresh を実行し、その変更が PNG に反映されることを確認
- [ ] `docs/readme/grn/*.png` と `README.md` の Examples ブロックが更新されることを確認

## 依存 / 注意

- PNG 生成: `resvg` が必要
- README 用縮小: `sips` が必要
- ParamStore を反映すると、従来（コードだけ）の出力と変わる可能性があるため、どちらを “正” とするかを明文化する
