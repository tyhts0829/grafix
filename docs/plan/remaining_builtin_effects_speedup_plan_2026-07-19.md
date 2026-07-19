# 5 effect を除く全組み込み effect 高速化計画

- 作成日: 2026-07-19
- 調査時 HEAD: `cc484fa`
- 状態: 実装・formal long ABAB・full pytest 完了
- 対象数: 27
- 固定 seed: `20260719`
- 除外:
  - `fill`
  - `subdivide`
  - `scale`
  - `rotate`
  - `translate`
- 除外 5 件の完了記録:
  - `docs/plan/fill_subdivide_transform_effects_speedup_plan_2026-07-19.md`

調査時 workspace には本計画と無関係な未コミット差分がある。実装開始時はそれらを
整理・巻き戻し・上書きせず、ユーザーが承認した開始 source を読み取り専用 snapshot
として保存し、その内容を正式な before とする。

本書前半の未チェック項目には、実測後に不採用または不要と判断した実装候補・
網羅的追加案も含まれる。最終的な完了条件と採否の正本は 11章、17.6〜17.10 とする。

## 1. 目的

除外 5 件以外の全組み込み effect を同じ基準で計測し、既存挙動を一切壊さずに
実作業を高速化する。

「全 effect の高速化」は、対象 27 件の actual-work、境界条件、cold/warm、
メモリを全て計測・検証することを意味する。全 27 件へ無理に複雑な fast path を
追加することは意味しない。既に十分速い、外部ライブラリが支配する、または exact
互換のまま有意な改善を作れない effect は変更せず、測定値と不採用理由を記録する。

速度より正しさを優先する。baseline と 1 件でも説明のない差がある最適化は採用しない。
浮動小数点の許容誤差を後から広げて差を隠すこともしない。

## 2. 対象の完全性

次の 3 経路を照合し、除外後の集合が 27 件で一致することを確認した。

1. `src/grafix/core/builtins.py::_BUILTIN_EFFECT_MODULES`
2. `src/grafix/core/effects/*.py` の `@effect` 関数
3. `ensure_builtin_effects_registered()` 後の `effect_registry`

対象は次の 27 件である。

```text
affine, bold, buffer, clip, collapse, dash, displace, drop,
extrude, growth, highpass, isocontour, lowpass, metaball,
mirror, mirror3d, partition, pixelate, quantize,
reaction_diffusion, relax, repeat, trim, twist, warp, weave,
wobble
```

ユーザー定義 `@effect` は任意に追加できるため実装対象外とする。ただし registry、
effect wrapper、実体 geometry 検証の共通契約は回帰させない。

## 3. 変更してはならない契約

### 3.1 公開 API と geometry

- 公開名、signature、default、ParamMeta、choices、UI visibility、`n_inputs`、
  cache policy、型 stub を変更しない。
- wrapper 通過後の canonical geometry は
  `coords=float32, shape=(N, 3)`、`offsets=int32, shape=(M+1,)` のままとする。
- 頂点順、polyline 順、ring/hole 順、向き、明示閉鎖点、重複点、offsets を維持する。
- 入力配列を変更しない。実行前後の raw bytes、shape、strides、writeability を比較する。
- no-op / invalid parameter / empty の戻り値が入力配列 object を共有する場合、その
  object identity を維持する。
- 座標だけを変える effect が入力 `offsets` object を共有する場合、その共有を維持する。
- 新規出力の C/F layout、writeability、入力との memory sharing も変更前どおりにする。
- `keep_original`、`show_mask`、`show_planes`、`draw_outline` 等による追加順を維持する。
- `clip` / `warp` の複数入力順、arity error、base/mask の no-op 選択を維持する。

### 3.2 分岐、診断、失敗

- parameter の左から右への評価順、早期 return の位置、未使用引数を評価しない挙動を
  維持する。
- 例外の型、message、`RealizeError.__cause__`、発生タイミングを維持する。
- warning の category、message、件数、順序を維持する。
- operation diagnostic の
  `op / original_value / effective_value / reason / severity / 順序`
  と重複抑止を維持する。
- clamp、silent no-op、empty 出力、入力返却を effect 間で統一しない。現行の
  effect 固有仕様をそのまま固定する。
- resource budget、grid/vertex/iteration cap は、検査タイミング、境界値、
  部分出力の有無、例外を維持する。
- `draft` と `final` は別契約とする。final の grid pitch、segment 数、
  iteration 数を高速化目的で暗黙に減らさない。

### 3.3 乱数と決定性

次の effect は bit generator、seed、乱数 draw 数、draw 順を固定する。

```text
bold, collapse, dash, drop, growth, partition, reaction_diffusion
```

`weave` の数式由来の疑似乱数も、式、seed、attempt 数、評価順を固定する。

特に次を変更しない。

- `bold`: 全 `u` を生成した後に全 `v` を生成する順序
- `collapse`: seed 0、有効 segment だけが乱数を消費する対応
- `dash`: line 順の jitter 消費
- `drop`: line mode は全 line、face mode は対象 face だけが乱数を消費する規則
- `partition`: `xs → ys → density`、rejection batch、top-up の消費順
- `reaction_diffusion`: boolean index の row-major 順で作る初期 noise
- `growth`: seed center、ring、iteration にまたがる消費順

### 3.4 数値、JIT、外部 backend

- 通常の有限入力は `coords` と `offsets` の raw bytes を exact 一致させる。
- NaN payload、NaN の位置、Inf、signed zero、subnormal も `view(np.uint32)` 等で
  bitwise 比較し、`equal_nan=True` だけで済ませない。
- float32/float64 の境界、演算の結合順、reduction 順、比較の strict/inclusive、
  `np.rint`、half-away-from-zero を維持する。
- 現在 `fastmath=True` の kernel はその結果を baseline とする。新規 fastmath は
  原則追加せず、既存 fastmath を無断で外さない。
- 新規 `parallel=True` は独立した出力領域だけへ限定する。force、sum、RNG 等の
  reduction 順が変わる並列化は行わない。
- Numba の Python fallback、compiled path、thread 数 1 / 2 / 4 で出力を比較する。
- Shapely/GEOS と pyclipper の version を正式 environment identity に含める。
  version が異なる run の性能・checksum 比較は拒否する。
- 新規依存、互換 wrapper、旧実装 shim、無制限 cache は追加しない。

## 4. 現状調査

### 4.1 テスト

調査時 workspace で次を実行した。

```text
tests/core/effects: 276 passed in 23.32s
```

対象 27 effect の専用テストは、`tests/core/effects/` と
`tests/core/test_effect_{bold,extrude,wobble}.py` を合わせて意味的に
165 test 関数ある。ただし statement/branch coverage の実測値ではない。

特に `extrude / highpass / lowpass / mirror / partition / quantize / relax /
wobble` は専用 test が各 3 件だけである。既存 test は代表的な見た目や正常系を
確認しているが、演算順、RNG 消費、object identity、IEEE 値、cap の直前直後、
診断全文まで固定するには不足している。

### 4.2 現行 benchmark の不足

`src/grafix/devtools/benchmarks/runner.py::_effect_definitions()` は対象 27 件を名前上は
全て登録している。しかし、現在の 1 fixture 中心の case は高速化の正式 baseline
には不足する。

- `effect.drop.many_lines` は default 条件が全て無効で、実質 no-op。
- `effect.weave.many_lines` は開線だけなので、実質 no-op。
- mode、quality、one-long-line / many-short-lines の差がほぼ測れない。
- actual work を行ったことを hard contract で確認していない。
- frozen expected checksum を持つのは
  `growth / metaball / reaction_diffusion` の draft/final だけ。
- `_workload_effect()` は evaluator だけでなく typed metrics、diagnostic snapshot、
  checksum/contract 作成も timed workload 内で行う。effect 本体の時間を分離できない。
- environment fingerprint に Shapely/GEOS と pyclipper が入っていない。
- exact geometry checksum だけでは strides、writeability、object identity、
  alias、diagnostic、warning、exception を検証できない。

現在の case は smoke/regression control として残し、正式 actual-work case を別に追加する。

### 4.3 静的に見えるボトルネック

正式な優先度は Phase 0 の実測後に確定する。現時点で有望な箇所は次である。

1. `reaction_diffusion`: `steps × bbox cells` の serial dense simulation
2. `metaball`: `grid cells × total segments` の serial field 評価
3. `growth`: iteration ごとの list/packed 変換、scratch 再確保、force 計算
4. `warp`: `base vertices × ring segments` の SDF と lens で未使用の法線計算
5. `displace`: 1 頂点 3 回の Perlin と中間 noise 配列
6. `dash`: count/fill での弧長二重計算と line ごとの JIT dispatch
7. `lowpass` / `highpass`: line ごとの JIT dispatch と convolution 一時配列
8. `relax`: Python dict/set/DFS による topology 構築
9. `mirror3d`: polyhedral 行列の毎回再生成と piece ごとの小配列
10. `weave`: candidate ごとの全 edge 走査、iteration scratch、graph trace

## 5. Phase 0: 正しさ oracle と計測基盤を先に作る

### 5.1 immutable baseline

- [x] ユーザー承認後、実装開始直前の対象 source、benchmark、test の SHA-256 manifest
      と dirty diff hash を保存する。
- [x] その source を `/tmp` の読み取り専用 baseline tree へ複製し、candidate tree と
      別 process、別 `NUMBA_CACHE_DIR` で実行する。
- [x] commit ID だけで dirty workspace を表したことにしない。
- [x] Python、Grafix、NumPy、Numba、BLAS、CPU、thread 設定、Shapely、GEOS、
      pyclipper の version を保存する。
- [x] baseline runner と candidate runner は同一 request JSON を受け、
      geometry、diagnostic、warning、exception、identity 情報を別々に返す。

旧実装を production package に残したり、runtime fallback として呼んだりしない。
旧 source はテスト時だけ別 process で使う。

### 5.2 三重 oracle

1. **baseline subprocess**
   - implementation 前の実装を同一入力で実行し、candidate と exact 比較する。
2. **frozen golden / checksum**
   - 小型の重要 case は配列 bytes と diagnostic を repository 内 golden として固定する。
   - actual-work は expected checksum と work metric を hard contract にする。
3. **semantic / metamorphic test**
   - 平面復元、閉鎖、境界内、決定性、energy 等の意味的性質を検査する。

semantic test だけ、または画像の見た目だけで同値と判定しない。

### 5.3 timed evaluator と観測の分離

- [x] effect benchmark の timer は evaluator call だけを囲む。
- [x] preview quality context と diagnostic context は timer の外で開始・終了し、
      emit 自体だけを evaluator 時間へ含める。
- [x] output materialization、checksum、typed metrics、contract 判定は timer 停止後に行う。
- [x] 全 sample の出力を timer 外で検証し、最後の sample だけを検査して
      nondeterminism を見逃さない。
- [x] warmup/JIT compile、process import、compile-cold を別 mode にする。
- [x] stage microbenchmark は end-to-end primary case を置き換えない。

runner 全体を再設計せず、effect case に必要な最小 lifecycle 拡張に留める。

### 5.4 environment と hard contract

- [x] Shapely version、GEOS version、pyclipper version を environment fingerprint へ加える。
- [x] case source、fixture source、effect source、共有 `util.py` の checksum を記録する。
- [x] dtype / shape / exact bytes / offsets 単調性を hard contract にする。
- [x] actual-work case に「入力と出力が異なる」「期待 work が 0 でない」contract を加える。
- [ ] no-op case は逆に object identity と work 0 を hard contract にする。
- [x] diagnostic、warning、exception、input mutation、alias は differential test の
      hard failure にする。
- [x] compare に `--allow-incompatible` を使わない。

## 6. 正式 benchmark case

fixture の規模、parameter、seed、quality、backend version、case source hash を baseline
取得前に固定する。表の primary は end-to-end actual-work、secondary は branch/cold/
guardrail 用である。

| effect | primary actual-work | secondary / guardrail |
| --- | --- | --- |
| `affine` | 50k 頂点、auto-center、scale+XYZ rotate+delta | fixed pivot、many-lines、identity、IEEE |
| `bold` | 5k lines、count=10、radius>0 | one-long-line、count=1、radius=0、budget |
| `buffer` | big ring の正距離、many-rings の union on/off | 負距離、3 join、quad clamp、傾斜面、keep |
| `clip` | 5k lines と outer+holes の inside | outside、outline、量子化境界、傾斜面 |
| `collapse` | 50k 頂点、subdivisions、mask 無効 | many-lines、mask slope、退化 segment、budget |
| `dash` | 50k 頂点、scalar pattern | many-lines+jitter、cycle pattern、zero-length |
| `displace` | 50k 頂点、default no-gradient | amp gradient、freq gradient、radial、0 amplitude |
| `drop` | 5k lines、interval+length+probability | face/many-rings、keep/drop、全条件無効 no-op |
| `extrude` | 50k 頂点、subdivision+scale+delta | many-lines、origin/auto、edge 省略境界、clamp |
| `growth` | rings_2 の draft/final | holes、multi-ring、slide/bounce、budget |
| `lowpass` | 50k open line、大 kernel | 5k short lines、closed ring、cap/no-op |
| `highpass` | 50k open line、大 kernel | 5k short lines、closed ring、gain=0、cap |
| `isocontour` | rings_2、both、複数 level | inside/outside、gamma/phase、keep、grid reject |
| `metaball` | rings_2 の draft/final | many-rings、exterior/both、draft budget |
| `mirror` | 5k lines の n=1/2/8 | source side、wedge boundary dedup、show planes |
| `mirror3d` | 5k lines の azimuth と I group | T/O、reflection、equator、show planes、cold cache |
| `partition` | rings_2、site 30/128、merge | group/ring、density、top-up、傾斜面 |
| `pixelate` | spaced 50k line の actual stair | many-lines、3 corner、Z-only、vertex cap |
| `quantize` | 500k 頂点、非等方 step | half tie、signed zero、invalid/no-op |
| `reaction_diffusion` | rings_2 の draft/final | dense/sparse mask、boundary 2 種、0 step |
| `relax` | 共有 node を持つ 10k-node network | topology-only、cycle、multi-component、no-edge |
| `repeat` | many-lines の grid transform | radial multi-ring、pure offset、budget、count=0 |
| `trim` | 50k line の interior range | 5k short lines、closed/degenerate、full/no-op |
| `twist` | 50k 頂点、任意 3D axis | fixed pivot、many-lines、zero range、zero axis |
| `warp` | 50k base+mask の lens と attract | 4 kind、2 profile、repel、extras、many-rings |
| `weave` | big closed ring、candidate 100/500 | tilted/nonplanar、mixed open+closed、0 candidate |
| `wobble` | 500k 頂点、XYZ amplitude/frequency | axis 0、phase、identity、IEEE |

### 6.1 typed metrics

全 case:

- `n_vertices`, `n_lines`, `closed_lines`, `output_bytes`
- `input_vertices`, `input_lines`
- `actual_work` boolean
- `quality`
- `diagnostics`
- `process_cold`, `compile_cold`, `warm` の区別

effect 固有:

- copy 系: copies、effective output vertices/lines
- resample/filter: resampled vertices、kernel radius、open/closed lines
- grid 系: requested/effective pitch、nx、ny、cells
- simulation: requested/effective steps/iterations、active cells、points
- segment field: ring count、segment count、cells×segments または points×segments
- graph 系: nodes、edges、components、candidates
- external geometry: input/output paths、rings、backend/version

計測専用 counter を production hot loop に無条件追加せず、setup、parameter、output、
既存 diagnostic から導出する。内部 phase の計測が必要な場合は opt-in の
benchmark-only driver に分離する。

## 7. 性能の採用条件

### 7.1 correctness gate

次のいずれかが変われば性能値に関係なく不採用とする。

- exact geometry bytes、topology、順序、閉鎖
- no-op identity、offsets alias、input mutation
- diagnostic、warning、exception、評価順
- RNG sequence / draw count
- draft/final の effective work
- resource cap と失敗挙動
- public API / metadata / stub

許容誤差や ULP 上限による採用は本計画では行わない。bitwise 一致しない案を
検討する必要が生じた場合は、この計画とは別にユーザー承認を取り直す。

### 7.2 warm

- baseline median が 10 ms 以上の primary:
  - median 20% 以上改善
  - 改善量が baseline の `3 * MAD` を超える
- 1–10 ms の primary:
  - median 10% 以上改善
  - 50 microseconds 以上改善
  - 改善量が `3 * MAD` を超える
- 1 ms 未満:
  - 複雑な専用 fast path は追加しない。
  - 共有改善で速くなる場合だけ採用する。
- p95 が 10% 超悪化した場合は ABAB で再測定し、再現すれば不採用とする。
- p99 / max は hard timing gate にせず、外れ値の原因調査と before/after 記録を必須にする。
- small/no-op/secondary は 5% かつ 2 microseconds を超える悪化を許容しない。
- helper が速くても end-to-end primary が noise 内なら production 変更を残さない。
- parallel 化した case は production thread profile を性能主判定、single-thread profile を
  非回帰判定にする。thread 数を伏せて両者を同じ結果として扱わない。

### 7.3 cold、JIT、memory

- process-cold は 10% 超悪化させない。
- compile-cold は 15% または 500 ms の小さい方を超えて悪化させない。
- 新しい Numba kernel は次を全て満たす場合だけ採用する。
  - 構造的な NumPy/Python 改善だけでは目標に届かない
  - warm primary が 2 倍以上
  - exact output、warning、exception が一致
  - small input の crossover が明示される
- peak RSS / temporary bytes は原則 10% 超増加させない。
- bounded cache は entry 数と byte 上限を持つ。`mirror3d` の group cache 候補は
  T/O/I の最大 3 entry とする。
- 出力そのものに必要な bytes と scratch/cache bytes を分けて記録する。

### 7.4 測定方法

- 同一 machine、電源条件、environment fingerprint で測る。
- warm は十分な warmup 後、median / MAD / p95 を保存する。
- base/head を A1→B1→A2→B2 で交互に実行する。
- `A2/A1` と `B2/B1` を thermal/order drift control にする。
- Numba thread 数 1 と production 設定を分ける。
- external backend case は同一 process warm と process-cold を分ける。
- warmup の high-water mark で増分が隠れないよう、大規模 primary は setup 完了後の
  actual-work 1 回だけを fresh process で測る isolated RSS case も用意する。

## 8. effect 別の実装候補

以下は静的調査から得た「最初に測る候補」であり、実装決定ではない。Phase 0 の
profile、exact differential、性能 gate を通過した案だけを残す。

### 8.1 座標変換、複製、選択

#### `affine`

- [ ] 大きな canonical finite 入力だけ、現行 float64 演算順を再現する fused kernelを試す。
- [ ] `centered / scaled / rotated / transformed` の Nx3 temporary を減らす。
- [ ] float64 mean、Rz・Ry・Rx、identity return、offsets 共有を exact 固定する。
- [ ] 合成 4x4 matrix 化は演算結合順が変わるため行わない。

#### `quantize`

- [ ] float64 divide→abs/floor/sign→multiply を 1 pass で最終 float32 へ書く候補を測る。
- [ ] 小入力は NumPy、十分大きな入力だけ fused path とする crossover を決める。
- [ ] half-away-from-zero、nextafter half tie、signed zero、NaN/Inf warning を固定する。

#### `wobble`

- [ ] 3 軸の float64 sin と出力書込みを fused kernel 化する候補を測る。
- [ ] amplitude 0 の軸を省略する案は、有限入力専用で exact の場合だけ検討する。
- [ ] `0 * NaN` 等を変える無条件の軸省略は行わない。

#### `twist`

- [ ] projection/min/max pass の後、Rodrigues 式を 1 頂点ずつ出力へ書く候補を測る。
- [ ] world projection range、float64 center、`cross(v, k)` の向き、1e-9 判定を固定する。
- [ ] reduction 順が変わる parallel min/max や合成行列化は行わない。

#### `bold`

- [x] copy-major の 2D/3D view または direct fill で Python copy loop を除く。
- [x] offsets tail を int64 で加算後 int32 化する現行結果を一括生成する。
- [x] RNG の `u` 全件→`v` 全件、最初の原線、budget scratch 算定を維持する。
- [x] broadcast で peak RSS が増える場合は fixed-size chunk にする。

#### `drop`

- [x] canonical な 2 点 line の packed centroid/length と keep mask を一括計算する。
- [x] 同経路の `np.concatenate(list)` を exact-size direct pack に置き換える。
- [x] RNG 値は現行 generator から現行順で先に生成し、一括判定へ渡す。
- [x] mean/length の reduction 順、face index、閾値等号、空 line 除外を固定する。

#### `repeat`

- [ ] 既存の全 copy Numba kernel を control とし、まず変更なしで測る。
- [ ] pure offset / identity scale+rotation の branch specialization を exact 比較する。
- [ ] 十分大きい copy block だけ、独立領域への copy-level `prange` を検討する。
- [ ] interpolation t/curve、float32 center/angle、grid/radial copy 順を固定する。

### 8.2 可変 topology と packed line

#### `collapse`

- [ ] Python/NumPy の line 別 count を packed Numba count/prefix にする。
- [ ] 全 coords の float64 copy を避け、scalar を同じ float64 値として読む候補を試す。
- [ ] theta/cos/sin scratch を同じ RNG 対応のまま bounded chunk 化する。
- [ ] invalid segment、0/1点 line、mask OR 式、segment 順を固定する。

#### `dash`

- [x] packed arc-length/count/fill を試作し、warm と exact differential を評価する。
- [x] `u_pos += pattern` を `k * pattern` へ変えず、累積丸めを維持する。
- [x] warm は約 49〜50%短縮したが compile-cold が 50〜61%悪化したため不採用とする。
- [x] production source/test を immutable baseline と byte 完全一致へ戻す。

#### `extrude`

- [ ] 全 line の subdivision/output count を 1 回で計画し exact-size allocate する。
- [ ] centroid、変換、changed mask、original/extruded/edge の fill を packed kernel 化する。
- [ ] 出力順「全 original → 各 line の extruded + edges」を固定する。
- [ ] `_CONNECT_RTOL/_CONNECT_ATOL`、line<2 除外、clamp diagnostic を固定する。

#### `pixelate`

- [ ] packed line-length kernel→prefix→全 line fill kernel を実装候補にする。
- [ ] 量子化 temporary の融合は half-away と int cast の exact 比較後だけ採用する。
- [ ] vertex cap は超過する最初の line から後続を全て打ち切る現仕様を維持する。
- [ ] Bresenham 分岐、corner 順、Z 補間、空 line skip を固定する。

#### `trim`

- [ ] packed arc-length/count→prefix→fill の 2 pass 化を試す。
- [ ] line ごとの可変配列返却と最終 `pack_polylines` の再 copy を除く。
- [ ] singleton/zero-length、全 line 消滅時の入力返却、diagnostic を固定する。
- [ ] search boundary、補間点重複判定、非対称 allclose 式を固定する。

#### `mirror`

- [x] n=1/2 と n>=3 を別 case、別最適化単位にする。
- [ ] n=1/2 の Python clip を、その数値仕様を再現する packed count/fill へ置換できるか試す。
- [x] n>=3 の 2 段 clip を line 単位呼出しから packed 2-call へまとめる。
- [x] EPS、include-boundary、piece/copy 順、dedup quantization、plane 順を固定する。

#### `mirror3d`

- [x] T/O/I rotation matrix を生成順どおり readonly 3-entry cache にする。
- [x] uniform finite な source pieces×matrix を source-major の exact-size packed transform
      にする。
- [x] dedup key を同じ quantization の `(point_count, bytes)` にできるか exact 比較する。
- [x] clip と transform の順序を交換しない。

#### `clip`

- [x] `np.rint(xy*1000)` 後の tuple 化、連続重複除去、閉点除去を packed 化する。
- [x] pyclipper 出力 path の 3D 復元と pack を一括化する。
- [x] open subject、closed mask、even-odd、`OpenPathsFromPolyTree` 順を固定する。
- [x] pyclipper 本体のアルゴリズムや scale=1000 は変更しない。

#### `buffer`

- [ ] union on/off と Shapely/packing の phase を分離 profile する。
- [ ] safe な場合だけ coordinate conversion と最終 pack の allocation を減らす。
- [ ] union=False の line ごとの basis と buffer call を共通 basis/union へ変えない。
- [ ] Shapely bulk API は geometry、向き、順序が exact の場合だけ採用する。

#### `partition`

- [ ] grouping、sampling、Voronoi、intersection、pack を別 phase で計測する。
- [ ] even-odd grouping に bbox/STRtree prefilter を使う場合も候補を元 index 順に処理する。
- [ ] Shapely bulk intersection は出力 geometry/order が exact の場合だけ採用する。
- [ ] RNG batch、top-up、invalid polygon repair、centroid sort を固定する。

### 8.3 filter、noise、graph

#### `displace`

- [ ] no-gradient / amplitude-gradient-only の `perlin_core` と加算 pass を融合する。
- [ ] noise を現行どおり float32 へ丸めてから amplitude を掛ける。
- [ ] 十分大きな入力だけ vertex-level `prange` を試す。
- [ ] +0/+100/+200 位相、fastmath、gradient clamp/profile、0*NaN を固定する。

#### `lowpass` / `highpass`

- [x] shared resample 後の全 line convolution を packed 1-call kernel にする。
- [x] line ごとの filtered temporary をなくし、最終 output slice へ直接書く。
- [ ] reflect index の整数写像化は現行 while と exhaustive exact 比較後だけ採用する。
- [ ] FFT/IIR/近似 kernel、weight 加算順変更は行わない。
- [ ] closed line は末尾を除いて filter し、最後に先頭を複写する規則を固定する。

#### `relax`

- [x] topology build と iteration を分けて profile する。
- [x] node/edge/adjacency/visited の Python scalar 変換を一括 list 化し、
      first-occurrence、edge sort、DFS 順を維持する。
- [x] 各 list fast path に推定 scratch 8 MiB 上限を設け、超過時は baseline の
      ndarray scalar scan へ戻す。
- [ ] forces を 1 回確保し iteration ごとに同じ順で zero fill する。
- [x] -0.0、NaN、node order、sorted edge、DFS stack、tie、force 加算順を固定する。

#### `weave`

- [ ] candidate loop 内の固定 scratch と relaxation forces を 1 回確保して再利用する。
- [ ] graph adjacency を出力順を保つ CSR にできるか検証する。
- [ ] spatial index を導入する場合、候補 edge を元 edge id 順へ戻してから判定する。
- [ ] pseudo-random 式、2 attempts、最小 t の 2 交点、max_int=20、split/append 順、
      chain/cycle 順を固定する。
- [ ] intersection/force の fastmath・加算順を変更しない。

### 8.4 grid、距離場、simulation

#### `warp`

- [x] lens 専用 distance-only kernel を作り、未使用の gx/gy 計算と配列を除く。
- [x] ring AABB の距離下界が現在の最短距離以上なら、distance 用 segment 走査だけを
      exact に skip する。inside parity に必要な走査は残す。
- [x] lens/attract 後処理を output へ直接書き、一時配列を減らす。
- [x] lens は local z=0、attract は aligned z 維持という現行差を固定する。
- [x] extras、early-return identity、band/profile/swirl を固定する。

#### `metaball`

- [x] cell/row 間が独立な field kernel の `prange` を最優先で試す。
- [x] segment dx/dy/denom 等を現行式で前計算し、cell 内の ring/segment 加算順は維持する。
- [x] serial/parallel の crossover と thread 数別 exact checksum を固定する。
- [x] Gaussian の遠距離寄与を radius で切る近似、final ring/grid 簡略化は行わない。
- [x] draft の簡略化、diagnostic、Marching Squares、exterior filter を固定する。

#### `isocontour`

- [ ] EDT、sin field、Marching Squares count/fill/stitch、3D pack を別々に profile する。
- [ ] EDT の独立 row/column、Marching Squares の row count/prefix/fill の
      order-preserving parallel 化を候補にする。
- [ ] loop の 3D 復元と pack を一括化する。
- [ ] SDF 符号、gamma、sin level、sample range、ambiguous case、loop 順を固定する。

#### `reaction_diffusion`

- [x] domain の active cell と 4 neighbor state bits を simulation 前に 1 回構築する。
- [ ] occupancy により dense row kernel と sparse active-cell kernel を選ぶ。
- [x] mask 外の定数値を ping-pong buffer へ 1 回初期化し、毎 step の書込みを省く。
- [x] cell 間だけ `prange` 化し、step ごとの barrier と cell 内演算順を維持する。
- [x] noflux/dirichlet、float32 ping-pong、clamp、noise、blob、draft budget/relocationを
      iteration snapshot と最終 checksum の両方で固定する。

#### `growth`

- [x] point 挿入が 1 segment 1 point のままなら ring 再構築を省く。
- [x] prev/next を全点 Python loop ではなく連続 index と ring 端補正で構築する。
- [ ] simulation 中は packed points/ring_offsets を正本とし、不要な
      list↔packed 変換を除く。
- [ ] topology 不変 iteration では prev/next を再利用する。
- [ ] forces、spatial hash、SDF sample、boundary 用 scratch を bounded 再利用する。
- [ ] SDF sample と boundary constraint の一時配列を減らせるか測る。
- [x] force 加算順を変える並列化、近似近傍、point insertion 順変更は行わない。
- [x] RNG、ring 順、per-ring/global budget、draft/final diagnostic を iteration ごとに固定する。

## 9. 共有 `util.py` の扱い

対象 effect は `PlanarFrame`、ring extraction、GridSpec、scanline mask、EDT、
Marching Squares、resample を共有する。

- [ ] helper 単体 benchmark と全 consumer の end-to-end benchmark を両方通す。
- [ ] helper の最適化 1 件を独立した変更単位にする。
- [ ] `PlanarFrame` の origin/u/v、rank/status、closure tolerance を exact 比較する。
- [ ] scanline/marching の row-major 順と ambiguous case を固定する。
- [ ] resample の open/closed count、cap、閉鎖点を固定する。
- [ ] `buffer` / `partition` 独自 plane basis を、性能だけを理由に `util.py` へ
      安易に統合しない。basis の数値仕様が exact に違うためである。
- [ ] 共有 helper 変更後は除外 5 件を含む全 effect test も実行する。

## 10. 回帰テスト計画

### 10.1 共通 characterization

- [ ] empty geometry、offsets が `[0]`、0/1/2 点 line、空 line を含む packed geometry
- [ ] one-long-line、many-short-lines、many-rings、複数 input
- [ ] open/closed、厳密閉鎖/近似閉鎖、重複点、zero-length segment
- [ ] C/F contiguous、strided、readonly、ndarray subclass
- [ ] NaN payload、Inf、signed zero、subnormal、overflow/underflow
- [ ] `np.nextafter` による 0、±0.5、EPS、planarity、closure、cap 境界
- [ ] invalid choice の direct-call no-op/ValueError と `E.*` eager validation の違い
- [ ] diagnostic、warning、exception、input bytes、identity、alias
- [ ] resource/grid/vertex/iteration limit の直前・一致・1 超過

### 10.2 differential 規模

- [ ] 座標変換/量子化系: 固定 seed で 20,000 case
- [ ] line/topology/selection 系: 固定 seed で 5,000 case
- [ ] RNG effect: seed 0..255 と parameter 2,000 case
- [ ] planar/external geometry 系: mode 別 1,000 small case
- [ ] grid/simulation 系: end-to-end small 256 case、kernel/grid helper 10,000 case
- [ ] Numba kernel: compiled / `.py_func` / `NUMBA_DISABLE_JIT=1` の可能な経路
- [ ] thread 数 1 / 2 / 4 の exact output

重い fuzz/soak/full suite は repository の Ask-first 方針に従い、実行直前に許可を取る。

### 10.3 effect 固有の最低追加項目

- [ ] `bold/collapse/dash/drop/partition/growth/reaction_diffusion/weave`: RNG golden
- [ ] `buffer/clip/partition`: backend version、穴、退化、出力順
- [ ] `extrude/relax/trim/weave/growth`: diagnostic 全 field と順序
- [ ] `lowpass/highpass`: open/closed exact coefficient、resample/kernel cap
- [ ] `mirror/mirror3d`: clip 交点、boundary dedup、source side、plane 順
- [ ] `pixelate/quantize`: half tie、signed zero、cap 打切り
- [ ] `isocontour/metaball/reaction_diffusion/growth`: draft/final 別 checksum
- [ ] `warp`: lens 4 kind×2 profile、attract/repel、extras 順
- [ ] `affine/displace/twist/wobble`: offsets identity、input 不変、IEEE

## 11. 実装順

### Phase 0: benchmark と oracle

- [x] immutable baseline、manifest、dependency fingerprint を作る。
- [x] evaluator timing と観測を分離する。
- [x] `effects-remaining` suite と actual-work fixture/contract を追加する。
- [x] 27 件全ての before warm 値を取得する。
- [x] Numba、Shapely、pyclipper、cache 候補の process/compile-cold を取得する。
- [x] phase profile から正式 P0/P1/control を決め、計画書へ実測値を追記する。

### Phase 1: correctness を先に固定

- [ ] 共通 characterization と baseline subprocess comparison を追加する。
- [ ] 各 effect の不足 branch、RNG、diagnostic、cap test を追加する。
- [x] actual-work expected checksum を frozen hard contract にする。
- [x] 実装変更前に対象 test と full effect test を成功させる。

### Phase 2: 低リスクな allocation/dispatch 削減

- [x] `mirror3d` bounded matrix cache と packed transform/dedup
- [x] `dash` arc-length reuse を試作・検証し、compile-cold gate で不採用・baseline 復帰
- [x] `lowpass/highpass` packed convolution
- [x] `drop` の canonical 2-point packed selection/direct pack
- [x] `extrude` packed 候補を試作・検証し、compile-cold と many-lines gate で不採用・
      baseline 復帰
- [ ] `pixelate/trim` packed count/fill
- [x] `bold` copy/offset pack
- [ ] `affine/quantize/twist/wobble` は crossover と exact が成立するものだけ

1 effect または 1 shared helper を 1 変更単位とし、毎回 differential、target test、
before/after を通してから次へ進む。

### Phase 3: graph、mirror、noise

- [ ] `collapse` packed count/scratch
- [x] `mirror` n>=3 packed clip、`mirror3d` packed transform/dedup
- [ ] `displace` Perlin+add fusion
- [x] `relax` bounded topology list conversion
- [ ] `weave` scratch/graph。spatial index は exact の場合だけ
- [ ] `repeat` は control。測定で必要な specialization だけ

### Phase 4: heavy field/simulation

- [x] `warp` distance-only と exact pruning
- [x] `metaball` cell parallel と segment invariant
- [ ] `isocontour` EDT/Marching Squares の order-preserving 改善
- [x] `reaction_diffusion` active-neighbor state と bounded row parallel
- [x] `growth` no-insertion reuse と prev/next vector build

各 iteration 系は最終出力だけでなく、固定 iteration 番号の中間 snapshot を比較する。

### Phase 5: external geometry

- [x] `clip` conversion/pack
- [ ] `buffer` conversion/pack。Shapely 支配なら実装変更なし
- [ ] `partition` grouping/intersection。backend 出力が exact の場合だけ

external backend 自体を別アルゴリズムへ置換しない。

### Phase 6: 統合検証

- [x] 全 27 件・33 case の短時間 after warm run を取得する。
- [x] process-cold / compile-cold と isolated one-call resource audit を取得する。
- [x] 短時間 A1→C1→A2→C2 と environment/case compatibility を確認する。
- [x] 対象 test、全 effect test、対象 Ruff/Mypy、`git diff --check` を実行する。
- [x] full pytest を実行する。
- [x] formal long ABAB を single-thread 全33 caseと production 10-thread 代表5 caseで
      実行する。
- [x] 各 effect の採用/不採用、未変更理由、tradeoff、短時間最終値を本計画へ記録する。

## 12. 正式計測コマンド

Phase 0 の suite 実装後、base/head で同じ command と case source を使う。

```bash
PY=/opt/anaconda3/envs/gl5/bin/python
OUT=/tmp/grafix-remaining-effects

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
export NUMBA_NUM_THREADS=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMBA_CACHE_DIR=/tmp/grafix-remaining-effects-numba

PYTHONPATH=src "$PY" -m grafix benchmark run \
  --suite effects-remaining \
  --profile long \
  --mode warm \
  --disable-gc \
  --seed 20260719 \
  --timeout 1200 \
  --run-id remaining-effects-before-warm-A1 \
  --out "$OUT"
```

process-cold は Shapely/pyclipper、`mirror3d` cache、代表 Numba case を明示選択する。
compile-cold は新規/変更 Numba kernel の case だけを空の専用 cache で実行する。

正式 compare は environment compatibility を崩さないよう、base/head で同じ文字列の
`NUMBA_CACHE_DIR` を使う。base/head は絶対 source path が異なるため、Numba の
module locator が作る cache directory は同じ root 内でも分離される。compile-cold
は runner が case/process ごとの空 cache を作る。各 source の A1/A2 または B1/B2
では同じ cache 状態を再現する。production thread profile は single-thread profile
と別 artifact にする。

## 13. 最終検証コマンド

```bash
PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-remaining-effects-tests \
NUMBA_NUM_THREADS=1 \
PYTHONPATH=src \
/opt/anaconda3/envs/gl5/bin/python -m pytest -q -p no:cacheprovider \
  tests/core/effects \
  tests/core/test_effect_bold.py \
  tests/core/test_effect_extrude.py \
  tests/core/test_effect_wobble.py \
  tests/core/test_effect_bypass.py \
  tests/core/test_operation_diagnostics.py \
  tests/core/test_preview_quality.py \
  tests/core/test_resource_budget.py \
  tests/core/test_silent_degradation_diagnostics.py \
  tests/core/test_lazy_builtins.py \
  tests/api/test_operation_argument_validation.py \
  tests/api/test_operation_catalog.py \
  tests/devtools/benchmarks/test_effect_benchmark.py \
  tests/stubs/test_api_stub_sync.py

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-remaining-effects-full \
NUMBA_NUM_THREADS=1 \
PYTHONPATH=src \
/opt/anaconda3/envs/gl5/bin/python -m pytest -q -p no:cacheprovider

/opt/anaconda3/envs/gl5/bin/python -m ruff check \
  src/grafix/core/effects \
  src/grafix/devtools/benchmarks \
  tests/core/effects \
  tests/devtools/benchmarks/test_effect_benchmark.py

/opt/anaconda3/envs/gl5/bin/python -m mypy src/grafix/core/effects
git diff --check
```

full pytest、長い differential、cold、ABAB は長時間実行に当たるため、実行前に
repository の Ask-first 方針に従う。

## 14. 変更予定範囲

benchmark / environment:

- `src/grafix/devtools/benchmarks/cases.py`
- `src/grafix/devtools/benchmarks/runner.py`
- `src/grafix/devtools/benchmarks/environment.py`
- 必要最小限の benchmark schema/lifecycle
- `tests/devtools/benchmarks/test_effect_benchmark.py`
- environment compatibility test

correctness:

- `tests/core/effects/`
- `tests/core/test_effect_bold.py`
- `tests/core/test_effect_extrude.py`
- `tests/core/test_effect_wobble.py`
- test-only baseline/differential helper

production:

- `src/grafix/core/effects/` のうち性能・正しさ gate を通過した effect だけ
- `src/grafix/core/effects/util.py` は共有 helper 改善が全 consumer の gate を
  通過した場合だけ

公開 API、stub、metadata の変更は予定しない。実測で変更不要と判断した effect は
production file を変更せず、benchmark/test/本計画へ結果だけを残す。

## 15. 停止・不採用条件

次の場合は複雑な代案へ進まず、その変更を不採用として記録する。

- exact geometry、topology、順序、identity、alias が変わる。
- warning、diagnostic、exception、RNG、resource budget が変わる。
- 許容誤差、compatibility shim、旧/new 二重実装で差を隠す必要がある。
- benchmark が no-op、guard、checksum/metrics の時間を測っている。
- helper は速いが end-to-end 改善が noise 内である。
- small/p95/process-cold/compile-cold/RSS の悪化が採用条件を超える。
- cache または scratch の上限を説明できない。
- approximate spatial/grid/field algorithm が final 品質へ混入する。
- force/RNG/reduction 順が変わる並列化しか改善案がない。
- external backend version/order の違いを Grafix の高速化と誤認する。
- 全体 test の失敗を今回変更と既存の並行差分で区別できない。

## 16. 完了時に記録する内容

- 全 27 effect の primary/secondary case と actual-work contract
- before/after median、MAD、p95、p99、max、ratio
- warm / process-cold / compile-cold、thread 数の区別
- exact checksum、diagnostic、warning、exception、identity contract
- peak RSS、scratch、cache entry/bytes
- target/full test、Ruff、Mypy、`git diff --check`
- production 実装を変更しなかった effect と理由
- 不採用案、既知 tradeoff、残課題
- baseline source manifest と environment fingerprint

## 17. 実施記録

### 17.1 Phase 0 baseline と oracle

2026-07-19 に次を固定した。

- immutable source:
  `/tmp/grafix-remaining-effects-baseline-20260719`
- harness overlay:
  `/tmp/grafix-remaining-effects-baseline-harness`
- HEAD:
  `cc484fae49b80b3d9a22a3625226336dd3042093`
- 実装開始時の対象 dirty diff SHA-256:
  `c1bfde18e6afc1f31850abc71f4ed7d58ee04e654450d5cddf213246c12fcd3f`
- effect/benchmark/test 96 file manifest SHA-256:
  `e9adc4af453d34db83b33f3e8cf6bf158742caf991692d286154c47afbb5294f`
- baseline source は読み取り専用とし、baseline/candidate で別
  `NUMBA_CACHE_DIR` を使用する。

`effects-remaining` は 27 effect、33 case を持つ。30 primary case（heavy 3 件は
draft/final）に加え、packed line 改善の回帰を観測する `dash`、`lowpass`、
`highpass` の many-short-lines secondary case を 3 件置く。
全 case で immutable baseline の geometry checksum、diagnostic、warning、
layout/writeability、identity/alias を frozen hard contract にした。入力 mutation、
packed dtype/shape、offsets、actual-work、同一 process 内の再実行決定性も hard
contract で検査する。effect と `util.py` の source SHA-256 は結果 metric に記録する。

environment fingerprint で確認した backend は次のとおり。

| dependency/backend | version |
| --- | --- |
| Grafix | 0.0.6 |
| NumPy | 2.3.5 |
| Numba | 0.63.1 |
| Shapely | 2.1.2 |
| GEOS | 3.13.1 |
| pyclipper | 1.4.0 |

実装前の full effect test は `276 passed`。benchmark lifecycle、actual-work、
backend fingerprint を含む対象 test は `50 passed`。

### 17.2 実装前 warm profile と優先度

single-thread、GC off、seed `20260719` で当初の全 30 primary case の
evaluator-only warm を取得した。
fresh-process smoke artifact は
`/tmp/grafix-remaining-effects/runs/remaining-effects-before-smoke-A1.json` で、
当時の 30/30 case が hard contract を通過した。その後追加した secondary 3 case
にも immutable baseline の hard contract を固定済みであり、正式比較では同一
33-case harness を baseline/candidate の両方に重ねる。以下は smoke median であり、最終採用値は
long profile の ABAB で更新する。

同一 33-case harness を immutable baseline に重ねた正式 smoke A1 は
`/tmp/grafix-remaining-effects-formal/runs/remaining-effects-before-smoke-33-A1.json`
へ保存し、33/33 case が hard contract を通過した。この時点の benchmark source
SHA-256 は `remaining_effect_benchmark.py` が
`f56e7291a26bfcac89e970b1f1f99f69c1b29313a654b15610f216903adbc561`、
`runner.py` が
`fb07148992acaff21b9f8ac687a30686d82563e7a97901ba25ba34324295d8d5` である。

| 優先度 | case | before median |
| --- | --- | ---: |
| P0 | mirror3d / I group / 5k lines | 388.733 ms |
| P0 | reaction_diffusion / final | 355.339 ms |
| P0 | metaball / final | 208.031 ms |
| P0 | warp / binary long mask | 73.227 ms |
| P0 | clip / binary mask | 65.712 ms |
| P1 | reaction_diffusion / draft | 44.898 ms |
| P1 | drop / many lines | 21.171 ms |
| P1 | growth / final | 20.411 ms |
| P1 | metaball / draft | 17.805 ms |
| P1 | mirror / many lines | 14.069 ms |
| P1 | extrude / long line | 13.062 ms |
| P1 | relax / shared network | 12.429 ms |

baseline が 1 ms 未満の `wobble`、`bold`、`lowpass`、`highpass`、`trim`、
`repeat`、`dash` は primary control とする。別の many-short-lines secondary が
明確に遅い場合だけ、その形状に対する共有/packed 改善を採用する。

external/cache 4 case の process-cold smoke は
`remaining-effects-before-process-cold-smoke.json`、Numba 19 case の isolated empty
cache 1-sample compile-cold は
`remaining-effects-before-compile-cold-smoke.json` に保存し、全 case が hard
contract を通過した。compile-cold は約 0.50–3.46 s であり、新しい JIT kernel の
追加はこの初回費用を上回る明確な warm 改善がある場合だけ採用する。

33-case harness 固定後の対応 artifact は
`remaining-effects-before-process-cold-33-A1.json`（4/4）と
`remaining-effects-before-compile-cold-33-A1.json`（secondary を含む 22/22）で、
いずれも `/tmp/grafix-remaining-effects-formal/runs/` に保存し、全 hard contract
が通過した。

### 17.3 採用候補の中間実施記録

以下は候補ごとの staged 測定である。後続の resource audit と formal v2 で実装を
追加修正しているため、最終採否・数値は 17.4 以降を正本とする。

- `mirror3d`
  - T/O/I 回転行列を readonly、最大 3 entry の cache にした。
  - dedup key を同じ量子化の `(point_count, bytes)` にした。
  - 15 differential case と全 96 rotation matrix が baseline と exact 一致。
  - I group warm matrix 生成は約 702 倍、128-line end-to-end warm は約 19%改善。
- `lowpass` / `highpass`
  - 全 line の convolution を packed 1-call kernel にし、line ごとの dispatcher と
    filtered temporary を除いた。
  - 5,000 geometry × 2 effect の 10,000 differential run が exact 一致。
  - 5,000 lines × 8 vertices では lowpass 23.8%、highpass 24.8%短縮。
  - FFT/IIR、反射 index の算術化、weight/reduction 順変更は不採用。
- `dash`（試作後に不採用）
  - packed arc-length/count/fill の試作は baseline 243 case と大型 7 caseで
    bitwise exact、warm は約 49〜50%短縮した。
  - 一方、empty-cache compile-cold が繰り返し 50〜61%悪化し、15% gate を超えた。
  - production source と専用 test は immutable baseline と byte 完全一致へ戻した。
- `bold`
  - count 8 以上の標準 finite packed 入力で copies 倍の float64 temporary をなくし、
    float64 ufunc 加算から float32 output へ direct pack した。
  - 3,287 differential case が geometry、warning/exception、RNG、identity を含め exact。
  - 5,000 lines / count 10 は約 39%、50,000 lines は約 20.5%短縮。
  - isolated RSS 増分は約 56%減り、process-cold は 0.8%悪化で gate 内。
- `drop`
  - 64 本以上の canonical finite 2-point packed line を対象に、centroid/length、
    interval/probability 判定、exact-size pack を一括化した。
  - mixed/empty/face/非標準配列は従来経路へ戻し、5,000 differential case と
    seed 0..255 が geometry、RNG draw 順、warning/exception、identity を含め exact。
  - 5,000 lines の actual-work case は 20.558 ms から 0.427 ms
    （97.9%短縮、約 48.2 倍）。small/face control と process-cold に回帰なし。
- `clip`
  - 32 path 以上の有限 packed 入力だけ、scale=1000 の量子化、連続重複除去、
    pyclipper 出力の world 復元と pack を入力/出力順どおり一括化した。
  - pyclipper 1.4.0 の `Execute2`、even-odd、open/closed path、出力順は変更していない。
    4,788 differential case が量子化 half 境界、tilted/hole/degenerate、NaN、
    errstate、非標準配列、warning/exception/identity を含め exact。
  - primary の 87.0% は変更禁止の pyclipper backend であり、backend を変えない
    理論上限は約 13%。非 backend 部分を約 86%短縮し、inside primary は
    10〜11%、outside は 15〜16%、process-cold は 10.5%改善した。P0 の絶対 20%
    には Amdahl 上届かないため、backend 改変で数値を追わず、この bounded
    conversion 改善だけを採用した。isolated RSS 増分は 6.0%で gate 内。
- `warp`
  - lens だけを distance/parity 専用 kernel に分け、edge invariant を 1 回構築し、
    ring/edge AABB 下界で結果へ影響しない距離計算だけを skip した。parity 走査、
    attract/repel、local z、extras は従来どおりである。
  - 31 scenario × threads 1/2/4、random 80 case、primary 50k vertices が immutable
    baseline と bitwise 一致。4 kind × 2 profile、hole/degenerate/tie、NaN/Inf、
    layout、diagnostic/warning/identity を含む。
  - formal smoke は 73.163 ms から 56.312 ms（23.0%短縮）。詳細 staged profile は
    73.863 ms から 55.086 ms（25.4%短縮）で、small は 0.7%改善。
    compile-cold は 5.5〜8.2%増で gate 内、process-cold は 0.48 s から 0.41 s、
    RSS は約 2.7%減った。
- `metaball`
  - segment の ax/ay/dx/dy/denom を ring/segment 順のまま 1 回 packし、
    row→ring→segment→cell に loop interchange した。固定 cell から見た ring 加算、
    segment 比較、式の順序は不変で、2 thread 以上だけ row `prange` を使う。
  - direct field 2,500 random case と end-to-end 336 case を threads 1/2/4 で
    immutable baseline と exact 比較し、draft/final checksum、diagnostic/error、
    tilted/degenerate/signed-zero/非標準配列も一致。
  - formal 1-thread ABAB は final が 200.971→94.231 ms と
    201.962→94.449 ms（53.1〜53.2%短縮）、draft が約 49%短縮。
    final は threads 1/2/4 で 97.744/50.604/26.738 ms。
  - compile-cold は ABAB 中央で 0.6%改善、process-cold は 35〜39%改善。
    warm/process-cold RSS も 2〜6%減り、全 cold/RSS gate を通過した。
- `reaction_diffusion`
  - serial は mask 外の定数を両 ping-pong buffer へ 1 回だけ書く。65,536 cells、
    8 steps、2 threads 以上の有限入力では active/4-neighbor state bits を前計算し、
    step barrier を保つ row `prange` kernel を遅延 dispatch する。小規模、1 thread、
    非有限入力は serial のままである。
  - randomized kernel 10,000 case、parallel threads 1/2/4 各 1,000 case、
    noflux/dirichlet iteration snapshot、draft/final 13 hard contracts が baseline と
    bitwise 一致。RNG、diagnostic、dtype/strides、入力不変も一致した。
  - production 10 threads の final は 344.547 ms から 161.642 ms
    （53.1%短縮）。kernel 単体は threads 2/4/10 で 38/57/61%短縮した。
    1-thread end-to-end は複数 smoke で -7%〜+1.3%の範囲にあり、実質中立。
  - parallel kernel は対象 branch まで compile せず、1-thread compile-cold を増やさない。
    absolute RSS は 1 thread +2.0%、10 threads +9.5%で gate 内。active-index sparse
    候補は遅かったため不採用とした。
- `growth`
  - point 分割数が全 segment で 1 の iteration は ring を再構築せず、prev/next は
    連続 `arange` と ring 端だけの補正で作る。force、RNG、挿入順、ring 順、
    iteration/work budget は変更していない。
  - immutable baseline との end-to-end 256 case、slide/bounce、iteration 1/9/64、
    draft/final snapshot、diagnostic/warning/exception/identity が bitwise 一致し、
    draft/final 各 13 hard contracts を通過した。
  - formal smoke は final 19.494→10.424 ms（46.5%短縮）、draft
    9.115→5.440 ms（40.3%短縮）。empty-cache 初回は 2.2%増で gate 内、
    process wall/RSS は回帰なし。

### 17.4 formal v2 harness と hard contract

resource audit 後の最終比較には
`/tmp/grafix-remaining-effects-formal-v2/` の artifact を使った。baseline effect
source は immutable のまま、同一 harness を baseline/candidate へ重ねている。

| file | SHA-256 |
| --- | --- |
| `remaining_effect_benchmark.py` | `bf15e7d46d9459c7cbba3798b3cf59b8d2af2538539201f410f254e8a404f110` |
| `runner.py` | `fb07148992acaff21b9f8ac687a30686d82563e7a97901ba25ba34324295d8d5` |
| `environment.py` | `32b90bff91c492ef12ce6ece3f070d09dd3d5fedc495e65f2deebd1af16f86ee` |

33 case 全てに immutable baseline 由来の expected checksum、diagnostic、warning、
layout、alias を固定した。入力 snapshot は raw bytes に加えて dtype、shape、
strides、C/F contiguous、writeability、`OWNDATA`、alignment を持つ。出力 layout
も同じ属性を持ち、alias は `shares_memory` だけでなく
`coords is input.coords` / `offsets is input.offsets` を別々に検査する。
タイマーは evaluator のみを囲み、postprocess、checksum、metrics、contract 判定は
停止後に行う。

最終 smoke の A1→C1、A2→C2 はいずれも次を満たした。

- environment compatible
- 33/33 status `ok`
- 33/33 exact checksum 一致
- 33/33 hard contract 通過
- compare warning なし
- `--allow-incompatible` 不使用

### 17.5 最終候補の短時間 formal warm 結果

次は single-thread、evaluator-only の smoke median である。短時間 artifact なので
p95/MAD を含む正式な性能確定は long ABAB 後に行うが、staged differential と
cold/resource gate を通過した 12 effect を production 候補として残した。
最終性能の正本は 17.10 の long ABAB とする。

| effect / case | A1→C1 median | A2→C2 median | 短縮率 |
| --- | ---: | ---: | ---: |
| `bold` many-lines | 0.508→0.327 ms | 0.450→0.335 ms | 25.5〜35.5% |
| `clip` binary-mask | 59.601→52.671 ms | 61.870→54.207 ms | 11.6〜12.4% |
| `drop` many-lines | 20.240→0.428 ms | 19.623→0.425 ms | 97.8〜97.9% |
| `growth` draft | 9.146→5.248 ms | 9.254→5.444 ms | 41.2〜42.6% |
| `growth` final | 18.874→9.956 ms | 19.086→10.053 ms | 47.3% |
| `highpass` many-lines | 16.047→12.285 ms | 16.077→11.776 ms | 23.4〜26.8% |
| `lowpass` many-lines | 15.829→12.207 ms | 16.024→11.841 ms | 22.9〜26.1% |
| `metaball` draft | 16.988→9.112 ms | 16.980→8.676 ms | 46.4〜48.9% |
| `metaball` final | 200.537→93.025 ms | 202.414→94.210 ms | 53.5〜53.6% |
| `mirror` many-lines | 13.369→3.617 ms | 13.668→3.777 ms | 72.4〜72.9% |
| `mirror3d` I-group | 353.591→146.065 ms | 355.502→143.632 ms | 58.7〜59.6% |
| `reaction_diffusion` final、1 thread | 348.569→333.882 ms | 347.008→336.257 ms | 3.1〜4.2% |
| `relax` shared-network | 12.340→6.270 ms | 12.491→6.421 ms | 48.6〜49.2% |
| `warp` binary-mask | 72.406→55.534 ms | 72.690→54.769 ms | 23.3〜24.7% |

`lowpass/highpass` の one-long-line は -4.0〜+2.7% の範囲で実質中立であり、
many-lines の dispatcher/allocation 削減が主効果である。
`reaction_diffusion` は single-thread を非回帰 profile とし、production 10 threads
の final は 53.1%短縮した。`clip` は時間の約 87%を変更禁止の pyclipper が占め、
非 backend 部分を約 86%短縮した結果であるため、P0 の一律 20%ではなく
Amdahl 上限を明示した安全な例外として採用した。

formal artifact:

- baseline warm:
  `runs/remaining-effects-v2-before-smoke-{A1,A2}.json`
- candidate warm:
  `runs/remaining-effects-v2-after-final-smoke-{C1,C2}.json`
- compare:
  `compare-final-smoke-{A1-C1,A2-C2}.json`

### 17.6 全 27 effect の採否

「未変更」も、同一 harness で actual-work と hard contract を測った完了結果である。

| effect | 採否 | 最終判断 |
| --- | --- | --- |
| `affine` | 未変更 | 約 2.2 ms。演算結合順を保つ fused 案の cold/複雑性に見合う安全な改善なし。 |
| `bold` | 採用 | finite canonical、count≥8 の direct pack。RNG、warning、出力順を exact 維持。 |
| `buffer` | 未変更 | 約 3 msで Shapely backend 支配。basis/geometry 順を変えず有意な改善なし。 |
| `clip` | 採用 | bounded packed path conversion/world pack。pyclipper、scale、even-odd は不変。 |
| `collapse` | 未変更 | 約 4 ms。RNG scratch と segment 対応を exact に保つ変更の利得が不足。 |
| `dash` | 不採用・復帰 | warm 約 49〜50%短縮の試作は compile-cold 50〜61%悪化。source/test を baseline 復帰。 |
| `displace` | 未変更 | 約 2.3 ms。Perlin の float32丸め/位相/parallel exact risk に見合う利得なし。 |
| `drop` | 採用 | 64〜32,768 本の finite canonical 2-point line を packed selection/direct pack。 |
| `extrude` | 不採用・復帰 | fused 試作は warm 約 35%短縮したが compile-cold 36〜43%悪化し many-lines も回帰。 |
| `growth` | 採用 | no-insertion ring reuse と prev/next vector build。force/RNG/iteration 順は不変。 |
| `highpass` | 採用 | resample 後の packed one-call convolution と direct output。 |
| `isocontour` | 未変更 | 約 5 ms。EDT/Marching Squares の順序を変えない安全な利得が不足。 |
| `lowpass` | 採用 | resample 後の packed one-call convolution と direct output。 |
| `metaball` | 採用 | bounded segment invariant/row scratch と worker-local parallel row。近似なし。 |
| `mirror` | 採用 | n≥3 の half-plane clip を packed 2-call 化。n=1/2 の数値仕様は変更なし。 |
| `mirror3d` | 採用 | readonly 3-entry group cache、uniform finite packed transform/dedup。 |
| `partition` | 未変更 | 約 4.9 ms。Shapely/Voronoi と RNG/order を保つ改善が不足。 |
| `pixelate` | 未変更 | 約 1.1 msの control。専用 fast path の複雑性に見合わない。 |
| `quantize` | 未変更 | 約 1.0 msの control。JIT cold と IEEE 境界 risk に見合わない。 |
| `reaction_diffusion` | 採用 | outside 初期化の一回化と、大規模・複数 thread だけ active-neighbor parallel。 |
| `relax` | 採用 | topology の Python list 一括変換。全経路を 8 MiB scratch cap で制限。 |
| `repeat` | 未変更 | 既に packed kernel、約 0.22 ms。 |
| `trim` | 未変更 | 約 0.22 msの control。 |
| `twist` | 未変更 | 約 2.8 ms。Rodrigues 演算順を保つ fused/cold 案の利得が不足。 |
| `warp` | 採用 | lens distance-only、exact AABB pruning、direct postprocess。 |
| `weave` | 未変更 | 約 1.7 ms。topology/trace 順を変えない高速化の利得が不足。 |
| `wobble` | 未変更 | 1 ms未満の control。専用 JITを追加しない。 |

production effect source を immutable baseline と比較すると、差があるのは
`bold, clip, drop, growth, highpass, lowpass, metaball, mirror, mirror3d,
reaction_diffusion, relax, warp` の 12 file だけである。`dash.py`、
`test_dash.py`、`extrude.py` は `cmp` で baseline と byte 完全一致した。

### 17.7 resource audit と bounded fallback

warm benchmark の `ru_maxrss` は process 生存期間中の high-water mark であり、
warmup/前 case の peak を引き継ぐ。また evaluator の出力を観測まで保持するため、
巨大入力で「1回の候補 scratch 増分」だけを分離できない。この値を単独の採否根拠に
せず、fresh process で setup 後の actual-work を一度だけ実行する isolated audit を
正本とした。

初期候補では大規模 adversarial case に、概算で `relax` 131→369 MiB、
`clip` 185→310 MiB、`metaball` 169→262 MiB、`drop` 121→203 MiB、
`warp` 453→501 MiB、`dash` は約 +27 MiB の peak 増加が見つかった。
そこで次の上限と baseline fallback を追加し、unbounded scratch を残さなかった。

| effect | resource gate |
| --- | --- |
| `clip` | total vertices≤16,384、lines≤4,096。追加 scratch 見積り約 7 MiB。 |
| `drop` | fast path は 64〜32,768 lines。範囲外は line-wise baseline。 |
| `metaball` | packed path は grid points≥256、segment scratch≤8 MiB、row scratch≤8 MiB。超過時は cell→ring→segment baseline。parallel は worker-local 1 row。 |
| `relax` | nodes/edges/adjacency/visited の各 Python list scratch≤8 MiB。超過時は ndarray scalar scan。 |
| `warp` | base points≥256、work≥100,000、edge scratch 56 byte/segment かつ≤8 MiB。範囲外は full SDF baseline。 |
| `mirror3d` | T/O/I の readonly LRU cache は最大 3 entry。 |
| `dash` | resource と compile-cold の両 gateを満たさないため試作全体を撤回。 |

cap 直前/直後、fallback、巨大 duplicate network、tiny-base/huge-mask、thread
1/2/4 を対象 test と subprocess differential で確認した。

### 17.8 cold 検証

process-cold の final compare は 4/4 compatible、checksum exact、hard contract 通過で、
`buffer` と `partition` は各 1.4%悪化、`clip` は 7.9%短縮、`mirror3d` は
57.5%短縮だった。全て 10% gate 内である。

compile-cold は A1→C1 / A2→C2 の 22/22 case が compatible、checksum exact、
hard contract 通過だった。採用変更の主な変化は次のとおりで、全て 15% gate 内である。

- `lowpass/highpass`: 2.7〜9.2%悪化
- `metaball`: 3.4〜8.6%悪化
- `mirror`: 2.7〜3.8%悪化
- `reaction_diffusion`: 1.5〜5.0%悪化
- `relax`: -2.9〜+1.8%の範囲
- `warp`: 20.7〜20.9%短縮
- baseline 復帰後の `dash`: -0.9〜+1.9%の測定揺れ

artifact:

- process-cold:
  `runs/remaining-effects-v2-{before-process-cold-A1,after-final-process-cold-C1}.json`
  と `compare-final-process-cold-A1-C1.json`
- compile-cold:
  `runs/remaining-effects-v2-{before-compile-cold-A1,before-compile-cold-A2,
  after-final-compile-cold-C1,after-final-compile-cold-C2}.json`
  と `compare-final-compile-cold-{A1-C1,A2-C2}.json`

### 17.9 統合検証と残作業

resource gate 修正と `dash/extrude` 復帰後に、対象 effect、API、diagnostic、
resource、benchmark、stub の統合 suite を実行した。

```text
463 passed in 8.43s
```

追加で次を確認した。

- 対象 production/test/benchmark の `ruff check`: 成功
- 対象 production/benchmark 15 file の Mypy: `Success: no issues found`
- `git diff --check`: 成功
- formal v2 benchmark source SHA-256: frozen 値と一致
- immutable baseline と異なる production effect: 採用 12 file だけ

ユーザー承認後、formal long ABAB と repository 全体の full pytest も実行した。
結果は 17.10 に記録する。追加の unbounded soak は行わず、resource は 17.7 の
fresh-process adversarial audit、正しさは frozen hard contract、固定 seed
differential、thread parity、full pytest を正本とする。

### 17.10 formal long ABAB と full pytest

#### single-thread 全33 case

profile `long`（30 samples、3 warmup、target 50 ms）、GC off、seed `20260719`、
`NUMBA_NUM_THREADS=1` で A1→C1→A2→C2 を直列実行した。両 compare と drift
compare は environment compatible、33/33 status `ok`、exact checksum 一致、
全 hard contract 通過、warning なしだった。

採用 effect の正式 long 結果は次のとおりである。値は
`A1→C1 / A2→C2` の短縮率である。

| effect / case | median 短縮率 | p95 短縮率 |
| --- | ---: | ---: |
| `bold` many-lines | 34.9% / 43.5% | 36.3% / 47.4% |
| `clip` binary-mask | 11.0% / 11.6% | 10.3% / 10.0% |
| `drop` many-lines | 97.9% / 97.9% | 97.8% / 97.8% |
| `growth` draft | 38.9% / 40.2% | 39.9% / 41.6% |
| `growth` final | 46.3% / 46.7% | 45.4% / 47.2% |
| `highpass` many-lines | 24.7% / 24.9% | 24.8% / 24.2% |
| `lowpass` many-lines | 24.1% / 24.7% | 24.6% / 24.0% |
| `metaball` draft | 49.7% / 49.9% | 50.1% / 49.5% |
| `metaball` final | 53.0% / 53.4% | 53.2% / 53.1% |
| `mirror` many-lines | 72.8% / 72.7% | 73.2% / 73.0% |
| `mirror3d` I-group | 59.1% / 59.4% | 58.2% / 58.8% |
| `reaction_diffusion` final、1 thread | 3.6% / 3.6% | 4.0% / 3.7% |
| `relax` shared-network | 49.3% / 49.0% | 50.0% / 49.0% |
| `warp` binary-mask | 23.0% / 23.2% | 21.9% / 22.5% |

`highpass/lowpass` の one-long-line は median 0.1〜1.1%短縮で中立だった。
採用 primary の改善量は全て baseline の `3 * MAD` を超えた。
`clip` は 17.5 記載の backend 支配による明示例外、`bold` は新規 JITを持たない
単純な direct pack と RSS削減、`reaction_diffusion` は次の production-thread
profileを主判定とする。

変更していない `pixelate` は A1→C1 で median 8.4%悪化に見えたが、A1→A2 の
baseline drift 自体が 8.1%で、A2→C2 は 0.5%短縮だった。その他の未変更 control
にも ABAB で再現する secondary regression はなかった。

#### production 10-thread 代表5 case

parallel branch を持つ代表5 caseは `NUMBA_NUM_THREADS=10` でも同じ long ABAB を
行った。2組とも 5/5 exact、全 hard contract 通過、warning なしだった。

| effect / case | median 短縮率 A1→C1 / A2→C2 | p95 短縮率 A1→C1 / A2→C2 |
| --- | ---: | ---: |
| `metaball` draft | 85.4% / 85.4% | 85.4% / 85.1% |
| `metaball` final | 90.2% / 90.2% | 89.7% / 89.5% |
| `reaction_diffusion` draft | 4.5% / 3.9% | 4.9% / 4.1% |
| `reaction_diffusion` final | 56.4% / 55.7% | 52.8% / 53.1% |
| `warp` binary-mask | 25.5% / 15.1% | 21.4% / 24.4% |

`warp` の baseline median は A1→A2 で 10.2% drift したが、candidate drift は
2.3%、single-thread は2組とも23%以上短縮、production p95も2組とも21%以上短縮
しており、採用判断は変わらない。

artifact:

- single-thread run:
  `runs/remaining-effects-v2-{before-long-A1,before-long-A2,
  after-final-long-C1,after-final-long-C2}.json`
- single-thread compare:
  `compare-final-long-{A1-C1,A2-C2,drift-A1-A2,drift-C1-C2}.json`
- production 10-thread run:
  `runs/remaining-effects-v2-{before-prod10-long-A1,before-prod10-long-A2,
  after-final-prod10-long-C1,after-final-prod10-long-C2}.json`
- production 10-thread compare:
  `compare-final-prod10-long-{A1-C1,A2-C2,drift-A1-A2,drift-C1-C2}.json`

#### full pytest

最終 source に対し repository 全体を実行した。

```text
1875 passed, 1 skipped in 69.57s
```

以上により、計画で必須とした correctness、warm long、production thread、cold、
resource、target/full test の gate は全て完了した。
