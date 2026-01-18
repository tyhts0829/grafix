# README Development 追記案: RealizedGeometry 概要（2026-01-18）

## 目的

ユーザーが `@primitive` / `@effect` で自作オペレータを書くときに必要となる、`RealizedGeometry`（評価結果の実体データ構造）を `README.md` の `## Development` に追記する。

## 作業ステップ（チェックリスト）

- [x] `README.md` の `## Development` 内に `RealizedGeometry` のサブセクションを追加する（`Geometry` 節の直後）
- [x] `coords` / `offsets` の意味（ポリライン表現）と shape/dtype を説明する
- [x] primitive/effect が `RealizedGeometry` を返す/受け取ること、配列が不変（read-only）として扱われることを説明する

## README への追記文案（英語 / 追加予定）

以下を `## Development` の `### Geometry (the core data model)` 直後に追加する想定です。

```md
### RealizedGeometry (what primitives/effects compute)

When the `Geometry` DAG is evaluated, each node produces a `RealizedGeometry`, a compact polyline representation:

- `coords`: `np.ndarray` of `float32`, shape `(N, 3)` (x, y, z). 2D `(N, 2)` is also accepted (z=0 is implied).
- `offsets`: `np.ndarray` of `int32`, shape `(M+1,)`, where polyline `i` is `coords[offsets[i]:offsets[i+1]]`.

Custom primitives return a `RealizedGeometry`. Custom effects take `Sequence[RealizedGeometry]` (usually 1 input) and return a new
`RealizedGeometry`. The arrays are treated as immutable (`writeable=False`), so effects should not mutate inputs in-place.
```
