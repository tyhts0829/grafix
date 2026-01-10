# どこで: Grafix パッケージ（`src/grafix/`）の devtools CLI（`python -m grafix ...`）。

# 何を: 組み込み effect / primitive を CLI から一覧できる `python -m grafix list ...` を追加する計画。

# なぜ: 使える op 名（= 関数名）の探索コストを下げ、スケッチ作成・デバッグ・ドキュメント整備を楽にするため。

# 組み込み effect/primitive の一覧 CLI 追加: 実装計画（2026-01-09）

## 現状整理（前提）

- CLI 入口: `src/grafix/__main__.py`（`python -m grafix`）。
  - 既存サブコマンド: `benchmark` / `generate_stub`
- 組み込み登録の仕組み:
  - effect: `grafix.core.effect_registry.effect_registry`（`@effect(meta=...)` で登録）
  - primitive: `grafix.core.primitive_registry.primitive_registry`（`@primitive(meta=...)` で登録）
- 組み込みの import 起点:
  - `grafix.api.effects` / `grafix.api.primitives` が「実装モジュールを import → registry を初期化」している。
  - `grafix.devtools.generate_stub` もこの import 起点（API と一致する集合を前提）で列挙している。
- 2026-01-09 時点の内訳（`src/grafix/core/` から単純カウント）:
  - effects: 24
  - primitives: 7

## ゴール

- `python -m grafix` から組み込み effect / primitive の名前を一覧できる。
- 出力順が安定（名前でソート）し、スクリプト/パイプで扱いやすい。
- 外部依存（click/typer 等）を増やさない（`argparse` のまま）。

## 非ゴール（今回やらない）

- `grafix` 本体のユーザー向け CLI（スケッチ実行、export、GUI 起動など）を作り込む。
- プラグインやユーザー定義の effect/primitive の自動探索・ロード機構。
- 各 op の詳細ヘルプ（docstring 全文整形、検索、色付け等）を作り込む。

## CLI 仕様案（叩き台）

### サブコマンド構成

- `python -m grafix list [effects|primitives|all]`
  - 省略時は `all`（両方出す）

### 出力フォーマット（最小）

- 既定: 1 行 1 エントリ（パイプ前提、見出しなし）
  - `effects` の場合: effect 名のみを出す
  - `primitives` の場合: primitive 名のみを出す
  - `all` の場合: `effects:` / `primitives:` の見出し + 各 1 行（ここだけ見出しあり）

### オプション（必要になったら）

- `--json`:
  - `{"effects":[...],"primitives":[...]}` を stdout に出す（人間より機械向け）
- `--details`（入れるなら `--json` とセットに限定するのが単純）:
  - effect: `name`, `n_inputs`, `params`（`ParamMeta.kind/ui_min/ui_max/choices`）, `defaults`
  - primitive: `name`, `params`, `defaults`

## 実装方針（最小）

- 列挙のソースは「public API と同じ集合」に寄せる:
  - `import grafix.api.primitives` と `import grafix.api.effects` を最初に実行して registry を初期化
  - その後 `primitive_registry.items()` / `effect_registry.items()` を参照して名前を収集
- CLI の分岐は `src/grafix/__main__.py` に 1 サブコマンド追加し、実処理は `grafix.devtools` に寄せる。
  - 例: `grafix.devtools.list_builtins.main(argv)`（`argv` 対応）

## ユーザー確認が必要な決定事項

- [x] コマンド名: `list` で良い？（代案: `ops`, `builtins`）；list でいい。
- [x] 既定出力: `all` のときだけ見出しありで良い？（常に見出しなし/常に見出しあり、どちらが好み？）；はい
- [x] `--json` は必要？（後からでも追加可能）；不要
- [x] `--details`（meta/defaults の出力）は今回入れる？（入れるなら JSON 限定にする？）；なし
- [x] 一覧対象: effect/primitive のみで良い？（将来 `preset` も並べたい？ → 今回は非ゴールのままにするか）；まずは effect と primitive のみ。

## 実装チェックリスト

- [x] CLI 入口を拡張
  - [x] `src/grafix/__main__.py` に `list` サブコマンドを追加
  - [x] `python -m grafix list --help` が期待どおり表示される
- [x] 列挙処理を実装
  - [x] `src/grafix/devtools/list_builtins.py`（新規）を追加
  - [x] `grafix.api.primitives` / `grafix.api.effects` を import して registry を初期化する
  - [x] effect / primitive 名を安定ソートして出力する
- [x] ドキュメント（最小）
  - [x] `README.md` に実行例を追記
- [x] 検証（手元コマンド）
  - [x] `python -m grafix list --help`
  - [x] `python -m grafix list effects`
  - [x] `python -m grafix list primitives`
  - [x] `python -m grafix list`（両方）

## Done（受け入れ条件）

- [x] 組み込み effect / primitive を CLI で迷わず列挙できる
- [x] 出力が安定し、コピペ/パイプで扱える
