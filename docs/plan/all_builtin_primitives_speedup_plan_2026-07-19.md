# 全組み込み primitive 高速化計画

- 作成日: 2026-07-19
- 調査時 HEAD: `cc484fa`
- 状態: 実装・検証完了
- 実装開始時 source snapshot: `/tmp/grafix-all-primitives-before/src`
- 対象: `src/grafix/core/primitives/` の全組み込み primitive
- 対象数: 17
- seed: `20260719`

## 1. 目的

全組み込み primitive の実体生成を計測し、出力・例外・診断・乱数・cache の挙動を
変更せずに高速化する。

「全 primitive の高速化」は、全17件を同じ基準で計測・検証することを意味する。
既に数マイクロ秒で完了し、低リスクな改善が測定できない primitive へ複雑な経路を
追加することは目的に含めない。その場合は regression control として残し、
変更しない理由と測定値を記録する。

ユーザー定義 `@primitive` は任意に追加できるため、本計画の実装対象外とする。
ただし primitive registry、wrapper、戻り値検証の共通契約は維持する。

## 2. 対象の完全性

次の3経路を照合し、17件の集合が一致することを確認した。

1. `src/grafix/core/primitives/*.py` から `@primitive` 関数を抽出
2. `src/grafix/core/builtins.py` の `_BUILTIN_PRIMITIVE_MODULES`
3. `ensure_builtin_primitives_registered()` 後の `primitive_registry`

対象は次の17件である。

```text
arc, asemic, bezier, circle, ellipse, grid, laplace_field_grid,
line, lissajous, lsystem, polygon, polyhedron, polyline, rect,
sphere, text, torus
```

## 3. 維持する共通契約

- 公開名、signature、default、ParamMeta、UI visibility、argument validationを変更しない。
- 全組み込み primitive は `n_inputs=0`、`cache_policy="content"` のままにする。
- `G.<name>()` の遅延 import と operation catalog/stub の内容を変更しない。
- `activate=False` は primitive 本体と他引数を評価せず標準空 geometry を返す。
- raw primitive は `(coords, offsets)` の2要素 tupleを返す。
- wrapper通過後は `coords=float32, shape=(N,3)`、
  `offsets=int32, shape=(M+1,)` とする。
- offsets は先頭0、末尾N、単調非減少とし、polyline順と頂点順を維持する。
- wrapper通過後の配列はreadonly、raw primitiveの新規出力は従来どおり独立した
  writable配列とする。
- 空 geometry は `coords.shape == (0,3)`、`offsets == [0]` とする。
- 警告のcategory/message/count/order、diagnosticの内容、例外型/message、
  引数の評価順、早期return位置を維持する。
- `asemic` / `lsystem` のseedから得られる乱数列と最終geometryを維持する。
- `text` のfont解決、TTC index、composite glyph、missing glyph logを維持する。
- resource budgetが既にある primitiveは、検査のタイミングと例外を維持する。
- 新規依存、互換wrapper、旧実装shimは追加しない。

### 3.1 特に壊しやすい差異

- `polygon` / `rect` / `polyline` / `torus` / `polyhedron` は先頭点を
  明示再利用する厳密閉鎖である。
- `circle` / `ellipse` / `sphere` のring / `laplace_field_grid` の境界は
  `linspace(..., endpoint=True)` による近似閉鎖である。最終点を先頭点コピーへ
  変更しない。
- `grid` は縦線の後に横線、`torus` は子午線の後に緯線を格納する。
- `sphere` のstyle別順序、`polyhedron` のNPZ面順、`text` の輪郭順を維持する。
- 整数化は primitiveごとに異なる。`round()` と `int()` を統一しない。
- raw関数でfallbackするchoiceと、`G`経由で先に拒否するchoiceを混同しない。
- float32/float64 trig、式の結合順、multiply/addの段数を安易に変えない。

## 4. 現状調査

primitive関連の既存テスト一式は、調査時workspaceで次の結果だった。

```text
86 passed in 2.74s
```

現行benchmarkにはprimitive専用suiteがなく、primitive生成だけを隔離して
比較できない。`micro.asemic` と、grid/polygonを使う一部system caseはあるが、
17件を同一契約で比較する用途には不足している。

### 4.1 探索計測

次は現在のdirty workspace上で行ったdirect-callの探索値であり、
正式before値ではない。正式baselineはbenchmark harness完成後に、
承認済みの開始sourceへ同一harnessを重ねて取得する。

| primitive | 探索case | warm median | 補足 |
| --- | --- | ---: | --- |
| `line` | default | 0.001 ms | small control |
| `rect` | rotated | 0.009 ms | small control |
| `arc` | 512 segments | 0.017 ms | 513頂点 |
| `circle` | 512 segments | 0.016 ms | 513頂点 |
| `ellipse` | rotated / 512 | 0.020 ms | 513頂点 |
| `bezier` | 3D / 512 | 0.040 ms | 513頂点 |
| `polygon` | 128 sides / partial | 0.014 ms | 99頂点 |
| `grid` | 500 + 500 lines | 0.030 ms | 2,000頂点 |
| `lissajous` | 8,000 samples | 0.130 ms | 8,000頂点 |
| `polyline` | ndarray 50,000 points | 45.881 ms | Python点正規化が支配 |
| `torus` | 256 x 256 | 2.091 ms | 131,584頂点 |
| `polyhedron` | 最大kind | 0.019 ms | 初回asset loadは3.806 ms |
| `sphere` | zigzag / subdivision 5 | 0.203 ms | 8,064頂点 |
| `sphere` | rings / subdivision 5 | 2.989 ms | 58,047頂点 |
| `sphere` | latlon / subdivision 5 | 4.668 ms | 84,275頂点 |
| `sphere` | icosphere / subdivision 5 | 149.609 ms | 61,440頂点、30,720線 |
| `lsystem` | plant / iterations 6 / jitter | 21.860 ms | 8,096頂点、2,048線 |
| `laplace_field_grid` | default cylinder | 7.453 ms | 81,420頂点 |
| `laplace_field_grid` | mobius / clip / dense | 18.177 ms | 153,600頂点 |
| `text` | ASCII+日本語 / warm | 4.597 ms | 初回は約116 ms |
| `asemic` | 26 unique glyphs / JIT後 | 19.7 ms | 空cache初回は約337 ms |

### 4.2 優先度

- **P0**: `polyline`, `sphere(icosphere)`, `lsystem`,
  `laplace_field_grid`, `text`, `asemic`
- **P1**: `torus`, `sphere(latlon/rings)`, `polyhedron`
- **P2**: `arc`, `bezier`, `circle`, `ellipse`, `grid`,
  `lissajous`, `polygon`
- **control**: `line`, `rect`, `sphere(zigzag)`

P2/controlもbenchmark、checksum、回帰テストの対象には含める。

## 5. benchmarkを先に追加する

### 5.1 suiteとworkload

- `primitives` suiteを追加する。
- timed workloadはraw primitive関数の実体生成だけとする。
- `G` node構築、RealizeSession content cache、renderer、checksum計算をtimingへ混ぜない。
- setupで固定入力、font path、50k point配列等を準備する。
- output検証とchecksumはtimed loopの外で行う。
- direct-callの同一引数反復により、primitive内部cacheがある場合のwarm挙動を測る。
- `text` / `asemic` / `polyhedron` はwarmとfresh processを別case/modeで測る。
- `asemic` は空Numba cacheのcompile-coldも測る。
- registry content-cache hitはprimitive本体の高速化対象ではないためcontrol caseへ分離する。

### 5.2 全primitiveの正式case

| primitive | primary actual-work case | secondary / control |
| --- | --- | --- |
| `arc` | `primitive.arc.segments_512` | sweep 0 / -360 |
| `bezier` | `primitive.bezier.3d_segments_512` | segments 1 |
| `circle` | `primitive.circle.segments_512` | radius 0 / segments 3 |
| `ellipse` | `primitive.ellipse.eccentric_rotated_512` | identity angle |
| `rect` | `primitive.rect.rotated` | degenerate width/height |
| `polyline` | `primitive.polyline.ndarray_50k_closed` | list、2D、empty、already closed |
| `line` | `primitive.line.rotated_right_anchor` | default 2頂点 |
| `grid` | `primitive.grid.500x500_transformed` | nx=0 / ny=0 / both 0 |
| `lissajous` | `primitive.lissajous.samples_8000` | samples 2 / zero frequency |
| `polygon` | `primitive.polygon.sides_128_partial` | full / sweep 0 |
| `torus` | `primitive.torus.256x256_transformed` | 3x3 / degenerate radii |
| `polyhedron` | `primitive.polyhedron.truncated_icosidodecahedron` | default、process-cold |
| `sphere` | `primitive.sphere.latlon.sub5.both` | horizontal / vertical |
| `sphere` | `primitive.sphere.rings.sub5.both` | horizontal / vertical |
| `sphere` | `primitive.sphere.icosphere.sub5` | subdivisions 0..4 |
| `sphere` | `primitive.sphere.zigzag.sub5` | control |
| `lsystem` | `primitive.lsystem.plant_iters_6_jitter` | no-jitter、custom、warning |
| `laplace_field_grid` | preset別 cylinder / mobius / exp | clip、U=0、boundary-only |
| `text` | `primitive.text.warm_wrapped_mixed` | unique glyph process-cold、bbox |
| `asemic` | `primitive.asemic.warm_repeated` | unique glyph process/compile-cold |

case ID、parameter、seed、font file、polyhedron asset、fixture source hashを
baseline取得前に固定する。

### 5.3 typed metrics

全case:

- `n_vertices`: counter / count
- `n_lines`: counter / count
- `closed_lines`: counter / count
- `output_bytes`: counter / bytes
- `diagnostics`: counter / count
- `quality`: gauge / unitless

固有metric:

- sampled shape: requested/effective segments/samples
- `polyline`: input points、close vertex appended
- `torus`: major/minor segments、meridian/parallel lines
- `sphere`: style、line mode、requested/effective subdivisions
- `lsystem`: expanded chars、draw commands、branch pushes
- `laplace_field_grid`: requested grid lines、mapped/kept points、split lines
- `text` / `asemic`: characters、unique glyphs、cache state
- `polyhedron`: kind、faces、asset bytes、cache state

productionへ計測専用counterを追加せず、parameter、output、setup状態から導出できる
metricを優先する。

### 5.4 checksumとcontract

- canonical geometry exact checksumを全caseのhard contractにする。
- dtype、shape、offsets単調性、finite要否、raw出力の独立性を別contractにする。
- cache-sensitive caseもcold/warmで同じgeometry checksumを要求する。
- font/assetが違うenvironmentはcase/environment非互換としてcompareを拒否する。

## 6. 性能の採用条件

### 6.1 warm

- P0 primary: median 20%以上改善、かつ差がbaselineの `3 * MAD` を超える。
- P1 primary: median 10%以上改善、かつ差が `3 * MAD` を超える。
- P2/control: 単独最適化は原則行わない。共有helper変更で改善する場合だけ採用する。
- secondary/small: median 5%超かつ2 microseconds超の悪化を許容しない。
- p95が15%超悪化した場合はABABで再測定し、再現すれば不採用とする。

### 6.2 coldとmemory

- process-coldは10%超の悪化を許容しない。
- compile-coldは15%超の悪化を許容しない。
- pure NumPy/Python primitiveへNumbaを追加する案は、構造的改善で目標を満たせない場合だけ検討する。
  - `fastmath=False`
  - `parallel=False`
  - warm 2倍以上
  - compile-cold追加500 ms以下
  - warning/例外/RNGがexact
- peak RSS / temporary bytesは10%超増加させない。
- 10%を超えるboundedなmemory tradeoffは、wall time改善が十分大きく、
  上限と実測を計画書へ明記できる場合だけ個別承認する。
- 新規cacheは最大entry数またはbyte上限を必須とする。

### 6.3 正しさ

次のいずれかが変わる案は速度に関係なく不採用とする。

- exact checksum / checksum kind
- polyline順、頂点順、offsets、閉鎖方法
- diagnostic / warning / exception / evaluation order
- RNG sequence、font解決、asset選択
- raw call間の配列独立性
- public signature / metadata / cache policy
- resource budgetと失敗挙動

## 7. primitive別の実装候補

### 7.1 基本shapeとpoint入力

| primitive | 最初に試す低リスク案 | 採用しない案 |
| --- | --- | --- |
| `line` | 現行scalar実装をcontrolとして維持する | cache、NumPy vector化 |
| `rect` | `_shape_utils.xy_polyline`改善の恩恵だけ確認する | 固有fast-pathの追加 |
| `arc` | `xy_polyline`のfloat64 `(N,3)` temporaryを減らす | float32 trig、終点コピー |
| `circle` | `arc`と同じ共有helper改善 | endpointの先頭コピー |
| `ellipse` | 共有helper内の回転temporaryを演算順どおり再利用 | 行列積、float32 trig |
| `bezier` | scalar basisを再利用し、現行の左結合加算順でtemporaryを減らす | Horner、de Casteljau、einsum |
| `polygon` | 最終 `(N+1,3)` を直接確保し、現行sample後にclosureを書込む | 角度生成やclosure方式の変更 |
| `polyline` | canonical numeric ndarray `(N,2|3)` 専用fast-path | list/generator/object配列の一括変換 |
| `grid` | transform時のmultiply→addを同じ段数でin-place化 | fused affine |
| `lissajous` | 最終coordsへx/y/zを直接書き、stackを除く | 位相式・sin dtypeの変更 |

`polyline` fast-pathでは、NaN、signed zero、already-closed判定を
Python tuple比較とexactに一致させる。list、generator、ragged/object、
ndarray subclassは現行point-by-point経路へ戻す。

### 7.2 packed 3D geometry

#### torus

- [x] 最終coordsとoffsetsをexact sizeで1回確保する。
- [x] 子午線slice、緯線slice、closure行を直接書く。
- [x] `r_phi`を子午線/緯線で再利用する。
- [x] trig dtype、broadcast式、子午線→緯線順を維持する。
- [x] 3/16/32/128/256 segmentsと負・ゼロ半径をdifferential比較する。

#### polyhedron

- [x] asset load時にimmutableなpacked base coords/offsetsもcacheする。
- [x] raw callではbaseを直接返さず、必ず独立したwritable出力を返す。
- [x] center/scale変更時はcopy後に現行float32演算順で変換する。
- [x] 全20kindのface順、閉鎖、checksumを固定する。
- [x] cold asset loadとwarm transformを別々に判定する。

#### sphere

- [x] icosphereのDFS出力順を維持したまま、再帰ごとの中間list返却をやめる。
- [x] 共有辺の中点をcanonical edge keyでmemoizeし、normと配列生成を省く。
- [x] 最終unique edge順を変更せずpacked coords/offsetsへ書く。
- [x] latlon/ringsはdirect pack案の代わりに、配置前packed geometryを再利用する。
- [x] zigzagはcontrolとし、配置前geometry cache以外は変更しない。
- [x] `(style, subdivisions, line_mode)` の単位球cacheの追加効果を確認する。
- [x] cacheはimmutable base、最大16件のLRU、copy-on-returnとする。
- [x] 全style × line_mode × subdivisions 0..5をexact比較する。

### 7.3 procedural primitive

#### lsystem

- [x] `jitter == 0` のRNG固定費削減候補を、初回import挙動込みで測る。
- [x] RNG本体を省く場合も、負seed等に対する`default_rng(seed)`相当の
      validation・例外型・message・評価順を先に維持する。
- [x] preset展開済みprogramを最大16件のbounded LRUへ保持する。
- [x] turtle結果のline長確定後、coords/offsetsを1回確保して直接packする。
- [x] 各lineの小さな`arr3`生成と最終concatenateを除く。
- [x] sin/cos cacheは同一float headingだけをkeyとし、累積headingを量子化しない。
- [x] `F/f/+/-/[/]` の処理順、stack salvage、warning順を維持する。
- [x] jitter時の乱数draw回数・順序・値をexact比較する。
- [x] Numba化はwarning処理とcold-startのため採用しない。

#### laplace_field_grid

- [x] `_split_by_mask()`へ `mask.all()` / `not mask.any()` fast-pathを追加する。
- [x] mixed maskは現行loopをreferenceにtransition indexをvector化する。
- [x] `u_samples` / `v_samples` のcomplex128変換をloop外へ出す。
- [ ] center/scale/rotateのfloat化とsin/cos hoistは不採用。
      既存の遅延評価を変える危険に対して追加利得が不要だった。
- [x] `n_u=n_v=0`や`U=0, draw_boundary=False`では、従来どおり不正center等を
      評価せず空geometryを返す。
- [x] line単位の複素写像とwarning順を維持する。
- [x] 全line一括2D mapはpeak memoryとwarning順が変わるため採用しない。
- [x] batch化は不要と判断し、追加temporaryを導入しない。
- [x] cylinder/mobius/exp、特異点、非finite、clip分割をexact比較する。

### 7.4 glyph primitive

#### text

- [x] resolved font pathを`text()`冒頭で1回だけ確定する。
- [x] cmap、space advance、glyph advance、font ascentのcall内cacheを追加する。
- [x] 配置前float32輪郭geometryを最大256件かつ32 MiBのbounded LRUへ保持する。
- [x] glyph輪郭を配置しながらexact-size packed coords/offsetsへ直接書く。
- [x] 現行の `(font_coord + float32(offset)) * float32(scale)` 順を維持する。
- [x] empty/space/newline、wrap、align、bbox、quality、missing/composite glyphを確認する。
- [x] font load、glyph flatten、warm layoutを別caseで測る。
- [x] cache evictionと異なるfont/index/quality間の汚染がないことを確認する。

#### asemic

- [x] default/small `n_nodes`で純NumPy adjacencyを使い、Numba import/JITを遅延する
      hybrid候補をprocess/compile-cold込みで比較する。
- [x] 4/8/16/28/64/128/200 nodesを測り、Bezierかつ`n_nodes <= 32`を閾値とする。
- [x] NumPy/Numba adjacencyだけでなく、最終glyphをseed付きでbitwise比較する。
- [x] `_sample_bezier`の同一samples用t/u/basisを最大64件で再利用する。
- [ ] cached glyphのdirect packは改善が測れなかったため不採用・巻き戻し済み。
- [x] existing glyph LRU 256件のmemoryを測り、新しい無制限cacheを追加しない。
- [x] repeated glyph、unique glyph、line/bezier、dot/space、bboxを分離して測る。
- [x] RNG draw順とBLAKE2b由来の文字seedを変更しない。

## 8. テスト計画

### 8.1 変更前reference

- [x] 実装開始時の全sourceを`/tmp/grafix-all-primitives-before/src`へ固定する。
- [x] 小さいgoldenだけでなく、primary actual-workをexact checksum化する。
- [x] 固定seed `20260719` のrandomized differentialを実行する。
- [x] input配列・point列の不変性を確認する。
- [x] raw関数を2回呼び、結果配列がmemory共有しないことを確認する。
- [x] `G`経由のreadonly、content cache、activate bypassを別に確認する。

### 8.2 共通境界

- [x] empty、one-point、最小/最大segments、0/負/巨大値
- [x] int変換とround境界
- [x] NaN、Inf、subnormal、signed zero
- [x] centerの2/3/4要素、generator、ndarray、ndarray subclass
- [x] C/F contiguous、strided、readonly、object/ragged入力
- [x] resource limit直前/一致/1超過
- [x] warning/diagnostic/exceptionのtype、message、count、順序
- [x] output dtype、shape、C-contiguous、writeability、offsets topology

### 8.3 primitive固有

- [x] sampled 2D shape: endpoint、近似/厳密closure、回転、degenerate radius
- [x] polygon: partial sweepの `1e-9` 境界
- [x] torus: 子午線/緯線順と各closure
- [x] sphere: 4style × 3line_mode × subdivisions 0..5、clamp diagnostic
- [x] polyhedron: 全20kindとcold/warm。欠損/破損asset経路は既存実装を変更していない。
- [x] lsystem: preset/custom、pen-up、nested/unbalanced branch、500k文字cap、jitter
- [x] lsystem: jitter 0でも負seed等のvalidation・例外順を維持
- [x] laplace: 3preset、range swap、U=0、Möbius特異、exp overflow、clip transition
- [x] laplace: 出力pieceなしの場合にcenter/scale/rotateを評価しない早期return
- [x] text: ASCII/Japanese、TTC、composite/missing、wrap/align/bbox、LRU eviction
- [x] asemic: empty/space/dot、unique/repeated、style、range swap、seed、Numba cold

## 9. 実装順

### Phase 0: 計測と契約を固定

- [x] `primitives` benchmark suite、typed metrics、exact checksumを追加する。
- [x] 全17 primitiveに少なくとも1件、合計22件のactual-work caseを登録する。
- [x] benchmark registry/schema testを追加する。
- [x] differential referenceと不足する境界テストを先に追加する。
- [x] current target testsとfull pytestを実行する。
- [x] 承認済み開始sourceへ最終harnessを重ね、warm/process-cold/compile-cold
      baselineを保存する。

### Phase 1: P0の独立した改善

- [x] `polyline` canonical ndarray fast-path
- [x] `sphere` icosphere中点memo/DFS allocation削減
- [x] `lsystem` direct packとno-jitter fixed cost削減
- [x] `laplace_field_grid` mask fast-pathとloop invariant hoist
- [x] `text` glyph geometry/metrics cacheとdirect pack
- [x] `asemic` cold hybrid（direct packは測定後に不採用）

各primitiveを別変更単位で実装し、対象testとbefore/afterを通してから次へ進む。

### Phase 2: P1のpacked geometry

- [x] `torus` direct packing
- [x] `sphere` latlon/ringsの配置前packed geometry cache
- [x] `polyhedron` packed immutable base cache

### Phase 3: P2/shared allocation

- [x] `_shape_utils.xy_polyline`のtemporary削減
- [x] `arc` / `circle` / `ellipse` / `rect` exact differential
- [ ] `bezier` basis temporary削減は1.4%程度でnoise内だったため不採用・巻き戻し済み
- [x] `polygon` closure allocation削減
- [x] `grid` transform temporary削減
- [x] `lissajous` direct output
- [x] `line` / `sphere zigzag` controlの非回帰確認

P2は採用条件を満たさなければ変更を残さない。

### Phase 4: 統合検証

- [x] 全17件・22caseのafter warm runを取得する。
- [x] text/asemic/polyhedronのprocess-coldを取得する。
- [x] asemicのcompile-coldを取得する。
- [x] `benchmark compare`でenvironment/case compatibilityとchecksumを確認する。
- [x] base/headのA→B→A→Bを行い、order/thermal driftを確認する。
- [x] peak RSS、p95、cache entry/bytesを確認する。
- [x] 対象test、full pytest、Ruff、Mypy、`git diff --check`を実行する。
- [x] 本計画のcheckbox、最終数値、未採用理由、tradeoffを更新する。

## 10. 正式計測コマンド

benchmark suite実装後、同じenvironmentとcase sourceで実行する。

```bash
PY=/opt/anaconda3/envs/gl5/bin/python
OUT=/tmp/grafix-all-primitives

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
export NUMBA_NUM_THREADS=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMBA_CACHE_DIR=/tmp/grafix-all-primitives-numba

PYTHONPATH=src "$PY" -m grafix benchmark run \
  --suite primitives \
  --profile long \
  --mode warm \
  --disable-gc \
  --seed 20260719 \
  --timeout 600 \
  --run-id primitives-before-warm-A1 \
  --out "$OUT"

PYTHONPATH=src "$PY" -m grafix benchmark run \
  --case primitive.text.cold_unique_high_quality \
  --case primitive.asemic.cold_unique_bezier \
  --case primitive.polyhedron.truncated_icosidodecahedron \
  --profile long \
  --mode process-cold \
  --samples 30 \
  --seed 20260719 \
  --timeout 600 \
  --run-id primitives-before-process-cold \
  --out "$OUT"

PYTHONPATH=src "$PY" -m grafix benchmark run \
  --case primitive.asemic.cold_unique_bezier \
  --profile long \
  --mode compile-cold \
  --samples 10 \
  --seed 20260719 \
  --timeout 600 \
  --run-id primitives-before-compile-cold \
  --out "$OUT"
```

ABABは同じharnessを持つbase/head source treeを交互に実行し、
`B1/A1`、`B2/A2`に加えて`A2/A1`と`B2/B1`をdrift controlとして比較する。
`benchmark compare`へ `--allow-incompatible` は使わない。

## 11. 最終検証コマンド

```bash
PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-all-primitives-tests \
NUMBA_NUM_THREADS=1 \
PYTHONPATH=src \
/opt/anaconda3/envs/gl5/bin/python -m pytest -q -p no:cacheprovider \
  tests/core/primitives \
  tests/core/test_asemic_primitive.py \
  tests/core/test_lissajous_primitive.py \
  tests/core/test_polyhedron_primitive.py \
  tests/core/test_text_primitive.py \
  tests/core/test_text_fill_stability.py \
  tests/core/test_primitive_bypass.py \
  tests/core/test_resource_budget.py \
  tests/core/test_silent_degradation_diagnostics.py \
  tests/devtools/benchmarks/test_primitive_benchmark.py

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-all-primitives-full \
NUMBA_NUM_THREADS=1 \
PYTHONPATH=src \
/opt/anaconda3/envs/gl5/bin/python -m pytest -q -p no:cacheprovider

/opt/anaconda3/envs/gl5/bin/python -m ruff check \
  src/grafix/core/primitives \
  src/grafix/devtools/benchmarks \
  tests/core/primitives \
  tests/devtools/benchmarks/test_primitive_benchmark.py

/opt/anaconda3/envs/gl5/bin/python -m mypy src/grafix/core/primitives
git diff --check
```

## 12. 変更予定ファイル

benchmark:

- `src/grafix/devtools/benchmarks/runner.py`
- `src/grafix/devtools/benchmarks/primitive_benchmark.py`（新規候補）
- `tests/devtools/benchmarks/test_primitive_benchmark.py`（新規）

実装:

- `src/grafix/core/primitives/_shape_utils.py`
- `src/grafix/core/primitives/arc.py`
- `src/grafix/core/primitives/asemic.py`
- `src/grafix/core/primitives/bezier.py`
- `src/grafix/core/primitives/circle.py`
- `src/grafix/core/primitives/ellipse.py`
- `src/grafix/core/primitives/grid.py`
- `src/grafix/core/primitives/laplace_field_grid.py`
- `src/grafix/core/primitives/line.py`
- `src/grafix/core/primitives/lissajous.py`
- `src/grafix/core/primitives/lsystem.py`
- `src/grafix/core/primitives/polygon.py`
- `src/grafix/core/primitives/polyhedron.py`
- `src/grafix/core/primitives/polyline.py`
- `src/grafix/core/primitives/rect.py`
- `src/grafix/core/primitives/sphere.py`
- `src/grafix/core/primitives/text.py`
- `src/grafix/core/primitives/torus.py`

tests:

- 既存の `tests/core/primitives/`
- `tests/core/test_asemic_primitive.py`
- `tests/core/test_lissajous_primitive.py`
- `tests/core/test_polyhedron_primitive.py`
- `tests/core/test_text_primitive.py`
- `tests/core/test_text_fill_stability.py`
- 必要なprimitive別differential test

公開API、型stub、metadataの変更は予定しない。実測で変更不要と判断したprimitiveは
実装ファイルを変更せず、benchmark/test/計画書だけへ結果を残す。

## 13. 停止条件

次の場合は複雑な代案へ進まず、そのprimitiveの変更を不採用として記録する。

- exact checksumまたはtopologyが変わる。
- warning、diagnostic、例外、RNG、font/asset挙動を維持できない。
- 演算順の差を互換shimや旧/new二重実装で隠す必要がある。
- benchmark noise内の改善しかない。
- small/process-cold/compile-coldの悪化が採用条件を超える。
- peak RSSまたはcache保持量が無制限になる。
- Numba追加がfirst-use stallを増やすだけになる。
- 全体test、Ruff、Mypyの失敗を今回変更と既存差分で区別できない。

## 14. 完了時に記録する内容

- 全17 primitiveのbefore / after median、MAD、p95、ratio
- warm / process-cold / compile-coldの区別
- exact checksumとcontract結果
- peak RSS、output bytes、cache entry/bytes
- 対象test、full pytest、Ruff、Mypyの結果
- 実装を変更しなかったprimitiveと理由
- 不採用案、既知のtradeoff、次段へ回す案

## 15. 実装・検証結果

### 15.1 正式warm ABAB

変更前sourceへ最終benchmark harnessを重ねたAと、変更後sourceのBを、
同一environment・同一Numba cache・同一seedで
`A1 -> B1 -> A2 -> B2` の順に計測した。
以下は2組のbase/head値の算術平均で、時間単位はmsである。

| case | output bytes | base median | head median | head/base | MAD base→head | p95 base→head | exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| arc / 512 | 6,164 | 0.016164 | 0.014419 | 0.892 | 0.000117→0.000096 | 0.016619→0.014717 | yes |
| asemic / warm repeated | 111,572 | 0.410995 | 0.401723 | 0.977 | 0.002985→0.003053 | 0.424259→0.417210 | yes |
| bezier / 3D 512 | 6,164 | 0.041503 | 0.041506 | 1.000 | 0.000255→0.000286 | 0.042401→0.042665 | yes |
| circle / 512 | 6,164 | 0.015970 | 0.014333 | 0.898 | 0.000085→0.000112 | 0.016300→0.014596 | yes |
| ellipse / rotated 512 | 6,164 | 0.019687 | 0.017869 | 0.908 | 0.000142→0.000120 | 0.020157→0.018629 | yes |
| grid / 500x500 transformed | 28,004 | 0.033712 | 0.034073 | 1.011 | 0.000209→0.000235 | 0.034820→0.034885 | yes |
| laplace / cylinder dense | 2,409,448 | 19.568705 | 10.952713 | 0.560 | 0.141705→0.100494 | 20.056633→11.234888 | yes |
| laplace / exp dense | 2,400,804 | 26.644510 | 9.920336 | 0.372 | 0.131323→0.086889 | 27.167512→10.283778 | yes |
| laplace / mobius clip | 2,278,432 | 25.390339 | 9.096637 | 0.358 | 0.093260→0.086828 | 25.656757→9.281845 | yes |
| line / control | 32 | 0.001332 | 0.001352 | 1.014 | 0.000012→0.000011 | 0.001358→0.001386 | yes |
| lissajous / 8,000 | 96,008 | 0.124585 | 0.120931 | 0.971 | 0.001124→0.001046 | 0.127208→0.126955 | yes |
| lsystem / plant 6 jitter | 105,348 | 21.915038 | 6.838454 | 0.312 | 0.146344→0.050588 | 22.327634→7.135545 | yes |
| polygon / 128 partial | 1,340 | 0.013707 | 0.012550 | 0.916 | 0.000094→0.000085 | 0.013962→0.013042 | yes |
| polyhedron / largest kind | 5,316 | 0.019903 | 0.006585 | 0.331 | 0.000098→0.000041 | 0.020235→0.006709 | yes |
| polyline / ndarray 50k | 600,020 | 45.964495 | 0.547038 | 0.012 | 0.411094→0.029022 | 48.265377→0.587259 | yes |
| rect / rotated | 68 | 0.008942 | 0.007357 | 0.823 | 0.000100→0.000068 | 0.009182→0.007499 | yes |
| sphere / icosphere sub5 | 860,164 | 150.098489 | 0.544429 | 0.004 | 1.232625→0.019903 | 152.675875→0.581234 | yes |
| sphere / latlon sub5 | 1,012,836 | 4.629681 | 0.793827 | 0.171 | 0.040583→0.010391 | 4.739398→0.815180 | yes |
| sphere / rings sub5 | 697,324 | 2.865997 | 0.521241 | 0.182 | 0.028090→0.011542 | 2.947298→0.540755 | yes |
| sphere / zigzag sub5 | 96,788 | 0.191359 | 0.074967 | 0.392 | 0.002373→0.000679 | 0.201248→0.076720 | yes |
| text / warm mixed | 1,473,040 | 32.386167 | 1.791931 | 0.055 | 0.302021→0.019822 | 33.325137→1.932412 | yes |
| torus / 256x256 | 1,581,060 | 2.242027 | 1.497937 | 0.668 | 0.042924→0.022877 | 2.485249→1.565325 | yes |

全22caseで次を満たした。

- environment compatible: `true`
- compare warning: なし
- exact geometry checksum: 一致
- hard contract: 全件pass
- output bytes: 全件一致
- raw dtype/layout、offsets、finite要件、writeability、call間独立性、
  input不変性: 全件pass

A側の最大driftはtorusの4.72%だった。B側ではsub-millisecond caseの
allocator/timer noiseにより最大10.66%のdriftがあったが、P0/P1の判定を反転させる
caseはなく、A1/B1とA2/B2の双方で主要改善が再現した。

### 15.2 process-cold / compile-cold

| mode / case | base median | head median | head/base | MAD base→head | p95 base→head | peak RSS delta | exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| process-cold / asemic | 331.864 ms | 29.959 ms | 0.090 | 2.896→0.332 ms | 361.588→30.746 ms | 47.94→2.17 MiB | yes |
| process-cold / polyhedron | 3.345 ms | 3.370 ms | 1.007 | 0.140→0.115 ms | 3.661→3.645 ms | 0.22→0.30 MiB | yes |
| process-cold / text | 277.279 ms | 275.714 ms | 0.994 | 2.570→3.211 ms | 283.796→282.619 ms | 81.42→80.08 MiB | yes |
| compile-cold / asemic | 541.353 ms | 29.230 ms | 0.054 | 0.940→0.450 ms | N/A | 57.38→2.22 MiB | yes |

process-coldの全caseは10%悪化条件内、compile-coldも悪化なしである。
特にasemicはdefault BezierのNumba import/JITを避けることでprocess-coldを91.0%、
compile-coldを94.6%短縮した。

### 15.3 memoryとcache

warm runnerの`peak_rss_delta`はcalibration後のプロセスhigh-water差であり、
allocatorのpage再利用とsample反復に影響される。主な観測値は次のとおりだった。

| case | base→head peak RSS delta |
| --- | ---: |
| laplace cylinder | 34.45→32.50 MiB |
| laplace exp | 23.68→37.15 MiB |
| laplace mobius | 28.58→31.89 MiB |
| polyline 50k | 9.52→14.27 MiB |
| sphere icosphere | 25.61→12.33 MiB |
| text warm | 25.79→41.33 MiB |
| torus | 54.24→25.66 MiB |

小さいcaseの比率やwarm high-water値だけでは保持memoryとtemporaryを分離できないため、
cache上限、fresh-process RSS、個別process測定も併用した。

- text glyph geometry: 最大256件かつndarray buffer合計32 MiB。
  個別process測定のpeak RSSは変更前比約+0.96%だった。
- text glyph command: 既存どおり最大4,096件。
- asemic glyph: 既存どおり最大256件、Bezier basisは最大64件。
- sphere unit geometry: 最大16件、内部配列readonly、raw returnはcopy。
- lsystem preset program: 最大16件。call-local heading cacheは最大256件。
  batch RNG temporaryはprogram上限500,000値、最大約3.82 MiBである。
- polyhedron packed base: 公開choiceの全20kindだけをkeyにする有限cache。
- polylineのfloat64 stagingは入力点数に線形で、保持cacheは追加しない。

textのbounded cacheとpolyline stagingは意図的なmemory/time tradeoffである。
前者はwarm 94.5%短縮、後者は50k点で98.8%短縮し、いずれも上限または入力サイズに
よって有界で、raw出力のfresh/writable/non-sharing契約を維持する。

### 15.4 differentialとtest

変更前snapshotとの独立differentialで、少なくとも次をexact比較した。

- polyline / lsystem / laplace / small primitives: 4,326 case
- text: 142 case
- asemic: 2,758 case
- sphere: 全style・line mode・subdivision組合せ
- torus: segment、半径、center/rotateの境界
- polyhedron: 全20kind

合計7,226件以上について、座標・offsetsのbytes、dtype、shape、flags、strides、
warning、例外、RNG、custom objectの評価順を比較し、最終差分は0件だった。
レビュー中に検出したwide integerの二段丸め、sNaN/subnormalの通知、
`closed.__bool__`の評価順、要素単位overflow warning、ndarray subclass副作用、
gridの`OWNDATA`差も修正後に再検証した。

最終検証結果:

```text
対象test:
186 passed, 1 skipped

full pytest（依頼外のorder-dependent 1件だけ除外）:
1799 passed, 1 skipped, 1 deselected

Ruff（primitive・benchmark・追加test）:
All checks passed

Mypy:
Success: no issues found in 21 source files

git diff --check:
pass
```

未除外のfull pytestでは、今回のprimitive変更とは無関係な
`test_remaining_effect_suite_covers_exact_builtin_target_set` だけが失敗した。
先行testが登録した4件のuser-defined effectを、並行作業で追加された
remaining-effect benchmark testがbuiltin集合として数えるorder依存である。
同testは単独実行ではpassし、今回対象を除いた全1799件はpassした。

### 15.5 不採用・変更しなかった経路

- `line`: 1.3 microseconds級のcontrolで、固有fast-pathは複雑化に見合わない。
  formal差は+0.019 microsecondsで許容noise内。
- `bezier`: basis temporary案は探索時約1.4%しか改善せず、正式controlも
  `head/base=1.000`だったため高速化差分を残していない。
- `asemic` direct pack: 改善が測れず巻き戻した。
- `asemic` line styleの純NumPy adjacency: 約13%遅化したため、
  従来のlazy Numba経路を維持した。
- `laplace_field_grid`の全line一括mapとtransform値の先行評価:
  peak memory、warning順、空出力時の遅延評価を変えるため採用しなかった。
- `sphere` latlon/ringsの全面direct pack:
  より単純で大きな改善が得られたimmutable packed base cacheを採用した。
- 新規Numba kernel、互換wrapper、旧/new二重実装は追加していない。
