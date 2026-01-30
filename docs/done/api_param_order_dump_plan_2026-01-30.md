# 何を: primitive / effect / preset の「公開引数名」と「表示順（順番）」を 1 枚の md に書き出す。

# なぜ: 引数の命名と順序の一貫性を、人間が一覧で比較できるようにするため。

## ゴール

- `docs/review/api_param_order_2026-01-30.md` を新規作成し、以下を列挙する。
  - primitive（`G.*`）: 引数名と順序
  - effect（`E.*`）: 引数名と順序
  - preset（`P.*`）: 引数名と順序

## スコープ（案）

- primitive / effect: `grafix.core.*_registry` に登録済みの **組み込み**のみ（= `src/grafix/core/builtins.py` 経由）。
- preset: `.grafix/config.yaml` の `paths.preset_module_dirs` を autoload した結果（このリポでは既定で `sketch/presets`）を対象。

## 出力の定義（案）

- 「引数名と順序」は **GUI/永続化の行順**として扱い、registry が持つ `param_order` を正とする。
  - 例: `('center', 'scale', ...)`
- 予約引数の `activate` / `name` / `key` は一覧から除外する（あなたと合意済み）。
- effect の実装引数 `inputs` は内部用のため出力しない（= registry の `param_order` には含まれない前提）。

## 要確認（あなたに確認したい点）

1. `activate`（予約引数）を **一覧に含める**方針で良い？（含めない方が良ければ除外します）:不要
2. preset の予約引数 `name` / `key` は GUI 非公開ですが、**一覧に含める**べき？（含める場合は `activate, name, key, ...` のように別枠で追記します）：不要

## 実装チェックリスト

- [x] 1. 上の「要確認」2 点について合意する（出力定義を確定）
- [x] 2. Python で registry / preset autoload を実行し、op -> param_order を収集する
- [x] 3. `docs/review/api_param_order_2026-01-30.md` を生成する（表 or 箇条書き）
- [x] 4. 件数を確認する（primitive=8 / effect=30 / preset=autoload 結果）＋欠落が無いことを目視確認する
