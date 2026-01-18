# README Development 追記案: Geometry / DAG 概要（2026-01-18）

## 目的

`README.md` の `## Development` に、Grafix の中核である `Geometry`（幾何レシピ DAG）についての開発者向け説明を追加する。

## 作業ステップ（チェックリスト）

- [x] `README.md` の `## Development` 冒頭に「Geometry / DAG」サブセクションを追加する
- [x] `Geometry` の構造（`id` / `op` / `inputs` / `args`、不変・内容署名ベース）を簡潔に説明する
- [x] primitive は `Geometry` を生成（葉ノード）、effect は `Geometry` を加工（入力を持つノード）という役割を説明する
- [x] `parameter_gui` はパラメータ（`args`）を変更し、グラフを再構築してインタラクティブに結果を更新することを説明する

## README への追記文案（英語 / 追加予定）

以下を `## Development` の先頭（Dev tools の前）に追加する想定です。

```md
### Geometry (the core data model)

Grafix is built around an immutable `Geometry` node, which represents a *recipe* (not yet realized polylines).
Nodes form a DAG (directed acyclic graph):

- `op`: the operator name (primitive/effect/concat are stored uniformly)
- `inputs`: child `Geometry` nodes (empty for primitives)
- `args`: normalized `(name, value)` pairs
- `id`: a content-based signature derived from `(op, inputs, args)`

Primitives (`G.*`) create leaf `Geometry` nodes. Effects (`E.*`) take one or more input `Geometry`s and return a new `Geometry`
that references them. Chaining operations in `draw(t)` builds the DAG.

When `parameter_gui` is enabled, the GUI edits the parameters (`args`) of ops. Updating a parameter creates new `Geometry` nodes
with new `id`s, while unchanged subgraphs keep their `id`s — which makes caching/reuse straightforward during interactive previews.
```
