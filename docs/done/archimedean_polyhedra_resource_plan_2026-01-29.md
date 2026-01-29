# リソース追加: アルキメデス立体 10 種（+キラル 2 種）を `resource/regular_polyhedron` に追加

作成日: 2026-01-29

## ゴール

- `src/grafix/resource/regular_polyhedron/` に、以下のアルキメデス立体データ（面ポリライン列）を **既存の `.npz` と同じフォーマット**で新規追加する。
- 生成は `src/grafix/devtools/` に置くスクリプトで行い、再生成可能にする（手作業で座標を貼らない）。

## 追加対象（10 種 + キラル 2 種）

- (1) Cuboctahedron（立方八面体）: 3.4.3.4（正三角形 + 正方形）
- (2) Icosidodecahedron（二十・十二面体）: 3.5.3.5（正三角形 + 正五角形）
- (3) Truncated tetrahedron（切頭四面体）: 3.6.6（正三角形 + 正六角形）
- (4) Truncated cube（切頭立方体）: 3.8.8（正三角形 + 正八角形）
- (5) Truncated octahedron（切頭八面体）: 4.6.6（正方形 + 正六角形）
- (6) Truncated dodecahedron（切頭十二面体）: 3.10.10（正三角形 + 正十角形）
- (7) Truncated icosahedron（切頭二十面体）: 5.6.6（正五角形 + 正六角形）
- (8) Rhombicuboctahedron（菱形立方八面体）: 3.4.4.4（正三角形 + 正方形）
- (9) Snub cube（斜方立方体）: 3.3.3.3.4（正三角形 + 正方形）※左右の鏡像で 2 種（キラル）
- (10) Snub dodecahedron（斜方十二面体）: 3.3.3.3.5（正三角形 + 正五角形）※左右の鏡像で 2 種（キラル）

## 既存フォーマット（合わせる仕様）

既存の `src/grafix/resource/regular_polyhedron/*_vertices_list.npz` を踏襲する。

- ファイル名: `{kind}_vertices_list.npz`
- 中身: `arr_0`, `arr_1`, ... の **面ポリライン列**
  - 各 `arr_i` は `float32` の `shape=(N,3)`（N は面の頂点数 + 1）
  - **閉ポリライン**（`arr_i[0] == arr_i[-1]`）
- スケール: 既存データ同様、全頂点が `||p|| == 0.5` の球面上に乗るよう正規化（向きは任意）

## 出力ファイル案（命名）

```
src/grafix/resource/regular_polyhedron/
  cuboctahedron_vertices_list.npz
  icosidodecahedron_vertices_list.npz
  truncated_tetrahedron_vertices_list.npz
  truncated_cube_vertices_list.npz
  truncated_octahedron_vertices_list.npz
  truncated_dodecahedron_vertices_list.npz
  truncated_icosahedron_vertices_list.npz
  rhombicuboctahedron_vertices_list.npz
  snub_cube_left_vertices_list.npz
  snub_cube_right_vertices_list.npz
  snub_dodecahedron_left_vertices_list.npz
  snub_dodecahedron_right_vertices_list.npz
```

※ `left/right` の命名は「反射（鏡像）で互いに移る」ことだけ保証し、どちらが左かの定義は固定しない（座標系の取り方で揺れるため）。

## 生成スクリプト（新規）

- `src/grafix/devtools/generate_archimedean_polyhedra_resource.py`（新規）
  - 役割: 上記 `.npz` を全て生成し、`src/grafix/resource/regular_polyhedron/` に書き出す
  - 依存: 追加しない（`numpy` のみ）

## 生成方針（中身）

### 共通パイプライン

1. **頂点集合**を作る（`float64[N,3]` → 最後に `float32`）
2. 頂点を `||p|| == 0.5` に正規化（必要なら全体スケール）
3. 頂点から **凸包の面**（頂点 index の集合）を抽出
   - `scipy` 等は使わず、頂点数が小さい前提で「支持平面を全探索→面を復元」するシンプル実装
4. 各面について、面内で 2D 射影して **周回順にソート**し、閉ポリライン化（先頭点を末尾に付与）
5. `np.savez(out_path, *polylines)` で `arr_0..` 形式で保存

### 形状ごとの頂点生成

#### A. 既存の正多面体から派生できるもの（rectify / truncate）

既存リソース（正多面体）の面ポリラインから、
`unique vertices` と `unique edges` を復元して操作する。

- Rectification（辺の中点）: `t=1/2` で各 edge を分割し中点を頂点化
  - (1) Cuboctahedron: cube（hexahedron）または octahedron から `t=1/2`
  - (2) Icosidodecahedron: icosahedron（または dodecahedron）から `t=1/2`
- Truncation（切頭）: 各 edge を比率 `t` で分割し、両端側の点を頂点化（各 edge から 2 点）
  - `t` は「元の面が正 n 角形」のとき `t = 1 / (2 + 2 cos(pi/n))`（n=3 なら 1/3）
  - (3) Truncated tetrahedron: tetrahedron（n=3）→ `t=1/3`
  - (4) Truncated cube: hexahedron（n=4）→ `t=1/(2+sqrt(2))`
  - (5) Truncated octahedron: octahedron（n=3）→ `t=1/3`
  - (6) Truncated dodecahedron: dodecahedron（n=5）→ `t=1/(2+phi)`（phi は黄金比）
  - (7) Truncated icosahedron: icosahedron（n=3）→ `t=1/3`

（メモ）この方式のメリット:

- “既存の座標系” を継承できるので、全体の向き/スケール方針が揃う
- face list を手で持たずに済む（凸包復元に任せる）

#### B. 直接座標を与えるもの

- (8) Rhombicuboctahedron:
  - 頂点を「`(±1, ±1, ±(1+sqrt(2)))` の順列（3\*8=24 点）」で生成してから正規化する案
  - その後は共通パイプラインで面抽出

#### C. Snub（キラル）系

ここは “座標生成の確定” が要るので、まず共通パイプラインで面抽出できる状態を作り、最後に詰める。

- (9) Snub cube / (10) Snub dodecahedron:
  - まず 1 種（片方のキラリティ）の頂点を生成し、もう片方は **反射**（例: `x -> -x`）で作る
  - 頂点生成は次のどちらかで確定する:
    - 方針 C-1) 既知のパラメータ（多項式の実根など）を `numpy` で解いて閉形式座標を組む
    - 方針 C-2) 回転対称群の軌道として `v0` を置き、簡単な数値探索で「最短距離が一様になる」`v0` を決める
  - 生成後のサニティチェックで、面種類（3/4 or 3/5）と面数が想定どおりになることを確認する

## サニティチェック（devtools 内で最小限）

生成した `(vertices, faces)` に対して以下を確認する（例外は `AssertionError` で十分）:

- 全頂点の半径が 0.5（許容誤差 `1e-5` 程度）
- 面サイズの分布が想定どおり（例: truncated icosahedron は 5 と 6 のみ、など）
- 最短のペア距離（=edge length）近傍の距離が 1 種にまとまる（=辺長が一様）
- 各面ポリラインが閉じている（先頭==末尾）

## 仕上げ（別タスク扱い）

今回は「データ追加」まで。以下は要望があれば別タスクでやる:

- `G.polyhedron` から新規データを選べるようにする（現状は正多面体 5 種固定）
- “正多面体” という名称/ドキュメントの見直し（Archimedean を含めるなら名称がズレる）

## 実装手順（チェックリスト）

- [x] 既存 `.npz` の仕様を確定（`dtype`/閉ポリライン/スケール）※この md の前提で OK か確認
- [x] `src/grafix/devtools/generate_archimedean_polyhedra_resource.py` を追加
- [x] 共通パイプライン（凸包→面→周回順→npz）を実装
- [x] A: rectify/truncate 系 7 種を生成して `.npz` 出力
- [x] B: rhombicuboctahedron を生成して `.npz` 出力
- [x] C: snub cube / snub dodecahedron の頂点生成方針（C-1/C-2）を決めて実装
- [x] snub の左右 2 種を反射で生成して `.npz` 出力
- [x] devtools のサニティチェックを全種で通す

## 確認したい（あなたに決めてもらう）

- `snub_*_left/right` の命名で良い？（`_a/_b` の方が良ければ変更する）；はい
- snub 系の頂点生成は C-1（閉形式）/C-2（数値探索）どちらで進めるのが良い？C-1で。
