# Grafix 現行実装ベース 性能改善計画

- 作成日: 2026-07-18
- 状態: 優先実装と deterministic benchmark は完了。実 GUI / 実 GL、row virtualization、
  JIT・capture・recording の条件付き項目、long soak は未完了
- 対象:
  - interactive preview と Parameter GUI の操作応答
  - core / effect / realize / renderer / multiprocessing
  - capture / recording の待ち時間
  - packaged benchmark、runtime trace、比較・回帰判定
- 関連資料:
  - `docs/plan/grafix_performance_improvement_ideas_2026-07-17.md`
  - `docs/plan/grafix_performance_improvement_implementation_plan_2026-07-17.md`
  - `docs/plan/interactive_slider_stutter_investigation_and_improvement_plan_2026-07-18.md`
  - `docs/memo/performance.md`

## 1. 結論

現時点では、concat、反復 DAG 評価、stable provenance、単一 animated topology、
slider revision starvation、長寿命 CPU cache など、以前の大きな問題は既に改善されている。
これらを再設計するのではなく、回帰 case として維持する。

次に着手すべき順序は次の通り。

1. **現場のカクつきを実際に落とせる benchmark / trace にする**
   - 現在の slider benchmark は `input → worker result` までで、
     GUI、history、merge、realize、GL submit、`Window.flip()` を含まない。
   - compare は主に median ratio と checksum を返すだけで、性能 contract、
     tail latency、scenario 内 metric の pass/fail を扱えない。
2. **大規模 ParamStore の単一キー変更を全件処理から外す**
   - history の全 store `deepcopy`、値変更による table 全再構築、
     merge の before/after 全走査が残っている。
   - 10,000 parameter では GUI 描画自体も全 widget を生成しており、行の仮想化が必要。
3. **draft preview で秒単位になる effect に作業量 budget を導入する**
   - `reaction_diffusion`、`metaball`、`growth` は軽い scene でも effect 側の
     work が支配し得る。
   - final の結果は変えず、draft だけを明示的・決定的に粗くする。
4. **複数 animated layer、MP snapshot、stale scene 再処理の固定費を減らす**
   - renderer の scratch topology は 1 件だけで、複数 layer が毎フレーム上書きする。
   - revision 変更時の full parameter snapshot は task と control 配布で重複し得る。
   - MP の同じ成功 result を再表示する間も `realize_scene()` が再実行される。
5. **実 GL / 実 GUI と長時間 soak は reference Mac で検証する**
   - fake GL と isolated child は決定性確認に残す。
   - driver、vsync、multi-window scheduling、present latency は実環境だけで測る。

effect の個別高速化や GPU batching を先に大量実装しない。Phase 0 で tail と因果関係を
可視化し、その結果により Phase 1 以降の実装順を確定する。

## 2. 現行実装の基準点

### 2.1 解消済みとして維持する項目

- schema v3 benchmark
  - case ごとの fresh process
  - warm / process-cold / compile-cold
  - raw sample、median、MAD、p95/p99、RSS high-water
  - source / environment / case compatibility key
  - exact output checksum
  - atomic no-clobber JSON と offline HTML report
- core
  - 反復 `Geometry +` の二乗化解消
  - iterative DAG evaluator
  - CPU realize cache の byte 上限と 4,096 entry 上限
- runtime
  - stable parameter provenance の revision cache
  - 通常 preview から provenance 具体化を除外
  - MP task への parameter snapshot 同梱による revision starvation 解消
  - freshness、stale streak、revision lag の計測
- renderer
  - static offsets の index / IBO 再利用
  - VBO-only upload
  - bounded candidate admission
  - fresh scene serial と snapshot revision に基づく transient mesh の昇格防止
- export
  - PNG / G-code の bounded long-lived worker
  - job 件数・推定 byte budget・shutdown drain

現行 registry には 61 benchmark case がある。主な正式結果は次の通り。

| 項目 | 現行結果 |
| --- | ---: |
| stable provenance / 1,000 parameters | median 0.00167 ms |
| steady parameter table / 1,000 rows | median 0.033 ms |
| steady parameter table / 10,000 rows | median 0.293 ms |
| repeated `+` / 10,000 parts | median 24.582 ms |
| animated coordinates / static offsets / 100k lines | median 0.235 ms、index build 1 回 |
| slider churn translate / scale | fresh 99.17%、input-to-result p95 約 27 ms |
| unique translate 200,000 回 | CPU cache 4,096 entries で plateau |

### 2.2 現行の残存ボトルネック

以下は探索計測であり、正式な before 値ではない。Phase 0 の同一 harness で取り直す。

#### Parameter GUI

| parameter 数 | history p50 | table model 再構築 p50 | merge p50 |
| ---: | ---: | ---: | ---: |
| 32 | 0.39 ms | 0.32 ms | 0.08 ms |
| 1,000 | 11.86 ms | 10.58 ms | 2.51 ms |
| 10,000 | 152.54 ms | 132.98 ms | 29.68 ms |

原因は次の現行コードで確認できる。

- `src/grafix/core/parameters/history.py`
  - GUI transaction の変更後に full memento を作る。
- `src/grafix/core/parameters/memento.py`
  - 全 state / meta を `deepcopy` する。
- `src/grafix/interactive/parameter_gui/table_model.py`
  - table model key が値変更でも進む `store.revision` を含む。
- `src/grafix/interactive/parameter_gui/store_bridge.py`
  - model miss で全 row の生成、分類、sort を行う。
- `src/grafix/interactive/parameter_gui/table.py`
  - 開いている全 row の widget を生成し、viewport 外を省略しない。
- `src/grafix/core/parameters/merge_ops.py`
  - 対象 key の before dict、rollback、事後 scan を別 pass で行う。

#### 重い effect

代表 fixture の探索値:

| effect | warm 1 回 |
| --- | ---: |
| `reaction_diffusion` | 約 3,445 ms |
| `metaball` | 約 3,020 ms |
| `growth` | 約 366 ms |
| `clip` | 約 60.8 ms |
| `extrude` | 約 51.2 ms |
| `mirror3d` | 約 45.7 ms |

`PlanarFrame` も同じ頂点数で line 数が多い場合に固定費が増える。

| 入力 | 頂点 | line | median |
| --- | ---: | ---: | ---: |
| long polyline | 50,000 | 1 | 6.57 ms |
| many short lines | 10,000 | 5,000 | 45.11 ms |

#### interactive / renderer / MP

- 8 animated layers × 120 frames、各 layer の offsets identity は安定:
  - 現行 index build は 960 回。
  - scratch topology が 1 件だけなので、layer ごとに相互上書きされる。
- parameter snapshot の pickle 探索値:

| parameter 数 | 1 payload |
| ---: | ---: |
| 32 | 0.058 ms / 2.3 KiB |
| 1,000 | 1.94 ms / 65 KiB |
| 10,000 | 21.97 ms / 650 KiB |

- revision 変更時は同内容の snapshot を task と worker 別 control queue に配る経路がある。
- `SceneRunner._run_mp()` は新 result が無い再表示 frame でも、最新成功 recipe に
  `realize_scene()` を再適用する。
- full GPU mesh cache は byte 上限だけで、tiny mesh の entry / GL object 数上限がない。

#### autosave / capture

- autosave は Parameter GUI frame の後半で serialize と atomic write を同期実行する。
  - 1,000 parameters の探索値は p50 約 4.0 ms、最大約 8.7 ms。
- video recording は GPU readback と ffmpeg stdin write を frame 内で行う。
- capture key は final scene の同期再評価を行い、SVG は encode / publish も同期である。

### 2.3 現行 benchmark が見逃すもの

1. `mp.draw.slider_churn` の scope は `draw + normalize_scene` で、realize 以降を除外する。
2. GUI benchmark は steady model を主に測り、実 ImGui widget と changed-frame を通らない。
3. renderer benchmark は fake GL、単一 layer である。
4. `PerfCollector.frame()` は preview の `on_draw` 内で、GUI window と `Window.flip()` を
   含まない。
5. runtime trace は既定 60 frames の平均で、p95/p99/max と frame 単位の因果を失う。
6. trace JSONL は集計時に render thread で open / write / close するが、その時間は
   `frame_ms` に含まれない。
7. compare は top-level median と checksum が中心で、nested scenario metric、
   contract、tail、memory slope を回帰判定に使わない。
8. slider の `interactive_target_met` が false でも、schema の case status は
   自動的には failure にならない。
9. RSS は high-water の端点だけで、long soak の current RSS、傾き、GC pause を持たない。
10. effect は原則 1 fixture で、draft/final、one-long/many-short、work size の曲線、
    初回 JIT latency を分離していない。

## 3. 性能目標と判定方針

### 3.1 interactive UX

reference Mac の正式 scenario では次を guardrail とする。

- input-to-present p95: 50 ms 以下
- input-to-present 改善目標: 33.3 ms 以下
- fresh displayed result ratio: 90% 以上
- consecutive stale display: 2 frames 以下
- parameter revision lag p95: 2 以下
- drag release から最終 revision 表示: 100 ms 以下
- 16.7 ms deadline miss 率、p99、max も保存し、median 改善だけで採用しない

32 parameters の軽量 scene と 1,000 parameters の大規模 store の両方で満たす。
10,000 parameters は soak / scaling 用とし、最初から全組合せを短い CI に入れない。

### 3.2 memory / resource

- queue、CPU cache、GPU candidate、dynamic mesh、full mesh は byte と entry の両方で bounded
- unique value soak の後半で cache entry / GPU object 数が plateau
- current RSS の後半傾きが継続的な増加を示さない
- transient slider 値の full GPU mesh promotion は 0
- settle 後の安定値は必要な mesh だけ 1 回昇格
- queue reject、worker restart、unbounded pending、provenance preview materialization は 0

### 3.3 benchmark gate

判定を次の 2 層に分ける。

#### Hosted CI の hard gate

- checksum / invariant
- final revision と表示 revision の一致
- revision の単調性
- queue / cache / candidate / object 上限
- timeout、error、reject、worker death が無いこと
- hard contract の pass

wall time、GPU timing、RSS 絶対値は hosted runner では soft observation にする。

#### Reference Mac の performance gate

noise study 完了後、同一 machine / display / power condition でのみ hard gate にする。

- median: 10% 超の悪化かつ 3 × MAD を超えた場合に failure
- p95: 15〜20% 超の悪化を failure 候補
- UX の絶対 guardrail は別 contract として判定
- base/head は一括順番実行ではなく、交互 block で thermal drift を抑える

## 4. Phase 0: benchmark と trace を先に完成させる

### 4.1 BENCH-02: typed metric と contract

schema は strict なまま新しい field を追加するため v4 に上げる。v3 互換 wrapper や
二重 reader は作らず、旧 artifact は旧 schema の記録として残す。

- [x] arbitrary nested `metrics` を、名前・型・単位・phase・scope を持つ metric に整理する。
- [x] metric kind を最低限 `counter`、`gauge`、`distribution` に限定する。
- [x] distribution は count、min/max、median、MAD、p95/p99 と、必要な raw sample を持つ。
- [x] scenario を `warmup`、`drag`、`settle` の phase に分ける。
- [x] `ContractResult` に ID、hard/soft、actual、comparator、limit、reason を持たせる。
- [x] runner は hard contract failure を case failure として返す。
- [x] CLI は checksum / hard contract failure を非 0 exit にする。
- [x] compare は median だけでなく指定 metric、tail、RSS、contract を比較する。
- [x] report は base/head delta、contract pass/fail、scaling curve、warning を表示する。
- [x] status、checksum、contract と timing noise を別列にする。
- [x] case source hash に scenario driver と contract 定義も含める。

受け入れ基準:

- `interactive_target_met=False` を持つ slider case が成功扱いにならない。
- hard と soft の違いが JSON、CLI exit、HTML のすべてで一致する。
- 非互換 environment / case / phase / metric unit の比較を拒否する。
- 既存の exact checksum と raw wall-time sample を失わない。

### 4.2 UX-01: input-to-present scenario

標準 scenario:

```text
30 frames warmup
120 frames drag at 60 Hz
30 frames settle
```

最初の matrix:

- operation: translate / scale
- parameter rows: 32 / 1,000
- animated layers: 1 / 8
- workers: 0 / 1
- transport: paused / playing
- Inspector: hidden / visible

全直積は作らず、原因を分離できる代表組合せを `short` に置き、残りを
`interactive` / `soak` profile に置く。

- [x] parameter revision 作成時刻を入力起点として記録する。
- [x] snapshot send / worker apply / task start / result receive を同じ revision と frame ID で結ぶ。
- [x] main-process realize、mesh upload、draw submit、preview flip 完了を結ぶ。
- [x] preview、GUI、full multi-window tick、scheduler jitter を別 metric にする。
- [x] presented revision と final Geometry checksum を correctness に使う。
- [x] stable control と changing sequence を同じ run に置く。
- [x] fake GUI / fake GL の deterministic case を hosted CI 用に作る。
- [ ] programmatic ImGui edit と実 window loop を通す local case を作る。
- [ ] visible / vsync-on の実 GUI case は reference Mac 専用にする。

### 4.3 TRACE-02: frame tail と causal trace

- [x] 直近 256 frames の bounded sample ring を持つ。
- [x] frame / full loop / preview draw+flip / GUI draw+flip の p50/p95/p99/max を表示する。
- [x] deadline miss count と最大連続 miss を表示する。
- [x] 次の causal event を revision / frame ID とともに記録する。
  - `parameter_revision_created`
  - `parameter_snapshot_built`
  - `mp_snapshot_sent`
  - `mp_snapshot_applied`
  - `mp_task_started`
  - `mp_result_received`
  - `realize_started` / `realize_finished`
  - `mesh_uploaded`
  - `draw_submitted`
  - `preview_presented`
- [ ] history、table model、merge、autosave、provenance、capture を section 化する。
- [ ] CPU cache entries/bytes、GPU objects/uploads、queue depth、current RSS、GC pause を記録する。
- [ ] trace に source、diff、config hash、seed、display refresh/scale、backend を header として持つ。
- [x] JSON writer を bounded buffer 化し、drop count を公開する。
- [x] render thread で毎 window open / write / close しない。
- [x] shutdown 時に footer と未flush/drop数を確定する。

受け入れ基準:

- disabled path は frame ごとの可変 allocation を追加しない。
- enabled path の overhead は軽量 scene で 0.2 ms/frame 未満または 2% 未満。
- trace を有効にしても、その I/O 自体が未計測の周期的 hitch を作らない。
- scenario summary を raw trace から再生成できる。

## 5. Phase 1A: 大規模 ParamStore / GUI

### 5.1 PARAM-01: changed-frame benchmark

- [x] `gui.parameter_edit.rows_{100,1000,10000}` を追加する。
- [ ] history、state apply、snapshot、merge、structure model、value overlay、widget draw を分離する。
- [ ] 1 key drag、MIDI、favorite、range edit、collapse、Undo/Redo を別 contract にする。
- [ ] 1,000 / 10,000 rows の current RSS と allocation count を保存する。

### 5.2 PARAM-02: patch history

- [x] 単一 parameter 編集は `key + kind + before + after` の patch として記録する。
- [x] 同じ drag / key / source の coalesce は `after` だけを更新する。
- [x] Undo/Redo は現在も存在し、現在の `ParamMeta.kind` が一致する key にだけ適用する。
- [x] code reload 後に削除・kind 変更された key を安全に無視する。
- [x] variation、A/B snapshot、一括 MIDI 解除など bulk 操作は full memento を維持する。
- [x] hot path と bulk path を互換 shim で二重実装せず、履歴 entry の型で明示する。

受け入れ基準:

- 1 key drag 中の full-store `deepcopy`: 0 回
- 1,000 parameters の history p95: 1 ms 以下を目標
- Undo/Redo、drag coalescing、branch 後 redo 破棄の既存意味を維持

### 5.3 PARAM-03: structure / value revision 分離

- [x] store の永続 revision は MP / save 用に維持する。
- [x] table 用に structure revision と value revision を分ける。
- [x] key、kind、row order、label、header、effect chain、registry 変更だけで structure revision を進める。
- [ ] `ui_value`、override、CC、favorite、effective/source は value overlay に分ける。
- [x] 1 key 値変更で row の分類・全 sort・全 dataclass rebuild を行わない。
- [x] loaded / observed、filter、collapse の visibility semantics を維持する。
- [x] merge の effective/source staging、適用、変更判定を 1 pass にする。
- [x] failed frame rollback は実際に触れた key だけを戻す。
- [x] reconcile は新規 group / structure 変化がある場合だけ実行する。

受け入れ基準:

- 1,000 parameters の 1 key drag で structure model build: 0
- parameter merge は record 数に 1 回だけ線形走査
- effective revision は 1 frame に最大 1 回
- changed GUI CPU section p95: 4 ms 以下を目標

### 5.4 GUI-02: row virtualization

- [ ] viewport 内の row と必要な header だけ widget を生成する。
- [ ] viewport 外は正しい高さだけ進め、scroll range を維持する。
- [ ] active item、MIDI learn、range edit、help、error、favorite の行は操作中に消さない。
- [ ] collapsed group は従来どおり描画も hit target も作らない。
- [ ] fixed-height row だけを clip 対象にし、可変高さ UI を無理に同一 clipper へ入れない。

受け入れ基準:

- 10,000 parameters の widget 生成数が総 row 数ではなく表示 row 数に比例
- scroll、focus、drag、collapse の visual / input regression が無い
- 1,000 rows の小規模側を 10% 以上悪化させない

### 5.5 PARAM-04: autosave

まず active interaction 中の同期 save を release 後 debounce へ移す。background writer は
この変更後も save spike が目標を超える場合だけ導入する。

- [ ] serialize / write / fsync を個別 trace する。
- [x] active drag 中は main-thread autosave を開始しない。
- [x] release 後 debounce、shutdown flush、atomic publish、失敗通知を維持する。
- [ ] recovery の最大遅延を明文化し、無期限延期しない。
- [ ] 必要な場合だけ immutable payload + latest-wins background writer を追加する。

## 6. Phase 1B: draft effect と共通 planar 経路

### 6.1 FX-03: quality 別 benchmark

- [x] heavy effect を draft / final の別 case にする。
- [x] grid cells、steps、segments、iterations、output vertices/lines を metric 化する。
- [ ] same vertex count の one-long-line / many-short-lines fixture を追加する。
- [x] compile-cold first activation と warm steady を分ける。
- [x] draft checksum と final checksum を別 contract にする。
- [x] final は現行 exact checksum、または明示した幾何 tolerance を維持する。

### 6.2 FX-04: draft work budget

- [x] `reaction_diffusion` は grid cell 上限と step 上限を別々に適用せず、
      `cells × steps` の work budget で同時に縮小する。
- [x] `growth` は draft iteration と total point の budget を設ける。
- [x] `metaball` は draft の grid 粗粒化と ring 簡略化を決定的に行う。
- [x] requested / effective work を diagnostics と benchmark metric に残す。
- [x] final quality の requested value と出力は変えない。

代表 fixture の draft 目標:

- p95 50 ms 以下
- 同一入力・seed・quality で checksum が決定的
- budget 境界で出力が空になるのではなく、低密度 preview を返す

### 6.3 GEO-02: packed PlanarFrame

- [x] line ごとの `np.diff`、小配列、advanced-index copy を避ける。
- [x] packed coords / offsets のまま重複除去、Newell 合計、最初の有効 edge を求める。
- [x] 既に clean な入力は追加 concatenate なしで利用する。
- [x] orientation、hole、open/closed、degenerate、非平面の意味を固定する。

受け入れ基準:

- 5,000 short lines: 10 ms 以下を目標
- long polyline: 10% を超える退行なし
- `fill`、`clip`、`warp`、`metaball`、`growth`、`isocontour`、
  `reaction_diffusion` の checksum / invariant 一致

### 6.4 JIT-01: first activation

- [ ] compile-cold で 500 ms を超える operation を一覧化する。
- [ ] warm が十分軽い小入力では NumPy path と Numba path の crossover を測る。
- [ ] 小入力だけ NumPy path が有利な operation は、初回 JIT を避ける。
- [ ] 全 effect の eager precompile は行わない。
- [ ] background compile は UI thread、安全性、終了処理の利益が実測で確認された場合だけ検討する。

## 7. Phase 2: interactive renderer / MP / pipeline

### 7.1 GL-03: multi-layer dynamic topology

- [x] 1 / 8 / 100 animated layers の formal case を追加する。
- [x] stable offsets / changing coords と changing topology を control にする。
- [x] dynamic topology / mesh を static full mesh cache と別責務にする。
- [x] layer ごとに安定した offsets identity を 2-hit admission 後に再利用する。
- [x] coordinates は VBO 更新、安定 topology は index build / IBO upload を省く。
- [x] byte と entry の両上限を持ち、release 時に全 GL object を解放する。
- [x] full mesh cache にも tiny mesh 用 entry 上限を追加する。

受け入れ基準:

- 8 layers × 120 frames の index build: 960 回から 16 回以下
- warmup 後の IBO upload: 0
- unique/transient topology で object 数と memory が plateau
- reference Mac の render p95 を 20% 以上改善した場合だけ採用

### 7.2 MP-02: snapshot 重複除去

- [x] revision ごとの immutable plain snapshot を 1 回だけ作る。
- [x] task と control 配布で同じ payload を再構築しない。
- [x] 1 worker は task snapshot の apply ACK 後、同 revision control broadcast を省く。
- [x] pickle time / bytes、queue wait、apply time を分離計測する。
- [ ] 0 / 1 / 2 / 4 workers と 32 / 1,000 / 10,000 parameters を測る。
- [x] full/delta protocolは 1,000 parameters の目標未達が残る場合だけ再検討する。

受け入れ基準:

- 1 worker changing revision の snapshot serialization: 1 回 / revision
- freshness、latest-wins、bounded queue、restart、epoch、last-good の契約を維持
- 1,000 parameters で input-to-result p95 50 ms 以下

### 7.3 RT-04: stale scene の再処理回避

- [x] MP result frame ID と realized frame ID を明示する。
- [x] 新 result も style revision 変化も無い再表示では、retained realized layers を再利用する。
- [x] style だけ変わった場合は geometry を再評価せず style overlay だけ更新する。
- [x] error と成功 result の同時 drain、source reload、quality / epoch 変更を test する。
- [x] sync draw は同じ `t` でも stateful user code を取り得るため、安易に full scene cache しない。

### 7.4 PIPE-02: many-layer 固定費

- [ ] 1 / 10 / 100 / 500 / 2,000 cache-hit layers を測る。
- [ ] layer style を immutable parameter snapshot から参照し、`get_state()` copy を避ける。
- [ ] layer style record の短命 list を frame buffer へ直接 append する。
- [ ] aggregate resource check は維持し、不要な中間 dataclass だけを減らす。
- [ ] draw batching は style / layer 順の意味を変えないことを証明できる場合だけ検討する。

### 7.5 LOOP-01: GUI / preview 順序

現行は preview を先に描き、その後 GUI が store を変更するため、入力反映は最低 1 tick 後になる。

- [ ] Phase 1A 完了後に `preview → GUI` と `GUI → preview` を同一 scenario で A/B する。
- [ ] input-to-present が 1 frame 改善し、idle preview p95 の悪化が 1 ms 未満なら順序を変更する。
- [ ] GUI が重いまま順序だけ先に変更しない。

## 8. Phase 3: 条件付き core / cache 改善

### 8.1 CACHE-02: alias accounting と registry 世代

- [ ] identity / no-op chain で同じ `RealizedGeometry` の byte 重複計上を測る。
- [ ] 実害がある場合だけ object identity + refcount で byte accounting する。
- [ ] registry revision 変更時に旧世代 cache / cacheability を一括回収する。
- [ ] 2Q など複雑な admission は単純 LRU の hot-entry 退行が再現した場合だけ検討する。

### 8.2 FX-05: heavy effect の algorithm

draft budget 後も final / draft の支配項である場合だけ進める。

- [ ] `metaball` の signed-distance grid を ring 単位で再利用し、
      cell × all-segments の総当たりを減らす。
- [ ] `growth` の iteration ごとの flatten / adjacency / scatter 再構築を再利用する。
- [ ] `reaction_diffusion` の kernel、memory traffic、marching squares を profiler で分離する。
- [ ] operation ごとに 20% 以上の p95 改善がない変更は採用しない。

### 8.3 XFORM-01: transform dtype

- [ ] affine / rotate / scale の float64 中間 allocation を計測する。
- [ ] float32 専用経路と現行の数値誤差を比較する。
- [ ] automatic DAG fusion は行わず、単一 operation の単純な経路に限定する。
- [ ] tolerance と速度の両方を満たす場合だけ採用する。

## 9. Phase 4: capture / recording は独立判断する

### 9.1 CAP-02: capture input latency

- [ ] key event から request admission までを 1 ms 未満の contract にする。
- [ ] final scene evaluation、provenance、encode、publish を別 metric にする。
- [ ] WYSIWYG draft capture と final re-evaluation の product contract を先に決める。
- [ ] final capture worker は ParamStore revision、source epoch、GPU context の所有権を
      明確にできる場合だけ導入する。
- [ ] 単に重い処理を次 frame へ移すだけの変更は行わない。

### 9.2 VIDEO-02: readback / encoder backpressure

- [ ] GPU readback、RGB copy、pipe write、ffmpeg backlog を分離計測する。
- [ ] recording frame drop / duplicate / pause の contract を定義する。
- [ ] PBO ring や encoder queue は real GL 計測で readback が支配する場合だけ導入する。
- [ ] queue は bounded latest-wins ではなく、録画の時間順契約に適した明示 backpressure を持つ。

## 10. Benchmark case の追加順

| 優先 | case 群 | 主な metric |
| --- | --- | --- |
| P0 | slider input-to-present | phase別 latency、freshness、stale、revision lag |
| P0 | parameter changed-frame | history、model、merge、widget 数 |
| P0 | heavy effect draft/final | work量、p95、checksum |
| P1 | multi-layer renderer | index build、upload bytes、GL objects、render tail |
| P1 | MP snapshot scaling | serialize bytes/time、queue wait、apply |
| P1 | long cache soak | current RSS slope、GC pause、entries/bytes |
| P1 | PlanarFrame shape matrix | vertices一定、line数 scaling |
| P2 | many-layer pipeline | layer固定費、cache hit、draw call |
| P2 | compile-cold activation | import、compile、first result、warm |
| P3 | capture / video | callback、evaluation、readback、encode、publish |

profile:

- `smoke`: semantic / bound contract を短時間で確認
- `short`: local before/after の代表 case
- `interactive`: reference Mac の実 GUI / 実 GL
- `soak`: 20,000 / 200,000 updates、または時間指定の長期 run
- `cold`: process-cold / compile-cold の first activation

重い matrix を既定 `smoke` に混ぜない。

## 11. 実 GL / 実 GUI の測定構成

### Tier A: deterministic hosted

- fake GL
- programmatic parameter edit
- vsync なし
- geometry checksum と operation count
- resource bound を hard gate

### Tier B: reference Mac offscreen / hidden

- real ModernGL context
- vsync なし
- CPU submit、upload、allocation、非同期 GPU timer query
- `ctx.finish()` は診断 control のみ

### Tier C: reference Mac visible

- 実 pyglet multi-window loop
- vsync あり
- display refresh、scale、framebuffer size、GPU / driver、power状態を記録
- input-to-present、scheduler jitter、flip duration を測定

Tier B / C の wall time は、同じ reference machine の compatible run 間だけ比較する。

## 12. 変更候補ファイル

### benchmark / trace

- `src/grafix/devtools/benchmarks/schema.py`
- `src/grafix/devtools/benchmarks/runner.py`
- `src/grafix/devtools/benchmarks/compare.py`
- `src/grafix/devtools/benchmarks/report.py`
- `src/grafix/devtools/benchmarks/cli.py`
- `src/grafix/devtools/benchmarks/mp_draw_benchmark.py`
- `src/grafix/interactive/runtime/perf.py`
- `src/grafix/interactive/runtime/window_loop.py`
- `src/grafix/interactive/runtime/monitor.py`
- 対応する `tests/devtools/benchmarks/`、`tests/interactive/runtime/`

### Parameter GUI

- `src/grafix/core/parameters/store.py`
- `src/grafix/core/parameters/history.py`
- `src/grafix/core/parameters/memento.py`
- `src/grafix/core/parameters/merge_ops.py`
- `src/grafix/core/parameters/autosave.py`
- `src/grafix/interactive/parameter_gui/table_model.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/table.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/interactive/runtime/parameter_gui_system.py`

### effect / runtime / renderer

- `src/grafix/core/effects/util.py`
- `src/grafix/core/effects/reaction_diffusion.py`
- `src/grafix/core/effects/metaball.py`
- `src/grafix/core/effects/growth.py`
- `src/grafix/core/pipeline.py`
- `src/grafix/core/realize.py`
- `src/grafix/interactive/runtime/mp_draw.py`
- `src/grafix/interactive/runtime/scene_runner.py`
- `src/grafix/interactive/gl/draw_renderer.py`
- `src/grafix/interactive/gl/line_mesh.py`

## 13. 実装しないこと

- slider revision starvation 修正、iterative evaluator、concat、lazy provenance を作り直さない。
- parameter 値を丸めて見かけ上 cache hit にしない。
- frame 途中で sync / MP を自動切替しない。
- queue、cache、trace buffer を無制限にしない。
- fake GL の改善だけで GPU 改善を断定しない。
- final quality の geometry、capture hash、parameter resolution を黙って変えない。
- 全 effect の eager JIT を行わない。
- 計測根拠なしに shared memory、compute shader、全 scene batching、DAG fusion を導入しない。
- 新規依存を追加しない。
- schema v3/v4 の互換 wrapper、shim、二重実装を作らない。

## 14. Phase 共通の停止条件

次の場合は複雑な代案へ進まず、その項目を未完了として記録する。

- checksum、draw order、layer style、Undo/Redo、capture provenance が維持できない。
- median は改善しても p95/p99/max、memory、startup が悪化する。
- reference case の改善が 10% 未満で、複雑性だけが増える。
- hosted runner の時間ノイズしか根拠がない。
- optional cache / batching のために所有権や終了処理が不明瞭になる。
- 実 GUI / 実 GL で再現しない推測上の問題である。

## 15. 実装順と進捗

- [x] 現行 worktree / 実装 / 既存計画の監査
- [x] core / interactive / benchmark の並行監査
- [x] 新しい性能改善計画の作成
- [x] 計画承認
- [ ] Phase 0: BENCH-02 / UX-01 / TRACE-02
- [ ] Phase 0 baseline と noise study
- [ ] Phase 1A: ParamStore / GUI
- [ ] Phase 1B: draft effect / PlanarFrame / first activation
- [ ] Phase 2: renderer / MP / pipeline / loop 順序
- [ ] Phase 3: 条件付き core / cache
- [ ] Phase 4: 条件付き capture / recording
- [x] full test / 対象 Ruff / mypy
- [ ] reference Mac の実 GUI / 実 GL
- [ ] 10 分以上または 200,000 update の soak
- [x] before / after / contract / checksum の実装時点 report

### 15.1 実装結果（2026-07-18）

今回の優先実装で完了した範囲は次の通り。

- benchmark schema v4、typed metric / distribution / hard-soft contract、CLI failure、
  compare、HTML report、self-sampling scenario
- fake GUI / fake GL の input-to-present formal case と causal trace
- patch history、structure/value/style revision、単一 key sparse refresh、merge rollback
- drag 中 autosave 抑止
- heavy effect の deterministic draft budget と draft/final checksum contract
- packed `PlanarFrame`
- multi-layer dynamic mesh pool、static/dynamic cache の byte/entry 上限
- MP snapshot の revision 単位 1-copy と 1-worker duplicate broadcast 除去
- stale scene の realized geometry 再利用と style-only overlay
- Inspector を preview より先に処理する同一 tick 入力経路

#### Formal benchmark 結果

すべて 2026-07-18 の同一 worktree、seed 0。effect は warm 21 samples、
Parameter/UX/renderer は内部 sample を持つ deterministic self-sampling case である。

| case | median | p95 | hard contract |
| --- | ---: | ---: | ---: |
| `effect.growth.draft.rings_2` | 14.714 ms | 15.082 ms | 1 / 1 pass |
| `effect.metaball.draft.rings_2` | 23.479 ms | 24.208 ms | 1 / 1 pass |
| `effect.reaction_diffusion.draft.rings_2` | 44.801 ms | 45.474 ms | 1 / 1 pass |
| `gui.parameter_edit.rows_100` | 0.0666 ms | 0.1212 ms | 16 / 16 pass |
| `gui.parameter_edit.rows_1000` | 0.1173 ms | 0.1627 ms | 16 / 16 pass |
| `gui.parameter_edit.rows_10000` | 0.6672 ms | 0.7254 ms | 16 / 16 pass |
| `interactive.slider.input_to_present.rows_32.workers_0` | 0.178 ms | 0.221 ms | 10 / 10 pass |
| `interactive.slider.input_to_present.rows_1000.workers_0` | 1.098 ms | 1.225 ms | 10 / 10 pass |
| `interactive.slider.input_to_present.rows_32.workers_1` | 26.220 ms | 31.065 ms | 10 / 10 pass |

draft effect の探索 before 値との比較では、p95 は `growth` 約 24.3 倍、
`metaball` 約 124.8 倍、`reaction_diffusion` 約 75.8 倍高速になった。
3 case とも p95 50 ms guardrail を満たし、draft checksum contract も通過した。
final checksum は既存 exact 値を hard contract として維持している。

Parameter changed-frame は 100 / 1,000 / 10,000 rows の全 case で、
changed frame ごとの full memento capture と table structure rebuild が 0 回、
変更 key / row が 1 件であることを contract で確認した。

renderer formal case は次の結果になった。

| topology | layers × frames | index build | VBO-only update | contract |
| --- | ---: | ---: | ---: | ---: |
| stable | 1 × 12 | 1 | 11 | 4 / 4 pass |
| stable | 8 × 12 | 8 | 88 | 4 / 4 pass |
| stable | 100 × 12 | 100 | 1,100 | 4 / 4 pass |
| changing control | 8 × 12 | 96 | 0 | 4 / 4 pass |

従来の 8 layers × 120 frames では 960 回だった index build は、安定 topology
なら layer ごとの初回 8 回だけとなり、同条件換算で 99.17% 削減される。
dynamic entry / byte 上限も全 case で contract を満たした。

追加の micro 計測では、packed `PlanarFrame` は many-short-lines が
45.11 ms から 0.895 ms（約 50.4 倍）、one-long-line が 6.57 ms から
5.609 ms（約 14.6% 改善）。PerfCollector の production-like 12,000 frame
計測は trace 有効時でも約 0.067 ms/frame で、0.2 ms/frame の目標内だった。
MP は plain snapshot 1 copy / revision、1-worker control broadcast 0 を
unit/formal scenario で確認した。

成果 JSON:

- `/tmp/grafix-final-effects-20260718-current21/runs/`
- `/tmp/grafix-final-param-20260718-current/runs/`
- `/tmp/grafix-final-ux-20260718-current/runs/`
- `/tmp/grafix-final-renderer-20260718-current/runs/`
- `/tmp/grafix-general-current-20260718/runs/`

#### エフェクト非依存の全般的な改善効果

以下では、特定 effect の draft budget を除外して評価する。倍率は、同一 harness の
before / current 実測、operation count からの換算、構造上の試算を区別する。

| 領域 | before | current | 改善効果 | 根拠 |
| --- | ---: | ---: | ---: | --- |
| Parameter changed-frame、1,000 rows、p95 | 30.814 ms | 0.108 ms | 285 倍、99.65% 削減 | HEAD/current の同一 CPU harness |
| Parameter changed-frame、10,000 rows、p95 | 307.778 ms | 0.403 ms | 763 倍、99.87% 削減 | HEAD/current の同一 CPU harness |
| 8 stable layers × 120 frames の index build | 960 回 | 8 回 | 120 倍、99.17% 削減 | formal counter の同条件換算 |
| 1-worker snapshot payload / revision | 2 payload 相当 | 1 payload | copy / transport 約 50% 削減 | code path と counter |
| autosave during active drag、1,000 rows | p50 4.0 ms、max 8.7 ms | 0 ms | 操作中 stall を除去 | 探索 before と suspension test |
| common `PlanarFrame`、many-short | 45.11 ms | 0.895 ms | 50.4 倍、98.02% 削減 | geometry 共通前処理の micro 実測 |
| common `PlanarFrame`、one-long | 6.57 ms | 5.609 ms | 1.17 倍、14.63% 削減 | 同上 |

Parameter harness は ImGui / GPU / provenance を含まない。現在のより広い formal case では、
1,000 / 10,000 rows の p95 はそれぞれ 0.163 / 0.725 ms で、changed frame の
full memento と table structure build はどちらも 0 回だった。10,000 rows は
旧 p95 で約 18.5 frames 分あった CPU stall 要因を、frame budget の 2.4% 程度へ
縮小した。ただし row virtualization は未実装なので、実 ImGui の全 widget 描画まで
763 倍になったという意味ではない。

Inspector を preview より先に処理することで、parameter 数や effect 種類に依存しない
固定 1 tick を除去した。短縮量は `1000 / refresh_rate` ms なので、30 / 60 / 120 /
144 Hz でそれぞれ約 33.3 / 16.7 / 8.3 / 6.9 ms となる。fake GUI / fake GL の
60 Hz モデルでは次のレンジになる。

- 32 rows sync: 旧順序なら p95 約 16.9 ms 相当、current 0.221 ms
- 1,000 rows sync: 旧順序と旧 changed-frame CPU cost の重なりを考慮すると
  約 31〜48 ms 相当、current 1.225 ms。約 25〜39 倍、96〜97% 短縮の試算
- 32 rows / 1 worker: 操作中 fresh 0 / 120 だった freeze case から、
  fresh 約 99〜100%、current input-to-present p95 31.065 ms、revision lag 最大 1

stale MP result の再表示は、従来の cache-hit `realize_scene()` を毎 display frame
実行する経路と、retained geometry を返す経路を同一 process で比較した。
128 vertices / layer の counterfactual probe の p95 は次の通り。

| layers | 毎回 re-realize | retained reuse | 改善 |
| ---: | ---: | ---: | ---: |
| 1 | 0.0233 ms | 0.00521 ms | 4.5 倍 |
| 10 | 0.1340 ms | 0.00496 ms | 27.0 倍 |
| 100 | 1.3488 ms | 0.00529 ms | 254.9 倍 |

実運用での削減率は worker result rate に依存する。60 Hz 表示に対し worker が
30 / 15 / 10 Hz なら、重複 realize / upload の削減見込みは約 50 / 75 / 83%。
fresh geometry、同期 draw、recording/final、毎 frame topology が変わる scene には
この倍率を適用しない。

MP snapshot の旧探索値は 1 payload 当たり 32 / 1,000 / 10,000 parameters で
0.058 / 1.94 / 21.97 ms、2.3 / 65 / 650 KiB だった。既定 1-worker で
task + duplicate control の 2 payload 相当から 1 payload へ減るため、revision 当たり
同量を節約する。60 revisions/s の上限試算では、1,000 parameters で約 116 ms CPU/s
と 3.8 MiB/s、10,000 parameters で約 1.32 CPU s/s と 38 MiB/s の転送相当を削減する。
これは serialization 部分の上限試算であり、end-to-end latency そのものではない。

全般的な総括として、軽量〜1,000 parameter の通常編集は freeze 解消に加えて
入力経路が約 25〜39 倍相当、大規模 10,000 parameter の CPU hot path 単体は
約 763 倍改善したと試算する。stable multi-layer renderer は topology/index 段階で
最大 120 倍だが、全 render 時間へ Amdahl 則を適用した現実的な期待レンジは
約 1.1〜2 倍である。static scene と毎 frame topology が変わる scene は原則横ばいで、
全 scene が一律に同じ倍率で高速化するわけではない。

#### 検証結果

- `pytest`: 1,529 passed
- `ruff check src tests`: pass
- `mypy src/grafix`: 213 files、issue 0
- `git diff --check`: pass
- 統合再監査: 対象範囲に残る P1 / P2 なし
- `ruff check .`: 今回の変更外である `.agents/` と `sketch/` の既存 33 件により failure。
  今回変更した `src/` / `tests/` には error なし

#### 未完了

- pyimgui2 / Dear ImGui 1.82 binding に `ListClipper` と active item ID API がなく、
  現行行は可変高かつ MIDI assignment が row render 時に動くため、手動 clip は操作を
  壊し得る。停止条件に従い row virtualization は未実装
- 実 ImGui / 実 GL / visible vsync の reference Mac 計測、交互 block noise study
- trace の history / table / autosave / provenance / capture 個別 section、
  resource gauge、source/diff/display/backend header
- changed-frame の MIDI / favorite / range / collapse 個別 formal contract と allocation count
- JIT first-activation crossover、many-layer pipeline、MP 0/1/2/4 workers ×
  32/1,000/10,000 parameters の全 matrix
- Phase 3 の条件付き cache / heavy-effect algorithm / transform dtype
- capture / video の実測に基づく条件付き改善
- 10 分以上または 200,000 update の long soak

## 16. 全体の完了定義

次をすべて満たした時点で、本計画を完了とする。

1. benchmark が checksum だけでなく hard performance contract を exit code へ反映する。
2. slider の input-to-present を GUI、realize、render、flip 込みで再現できる。
3. trace から遅い frame の parameter revision と各処理段階を追跡できる。
4. 1,000 parameter の単一キー drag で full memento と table structure rebuild が 0 回になる。
5. 10,000 parameter GUI の widget work が表示行数に比例する。
6. heavy effect の draft representative case が p95 50 ms 以下に収まり、final 出力は変わらない。
7. 複数 animated layer の index / IBO 再構築が warmup 後に止まる。
8. 1-worker revision churn で snapshot serialization が 1 回 / revision になる。
9. cache、queue、GPU object、RSS が long soak で plateau する。
10. reference Mac の UX guardrail、全 checksum、既存 test、lint、type check が通る。
