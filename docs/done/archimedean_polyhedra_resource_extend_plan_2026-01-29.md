# リソース追加: Archimedean 3 種を `polyhedron(type_index)` から選べるようにする

作成日: 2026-01-29

## 対象

既存の `src/grafix/devtools/generate_archimedean_polyhedra_resource.py` で生成しつつ、
`src/grafix/core/primitives/polyhedron.py` の `type_index` から選択できるようにする。

追加したい形状:

- Truncated cuboctahedron（切頭立方八面体 / great rhombicuboctahedron）
  - 面: 正方形 12 / 正六角形 8 / 正八角形 6
  - 頂点配置: 4.6.8
- Rhombicosidodecahedron（菱形二十・十二面体）
  - 面: 正三角形 20 / 正方形 30 / 正五角形 12
  - 頂点配置: 3.4.5.4
- Truncated icosidodecahedron（切頭二十・十二面体 / great rhombicosidodecahedron）
  - 面: 正方形 30 / 正六角形 20 / 正十角形 12
  - 頂点配置: 4.6.10

## 出力ファイル（命名）

```
src/grafix/resource/regular_polyhedron/
  truncated_cuboctahedron_vertices_list.npz
  rhombicosidodecahedron_vertices_list.npz
  truncated_icosidodecahedron_vertices_list.npz
```

## 実装方針（頂点生成）

追加依存は入れず、`numpy` のみで決定的に生成する。
（全頂点は既存データと同様に `||p|| == 0.5` に正規化）

- `truncated_cuboctahedron`
  - √2 を使う既知座標（48 vertices）
  - `(1, 1+sqrt(2), 1+2sqrt(2))` の **全 permutation + 全符号**（重複は unique）
- `rhombicosidodecahedron`
  - φ（黄金比）を使う既知座標（60 vertices）
  - icosahedral rotation（60 個）で `v0=(0, 2+φ, φ^2)` の軌道を作る
- `truncated_icosidodecahedron`
  - φ を使う既知座標（120 vertices; rotation では 2 orbit）
  - icosahedral rotation（60 個）で `v0=(1, 3+2φ, 1+2φ)` の軌道 + `x -> -x` 反射した軌道を union

## 実装手順（チェックリスト）

- [x] `src/grafix/devtools/generate_archimedean_polyhedra_resource.py` に 3 形状の頂点生成関数を追加
- [x] `_validate()` の expected に 3 形状を追加（頂点数/面内訳/面数/辺数）
- [x] `generate_all()` の tasks に 3 形状を追加して `.npz` を生成できるようにする
- [x] `python src/grafix/devtools/generate_archimedean_polyhedra_resource.py` を実行して `.npz` を生成
- [x] `src/grafix/core/primitives/polyhedron.py` の `_TYPE_ORDER` に 3 形状を追記し、docstring の index 一覧も更新
- [x] `PYTHONPATH=src pytest -q tests/core/test_polyhedron_primitive.py` を実行して確認

## 確認

完了。
