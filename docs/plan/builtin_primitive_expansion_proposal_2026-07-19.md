# 組み込み primitive 拡充提案

- 作成日: 2026-07-19
- 調査時 HEAD: `cc484fa`
- 状態: Wave A 実装完了（Wave B以降は未着手）
- 対象: 調査時点の17件の組み込み primitive と32件の組み込み effect
- 目的: Grafixの表現力を増やしつつ、既存機能との重複とAPI肥大化を避ける

## 1. 結論

現状のGrafixは、基本2D輪郭、文字、L-system、平面領域の加工、基本3D
wireframeには強い。一方で、次の3領域に明確な空白がある。

1. 多数の線や複数curve segmentを、低水準packingなしで一つの連続geometryへする基盤
2. spiral、単調軸wave、splineのようなplotter-nativeな基本曲線
3. hex/triangular lattice、trochoid、streamline、3D curveのような非Cartesian語彙

提案する優先順位は次のとおり。

### P0: 基盤と基本曲線

- `polylines`（既存の見送り判断をbenchmark付きで再評価）
- `path`
- `spline`
- `spiral`
- `wave`

### P1: 高い表現価値を持つ独立primitive

- `star`
- `superellipse`
- `trochoid`
- `helix`
- `lattice`

### P2: 個別RFCが必要な研究候補

- `streamlines`
- `heightfield`
- `torus_knot`

最初に実装するなら、低リスクで用途が広い
`spiral -> wave -> spline` の順を推奨する。
同時に `polylines` と `path` は短い設計・benchmark spikeを行い、
既存の `G.polyline(...) + ...` 方針を本当に置き換える価値があるか判定する。

## 2. 現状の棚卸し

### 2.1 現行17 primitive

| 分類 | 現行primitive | 強い点 | 主な空白 |
| --- | --- | --- | --- |
| 基本2D | `line`, `arc`, `circle`, `ellipse`, `rect`, `polygon` | 単純輪郭を少数引数で生成できる | star、superellipse、spiral、単調軸wave |
| 任意path | `polyline`, `bezier` | 任意点列と単一cubic segmentを扱える | 複数pathのbatch、compound path、多点spline |
| 格子・数理曲線 | `grid`, `lissajous`, `laplace_field_grid` | Cartesian grid、周期曲線、共形写像格子 | hex/triangular lattice、rolling-circle曲線、一般streamline |
| 手続き生成 | `lsystem` | 分岐・fractal・turtle grammar | field積分、data-driven surface |
| 文字 | `text`, `asemic` | 実フォントと擬似文字を直接線へできる | 現時点で優先度の高い空白なし |
| 3D | `polyhedron`, `sphere`, `torus` | 基本wireframe surfaceを生成できる | helix、torus knot、heightfieldなどの3D curve/data surface |

### 2.2 effectで既に強い領域

新primitiveを増やす前に、次は既存effectの責務として扱う。

- 閉領域のハッチ: `fill`
- 等距離輪郭: `isocontour`
- Voronoi分割: `partition`
- 丸め・オフセット輪郭: `buffer`
- 有機変形: `subdivide` + `wobble` / `displace` / `relax`
- 複製配置: `repeat`
- 円柱・円錐・角柱: `circle` / `polygon` + `extrude`
- 平行移動・回転・拡縮: `translate` / `rotate` / `scale` / `affine`

したがって「見た目が作れる」という理由だけではprimitive追加の根拠にしない。
既存chainでは、連続性、topology、決定性、性能、authoringのいずれかを
明確に満たせない場合だけ追加する。

## 3. repository内の利用実態

### 3.1 curated sketch

trackedな `sketch/**/*.py` は63件ある。現行作品では `text`、`polygon`、`line` が
多く、単純な線素材へeffectを重ねる使い方は定着している。

一方、次のcustom primitiveが作品側へ現れている。

- `sketch/work/1.py`
  - `closed_path`: 現在は `polyline(closed=True)` で代替可能
  - `organic_blob`: 円・楕円と変形effectのrecipeへ寄せられる
- `sketch/work/2.py`
  - arcとcubic curveを手作業で接続
  - `flow_lines`: 現行presetより明示的なstreamline生成
- `sketch/work/3.py`
  - `closed_shape`: `polyline(closed=True)` で代替可能
  - shape固有の`horizontal_fill`: 一般解は `fill` / `clip`
- `sketch/presets/dot_matrix.py`
  - marker配置は `polygon` + `repeat` で構成
- `sketch/presets/flow.py`
  - `fill` + `subdivide` + `displace` + `clip` でflow風textureを構成

この結果から、custom primitiveが存在するだけで組み込み化すべきではない。
既存compositionへ素直に落とせるものと、geometry authoring自体の空白を分ける必要がある。

### 3.2 art-loop成果物

`.tmp`を除く `sketch/agent_loop/**/sketch.py` 703件を方向性の参考として調べた。

```text
custom @primitive を含むfile: 559 / 703
custom primitive定義:        650
RealizedGeometry直接生成:    309 files
NumPyでgeometryを手組み:     530 files
pack/concat/empty系helper:    305 files
```

art-loop artistにはcustom primitive利用を求める運用上のbiasがあり、variantの世代コピーも
含まれる。この数を一般ユーザーの需要頻度とはみなさない。
ただし次の不足方向が複数runで反復している点は有効なシグナルである。

- `cell`, `lattice`, `grid`, `mesh`
- `field`, `flow`, `wave`, `ribbon`
- `radial`, `polar`, `orbit`, `ring`, `spiral`
- `contour`, `terrain`
- `curve`, `knot`, `harmonograph`, `spirograph`
- 独自の`_pack*`, `_concat*`, `_empty*`

特に「作品固有の数式」より、複数線packingと基本curve samplingが各作品で再実装
されていることを重く見る。

## 4. 選定基準

新しい組み込みprimitiveは、原則として次をすべて満たす。

1. 複数の作品・用途へ再利用できる基本語彙である。
2. 既存primitive + effect 1〜2段でlosslessに表現できない。
3. 出力polylineの順序、開閉、頂点数を明確に仕様化できる。
4. pureかつdeterministicで、`cache_policy="content"` と整合する。
5. 乱数を使う場合は明示的な`seed`だけを使う。
6. callableや暗黙の外部file状態へ依存しない。
7. GUIで意味の分かる少数のscalar / bool / choice引数を中心にできる。
8. 配列確保前にvertex、line、scratchの上限を見積もれる。
9. pen plotterで不要な重複辺、zero-length線、意図しないconnectorを作らない。
10. 特定作品だけの完成motifならprimitiveでなくpreset / recipeにする。

## 5. 候補一覧

| 優先度 | candidate | 解決する空白 | 既存機能との重複 | 難度 | 判定 |
| --- | --- | --- | --- | :---: | --- |
| P0再評価 | `polylines` | 複数lineのpacking boilerplate | `polyline`の加算で代替可能 | M | benchmark gate付きで再検討 |
| P0 | `path` | line/quad/cubicを連続subpathとして構成 | 個別`arc`/`bezier`は連続ringにならない | M-L | 限定commandで採用候補 |
| P0 | `spline` | 多数anchorを通る滑らかなopen/closed curve | 単一cubic `bezier`のみ | M | 採用推奨 |
| P0 | `spiral` | 半径が連続変化する1-stroke | losslessな代替なし | S | 採用推奨 |
| P0 | `wave` | 単調軸に沿う周期curve | `lissajous`/`wobble`とは異なる | S | 採用推奨 |
| P1 | `star` | 交互内外半径のradial outline | `polygon`は単一半径 | S | quick win |
| P1 | `superellipse` | ellipseからsquircle/diamondへの連続形状 | `ellipse`/`buffer`は近似のみ | S | 採用候補 |
| P1 | `trochoid` | rolling-circle / spirograph curve | `lissajous`では表せない | M | 採用候補 |
| P1 | `helix` | 基本3D 1-stroke curve | 現行3Dはsurface中心 | S | 採用候補 |
| P1 | `lattice` | triangular / hexagonal network | `grid`はCartesianのみ | M | 採用候補 |
| P2 | `streamlines` | vector field積分curve | `laplace_field_grid`は3preset限定 | L | 個別RFC |
| P2 | `heightfield` | 2D数値配列から3D line surface | 直接代替なし | M | data-art需要を確認 |
| P2 | `torus_knot` | torus上の閉じた3D 1-stroke | `torus`はsurface wireframe | M | 個別RFC |

難度は、Sが小、Mが中、Lが大を表す。

## 6. P0候補の詳細

### 6.1 `G.polylines(...)`

#### 価値

複数polylineをまとめて渡し、packed `(coords, offsets)` を生成する基盤primitive。
作品側のpacking helperと、多数の `G.polyline(...)` nodeを減らせる。

```python
G.polylines(
    paths=(
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
        ((2.0, 0.0, 0.2), (2.0, 1.0, 0.2)),
    ),
    closed=False,
)
```

API案:

```python
def polylines(
    *,
    paths: Sequence[Sequence[Sequence[float]]],
    closed: bool = False,
) -> GeomTuple:
```

- `paths` は `polyline.points` と同様にcode-ownedとする。
- 2D点は`z=0`へ正規化する。
- 入力path順、各path内の頂点順を維持する。
- `closed=True`では各non-empty pathを個別に厳密閉鎖する。
- 空pathをoffsetへ残すか除くかは実装前に固定する。

#### 再評価が必要な理由

2026-07-16のroadmapでは、複数線は `G.polyline(...)` の加算で十分として
追加modelを見送った。この判断はAPIの小ささという点では正しい。

一方、現在のart-loop corpusではpacking helperと直接geometry生成が大量に残る。
運用biasを差し引いても、次をbenchmarkして判断を再度固定する価値がある。

- 10 / 100 / 1,000 pathのDAG構築時間
- content key生成時間とmemory
- realize時間とpeak RSS
- `G.polyline(...) + ...` に対するsource行数とsite管理量
- 既存custom helper 3件以上を挙動損失なく置換できるか

性能・保守性の差が小さければ追加しない。

### 6.2 `G.path(...)`

#### 価値

複数のline / quadratic / cubic segmentを、一つ以上の連続subpathとして生成する。
`arc + bezier`をGeometry加算すると別polylineになるため、閉領域を作る作品では
現在も点列samplingを手書きしている。

初版command案:

```text
M x y [z]              move
L x y [z]              line
Q cx cy [cz] x y [z]   quadratic Bezier
C c1... c2... end...   cubic Bezier
Z                      close current subpath
```

```python
G.path(
    commands=(
        ("M", 0.0, 0.0),
        ("L", 1.0, 0.0),
        ("C", 1.2, 0.0, 1.2, 1.0, 1.0, 1.0),
        ("L", 0.0, 1.0),
        ("Z",),
    ),
    segments_per_curve=24,
)
```

- `M`ごとに新しいpolylineを開始する。
- `Z`だけが先頭点の厳密コピーで閉鎖する。
- 初版ではelliptical arc commandを入れない。
- adaptive toleranceより、まず固定`segments_per_curve`で頂点上限を明確にする。
- 将来SVG path parserを追加しても、file I/Oはこのprimitiveへ持ち込まない。

### 6.3 `G.spline(...)`

#### 価値

少数anchorを通る滑らかなcurveを生成する。
`polyline`は角張り、現行`bezier`は4点1segmentなので、多点の有機線には
制御点計算とsegment連結が必要になる。

API案:

```python
def spline(
    *,
    points: Sequence[Sequence[float]] = (
        (-0.5, 0.0),
        (-0.2, 0.3),
        (0.2, -0.3),
        (0.5, 0.0),
    ),
    closed: bool = False,
    tension: float = 0.0,
    segments_per_span: int = 16,
) -> GeomTuple:
```

- 方式はcentripetal Catmull-Romへ固定し、`kind` choiceを増やさない。
- open/closedで端点処理を明示する。
- closed出力は末尾へ先頭を厳密コピーする。
- 0/1/2点、隣接重複点、全点一致の仕様を先に決める。
- `points`はcode-ownedでGUIへ表示しない。

### 6.4 `G.spiral(...)`

#### 価値

Archimedean spiralはplotterと相性の良い、移動の少ない連続1-strokeである。
半径と角度が同時に変化するため、現行effect chainではlosslessに作りにくい。

API案:

```python
def spiral(
    *,
    inner_radius: float = 0.0,
    outer_radius: float = 0.5,
    turns: float = 5.0,
    phase: float = 0.0,
    samples: int = 512,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
```

- 初版は半径を線形補間するArchimedean型だけにする。
- `turns`の符号で回転方向を表す。
- 1本のopen polyline、頂点数は`samples`。
- logarithmic/Fermat modeを初版へ入れない。
- 3D化は`helix`へ分離する。

### 6.5 `G.wave(...)`

#### 価値

X方向へ単調に進みながらYを周期変化させるcurve。
`lissajous`はXも周期運動し、`wobble`は各軸を同じ軸の座標で変位するため、
水平線から `y=sin(x)` を直接作る代替にならない。

API案:

```python
def wave(
    *,
    kind: str = "sine",
    length: float = 1.0,
    amplitude: float = 0.25,
    cycles: float = 3.0,
    phase: float = 0.0,
    samples: int = 256,
    angle: float = 0.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> GeomTuple:
```

- 初版choiceは`"sine"`と`"triangle"`だけにする。
- saw/squareは不連続点をconnectorで結ぶか分割するかが曖昧なため見送る。
- 1本のopen polyline。
- 回転はXY平面で行い、3D方向指定はeffectへ委ねる。

## 7. P1候補の詳細

### 7.1 `G.star(...)`

交互のouter/inner radiusからradial starを作る。

```python
G.star(
    points=5,
    outer_radius=0.5,
    inner_radius=0.2,
    phase=-90.0,
    center=(0.0, 0.0, 0.0),
)
```

- 頂点数は `2 * points + 1`。
- 末尾へ先頭を厳密コピーするclosed polyline。
- regular star polygon `{n/k}` は別topologyなので初版へ混ぜない。

### 7.2 `G.superellipse(...)`

`|x/a|^n + |y/b|^n = 1` の輪郭を生成する。
`n=2`でellipse、`n>2`でsquircle、`n=1`でdiamondとなり、
基本輪郭の探索範囲を少数引数で大きく広げる。

```python
G.superellipse(
    radius_x=0.5,
    radius_y=0.35,
    exponent=4.0,
    angle=0.0,
    segments=128,
    center=(0.0, 0.0, 0.0),
)
```

- exponentは正の有限値に限定する。
- signed-powerの0近傍と極端な指数をtestする。
- closed 1 polyline。

### 7.3 `G.trochoid(...)`

hypotrochoid / epitrochoid、いわゆるspirograph系のcurveを生成する。
`lissajous`とは異なるrolling-circleの語彙で、plotter向け装飾曲線として再利用性が高い。

APIは任意float半径より、整数歯数を優先する。

```python
G.trochoid(
    kind="hypotrochoid",
    fixed_teeth=96,
    rolling_teeth=40,
    pen_offset=0.35,
    samples_per_turn=256,
    phase=0.0,
    center=(0.0, 0.0, 0.0),
    scale=1.0,
)
```

- `gcd`から周期を決め、閉鎖条件を決定的にする。
- 最終点は先頭の厳密コピー。
- `pen_offset`を絶対長にするかrolling radius比にするかは実装RFCで確定する。

### 7.4 `G.helix(...)`

現行3D primitiveはsurface wireframe中心で、加工元になる基本3D 1-strokeがない。

```python
G.helix(
    radius_start=0.5,
    radius_end=0.5,
    height=1.0,
    turns=5.0,
    phase=0.0,
    samples=512,
    center=(0.0, 0.0, 0.0),
)
```

- +Z軸を既定軸とし、任意軸は`rotate`へ委ねる。
- radius_start/endで円筒helixと円錐helixを統一する。
- 1本のopen 3D polyline。

### 7.5 `G.lattice(...)`

Cartesian `grid`と重複させず、triangular / hexagonalだけを扱う。

```python
G.lattice(
    kind="hexagonal",
    nx=12,
    ny=10,
    spacing=0.1,
    center=(0.0, 0.0, 0.0),
)
```

- 初版の出力はunique edgeだけにする。
- 共有辺を重複描画しない。
- edge順を座標sort後の偶然へ任せず、生成規則として固定する。
- まず2点polyline列とし、wall chain stitchは別最適化とする。
- `output="cells"|"edges"`のようなmode追加は実需確認後に行う。

## 8. P2候補の詳細

### 8.1 `G.streamlines(...)`

需要は強いが、単純なcurve primitiveではないため個別RFCが必要。

```python
G.streamlines(
    field="curl_noise",
    seed_layout="grid",
    line_count=64,
    steps=160,
    step_size=0.01,
    width=1.0,
    height=1.0,
    frequency=1.0,
    strength=1.0,
    seed=0,
    center=(0.0, 0.0, 0.0),
)
```

必要な仕様:

- fieldは`curl_noise`, `vortex`, `dipole`等の組み込みchoiceだけにする。
- callable fieldはcontent key、spawn、reload、GUIを壊すため受けない。
- 積分法、境界停止、停留点、循環検知、線の分割条件を固定する。
- `line_count * (steps + 1)`を上限としてpreflightする。
- draft previewではline/step上限を決定的に下げる。
- noiseと積分utilityはeffect private moduleから直接importせず、中立なcore moduleへ置く。

### 8.2 `G.heightfield(...)`

2D数値配列をrow/column wireframeへ変換するdata-art入口。

```python
G.heightfield(
    values=(
        (0.0, 0.2, 0.0),
        (0.1, 0.5, 0.1),
        (0.0, 0.2, 0.0),
    ),
    width=1.0,
    height=1.0,
    z_scale=0.5,
    line_mode="both",
    center=(0.0, 0.0, 0.0),
)
```

- `values`はnested tuple/listのcode-owned引数とする。
- NumPy arrayをGeometry argumentとして直接保持しない。
- rowの後にcolumnを置く等、line順を固定する。
- 大きなdataではcontent key構築量も増えるため、実用上限を測る。

### 8.3 `G.torus_knot(...)`

`torus` surface上の `(p, q)` knotを1本の3D curveとして生成する。

```python
G.torus_knot(
    p=2,
    q=3,
    major_radius=0.5,
    minor_radius=0.2,
    samples=1024,
    phase=0.0,
    center=(0.0, 0.0, 0.0),
)
```

- 初版は`gcd(p, q) == 1`を要求し、link/retraceの曖昧さを避ける。
- closed 1 polyline、末尾は先頭の厳密コピー。
- 3D viewやprojectionでの実利用を確認してから採用する。

## 9. primitiveにしない、または先に別手段を選ぶ候補

| candidate | 先に使う手段 | 理由 |
| --- | --- | --- |
| `closed_path`, `closed_shape` | `polyline(closed=True)` | 既に同じ責務を持つ |
| `rounded_rect`, `capsule` | `rect` / `line` + `buffer(join="round")` | losslessに近いcompositionが短い |
| `organic_blob` | `circle` / `superellipse` + `subdivide` + `wobble` / `displace` | 完成motifよりrecipe向き |
| concentric circles | `circle` + `repeat(cumulative_scale=True)` | placement/compositionの責務 |
| radial spokes | `line` + `repeat(cumulative_rotate=True)` | placement/compositionの責務 |
| `polar_grid` | 上記2枝をまとめるpreset | primitive化の性能根拠がまだない |
| dot matrix / phyllotaxis | motif + `repeat`のlayout拡張またはpreset | 形より配置規則 |
| `voronoi` | closed mask + `partition` | 既存effectと重複 |
| hatch / horizontal fill | `fill` + 必要なら`clip` | 入力境界を加工するeffectの責務 |
| contour rings | closed mask + `isocontour` | 既存effectと重複 |
| noise terrain contours | scalar-field subsystemのRFC | grid、field、marching squaresの共通設計が先 |
| cylinder / cone / prism | `circle` / `polygon` + `extrude` | 既存chainで表現可能 |
| cuboid | `polyhedron(kind="hexahedron")` + `scale` | 既存chainで表現可能 |
| Koch / dragon / fractal tree | `lsystem`のpreset追加 | grammar generatorと重複 |
| generic `parametric(callable=...)` | user-defined `@primitive` | callableの署名、spawn、GUI、決定性が不安定 |
| SVG/file importer | 明示的なimport/conversion層 | 外部file更新をcontent keyへ反映しにくい |
| point cloud / scatter | markerとpen-down点の契約を先に設計 | 1頂点polylineはG-code上の描画点にならない |
| 巨大な`curve(kind=...)` | 小さい独立primitive | mode固有引数と`ui_visible`が肥大化する |

## 10. 共通の実装契約

採用するprimitiveには、次を共通要件とする。

### 10.1 geometry

- raw returnは `(coords, offsets)` の2要素tuple。
- `coords`は`float32`, shape `(N, 3)`, C-contiguous。
- `offsets`は`int32`, shape `(M + 1,)`, 先頭0、末尾N、単調非減少。
- raw配列は呼び出しごとにfresh、writable、non-sharing。
- 2D primitiveのZは0とする。
- closed curveは先頭座標を末尾へ明示コピーする。
- line順、vertex順、subpath順をdocstringへ記載する。
- plotterが同じ辺を二度描かないよう、networkはshared edgeを重複させない。

### 10.2 決定性とcache

- pure / deterministicを既定とする。
- global RNGを使わない。
- 乱数は引数`seed`からlocal `Generator`を作る。
- 単純な数式curveへmodule-global cacheやNumbaを追加しない。
- `RealizeSession`のcontent cacheへ任せる。
- 内部cacheが必要な場合だけbounded LRU + readonly保存 + copy-on-returnとする。
- 外部file、ambient locale、process-global mutable stateへ依存しない。

### 10.3 resource

- 最終配列を確保する前に`ensure_geometry_output()`を呼ぶ。
- exact countが難しい場合は安全な上限とscratch bytesを渡す。
- `ParamMeta.ui_min/ui_max`は安全上限ではないため、code入力にもpreflightを適用する。
- count計算はPython `int`で行い、int32 capacityも共通budgetで検査する。
- heavy primitiveは`PreviewQuality`のdraft/finalを検討するが、seedとtopology規則は維持する。

### 10.4 公開面

- NumPyスタイルの日本語docstringと型hintを付ける。
- 全公開引数へ`ParamMeta.description`を付ける。
- `src/grafix/core/builtins.py`のmanifestへ登録する。
- catalog、CLI describe、generated stubを同時更新する。
- code-ownedのnested sequenceはGUIへ無理に載せない。
- choiceは意味名で表し、整数indexにしない。

### 10.5 test / benchmark

- dtype、shape、offsets、C-contiguous、writeability
- direct raw call間の独立性と入力不変性
- realize後のreadonlyとcontent cache
- empty、最小値、degenerate、負値、NaN/Inf
- countのround/int境界
- resource budgetの直前、一致、1超過
- closed/open topologyとendpoint
- seed決定性
- `fill`, `subdivide`, `dash`, transformとの代表chain
- primary actual-workのbenchmark case、exact checksum、output bytes、peak RSS

## 11. 推奨ロードマップ

### Wave A: quick win

- [x] `spiral`本体・公開API・テスト・benchmark
- [x] `wave`本体・公開API・テスト・benchmark
- [x] `spline`本体・公開API・テスト・benchmark
- [x] 代表effect chainとresource budget境界の横断検証
- [x] Ruff・mypy・pytest・benchmarkの最終検証

各primitiveを独立した変更単位にし、catalog/test/benchmarkまで完結させる。

実装結果:

- 組み込みprimitiveは17件から20件になった。
- primitive benchmarkは全20件を25 actual-work caseで網羅する。
- 新3件を含む25 case smoke runは全件 `status=ok`、175 hard contractが通過した。
- Wave A対象の公開API・resource・stub・benchmarkテスト158件が通過した。
- repository全体ではpytest 2,083件が通過し、1件をskipした。
- 独立property/fuzzでは通常・極端値を含む11,000件以上を検証し、
  未解決の数値差分や非有限出力はない。

### Wave B: authoring基盤の判断

1. `polylines`のDAG/realize/content-key benchmark
2. 既存custom packing helper 3件以上の置換試作
3. `path`のcommand grammarとflatten規則を小さく固定
4. 採用時は `polylines -> path` の順に実装

`polylines`が性能・source簡素化のどちらにも寄与しない場合は、
2026-07-16の見送り判断を維持する。

### Wave C: 表現語彙

1. `star`
2. `superellipse`
3. `trochoid`
4. `helix`
5. `lattice`

thumbnail比較と実作品での再利用性を確認し、単なるdemo形状で終わる候補は採用しない。

### Wave D: research

- `streamlines`: 積分・停止・preview qualityを別RFCで設計
- `heightfield`: code-owned data量とcontent key costを測定
- `torus_knot`: 3D view / projectionでの利用価値を確認

## 12. 最終推奨

現在のGrafixへ最も必要なのは、似た基本shapeを大量に追加することではない。

優先すべきなのは、

1. **基本曲線の空白を埋める**: `spiral`, `wave`, `spline`
2. **手書きpackingを減らす**: `polylines`, `path`
3. **非Cartesian語彙を増やす**: `trochoid`, `lattice`, `helix`

の順である。

この順なら、既存のeffect chain中心の設計を壊さず、custom primitiveで毎回繰り返される
低水準処理を減らし、pen plotter向けの1-strokeとnetwork表現を増やせる。
