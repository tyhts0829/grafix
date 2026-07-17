# Grafix 高速化の実装改善アイデア

- 作成日: 2026-07-17
- 状態: 提案・調査メモ。実装未着手
- 対象: `src/grafix/` の実行性能、`src/grafix/devtools/benchmarks/`、runtime profiler、CI
- 前提: 破壊的変更を許容し、互換 shim は作らない。ただし描画結果、レイヤー順、capture provenance の意味は維持する

## 1. 結論

現時点で優先度が高いのは、単純な NumPy の局所最適化よりも、毎フレーム行っている不要な仕事を止めることである。

1. **計測を先に信頼できる状態へ直す**
   - 現行ベンチは実行確認には使えるが、環境の異なる run の比較、case 単位の RSS、出力の同値性、tail latency、実 GPU/GUI を十分に扱えない。
   - schema v3、case ごとの subprocess、raw sample、環境 fingerprint、出力 checksum、`compare` を先に入れる。
2. **fresh frame ごとの provenance 全量生成を止める**
   - 1,000 parameter の合成計測で約 10.3 ms/frame を占めた。capture が無い preview でも、store 全体の encode・sort・JSON・SHA-256 が走る。
3. **parameter GUI の既定経路を短絡する**
   - 1,000 rows の steady frame が現作業ツリーでは約 1.04 ms。表示条件によって不要な active mask と行配列の再構築を避ける。
4. **`Geometry` 連結と DAG 評価をスケールさせる**
   - 反復的な `+` は concat 入力を毎回コピー・再署名するため O(n²)。深い DAG は再帰上限にも達する。
5. **座標だけが動く scene で topology と scene 評価を再利用する**
   - 同じ offsets でも geometry key が変わるたびに index build と IBO upload が起きる。MP の同一結果や pause 中にも scene を再 realize している。

推奨順は、**Phase 0: ベンチ基盤 → Phase 1: provenance/GUI/topology の quick win → Phase 2: concat/DAG/scene 再利用 → Phase 3: planar・重い effect → Phase 4: MP/GPU 実験**とする。

## 2. 既にある良い土台

以下は既に実装されているため、同じ仕組みを作り直さない。

- `Geometry` は immutable recipe DAG と content ID を持つ。
- `RealizeSession` は session-owned の byte 上限付き LRU、inflight 合流、resource budget を持つ。
- `RealizedGeometry` は packed な `float32 coordinates` / `int32 offsets` を持つ。
- renderer は完全一致 geometry の GPU cache と 2-hit admission を持つ。
- GL buffer は幾何級数的に grow する。
- `PerfCollector` は frame/section/operation/layer/cache/worker lag と JSONL trace を収集できる。
- effect benchmark は warm/cold time、peak RSS、output size、JSON/HTML を生成できる。
- system benchmark は animated soak、draw→realize→indices、signature、parameter model、renderer cache、concat、G-code、cold import、MP を含む。
- CI には performance smoke と手動 long job がある。

既存の [`src_grafix_code_review_implementation_plan_2026-07-12.md`](src_grafix_code_review_implementation_plan_2026-07-12.md) では、signature、site ID、cold import、G-code、parameter model、renderer cache、planar backend、MP の改善が完了済みである。本書はその再実装ではなく、現在の作業ツリーで残っている固定費と、計測基盤の不足を対象にする。

## 3. 調査時の観測値と注意

### 3.1 現行 system benchmark の短い試走

2026-07-17 に次を実行した。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /opt/anaconda3/envs/gl5/bin/python -m grafix benchmark \
  --system --repeats 3 --warmup 1 \
  --run-id 20260717_080000 \
  --out /tmp/grafix-perf-audit
```

| case | 観測値 |
|---|---:|
| animated soak、48 frames | median 2.217 ms |
| draw → realize → indices | median 0.153 ms |
| parameter model、1,000 rows × 60 | steady median 1.038 ms、p95 1.190 ms |
| renderer、100k polylines、完全 cache hit | steady median 0.000166 ms |
| packed concat、128 parts | median 0.212 ms |
| cold `import grafix` | 114.642 ms、n=1 |
| MP heavy、n=4 / sync steady ratio | 3.04x |
| MP light、n=4 / sync steady ratio | 0.014x |

この値は**正式な baseline ではない**。調査時の worktree は dirty であり、repeats=3、実 GPU 無し、case が同じ process を共有する。現行 JSON は git SHA を持つが dirty diff、依存、CPU/GPU、実行引数、入力 checksum まで fingerprint していない。この制約自体がベンチ改善の根拠である。

### 3.2 追加した読み取り・合成計測

| 対象 | 観測 |
|---|---|
| `CaptureProvenanceBuilder.frame()` | 100 / 1,000 / 5,000 parameters で約 1.04 / 10.28 / 53.13 ms |
| parameter table の profile | 1,000 rows × 60 では `active_mask_for_rows()` が累積約 0.177 s |
| cache-hit scene pipeline | 10 / 100 / 1,000 layers で約 0.135 / 1.25 / 12.92 ms |
| `parameter_context` 無しの 1,000 layers | 約 4.26 ms。parameter/style の固定費が大きい |
| 反復 `Geometry + Geometry` | 100 / 500 / 1,000 / 2,000 parts で約 1.03 / 19.88 / 77.01 / 305.41 ms |
| 一括 `Geometry.create(op="concat")` | 同条件で約 0.02 / 0.08 / 0.17 / 0.34 ms |
| `PlanarFrame.from_points()` | 50k points × 1 line は約 6.75 ms、10k points × 5,000 short lines は約 46.82 ms |
| 動的座標・同一 topology | 100k polylines で約 0.32 ms/frame、1M polylines で約 2.86 ms/frame の index 側固定費 |

いずれも hotspot の存在を確認するための合成値であり、改善率の約束には使わない。正式な before/after は Phase 0 の runner で取り直す。

## 4. 優先度一覧

| ID | 優先度 | 改善案 | 主な効果 | 実装リスク |
|---|---|---|---|---|
| BENCH-01 | P0 | benchmark schema v3 と比較可能性 | 誤った最適化・回帰判定を防ぐ | 中 |
| RT-01 | P0 | provenance の revision cache と遅延 materialize | parameter 数に比例する毎 frame 固定費を除去 | 中 |
| GUI-01 | P0 | active mask・行配列の既定経路短絡 | parameter GUI の steady cost を削減 | 低 |
| GEO-01 | P0 | concat の O(n²) 解消と iterative DAG evaluator | 大規模 recipe の構築・評価を安定化 | 中 |
| GL-01 | P1 | geometry と topology の cache key 分離 | 動的座標で index build/IBO upload を回避 | 中 |
| RT-02 | P1 | 同じ worker frame / pause 中の realized scene 再利用 | 待機中・多レイヤーの CPU 固定費を削減 | 中 |
| RT-03 | P1 | layer style record の軽量化と draw batching | 多レイヤー scene の CPU/driver overhead を削減 | 中〜高 |
| FX-01 | P1 | `PlanarFrame` の packed many-short-lines 経路 | fill/growth/metaball 等の共通前処理を高速化 | 中 |
| FX-02 | P1 | reaction diffusion / metaball / relax の algorithm 改善 | 重い effect の桁違いの待ち時間を削減 | 高 |
| CACHE-01 | P2 | alias-aware cache と scan-resistant admission | animated root による静的 sub-DAG 追い出しを抑制 | 中 |
| MP-01 | P2 | worker-side realize と shared-memory result | 重い effect を main process から移す | 高 |
| PERF-01 | P1 | tail latency、outer frame、GPU timer、非同期 trace | 実操作の stutter を可視化 | 中 |
| GL-02 | P3 | stroke renderer / MSAA 構成比較 | GPU bound scene の改善余地を確認 | 高 |

## 5. P0: ベンチマーク基盤を先に直す

### 5.1 現行基盤の問題

1. **run 間の互換性を判定できない**
   - git SHA、Python、platform はあるが、dirty diff、依存 version、CPU/RAM/GPU、OS build、BLAS/Numba thread 設定、argv、case source hash、入力 checksum、Grafix config が不足する。
   - report は互換性を確認せず、最古と最新を時系列比較できる。
2. **RSS の意味が曖昧**
   - system case は同じ process の `ru_maxrss` を共有するため、後続 case の値がその case の peak とは限らない。
   - effect の cold RSS も interpreter/import/setup を含む。
3. **正しさの gate が弱い**
   - 多くの case は vertex/line/byte 数だけを出し、座標・offsets の checksum を持たない。空や誤った出力が速くても検知しにくい。
4. **workload が偏る**
   - unary/binary という arity 中心で input を選ぶため、effect に無関係または no-op に近い入力が混じる。
   - primitive、public pipeline、many-short-lines、多レイヤー、cache churn、実 GUI/GPU が不足する。
5. **統計と cold の定義が不十分**
   - 固定 repeats で自動校正がなく、n=3 の p95 も表示する。
   - Numba の fresh process は disk cache を使う可能性があり、「compile cold」と「process cold」が混ざる。
   - effect warm の raw sample は保存されない。
6. **CI は実行確認だけ**
   - baseline compare、soft alert、artifact upload がなく、`${{ runner.temp }}` の結果は job 後に失われる。
7. **runtime 計測に盲点がある**
   - frame time は主に `DrawWindowSystem` 内で、GUI、event loop、buffer swap、scheduler lateness、displayed fresh FPS を十分に含まない。
   - JSONL trace は render thread で open/write/close し、その I/O 時間が frame 計測外になり得る。
   - section は trace にあるが profiler panel には十分に表示されず、平均値中心で p95/p99/max/deadline miss が見えない。
   - [`docs/memo/performance.md`](../memo/performance.md) が参照する `sketch/perf_sketch.py` は現 worktree に存在せず、現行 renderer に独立した `indices` section もない。

### 5.2 推奨する最小構成

巨大な benchmark framework は作らず、既存 CLI を次の 4 層へ整理する。

```text
CaseSpec/Fixture
    ↓
isolated case runner（subprocess、校正、raw sample、memory sampler）
    ↓
schema v3 JSON（RunMeta + CaseResult + Sample）
    ↓
compare / report / CI policy
```

当初は新規依存を追加せず、`time.perf_counter_ns()` と subprocess で小さく実装する。内部 runner で安定性が足りないと確認できた場合だけ `pyperf` を検討する。`pytest-benchmark` や ASV への全面移行は不要である。Grafix 固有の frame、MP、GPU、soak はいずれにせよ custom runner が必要になる。

### 5.3 schema v3 に保存する情報

#### `RunMeta`

- schema version、run ID、UTC timestamp、完全な argv
- git commit、dirty flag、可能なら diff hash
- Python/Grafix/NumPy/Numba/moderngl/pyglet version
- macOS build、machine model、CPU、logical/physical core、RAM、GPU
- `PYTHONHASHSEED`、Numba/BLAS thread 数、Numba cache mode
- config/profile、random seed
- case registry の source hash

#### `CaseSpec`

- case ID と version
- fixture ID、size、parameter override、seed
- phase: `compile_cold` / `process_cold` / `warm` / `cache_hit` / `cache_miss` / `churn`
- measurement scope: evaluator-only / public pipeline / frame / GPU / export
- semantic compatibility 条件
- expected output checksum または不変条件

#### `CaseResult`

- 全 raw samples。summary だけにしない
- median、MAD、p90/p95/p99、max、confidence interval
- setup と timed body を分離した wall/CPU time
- baseline RSS、peak RSS、peak delta、必要な case だけ `tracemalloc`
- output checksum、vertices、lines、bytes
- cache hit/miss/eviction、allocation、frame drop、worker queue/drop/stale/restart
- error/skip reason

### 5.4 case の分離と cold の定義

- **case ごとに fresh subprocess** を既定とし、RSS と global cache を分離する。
- import を除外する micro case は child が setup 完了を通知してから測る。
- `compile_cold`: 空の一時 `NUMBA_CACHE_DIR` を用いる。
- `process_cold`: 新 process だが disk cache は warm。
- `warm`: 同じ child で warmup 後に校正した loop を測る。
- memory は setup 後 RSS を baseline とし、sampling peak との差を case の増分として記録する。
- wall time が短い micro case は 1 sample の loop 数を自動校正し、timer noise を下げる。
- p95/p99 を意思決定に使う suite は原則 20 samples 以上とする。smoke の n=1〜3 では tail percentile を gate にしない。

### 5.5 fixture と scenario matrix

少数の決定的 fixture を、意味のある effect にだけ割り当てる。

| 軸 | 代表値 |
|---|---|
| topology | empty/minimal、1 long line、many short lines、ring/hole、non-planar、multi-layer |
| size | small、medium、large |
| parameter | identity、typical、stress |
| cache | hit、miss、animated unique root、hot sub-DAG + churn |
| execution | evaluator-only、`Geometry` public pipeline、interactive frame、MP、export |

最低限、以下を専用 case とする。

- provenance: 0 / 100 / 1,000 / 5,000 parameters、capture 有無、store revision 変更有無
- parameter GUI: 100 / 1,000 / 10,000 rows、inactive 表示、検索/filter 有無、編集有無
- concat/DAG: 10〜10,000 parts、反復 `+` と bulk、深さ 10〜10,000
- renderer topology: static all、animated coordinates/static offsets、animated topology、cache churn
- multi-layer: 1 / 10 / 100 / 500 / 2,000 layers、same style / alternating style
- planar: one-long-line と many-short-lines を同じ総頂点数で比較
- effect: reaction diffusion の occupancy 10/50/90%、metaball の grid/segment 数、relax の graph size
- MP: n_worker 0/1/2/4 と draw cost sweep。startup、first result、steady、queue wait、transfer、result age を分離
- interactive: real window で scheduler lateness、fresh FPS、present、GPU time、GUI on/off
- soak: 5〜30 分で RSS slope、cache bytes、drop、stale、restarts を確認

各 geometry 出力は coordinates と offsets の canonical checksum を記録する。浮動小数の実装差を許容する case は、量子化 checksum と tolerance ベースの invariant を明示的に使い分ける。

### 5.6 CLI 案

既存の `python -m grafix benchmark` に責務を詰め込まず、subcommand を分ける。

```bash
python -m grafix benchmark list
python -m grafix benchmark run --suite smoke --profile local --out ...
python -m grafix benchmark run --suite pipeline --case concat_many --out ...
python -m grafix benchmark compare BASE.json HEAD.json
python -m grafix benchmark report RUNS_DIR --offline
python -m grafix benchmark trace summarize performance.jsonl
```

run ID は timestamp + random suffix とし、既存ファイルを上書きしない。壊れた JSON や schema 不一致は report で黙って無視せず、warning と件数を表示する。report は CDN へ依存せず offline で閲覧可能にする。

### 5.7 compare と CI policy

- fingerprint が非互換な run は既定で比較拒否し、明示 override の場合だけ参考表示する。
- 同じ CI job・同じ machine で base/head を交互に実行し、時間 drift を相殺する。
- hosted macOS の wall time は artifact と soft warning を基本とする。
- hard gate は、output checksum、cache byte 上限、RSS slope、frame drop/error のような決定的 invariant を優先する。
- 安定した wall-time ratio の hard gate が必要なら、固定された self-hosted Mac だけで行う。
- smoke/long とも JSON、HTML、trace を artifact upload する。
- effect の time-series だけでなく、system/MP/interactive case も同じ report に載せる。

### 5.8 BENCH-01 の受け入れ基準

- 同じ case が個別 subprocess で再実行でき、case peak RSS が実行順に依存しない。
- raw samples と output checksum が JSON に残る。
- dirty worktree、依存、CPU/GPU、argv、case version を判別できる。
- 非互換 run を `compare` が既定で拒否する。
- CI artifact から実行環境と結果を再確認できる。
- `--cold-processes`、`--seed`、GC/Numba cache 指定など、受理した CLI 引数が全 case に反映されるか、未対応なら parser が拒否する。
- runtime 用の保守された packaged scenario があり、存在しない `sketch/perf_sketch.py` への依存を解消する。

## 6. P0: 毎フレーム固定費を除去する

### 6.1 RT-01: capture provenance を revision cache + 遅延 materialize にする

#### 根拠

`draw_window_system.py` は fresh frame ごとに `_frame_provenance()` を呼ぶ。`capture_provenance.py::_parameter_snapshot()` は、capture request が無い preview でも次を行う。

1. `last_effective_by_key` 全件の sort
2. effective 値と source の JSON 化
3. `encode_param_store(..., preserve_explicit_overrides=True)`
4. canonical JSON 文字列化
5. SHA-256

parameter 数にほぼ線形で、合成計測では 1,000 件で約 10.3 ms、5,000 件で約 53.1 ms だった。

#### 実装案

1. persistent store payload の encode/hash を `store.revision` で cache する。
2. effective parameter 側には独立した `effective_revision` を設け、frame merge が値/source を変更した時だけ増やす。
3. frame 完了時は、小さい immutable token を保存する。
   - session provenance への参照
   - `t`、frame index、quality
   - store revision、effective revision
   - その frame に対応する immutable parameter digest/snapshot handle
4. capture/export/recording が実際に要求された時だけ完全な `CaptureProvenance` を materialize する。
5. session provenance の source/Git/config 探索は現状どおり builder 構築時だけにする。

遅延化だけで「後の frame の store を読んでしまう」実装にはしない。表示した frame と完全に対応する digest、または copy-on-write snapshot を frame 完了時に確定する必要がある。

#### 受け入れ基準

- capture request の無い preview で provenance section を現状比 90% 以上削減する。
- parameter 100 / 1,000 / 5,000 件で、store/effective revision が不変なら O(1) 相当になる。
- revision を 1 件変更した frame の manifest が現行実装と同じ canonical SHA-256 になる。
- export queue が遅延しても、capture manifest は request 時ではなく表示 frame の値を保持する。
- recording の最初の fresh frame、last-good frame、failed frame の既存 semantics を回帰させない。

### 6.2 GUI-01: parameter table の既定経路を短絡する

#### 根拠

`parameter_table_view_for_store()` は `show_inactive_params=True` でも `active_mask_for_rows()` を呼ぶ。1,000 rows × 60 の profile では、この関数が累積約 0.177 s を占めた。また `render_store_parameter_table()` は変更が無い frame でも、`rows_before`、`visible_mask`、`view_rows`、`rows_after` を毎回構築する。

#### 実装案

1. `show_inactive_params=True` かつ filter が active state を参照しない場合、active mask を作らず all-visible の既定経路へ進む。
2. visibility rule の group 化結果を model/effective revision で cache し、毎 frame の dict/list 構築を避ける。
3. `rows_after` は `changed=True` の時だけ構築する。
4. `model.rows` と immutable `visible_mask` をそのまま扱い、表示行だけが必要な箇所まで list 化を遅らせる。
5. profiler panel を閉じている時に詳細 row/operation 集計を有効にしない。常時必要な coarse counter と opt-in の deep profiler を分離する。

#### 受け入れ基準

- 1,000 rows、検索無し、編集無しの steady median を 0.5 ms 以下に戻す。
- 10,000 rows の scaling が概ね線形である。
- inactive 非表示、active filter、search、favorite、error、MIDI、collapse、編集の組合せで visible row と更新結果が現行と一致する。
- deep profiler off/on の frame overhead を別々に記録する。

### 6.3 GEO-01: concat の O(n²) と recursive DAG 評価を解消する

#### 根拠

`Geometry._concat()` は既存 concat の `inputs` を flatten し、`Geometry.create()` が全 input を tuple 化・再署名する。`sum()` や loop 内の `result += g` は、過去の全 input を毎回コピーするため O(n²) になる。合成計測では 2,000 parts が約 305 ms、一括 create は約 0.34 ms だった。

`RealizeSession` の registration/cacheability/evaluation は DAG を再帰的に辿るため、深さ約 500 の単項 chain でも Python の recursion limit に達し得る。

#### 実装案

低リスクな順に進める。

1. `Geometry.concat(iterable)` または内部 bulk builder を追加し、Grafix 内部の既知の反復 `+` producer を一括構築へ変更する。
2. `RealizeSession` を明示 stack の post-order evaluator にし、registration、cacheability、realize を同じ traversal plan から行う。
3. `+` 自体も O(1) にする必要がある場合は、concat を binary/persistent tree として保持し、realize 時だけ iterative に leaf を flatten する。
4. parenthesization で ID が変わることを許すか、concat leaf 列を canonical content とするかを先に決める。単に rolling hash を足して content-ID semantics を曖昧にしない。

#### 受け入れ基準

- 2,000 parts の bulk concat 構築を 5 ms 以下とし、10,000 parts でも O(n²) の曲線にならない。
- 深さ 10,000 の合法な DAG を `RecursionError` 無しで評価・cacheability 判定できる。
- leaf 順、coordinates、offsets、空 geometry、`sum()` の結果を回帰させない。
- DAG の共有 child を一度だけ評価し、cycle を想定しない現行の immutable construction を複雑化しない。

## 7. P1: scene・renderer の再利用単位を正す

### 7.1 GL-01: geometry key と topology key を分ける

#### 問題

renderer の完全一致 cache は static geometry には非常に速い。一方、coordinates だけが毎 frame 変わり offsets が同じ scene では geometry key が毎回変わり、同じ line indices を再構築し、IBO も再 upload する。2-hit candidate が一度しか来ない animated key の index array を保持すると、cache budget も消費する。

#### 実装案

- `GeometryCacheKey` とは別に、安全な `TopologyKey` を導入する。
  - 第一案は immutable offsets object identity + strong reference。
  - 将来は `RealizedGeometry` が計算済み topology ID を持ってもよいが、毎 frame の全 offsets hash は避ける。
- scratch mesh で topology hit なら indices/stats/IBO を再利用し、VBO だけ更新する。
- candidate admission は payload を持つ index cache ではなく、key/count 中心にする。static geometry の 2 回目は scratch から promote できる。
- non-cacheable/stateful geometry は candidate へ入れない。
- `_MeshCacheEntry.indices` が promotion 後に不要なら CPU 側保持をやめる。

#### 受け入れ基準

- `animated coordinates + static offsets` で index build 1 回、IBO upload 1 回、以後 VBO のみ更新する。
- `animated topology` と offsets object の再利用/破棄で誤った index を使わない。
- 100k / 1M polylines で CPU frame time、candidate bytes、VBO/IBO upload bytes を記録する。
- static full-cache hit の現性能を悪化させない。

### 7.2 RT-02: 同じ evaluated scene を再 realize しない

`SceneRunner._run_mp()` は新しい worker result が来ない frame や pause 中にも、last result を `realize_scene()` へ流す。worker 側ですでに normalize した scene を main 側で再 normalize/list copy する経路もある。

次の内部値を導入する。

```text
EvaluatedScene(
    worker_frame_id,
    normalized_layers,
    parameter_revision,
    style/default revision,
    quality,
    registry_revision,
)
```

この key が同じなら immutable `tuple[RealizedLayer, ...]` を再利用する。新 result、parameter/style/quality/registry 変更時だけ realize する。pause 中は同一 task の再 submit も coalesce する。

注意点は、operation diagnostics、parameter observation、last-good/fresh-frame の semantics を cache hit で失わないことである。「再利用した表示」と「新しく評価に成功した frame」を別の状態として持つ。

### 7.3 RT-03: 多レイヤー固定費と draw call を減らす

cache hit でも layer ごとに parameter context、style resolve、store lookup、resource check、dataclass、uniform write、draw call が残る。合成計測では 1,000 layers が約 12.9 msだった。

段階的に行う。

1. layer/style key を compact な immutable record にし、revision が不変なら再利用する。
2. 直前 layer と color/thickness が同じなら redundant uniform write を省く。
3. 同じ style の**隣接** layer を style run としてまとめ、順序を保ったまま draw call を減らす。
4. 必要なら scene-level mesh packing を検討するが、非隣接 layer の並べ替えはしない。

1 / 10 / 100 / 500 / 2,000 layers、same/alternating style で、scene resolve、uniform writes、draw calls、CPU submit、GPU time を分けて測る。交差する色付き線の描画順を保持する。

## 8. P1: geometry/effect の algorithm を改善する

### 8.1 FX-01: `PlanarFrame` の many-short-lines 経路

`PlanarFrame.from_points()` と `_clean_frame_lines()` は polyline ごとに `np.diff`、boolean mask、small array/list、concat を行う。総頂点が少なくても line 数が多いと Python/NumPy dispatch が支配する。

改善候補:

- packed coordinates/offsets を直接走査する Numba kernel で、finite、重複点除去、bbox、planarity summary を一度に作る。
- XY plane の明白な 2D 入力を fast path にする。
- output allocation を two-pass にし、small array の大量生成を避ける。
- fill、growth、metaball、isocontour、warp 等で同じ prepared planar representation を共有する。

one-long-line と many-short-lines を同じ総頂点数で比較し、many-short-lines を最低 3x 改善することを目安にする。既存の planarity tolerance、閉路、NaN、退化線の semantics は golden test で固定する。

### 8.2 FX-02a: reaction diffusion

現在の kernel は `steps × bbox cells` を走査する。mask occupancy が低い場合は、active cell index と近傍 index を一度構築して sparse kernel を回す方がよい。

- active cell list と 4/8-neighbor index を前計算する。
- occupancy によって dense/sparse kernel を選ぶ。
- scratch arrays を effect 評価内で再利用する。
- preview quality では明示的な iteration/resolution profile を使い、暗黙に結果を変えない。

grid 256/512、occupancy 10/50/90%、steps sweep で break-even を決める。random seed、boundary、mask edge の同値性を検証する。

### 8.3 FX-02b: metaball / field grid

ring segment ごとに全 grid cell を評価する O(grid cells × segments) を避ける。候補は次の順で比較する。

1. ring bbox で grid tile を絞る。
2. 既存 planar/grid backend と distance transform を再利用する。
3. spatial binning で各 tile の候補 segment だけ評価する。

出力 contour の tolerance を定義し、単に解像度を下げた高速化と algorithm 改善を混同しない。

### 8.4 FX-02c: relax topology

`relax.py` の topology 構築は Python の dict/set/adjacency/DFS が中心で、iteration kernel だけが Numba 化されている。exact bit pattern または量子化 key を明示し、`np.unique`/sort または packed Numba builder で vertex/edge adjacency を作る。まず topology build と iteration を別 case にし、どちらが支配的か確認する。

## 9. P2: cache と multiprocessing の構造改善

### 9.1 CACHE-01: alias と scan pollution

no-op/identity effect が入力と同じ `RealizedGeometry` object を返しても、別 key ごとに全 `nbytes` を加算すると同じ storage を重複計上し、alias sibling だけで eviction が起こる。また animated unique root の連続 miss が static hot sub-DAG を LRU から追い出す。

実装候補:

- 最初に、identity/no-op result は alias key を増やさず canonical child key へ解決する簡単な方式を試す。
- それで不足する場合だけ、array storage identity の refcount による byte accounting を入れる。
- scan pollution には probation/protected の単純な 2Q admission を比較する。
- global registry revision で全 operation cache が失効する問題は、実測で効く場合だけ per-op generation を検討する。

複雑な cache policy は maintenance cost が高い。hit ratio だけでなく、frame p95、cache bytes、eviction、static child 再計算数が改善する場合に限り採用する。

### 9.2 MP-01: worker-side realize と shared memory

現在の worker は主に draw + normalize を担い、重い NumPy/Numba effect の realize は main process に残る。真に重い scene では worker ごとに `RealizeSession` を持たせ、packed coordinates/offsets を shared-memory ring で返す余地がある。

ただし、これは最後に行う。

- 最初は n_worker=1 の prototype に限定する。
- descriptor に frame ID、layer metadata、buffer generation、shape/dtype を持たせる。
- latest-wins、cancellation、worker crash、buffer lifetime を明示する。
- Queue で大きな NumPy array を pickle しない。
- queue wait、draw、realize、transfer、result age、drop/stale/restart を分離計測する。

軽量 draw では MP が大幅に不利であるため、既定 worker 数を増やすだけの変更は行わない。draw/effect cost sweep から break-even を求め、明示 profile で選択する。

## 10. PERF-01: 現場で使える runtime profiler

ベンチマーク CLI と実アプリの profiler は役割を分けつつ、同じ metric 名と trace schema を使う。

### 常時収集する軽量 metric

- outer frame interval、scheduler lateness、fresh/stale displayed frame
- draw/realize/render/present の coarse time
- vertices、lines、layers、draw calls、VBO/IBO upload bytes
- CPU/GPU cache bytes と hit/miss/eviction
- MP submitted/completed/dropped/stale/restart、result age

### opt-in の詳細 metric

- operation/layer/section 別 p50/p95/p99/max
- deadline miss count と longest frame
- allocation/RSS sample
- asynchronous GL timer query による GPU time
- trace event

改善内容:

- bounded ring に raw frame sample を保持し、平均だけでなく tail と jitter を出す。
- `<other>` にまとめた overflow 数・時間を snapshot に明示する。
- profiler panel に section、draw call、upload、worker queue/age を表示する。
- `ctx.finish()` はデバッグ比較用に残し、通常の GPU 計測は複数 frame 遅延の timer query を使う。
- trace は長寿命 buffered writer または background writer にし、session header、monotonic timestamp、dropped event count を持たせる。
- trace I/O 自体の overhead も metric に含める。
- parameter GUI monitor があるだけで deep collector を有効にせず、panel open または明示設定で切り替える。

目標は「60 FPS か」だけでなく、「どの区間が 16.67 ms deadline を何回超えたか」「表示された fresh frame が何 FPS か」を現場で即座に判断できることである。

## 11. P3: GPU 実験は実測後に限定する

macOS の実 GPU で次を同じ visual tolerance、viewport、線数で比較する。

- 現行 geometry shader + MSAA 4x
- geometry shader + MSAA 0/2x
- instanced quad stroke
- CPU tessellation + indexed triangle

CPU submit、GPU timer、upload、draw call、anti-aliasing 品質、join/cap の差を分離する。GPU renderer の全面書き換え、float16 化、無条件の `parallel=True`、近似 geometry は、上位 hotspot を解消した後に profile が必要性を示すまで行わない。

## 12. 推奨ロードマップ

### Phase 0: 測定の信頼性

1. schema v3 の小さな dataclass と atomic/no-clobber writer
2. isolated case runner、raw sample、校正、checksum、RSS delta
3. fingerprint と `compare`
4. provenance/GUI/concat/topology/multilayer の regression case
5. CI artifact と soft comparison
6. packaged interactive performance scenario と performance memo の更新

**出口条件:** 同じ環境の base/head を正しく比較でき、非互換 run と誤出力を拒否できる。

### Phase 1: 低リスク quick win

1. GUI active-mask fast path と `rows_after` 遅延生成
2. provenance の store revision cache
3. topology scratch reuse と candidate payload 削減
4. profiler off/on overhead の分離

**出口条件:** visual/capture parity を保ち、既定 preview の frame p95 が明確に改善する。

### Phase 2: core scaling

1. bulk concat と内部 producer 移行
2. iterative DAG traversal/evaluator
3. evaluated scene / realized layers の revision cache
4. style uniform suppression、隣接 style run

**出口条件:** 10k-part DAG と 1k-layer scene が recursion/二乗時間なしで扱える。

### Phase 3: geometry/effect

1. packed `PlanarFrame` preprocessing
2. reaction diffusion dense/sparse
3. metaball spatial/grid backend
4. relax topology builder
5. cache alias/2Q は case が必要性を示したものだけ

**出口条件:** representative fixture の checksum/tolerance を守り、wall time と memory の両方が改善する。

### Phase 4: architecture experiment

1. worker-side realize + shared-memory の n=1 prototype
2. multi-worker break-even 再測定
3. GL timer query と stroke backend 比較

**出口条件:** 複雑性を含めても interactive p95、fresh FPS、RSS に明確な利益がある案だけ採用する。

## 13. 各改善で共通の完了条件

- before/after を同じ fingerprint、同じ fixture、同じ checksum で保存する。
- median だけでなく p95/max と memory を確認する。
- preview、capture/export、recording、headless のうち影響する経路を全部測る。
- 速度のために resource budget、cache byte 上限、last-good semantics を迂回しない。
- no-op、empty、NaN/degenerate、大規模入力の正しさを test する。
- 新しい cache は必ず revision/key、byte accounting、invalidation、lifetime を文書化する。
- 期待した改善が出ない案は残さず、単純な実装へ戻す。

## 14. 今は採用しない案

- benchmark framework の全面移行や大きな依存追加
- すべてを cache する unbounded memoization
- 既定 `n_worker` を根拠なく増やす
- GPU renderer の一括書き換え
- 精度や描画順を暗黙に落とす高速化
- 小配列まで無条件に multiprocessing/Numba parallel 化すること
- 既存 API を残すためだけの compatibility wrapper

まず BENCH-01、RT-01、GUI-01、GEO-01 の 4 件を独立した小さい実装計画へ分け、各計画の承認後に着手するのが妥当である。
