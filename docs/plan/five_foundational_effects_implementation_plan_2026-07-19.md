<!--
どこで: `docs/plan/five_foundational_effects_implementation_plan_2026-07-19.md`。
何を: resample / simplify / deduplicate / boolean / offset_curve の実装手順と受け入れ条件を定義する。
なぜ: effect の基盤的な空白を、小さく明確な API と回帰検証を伴って埋めるため。
-->

# 基盤 5 effect 実装計画

- 作成日: 2026-07-19
- 計画時 HEAD: `a005b76`
- 状態: **実装・検証完了**
- 起点:
  `docs/plan/ideas/builtin_effect_gap_proposals_2026-07-19.md`
- 実装対象:
  1. `resample`
  2. `simplify`
  3. `deduplicate`
  4. `boolean`
  5. `offset_curve`

## 1. 今回の範囲

前提提案の「まず追加する価値が高い 5 effect」を今回の実装範囲とする。
Phase C 以降の `perspective`、`conformal_map`、`advect`、`path_deform`、
`stipple`、`overunder`、`spiral_fill`、`stitch` は含めない。

既存 effect の公開契約を変更するのは、公開 `resample` の前提となる共通
再標本化 kernel の不具合修正に限定する。対象は連続する長さ 0 の segment、
閉曲線へ巨大 `step` を指定した際の seam 重複、有限な float32 極値の距離
overflow である。通常範囲の `lowpass` / `highpass` の数値契約は維持する。
新規依存、互換 wrapper、shim は追加しない。

### 計画作成時の workspace

計画作成時には、別作業による次の差分が存在する。

```text
 M docs/plan/builtin_primitive_expansion_proposal_2026-07-19.md
 M src/grafix/core/builtins.py
 M src/grafix/devtools/benchmarks/primitive_benchmark.py
 M tests/devtools/benchmarks/test_primitive_benchmark.py
?? src/grafix/core/primitives/spiral.py
?? tests/core/primitives/test_spiral.py
?? tests/core/primitives/test_wave_a_integration.py
```

これらは本計画の対象外であり、整理、削除、巻き戻し、上書きを行わない。
`src/grafix/core/builtins.py` は変更箇所が重なるため、実装直前に最新版を読み直し、
既存差分を保持したまま effect manifest だけを最小変更する。

## 2. 完了状態

### 準備

- [x] 現行 32 built-in effect と不足領域を棚卸しした。
- [x] 今回の対象を優先度上位 5 effect に限定した。
- [x] registry、metadata、stub、resource budget、benchmark の連動箇所を確認した。
- [x] 実装時に触れてはならない並行差分を記録した。
- [x] ユーザーが本計画を承認した。

### 実装

- [x] Phase 1: 共通前提と `resample`
- [x] Phase 2: `simplify`
- [x] Phase 3: `deduplicate`
- [x] Phase 4: 平面共通処理と `boolean`
- [x] Phase 5: `offset_curve`
- [x] Phase 6: manifest、stub、デモ、benchmark
- [x] Phase 7: focused / full 検証
- [x] 完了結果を本書へ反映した。

## 3. 共通契約

### 3.1 公開 API

```python
E.resample(step=0.5, closed="auto")
E.simplify(tolerance=0.05, closed="auto")
E.deduplicate(tolerance=1e-4, merge_chains=True)
E.boolean(mode="union")(a, b)
E.offset_curve(
    distance=1.0,
    side="both",
    count=1,
    join="round",
    keep_original=False,
)
```

- 全公開引数へ default、型ヒント、`ParamMeta`、日本語 description を付ける。
- `closed` は `"auto" | "open" | "closed"`。
- `mode` は `"union" | "intersection" | "difference" | "xor"`。
- `side` は `"left" | "right" | "both"`。
- `join` は `"round" | "mitre" | "bevel"`。
- choice は registry が DAG 作成時に検証し、stub の `Literal` に反映させる。
- `boolean` は `n_inputs=2` とし、現 API の制約どおりチェーン先頭でのみ使う。

### 3.2 Geometry と決定性

- 入出力は既存の packed geometry 契約を守る。
  - `coords`: `float32`, shape `(N, 3)`
  - `offsets`: `int32`, shape `(M + 1,)`
- 入力配列を変更しない。
- 空入力、退化線、複数 line、閉曲線の挙動を effect ごとに固定する。
- 出力の line 順、頂点順、ring seam、向き、同値候補の tie-break を決定的にする。
- 乱数を使わないため、5 effect とも `cache_policy="content"` の既定を使う。
- effect module 同士は import せず、共有処理だけを
  `src/grafix/core/effects/util.py` に置く。

### 3.3 不正値と resource budget

- `resample.step`、`simplify.tolerance`、`deduplicate.tolerance`、
  `offset_curve.distance` が負または非有限なら identity/no-op とする。
- `step == 0`、`tolerance == 0`、`distance == 0` の個別仕様は各章で定義する。
- Boolean や offset が定義できない非有限・非平面 geometry は、誤った平面結果を
  暗黙に返さず、理由を含む `ValueError` とする。
- 出力配列を確保する前に `ensure_geometry_output` を呼ぶ。
- 上限超過時は部分出力や黙示 no-op ではなく `ResourceLimitError` とする。

## 4. Phase 1: 共通前提と `resample`

### 4.1 閉曲線 resample の共通修正

現行 `resample_polylines` には、連続する重複頂点による長さ 0 の segment、
最小 3 標本となる閉曲線へ周長以上の `step` を与えた場合の seam 重複、
float32 減算・二乗の overflow という三つの境界不具合がある。

- [x] `effects/util.py` の閉曲線 kernel で長さ 0 の segment を決定的に読み飛ばす。
- [x] 巨大 `step` では閉曲線を最低 3 個の相異なる位置へ均等配置する。
- [x] 通常の float32 算術を保ち、overflow が必要な line だけ float64 へ退避する。
- [x] 開曲線、正常な閉曲線、`lowpass`、`highpass` の既存数値契約を変えない。
- [x] 連続重複点、巨大 `step`、float32 極値と `lowpass` / `highpass` の
      回帰 test を追加する。

### 4.2 `resample`

新規ファイル:

- `src/grafix/core/effects/resample.py`
- `tests/core/effects/test_resample.py`

仕様:

- XYZ の 3D 弧長で標本位置を決める。
- `step` は厳密な全区間長ではなく、既存 helper に合わせた目標間隔とする。
  開曲線の最後には `step` 未満の余り区間を許す。
- 開曲線は元の両端を厳密に維持する。
- 閉曲線は出力末尾を出力先頭の厳密コピーにする。
- `"auto"` は既存 `RESAMPLE_CLOSED_DISTANCE_EPS == 0.01` 以下の端点距離を
  閉曲線とみなす。
- `"closed"` でも 2 点以下の線を ring へ昇格させない。
- 0 点、1 点、全長 0 の line はそのままコピーする。
- `step <= 0` または非有限値は入力配列をそのまま返す。

実装:

- [x] `ResamplePlan.from_geometry` で全 line の出力数を配列確保前に計画する。
- [x] 現在の `ResourceBudget.max_output_vertices` を plan の sentinel に使う。
- [x] 頂点数、line 数、bytes を `ensure_geometry_output` で検査する。
- [x] 共通 plan / kernel を再利用し、effect 側は検証と identity 判定だけに保つ。
- [x] 全 line が実質コピーとなる場合は、不要な新規配列を返さない。

test:

- [x] open 直線の upsample / downsample、補間値、両端維持。
- [x] exact closed、near closed、forced open / closed、厳密 closure。
- [x] mixed packed lines、空 line、0 / 1 / 2 点、全長 0、連続重複点。
- [x] XYZ 弧長、入力不変、dtype、offsets、反復実行の byte 一致。
- [x] resource cap の境界値と 1 超過を、出力確保前に拒否する。

## 5. Phase 2: `simplify`

新規ファイル:

- `src/grafix/core/effects/simplify.py`
- `tests/core/effects/test_simplify.py`

仕様:

- XYZ の point-to-segment 距離を使う iterative
  Ramer-Douglas-Peucker とする。
- 再帰は使わず、index stack と keep mask で処理する。
- `tolerance <= 0` または非有限値は identity/no-op。
- 開曲線は両端を必ず維持する。
- 元頂点を選ぶだけとし、新しい補間座標は作らない。
- すべての頂点が残る場合は元の packed arrays を返す。

閉曲線:

1. `"auto"` は端点距離 `0.01` 以下を閉曲線とする。
2. 明示 closure 点を標本対象から外す。
3. 入力先頭を seam とする。
4. seam から最遠の頂点を第 2 anchor とし、距離 tie は小さい入力 index を選ぶ。
5. 二つの arc へ open RDP を適用して結合する。
6. 入力に 3 個以上の固有頂点がある場合、巨大 tolerance でも 3 個未満へ潰さない。
7. 出力順と向きを入力のまま保ち、最後に先頭を厳密コピーする。
8. 3 個未満の固有頂点しかない退化 ring はコピーする。

実装:

- [x] line ごとの keep index と exact output count を先に求める。
- [x] output と keep mask / stack の scratch bytes を resource preflight する。
- [x] packed output を一度だけ確保し、入力順にコピーする。

test:

- [x] collinear 点の削減、折れ点、tolerance 境界、開線端点。
- [x] Z 方向の偏差を含む XYZ 距離。
- [x] exact / near / forced closed、seam、向き、closure。
- [x] 有効 ring の最小 3 固有頂点と、退化 ring のコピー。
- [x] mixed lines、短線、重複点、入力不変、dtype、決定性。
- [x] no-op identity と scratch を含む resource cap。

## 6. Phase 3: `deduplicate`

新規ファイル:

- `src/grafix/core/effects/deduplicate.py`
- `tests/core/effects/test_deduplicate.py`

### 6.1 v1 の対象

- 各 polyline の連続 2 頂点を無向直線 segment とみなす。
- 同向・逆向きの同一 segment を一つにする。
- 部分 overlap、交差位置での分割、「一本の長線分」と「複数の分割線分」の同一視は
  v1 の対象外とする。
- XYZ すべてを endpoint key に使う。
- segment を持たない 0 / 1 点 line と zero-length segment は出力しない。

### 6.2 endpoint の一致規則

- `tolerance == 0` は有限な float32 座標の完全一致とする。
- `tolerance > 0` は各成分を tolerance 格子へ half-away-from-zero で量子化し、
  量子化 key が一致する endpoint を同じ node とする。
- 「ユークリッド距離が tolerance 以下」を意味しないことを docstring に明記する。
- node の出力座標は格子へスナップせず、最初に現れた endpoint を代表値とする。
- 非有限座標を一つでも含む geometry は `ValueError` とし、部分処理しない。

### 6.3 segment と chain の順序

- canonical edge key は node id の小さい順とし、逆向き duplicate も除く。
- edge の座標と向きは最初に現れた segment を採用する。
- `merge_chains=False`:
  - unique edge を first-seen 順に、各 2 点 polyline として返す。
- `merge_chains=True`:
  - degree 2 node だけを通過して maximal chain を作る。
  - degree が 2 でない branch node では勝手に edge 同士を接続しない。
  - 全 node が degree 2 の component は閉 loop とし、先頭を末尾へ再掲する。
  - adjacency は edge id 順、cycle seam は最小 edge id の元始点、
    cycle 方向はその edge の元向きとする。
  - `dict` / `set` の暗黙の反復順には依存しない。

実装:

- [x] packed input を一度走査し、node table と first-seen edge table を作る。
- [x] `merge_chains` の規則に従って exact output lines を組み立てる。
- [x] 中間 line 配列と二重確保を避け、chain を最終 packed buffer へ直接書く。
- [x] exact output count を resource preflight 後に一度だけ pack する。

test:

- [x] 同向 / 逆向き / 同一 line 内 duplicate。
- [x] tolerance 0、正値、量子化 tie と格子境界。
- [x] Z が異なる segment、first representative、first direction。
- [x] `merge_chains=False` の first-seen 順。
- [x] open chain、branch 分割、cycle closure、複数 component。
- [x] zero-length、0 / 1 点 line、empty、非有限入力。
- [x] branch により line 数が増える場合の resource preflight。

## 7. Phase 4: 平面共通処理と `boolean`

新規ファイル:

- `src/grafix/core/effects/boolean.py`
- `tests/core/effects/test_boolean.py`

### 7.1 順序・winding 非依存の共通平面

現行 `PlanarFrame.from_points` は ring の Newell ベクトルと最初の edge で frame の
向きを決める。この契約は既存 effect には適しているが、入力 ring の winding や
polyline の向きを反転すると local axes も反転する。これをそのまま使うと、
`boolean` の winding 非依存性と `offset_curve` の「入力方向に対する left/right」を
同時に満たせない。

- [x] `PlanarFrame.from_points` の既存契約は変更しない。
- [x] `effects/util.py` に、推定した平面から world 基準の canonical axes を作る
      小さな helper を追加する。
- [x] normal は最大絶対成分が正になるよう符号を固定する。
- [x] local X は固定 world axis を平面へ射影して決め、同率時の軸優先順も固定する。
- [x] local Y は canonical normal と X の外積から決める。
- [x] 平面内原点は world 原点を推定平面へ射影した点とし、入力順に依存させない。
- [x] 閉 ring の frame 推定では重複 closure 点を除き、seam の変更で平均が変わらない
      ようにする。
- [x] helper 自体を、winding、seam、line 順、open line の向き反転で検証する。

`boolean` では、二入力の有効 ring coords と line 境界を連結して一つの canonical
frame を推定する。全点が同じ平面にあることを `planarity_threshold` で検証し、
異なる平面、非平面、非有限入力は `ValueError` とする。両入力を同じ local XY へ
写し、出力を元の world 平面へ復元する。

### 7.2 Boolean

- 既存依存の Pyclipper を使い、scale は既存 `clip` と同じ `1000` とする。
- 各入力の閉 ring 群を winding 非依存の even-odd 領域として扱う。
- 空 line は無視する。それ以外は 3 個以上の固有頂点を持ち、端点距離 `0.01`
  以下で閉じた ring であることを要求する。
- 開 line と面積 0 の退化 ring を黙って領域化せず、`ValueError` とする。
- `Execute2` と `PolyTree` を使い、outer / hole / island の階層を保持する。
- 出力 ring は明示的に閉じる。
- local integer 空間で次を canonicalize してから world へ戻す。
  - outer は反時計回り、hole は時計回り
  - seam は辞書順で最小の頂点
  - 親子階層、面積、canonical vertex key による安定した ring 順
- `difference` は第 1 入力から第 2 入力を引く。

空入力は集合演算として扱う。

| mode | `boolean(a, empty)` | `boolean(empty, b)` |
|---|---|---|
| `union` | `a` | `b` |
| `intersection` | empty | empty |
| `difference` | `a` | empty |
| `xor` | `a` | `b` |

実装:

- [x] `@effect(meta=..., n_inputs=2)` で登録する。
- [x] ring 抽出、int path 変換、PolyTree traversal を module 内の小さな helper に分ける。
- [x] backend 結果の頂点数を数え、NumPy geometry 確保前に resource preflight する。
- [x] backend traversal 順や入力 winding に依存しない canonical output を返す。

test:

- [x] 4 mode の面積と輪郭、`difference` の入力順。
- [x] 非交差、接触、包含、hole、island、複数 ring。
- [x] 入力 winding と ring seam を変えても canonical output が一致する。
- [x] 空入力の集合則、退化 ring。
- [x] 傾斜平面の復元、異なる平面と非平面の拒否。
- [x] 二入力 arity と「チェーン先頭のみ」の API 制約。
- [x] dtype、明示 closure、入力不変、反復実行の byte 一致。

## 8. Phase 5: `offset_curve`

新規ファイル:

- `src/grafix/core/effects/offset_curve.py`
- `tests/core/effects/test_offset_curve.py`

### 8.1 平面 frame

Phase 4 で追加する canonical frame helper を geometry 全体へ一度使い、全 line で
left/right の基準を共有する。ただし、現行 `PlanarFrame` は rank 1 の直線を
無効とするため、最重要ケースである一本の直線をそのまま扱えない。

- [x] `PlanarFrame.from_points` の既存 rank / valid 契約は変更しない。
- [x] canonical frame helper に `allow_linear` 相当の明示分岐を持たせる。
- [x] rank 2 以上では world 基準の canonical axes を使う。
- [x] rank 1 では直線方向の最大絶対成分が正になるよう符号を固定して local X とし、
      最も直交する world axis を法線候補にする。同率時は Z、Y、X の順で選び、
      法線の符号も入力方向と独立に固定して principal plane を決定する。
- [x] rank 0、非有限、真の非平面曲線は `ValueError` とする。

純粋な 3D 直線では left/right 平面は一意でないため、この principal-plane 規則を
公開 docstring と test で固定する。

### 8.2 offset

- 既存依存の Shapely `LineString.offset_curve` を使う。
- `distance` は正の距離単位とし、0、負値、非有限値は identity/no-op。
- `count > 0` とし、0 以下は identity/no-op。
- `k = 1..count` について `k * distance` の offset を作る。
- local XY で left は正距離、right は負距離とする。
- 生成順は入力 line 順、距離の小さい順、left、right の順とする。
- `keep_original=True` の元 line は、`buffer` と同じく生成結果の後ろへ追加する。
- cusp や自己交差で一つの入力が複数 fragment へ分かれることを許容する。
- MultiLineString / GeometryCollection を再帰的に抽出し、fragment を canonical key で
  並べる。
- GEOS version により right 側の方向が変わらないよう、open fragment は入力の
  始点・終点との対応で向きを正規化する。
- closed ring の left/right は入力 winding に対して定義し、出力を明示閉鎖する。
- `quad_segs` と `mitre_limit` は v1 の公開 API に増やさず、backend の固定値を使う。

実装:

- [x] line ごと、level ごと、side ごとに Shapely offset を実行する。
- [x] fragment の向きと順序を backend version から独立させる。
- [x] GEOS 試行数を保守的に事前検査し、fragment ごとの累積量と最終 exact
      output count を resource preflight 後に pack する。
- [x] local Z を 0 として world 平面へ復元する。

test:

- [x] 水平 open line の left / right / both。
- [x] open line を反転すると、同じ `side` が入力方向に従って物理的に反対側へ移る。
- [x] count、生成順、keep_original。
- [x] round / mitre / bevel、corner、cusp、複数 fragment。
- [x] closed ring と winding、明示 closure。
- [x] 一本の XY / XZ / 任意 3D 直線に対する principal plane。
- [x] 複数 line の共通平面、傾斜平面の復元、非平面の拒否。
- [x] no-op identity、empty、入力不変、dtype、決定性、resource cap。

## 9. Phase 6: 公開面、デモ、benchmark

### 9.1 manifest / metadata / stub

- [x] `src/grafix/core/builtins.py` に 5 module を追加する。
- [x] 並行中の primitive manifest 差分を保持する。
- [x] operation catalog と description completeness の全体 test を通す。
- [x] `src/grafix/api/__init__.pyi` を stub generator で再生成する。
- [x] 手書きで lazy `E` API を重複実装しない。
- [x] `boolean` の二入力制約を docstring と使用例へ明記する。

### 9.2 代表デモ

- [x] `sketch/presets/effect_foundations.py` を追加する。
- [x] 5 effect を別領域で示し、少なくとも一例は既存 effect との chain にする。
- [x] デモを import / render し、空出力や resource error がないことを確認する。

### 9.3 benchmark

`remaining_effect_benchmark` は対象 built-in 集合を厳密比較しているため、
manifest だけを増やすと既存 test が失敗する。5 effect を同時に正式対象へ追加する。

- [x] `remaining_effect_benchmark.py` に 5 effect の actual-work case を追加する。
- [x] `resample`: long line の upsample / downsample。
- [x] `simplify`: 微小ノイズを含む long line。
- [x] `deduplicate`: 同向・逆向き duplicate と chain merge。
- [x] `boolean`: hole を含む二入力 ring。
- [x] `offset_curve`: one-long-line と many-lines。
- [x] `boolean` と `offset_curve` を process-cold 対象へ追加する。
- [x] 必要最小限の fixture と effect-specific work metric を追加する。
- [x] expected checksum は実装確定後の決定的出力から固定する。
- [x] built-in target set、case 数、packed layout、actual-work、input immutable の
      benchmark test を更新する。

## 10. Phase 7: 検証

実装中は狭い順に検証し、最後に全体を通す。実行環境の Python は
`/opt/anaconda3/envs/gl5/bin/python` を使う。

### focused

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /opt/anaconda3/envs/gl5/bin/python -m pytest -q \
  tests/core/effects/test_resample.py \
  tests/core/effects/test_simplify.py \
  tests/core/effects/test_deduplicate.py \
  tests/core/effects/test_boolean.py \
  tests/core/effects/test_offset_curve.py
```

- [x] 5 effect の focused test。
- [x] `lowpass` / `highpass` の resample 回帰 test。
- [x] effect registry / catalog / metadata test。
- [x] stub sync test。
- [x] remaining effect benchmark test。

### 静的検査

```bash
ruff check src/grafix/core/effects tests/core/effects
mypy src/grafix
```

- [x] ruff。
- [x] mypy。

### full

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /opt/anaconda3/envs/gl5/bin/python -m pytest -q -p no:cacheprovider
```

- [x] full pytest。
- [x] 失敗が本変更由来か並行差分由来かを切り分ける。
- [x] 本変更由来の失敗をすべて解消する。

## 11. 完了条件

次をすべて満たした時点で完了とする。

1. 5 effect が lazy `E` API、metadata、operation catalog、stub から利用できる。
2. 文書化した empty / no-op / degenerate / open / closed 契約が test で固定される。
3. XYZ-native 3 effect と planar 2 effect の座標契約が混同されていない。
4. planar effect が傾斜平面を復元し、不正な非平面入力を黙って変形しない。
5. line / ring / fragment の順序と向きが反復実行および backend 差に対して決定的である。
6. 大規模 output を NumPy 配列へ確保する前に共通 resource budget で拒否できる。
7. 新規依存や effect 間 import を増やしていない。
8. 代表デモ、focused test、stub sync、benchmark contract、full pytest が通る。
9. 並行中の依頼外差分を変更、削除、巻き戻ししていない。
10. 本書の完了項目と、未完了または意図的に見送った項目を最終状態へ更新している。

## 12. 完了記録

- 完了日: 2026-07-19
- 実装:
  - 5 effect と共通 planar / resource / packing 処理を追加した。
  - manifest、公開 stub、metadata、代表デモ、benchmark を同期した。
  - `deduplicate` は二重確保を避けるため、exact preflight 後に一度だけ直接
    pack する設計へ確定した。
  - `offset_curve` は保守的な GEOS 試行数の事前検査と、fragment ごとの累積検査、
    最終 exact output 検査を組み合わせた。
  - 共通 resample kernel は zero-length segment、closed ring への巨大 `step`、
    float32 極値の距離 overflow を修正した。
- 検証:
  - effect test: `473 passed`
  - benchmark / catalog / stub 関連 test: `38 passed`
  - full pytest: `2113 passed, 1 skipped`
  - `ruff check src/grafix/core/effects tests/core/effects`: 成功
  - `mypy src/grafix`: 成功（226 source files）
  - 代表デモ render: 成功（`coords=(292, 3)`, `offsets=(11,)`）
- 未完了または見送り: 今回の実装範囲にはなし。Phase C / D の候補は当初から対象外。
- 並行作業: primitive 関連を含む依頼外差分は保持し、整理、削除、巻き戻しを
  行っていない。
