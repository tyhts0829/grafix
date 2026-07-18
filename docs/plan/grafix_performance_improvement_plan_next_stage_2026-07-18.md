# Grafix 次段階パフォーマンス改善計画（現行実装再監査）

- 作成日: 2026-07-18
- 基準 commit: `cb807d7`
- 状態: 今回対象の実装・検証完了。Phase 1、PERF-04、GEO-03、GL-04 の
  低リスク部分を採用し、実 GUI / 実 GL / I/O / soak は未実施
- 対象:
  - Parameter GUI / ParamStore / autosave
  - interactive preview / multiprocessing / renderer
  - core geometry / pipeline / JIT
  - capture / video recording
  - packaged benchmark / runtime trace / 性能回帰判定
- 関連資料:
  - `docs/plan/grafix_performance_improvement_plan_current_state_2026-07-18.md`
  - `docs/plan/interactive_slider_stutter_investigation_and_improvement_plan_2026-07-18.md`
  - `docs/plan/grafix_performance_improvement_implementation_plan_2026-07-17.md`
  - `docs/memo/performance.md`

本計画は、前計画で完了した改善を再実装するものではない。現行コードと benchmark
registry を改めて読み直し、まだ正式計測されていない全般的な固定費、実 GUI / 実 GL
でしか見えない待ち時間、capture / recording の操作影響を次の対象として整理する。

## 0. 今回の実装・検証結果

### 0.1 完了した範囲

- 10,000 行を含む deterministic CPU benchmark を 12 case 追加し、registry を
  74 case から 86 case へ拡張した。
- static group layout、model-index の filtered layout、stable merge cache、
  bounded snapshot overlay、visibility/search cache、favorite immutable view を実装した。
- `PerfCollector` の causal pending を ordered prefix だけ処理するようにした。
- MP 用 snapshot plain dict 化を overlay-aware にした。
- trusted offsets を使う effect wrapper fast path と、同一 style の renderer uniform
  write cache を追加した。
- benchmark checksum を行数だけでなく、row/header/order、snapshot 全内容、
  effective/source/explicit、latency/drop/revision bounds まで検証する形へ強化した。
- 負の MIDI CC を含む部分一致、動的 source/MIDI 検索、favorite/error/loaded 変化、
  filtered model-index layout を pure reference と照合した。

### 0.2 最終 current 値

`after-final4-hotpaths-worktree`、warm、24 self-samples、no-ImGui CPU scope の結果。
12 case はすべて `status=ok` で、hard / soft contract は全件合格した。

| 10,000 行 case | current median | current p95 | 目標 |
| --- | ---: | ---: | ---: |
| stable favorite immutable view | 0.000250 ms | 0.000439 ms | 1 ms |
| stable group layout reuse | 0.023520 ms | 0.026869 ms | 1 ms |
| default visibility | 0.003021 ms | 0.005423 ms | 1 ms |
| search typing 全体 | 1.312833 ms | 4.535186 ms | 8 ms |
| dynamic source/MIDI search | 4.394646 ms | 5.341044 ms | 8 ms |
| stable merge、毎 sample 新規等価 record | 4.906875 ms | 5.050494 ms | 8 ms |
| one-key immutable snapshot | 0.003020 ms | 0.010767 ms | 1 ms |
| causal backlog future-head、4,096 pending | 0.001437 ms | 0.003779 ms | 0.02 ms |

同じ driver を基準 commit へそのまま適用できない case があるため、次の改善率は
formal timing gate ではなく、旧実装へ同条件の局所 driver を適用した参考試算である。
current の絶対値と semantic contract を正式結果とし、改善率を過度に一般化しない。

| 経路 | base / 旧実装参考 p95 | current p95 | 参考削減率 |
| --- | ---: | ---: | ---: |
| stable group layout | 37.712 ms | 0.026869 ms | 99.93% |
| production-like fresh-record merge | 38.502 ms | 5.050494 ms | 86.9% |
| one-key snapshot | 23.482 ms | 0.010767 ms | 99.95% |
| default visibility | 9.913 ms | 0.005423 ms | 99.95% |
| search typing | 61.109 ms | 4.535186 ms | 92.6% |
| causal future-head | 0.825 ms | 0.003779 ms | 99.54% |

全般的な changed-frame 指標として、同一 no-ImGui driver の 10,000 行 parameter edit
p95 は 0.707833 ms から 0.456698 ms へ 35.5% 減少した。one-key snapshot と
plain MP payload の合計 p95 は 20.049 ms から 2.409 ms へ 88.0% 減少した。
これらは特定 effect の algorithm ではなく、共通 Parameter / MP handoff の改善である。

追加の局所 probe では、trusted offsets により validation p95 が one-long で約 76%、
many-short で約 91%、100,000〜1,000,000 offsets の validation-only 区間で
約 96.7〜99.9% 減少した。Fake GL の同一 style draw では uniform 設定を省き、
1 / 8 / 100 layer の CPU draw 区間 p95 が約 53% / 61% / 65% 減少した。
どちらも effect 全体または visible frame 全体の改善率ではない。

### 0.3 トレードオフと未完了範囲

- 10,000 行 model 初回 build は参考 probe で median 110.85 ms から 116.68 ms
  へ 5.3% 増え、retained allocation は約 5.12 MiB から 11.48 MiB へ増えた。
  immutable layout / search corpus / group index の bounded な保持コストである。
- 10,000 record の初回 discovery merge は median 42.40 ms から 62.97 ms
  へ 48.5% 増え、stable cache の retained allocation は約 1.60 MiB 増えた。
  steady fresh-record merge の削減で数 frame 内に回収するが、startup 退行として残す。
- 実 ImGui / visible window、実 GL / GPU / flip-return、ABAB noise study、
  10 分 soak は未計測である。画面を取得できない実行環境では real GL context を
  作成できなかったため、Fake GL の局所値を visible UX の値として扱わない。
- MP delta protocol は、overlay-aware handoff が p95 2.409 ms まで下がり、
  設計着手条件を示す正式 worker matrix が未取得のため実装しなかった。
- autosave write-behind、capture、video、JIT inventory は今回の deterministic CPU
  hot path と独立しており、完全な immutable persistence payload と現場 trace が
  揃うまで未実装とした。
- row virtualization は現 binding に `ListClipper` / active item ID がなく、
  text / MIDI / keyboard semantics を証明できないため実装しなかった。

### 0.4 最終検証

- `PYTHONPATH=src ... pytest -q -p no:cacheprovider`: **1603 passed**
- `ruff check src tests`: **pass**
- `mypy src/grafix`: **215 source files、issue 0**
- `git diff --check`: **pass**
- `parameters` benchmark suite: **12 / 12 status ok、failed contract 0**
- read-only 追加監査:
  - search pure semantics: 1,600 random cases 一致
  - filtered model-index layout: 3,000 random masks で従来 regroup と一致
  - fake ImGui の非連続 model index、描画順、favorite、sparse edit、ID stack を確認

## 1. 結論

次段階は、以下の順で進める。

1. **現場と同じ経路を測れる benchmark / trace を先に完成させる**
   - 現在の 74 case は CPU correctness と fake GUI / fake GL の回帰検出には強い。
   - 一方、実 ImGui widget、GL submit、GPU、vsync、`Window.flip()`、capture、
     video、実ユーザー初回 JIT activation は測れていない。
   - reference Mac の ABAB 計測と noise-aware 判定を整備するまで、wall time を
     hosted CI の hard gate にしない。
2. **10,000 parameter で再び全件処理になる CPU 経路を減らす**
   - table の静的 group/layout 再構築
   - stable frame の `merge_frame_params()`
   - 単一値変更後の `store_snapshot()`
   - visibility / search filter
   - favorite 集合の再生成
   - `PerfCollector` の大きな causal backlog 全走査
3. **実 GUI の結果を見て row virtualization を安全に判断する**
   - 現 binding では `ListClipper` と active item ID API を利用できない。
   - MIDI learn、text edit、keyboard navigation を壊す単純な scroll-index clip は
     実装しない。
   - 先に row 描画の副作用を分離し、layout model と app-owned active row を作る。
4. **MP、renderer、many-layer は matrix 計測後に限定して最適化する**
   - full parameter snapshot の delta 化
   - 同一 style の redundant uniform write 除去
   - layer batching、worker-side realize、shared memory
   - これらは支配率と 20% 以上の end-to-end 改善を確認できた場合だけ採用する。
5. **autosave、capture、video、JIT は操作待ち時間として独立に扱う**
   - mutable `ParamStore` を background thread から読ませない。
   - capture は同期時間だけでなく、draft/final 切替による MP epoch と preview
     freshness への影響も測る。
   - video は readback と ffmpeg pipe write を分離して測る。

最優先は effect 個別のアルゴリズム変更や renderer 全面改造ではない。まず、軽い描画でも
発生する全般的な CPU 固定費と、現場の input-to-flip-return / present tail を同じ
計測系で結び付ける。

## 2. 現行実装の基準点

### 2.1 解消済みとして固定する項目

以下は前段階で完了している。次の実装で回帰させず、原則として再設計しない。

- benchmark schema v4
  - typed metric / distribution / contract
  - hard contract の CLI exit 反映
  - compare / offline report
  - fresh process、warm / process-cold / compile-cold
- Parameter
  - patch history
  - structure / value / style revision の分離
  - table model の sparse one-key value refresh
  - drag 中の autosave suspension
- effect / geometry
  - `growth` / `metaball` / `reaction_diffusion` の deterministic draft budget
  - packed `PlanarFrame`
- runtime / multiprocessing
  - parameter revision starvation の解消
  - 1-worker の重複 control snapshot 配布除去
  - stale result の retained geometry 再利用
  - GUI-first 処理順による固定 1 tick の除去
- renderer
  - dynamic mesh pool
  - entry / byte 上限
  - stable topology の VBO-only upload
  - multi-layer topology reuse
- runtime trace
  - bounded asynchronous writer
  - frame tail / causal event の基礎

### 2.2 現行 formal benchmark

registry は 74 case、うち self-sampling は 12 case である。

| category | case 数 |
| --- | ---: |
| effect | 35 |
| interactive | 13 |
| gui | 6 |
| micro | 6 |
| core | 4 |
| runtime | 4 |
| system | 3 |
| mp | 2 |
| pipeline | 1 |

代表的な現行値は次の通り。数値は同一 harness の current 値であり、異なる表の値を
直接足し合わせない。

| case | median | p95 | scope |
| --- | ---: | ---: | --- |
| parameter edit / 100 rows | - | 0.121 ms | no-ImGui |
| parameter edit / 1,000 rows | - | 0.163 ms | no-ImGui |
| parameter edit / 10,000 rows | - | 0.725 ms | no-ImGui |
| slider / 32 rows / sync | - | 0.221 ms | fake GUI / fake GL |
| slider / 1,000 rows / sync | - | 1.225 ms | fake GUI / fake GL |
| slider / 32 rows / 1 worker | - | 31.065 ms | fake GUI / fake GL |
| static renderer / 100k lines | 0.234 ms | 0.265 ms | fake GL |
| animated coords / static offsets / 100k | 0.279 ms | 0.473 ms | fake GL |
| changing topology / 100k | 3.297 ms | 3.513 ms | fake GL |
| stable provenance / 1,000 rows | 0.002 ms | 0.004 ms | CPU |
| changed effective provenance / 1,000 rows | 20.712 ms | 21.480 ms | CPU |

stable multi-layer renderer の 12 frames では、1 / 8 / 100 layers に対し index build が
1 / 8 / 100 回、VBO-only upload が 11 / 88 / 1,100 回である。既存の topology reuse
は期待どおり動いている。

### 2.3 新たに確認した探索値

以下は `cb807d7`、同一ローカル環境、warm synthetic fixture の探索値であり、
正式な before 値ではない。Phase 0 で packaged benchmark 化してから採否を決める。

| 経路 | 規模 | 探索値 |
| --- | ---: | ---: |
| `group_blocks_from_rows()` | 10,000 rows | median 34.05 ms |
| stable `merge_frame_params()` | 10,000 records | median 21.82 ms、p95 23.95 ms |
| 単一値変更後の `store_snapshot()` | 10,000 rows | median 25.34 ms |
| default parameter table view | 10,000 rows | median 9.36 ms |
| search filter | 10,000 rows | median 51.75 ms |
| `dumps_param_store()` | 10,000 rows | median 25.59 ms |
| 全行 favorite の sort / copy | 10,000 rows | median 5.41 ms |
| causal pending match | 4,096 entries | median 0.330 ms、max 3.39 ms |

これらは、既存の `gui.parameter_edit` が速いことと矛盾しない。現 formal case は
no-ImGui の変更反映を中心に測っており、毎 frame の grouping、全 draw record merge、
実 widget submit、単一変更後の共通 snapshot 再構築を同時には通していない。

### 2.4 現行計測の空白

| 領域 | 現状 | 次に必要なもの |
| --- | --- | --- |
| Parameter edit | no-ImGui | 実 widget と全 frame 経路 |
| slider UX | fake GUI / fake GL | visible window、flip、vsync |
| renderer | fake GL | 実 driver、GPU、present |
| capture | formal case 0 | admission から publish まで |
| video | formal case 0 | readback+materialize、pipe、finalize |
| JIT | full activation case 0 | import / register / first-call inclusive / warm |
| memory | peak RSS 中心 | current RSS slope、GC pause、resource plateau |
| soak | 短い case 中心 | 10 分または 200,000 update |
| compare gate | contract / checksum | reference Mac の noise-aware timing gate |

`compile-cold` は空の `NUMBA_CACHE_DIR` で first evaluator と Numba compile を
部分的に測っている。一方、現 runner では `setup()` が timed workload の外側にある。
そのため、lazy import と registry 登録まで含む実ユーザーの「最初に effect を使った
瞬間」はまだ測れていない。

## 3. 性能目標と判定方針

### 3.1 Interactive UX

reference Mac の visible-window profile では次を guardrail とする。通常の window
計測で取得できるのは `input-to-flip-return` であり、これを present proxy として保存する。
OS / driver の presentation feedback または外部計測が無い場合、物理表示完了を測った
`input-to-present` とは表記しない。

- input-to-flip-return p95: 50 ms 以下
- 改善目標: 33.3 ms 以下
- fresh displayed result ratio: 90% 以上
- consecutive stale display: 2 frames 以下
- parameter revision lag p95: 2 以下
- drag release から最終 revision 表示: 100 ms 以下
- input callback から capture intent 記録までの p95: 1 ms 以下
- final evaluation を除く job enqueue 自体の p95: 1 ms 以下
- 16.7 ms deadline miss 率、p99、max も保存する

### 3.2 Parameter / GUI

- 1,000 row changed draw p95: 4 ms 以下
- 10,000 row stable grouping: build 0 回
- 10,000 row stable merge p95: 8 ms 以下
- 10,000 row single-key snapshot p95: 1 ms 以下を目標
- 10,000 row default visibility p95: 1 ms 以下
- 10,000 row search query p95: 8 ms 以下
- virtualization 採用時:
  - widget submission 数が viewport 行数 + overscan + pinned 行数に比例
  - 10,000 row actual widget draw p95: 8 ms 以下
  - drag / text / MIDI / keyboard navigation の意味を変えない

snapshot の 1 ms 目標が単純な immutable 設計で達成できない場合、複雑な永続 map を
導入するのではなく、entry copy 削減または MP delta 専用 patch までで停止する。

### 3.3 Trace / resource

- production trace overhead:
  - 目標 p95 0.1 ms/frame 以下
  - guardrail p95 0.2 ms/frame 以下
- reference run の trace drop: 0
- CPU / GPU cache、queue、mesh、GL object は entry と byte の両方で bounded
- 10 分または 200,000 update の後半で resource count が plateau
- warmup 後の main / MP worker / export worker / ffmpeg と process tree 集計 RSS の
  後半傾き:
  - 暫定 soft guardrail 1 MiB/min 以下
  - noise study 後にのみ hard gate 化を検討

### 3.4 回帰判定

#### Hosted CI

hard gate にするもの:

- checksum / dtype / shape / finite / offsets invariant
- revision、frame index、time、epoch の単調性
- latest-wins または lossless-order contract
- queue / cache / object / byte 上限
- timeout、worker death、unexpected reject、trace footer 欠落
- hard contract の pass

wall time、GPU time、RSS 絶対値は hosted runner では observation に留める。

#### Reference Mac

最初に base/head を ABAB block で交互実行し、thermal drift と order effect を保存する。
environment fingerprint が一致する明示 profile でのみ、次を timing gate 候補とする。

- median: 10% 超の悪化、かつ差が 3 × MAD を超える
- p95: 20% 超の悪化
- absolute UX guardrail 違反

noise が閾値と同程度、fingerprint 不一致、self-sampling case の block 順を制御できない
場合は timing gate を有効化しない。

## 4. Phase 0: benchmark と trace を現場相当にする

### 4.1 BENCH-05: case scope と capability を明示する

- [ ] case に `fake-gui` / `real-imgui` / `fake-gl` / `real-gl` /
  `visible-window` / `reference-only` の capability を明示する
- [ ] capability 不足は pass ではなく、理由付き skip として artifact に残す
- [ ] smoke、deterministic CPU、reference Mac、soak profile を分離する
- [x] 既存 74 case の checksum と contract を維持する
- [x] `docs/memo/performance.md` の schema v3 表記を現行 v4 へ同期する

### 4.2 BENCH-06: Parameter の見逃し経路を formal 化する

追加候補:

- `gui.parameter_layout.rows_{1000,10000}`
- `gui.parameter_visibility.rows_{1000,10000}.mode_{default,search,favorite,error}`
- `runtime.parameter_merge.rows_{1000,10000}.change_{steady,one,all}`
- `runtime.parameter_snapshot.rows_{1000,10000}.change_{one,structure}`
- `gui.parameter_favorites.rows_10000`

保存する metric:

- group build count / group count / row index count
- mask rebuild count / predicate evaluation count / query parse count
- merge record count / rollback entry count / explicit follow count
- snapshot rebuilt entry count / copied bytes / mapping materialization count
- favorite sort / copy count
- median / MAD / p95 / p99 / allocation count

hard contract:

- row 順序、group header、collapse key、snippet 対応が現行と一致
- `effective_revision`、source、explicit follow、last-good rollback が一致
- snapshot は frame 内で固定され、canonical value の alias 安全性を守る
- initial discovery と structure change は汎用経路で正しく動く

今回、layout、default/search visibility、stable merge、one-key snapshot、
favorite、causal backlog の 12 case を `parameters` suite として追加した。
favorite/error 専用 visibility、merge one/all、snapshot structure、effect family shape
の formal case は未追加であり、既存 correctness test と局所 probe でのみ検証した。

#### Effect shape coverage

非 heavy effect は原則 1 fixture なので、全 effect の直積を増やさず、family 代表だけ
等頂点の one-long / many-short / many-rings で測る。

- transform: `scale`
- line-wise: `dash` / `trim` / filter 系の代表
- topology-changing: `fill`
- planar / binary: `warp` または `clip`

保存する metric は wrapper、validation、planar conversion、effect body とする。
これにより effect 固有のアルゴリズムではなく、line 数に比例する共通固定費を検出する。

### 4.3 BENCH-07: 実 ImGui / 実 GL / visible window

- [ ] 実 ImGui で 100 / 1,000 / 10,000 rows の widget submission を測る
- [ ] stable、one-key drag、filter typing、collapse、text edit、MIDI learn を分ける
- [ ] sync / 1-worker の slider を visible 60 Hz で実行する
- [ ] pyglet/backend の入力 callback で event sequence と timestamp を採り、
  parameter revision から flip return まで引き継ぐ
- [ ] input callback、GUI apply、history、merge、snapshot、draw、realize、upload、
  submit、GPU、flip return を分ける
- [ ] Retina / non-Retina、resize、Inspector focus の metadata を保存する
- [ ] fake harness は deterministic contract 用として残す

GPU timing は asynchronous timer query を使い、通常計測で `ctx.finish()` を挿入しない。
flip return、物理 present、GPU 完了を混同しない。
query は発行元 frame ID を持つ bounded outstanding ring で管理し、後続 frame で得た結果を
発行元へ帰属させる。未回収 / drop / shutdown drain を contract に含め、結果受取 frame
の CPU 時間として誤集計しない。

### 4.4 TRACE-03: causal section と resource gauge

追加する section / gauge 候補:

- history patch
- table layout / visibility / widget
- merge / snapshot / provenance
- autosave serialize / write / fsync
- capture final-eval / provenance / encode / publish
- draw call、uniform write、VBO / IBO upload bytes
- CPU / GPU cache entries・bytes
- renderer-owned GL create / release / live object count
- app-owned MP submitted / started / completed / dropped / pending / restart count
- process ごとの current RSS、process-tree RSS、GC pause
- recording readback+materialize / pipe write / queue

macOS では `multiprocessing.Queue.qsize()` を前提にしない。pending は app-owned counter
の差分から定義し、GL object も ModernGL の列挙ではなく renderer の create / release
counter から定義する。

trace header へ次を保存する。

- source identity / dirty diff hash
- case / sketch / seed
- parameter count / layer count
- display size / scale / refresh rate
- GUI / GL backend
- worker count
- quality / recording / capture 設定

`runtime.perf.production_trace.frames_12000` を追加する。
`PerfCollector.finish_frame()` の snapshot 集計と JSON encode は、この正式 full-event
benchmark で p99 が 0.2 ms を超えるか、max 0.2 ms 超が複数 block で再現する場合だけ
変更する。その場合は Inspector snapshot publish を約 10 Hz へ decimate し、JSON
encode を bounded writer 側へ移す。既存 production-like 探索値は trace 有効時でも
約 0.067 ms/frame であり、現時点での全面書き換えは不要である。

### 4.5 BENCH-08: noise-aware compare

- [ ] base/head を別 `BenchmarkRun` として ABAB 順に実行する runner を追加する
- [ ] run を混在させず、順序と対応を持つ paired comparison manifest を追加する
- [ ] block ごとの power source / mode、refresh rate、thermal pressure、
  clock/order drift を取得可能な範囲で artifact に保存する
- [ ] sensor 温度は nullable capability とし、取得不能でも失敗させない
- [ ] pooled MAD、median ratio、p95 ratio、order drift を表示する
- [ ] timing gate は明示 reference profile でのみ有効にする
- [ ] hosted CI では timing gate が誤って有効にならない contract を追加する

### 4.6 Phase 0 の完了条件

- [x] 現 formal case と探索 hot path の scope 差を report 上で説明できる
- [ ] 1 回の slider trace から最長 3 section と parameter revision を特定できる
- [ ] fake / real、CPU / GPU、submit / flip return / physical present を混同しない
- [ ] before artifact を保存し、以後の Phase が同一 case で比較できる

## 5. Phase 1: 全般的な Parameter CPU 固定費を減らす

### 5.1 PARAM-05: 静的 group/layout model

現状:

- `render_parameter_table()` が `group_blocks_from_rows()` を呼び、stable frame でも
  rows から block を再構成する。
- filter 後の部分 block、effect heading、snippet、collapse key が同じ処理へ混在する。

方針:

1. `ParameterTableModel` に immutable な group/layout を格納する。
2. block は `ParameterRow` の複製ではなく、model row index / range を参照する。
3. `ParameterTableView` は visible row index と visible group を保持する。
4. `render_parameter_table()` は layout と view を受け、再 grouping しない。
5. structure revision、registry revision、grouping metadata が変わった時だけ full rebuild する。

acceptance:

- [x] 10,000 row stable frame の group build が 0 回
- [x] stable grouping p95 1 ms 以下
- [x] row 順序、header、collapse、snippet、effect-step ordinal が一致
- [x] filter で一部だけ見える group の header semantics が一致
- [x] structure change は 1 回の rebuild で反映される

停止条件:

- filtered partial block の同値性を保つため毎 frame 全 block 再構成が必要になる場合、
  view layout の設計を先に見直し、二重 cache を追加し続けない。

### 5.2 PARAM-06: stable merge fast path

現状:

- 既存 record でも canonicalize、rollback dict 構築、explicit key 集合構築、
  事後 scan が繰り返される。

方針:

1. schema / ordinal / effect-step が既知の record を stable path とする。
2. 既存 state の base canonicalize を省ける条件を明示する。
3. effective / source が変化した key だけ rollback entry を持つ。
4. explicit follow の判定を同じ pass へ統合する。
5. 同一 key が 1 frame に複数回現れる場合は現行どおり last-record-wins とし、
   途中 record の explicit/effective を確定値として公開しない。
6. stable eligibility は cached structure metadata から判定し、判定だけの全 record
   pre-scan を追加しない。
7. initial discovery、structure change は、変更を始める前に判定して単一の汎用 path
   へ入る。
8. stable path の途中で例外が出た後に generic path を再実行しない。

acceptance:

- [x] 10,000 stable records の p95 8 ms 以下
- [x] one-key change の rollback entry 1 以下
- [x] all-key animated の throughput を悪化させない
- [x] duplicate-key case で last-record-wins を維持する
- [x] `effective_revision` と last-good state が現行と完全一致
- [x] merge 途中の例外でも runtime effective / source の last-good 値を維持する

停止条件:

- fast path と generic path の二重実装が大きくなる場合は、単一 pass 化だけで止める。
- failed-frame rollback の意味が変わる実装は採用しない。

### 5.3 PARAM-07: immutable snapshot の変更 key 差し替え

現状:

- `store_snapshot()` は同一 revision では cache hit する。
- ただし単一値変更でも store revision が進むと、10,000 entry の mapping を再構築する。
- 同じ snapshot は draw、MP、GUI の境界で使われる。
- autosave は現在 `ParamSnapshot` を使わず、永続化対象を `ParamStore` から直接
  走査する。collapsed header、lock、favorite、variation 等を含む完全な persistence
  snapshot は別設計が必要である。

方針:

1. まず entry clone と mapping materialization の時間・byte を分離する。
2. canonical immutable state / meta entry を key 単位で再利用する。
3. one-key patch で旧 frame snapshot が変化しない ownership contract を test する。
4. 必要なら base + bounded patch segment を試す。
5. structure change、unknown mutable value、patch 上限到達時は full rebuild する。

acceptance:

- [x] 10,000 row one-key snapshot p95 1 ms 以下を目標
- [x] rebuilt entry count が変更 key 数に比例
- [x] old snapshot、worker snapshot、current snapshot の checksum が安定
- [x] canonical value は immutable
- [x] patch chain / overlay / retained byte が bounded

停止条件:

- snapshot immutability を簡単な ownership で証明できない場合は採用しない。
- 新しい persistent-map dependency は別途明示承認がない限り追加しない。
- O(1) 化のために公開 mutable reference を返さない。

### 5.4 PARAM-08: visibility / filter の差分評価

方針:

1. key、group、静的 searchable corpus の index を model へ持つ。
2. source badge、override、MIDI CC、favorite、error、effective value に由来する検索
   token は動的 overlay として分離する。
3. query parse は query revision が変わった時だけ行う。
4. merge result または `ParamStoreRuntime` から changed effective key / group を公開する。
5. loaded / observed group の変化を追跡する group-visibility revision を追加する。
6. `ui_visible` は effective または visibility revision が変わった group だけ再評価する。
7. 依存を静的解析せず、変更 group 全体を conservative に再評価する。
8. unknown dependency は正しさ優先で full group fallback する。

acceptance:

- [x] 10,000 row stable mask rebuild 0 回
- [x] one-key animation の再評価 group 1 以下
- [x] default p95 1 ms 以下、search p95 8 ms 以下
- [x] 全 mode の mask が現行 pure evaluation と一致
- [x] loaded / observed、source badge、override、MIDI、favorite、error の変更を取りこぼさない
- [ ] query typing 中の input-to-flip-return p95 が UX guardrail 内

### 5.5 PARAM-09: favorite immutable view

- [x] favorite を static table model から view overlay へ移す
- [x] favorite revision を追加し、変更時に structure revision を進めない
- [x] toggle、codec load、reconcile、prune の全 mutation を共通 favorite operation
  経由にする
- [x] 共通化できない mutation は `(favorite_revision, table_revision)` で cache を
  invalidation する
- [x] revision 内では同じ immutable set / ordered view を再利用する
- [x] stable frame の sort / copy count を 0 にする
- [x] favorite toggle、load、variation scope を回帰 test する
- [x] favorite は現行どおり patch history / undo/redo の対象外とし、仕様変更しない

### 5.6 PERF-04: causal backlog prefix 処理

現状:

- presented revision の照合時に pending event 全体を tuple 化して走査する。
- revision は単調であり、通常は先頭 prefix だけを消費すればよい。

方針:

1. ordered pending の先頭から presented revision 以下だけを pop する。
2. 先頭が未来 revision なら即時終了する。
3. 順序保証のない event source が存在しないことを contract 化する。

case:

- `runtime.perf.causal_backlog.pending_{100,1000,4096}`

acceptance:

- [x] match 件数、latency、drop semantics が現行と一致
- [x] pending 上限 4,096 を維持
- [x] 4,096 pending の p95 0.02 ms 以下を目標
- [x] out-of-order input を contract violation として検出

探索値からは 15〜30 倍以上の局所改善余地がある。ただし通常 backlog が小さい frame の
全体改善率としては扱わない。

## 6. Phase 2: 実 GUI の widget scalability

### 6.1 GUI-03: virtualization 前提の副作用分離

監査環境の `imgui 2.0.0` / Dear ImGui 1.82 binding では、`ListClipper`、
`get_active_id()`、`get_item_id()` を利用できない。現行 row は可変高であり、
MIDI learn event の消費も `_render_cc_cell()` 内にある。

先に以下を行う。

- [ ] この段階は prototype とし、keyboard / active-item 同値性を証明するまで
  製品経路へ入れない
- [ ] MIDI learn event の適用を row draw 外の prepass へ移す
- [ ] help / error / active state の更新を visible row draw だけに依存させない
- [ ] app-owned active / focused / edited `ParameterKey` を持つ
- [ ] active row は viewport 外でも pinned set に含める
- [ ] kind / value / style / heading から deterministic row height を得る
- [ ] Retina、resize、font scale で row height model を検証する

### 6.2 GUI-04: viewport range rendering

前提が揃った後、次の 2 案を小さな prototype で比較する。

1. 現 binding の scroll / cursor / `table_next_row(min_row_height=...)` を使う
   bounded range rendering
2. clipper と active ID を安全に利用できる binding への更新

dependency 追加・更新は Ask-first とし、承認なしに実施しない。
app-owned active key は mouse drag の pin には使えるが、submit していない offscreen
item 間の ImGui keyboard navigation を単独では再現できない。binding capability または
実 GUI contract で証明できるまでは、本実装へ昇格させない。

acceptance:

- [ ] widget submission が visible rows + overscan + pinned rows に比例
- [ ] mouse drag 中に row が viewport 外へ出ても release を失わない
- [ ] text edit、popup、MIDI learn、help target を失わない
- [ ] Tab / Shift-Tab / PageUp / PageDown の操作を壊さない
- [ ] collapse / filter / resize 中に scroll jump を起こさない
- [ ] 10,000 row actual widget p95 8 ms 以下

停止条件:

- 上記入力のいずれかが壊れる場合は manual virtualization を採用しない。
- active ID を取得できず keyboard navigation の同値性を保証できない場合は、
  Phase 1 の layout/filter 改善までで止め、binding 更新を別判断にする。

実装しない案:

- scroll position だけから row index を推定する
- offscreen MIDI learn 対象を描画しないまま event を消費する
- 大規模 store を自動 collapse して性能問題を隠す
- pagination へ黙って UX を変更する

## 7. Phase 3: multiprocessing / renderer / many-layer

### 7.1 MP-03: revision churn scaling matrix

追加 case:

- parameters: 32 / 1,000 / 10,000
- workers: 0 / 1 / 2 / 4
- change: one-key / all-key

保存する metric:

- snapshot build / pickle / control apply
- payload bytes
- app-owned task/result submitted / started / completed / dropped / pending
- input-to-result / input-to-flip-return
- revision lag / stale streak / worker restart

hard contract:

- final revision と checksum が一致
- revision 採用が単調
- bounded queue、unexpected reject 0
- worker restart / epoch gap から復旧する

delta protocol は、次のいずれかを満たす場合だけ設計する。

- payload 処理が worker latency の 25% 以上
- 1,000 / 10,000 parameter が p95 50 ms guardrail を超える
- serialize が単独で frame budget を超える

採用時の最小仕様:

- startup / epoch / gap / restart は full base snapshot
- patch は base revision と target revision を持つ
- worker ACK、monotonic apply、checksum
- gap 検出時は full snapshot を再送
- 定期 full checkpoint と retained patch byte 上限

one-key / 10,000 parameters では wire bytes 99% 以上削減の余地があるが、
end-to-end 改善は正式 matrix で確認する。

今回、delta protocol は導入せず、既存 full payload の plain dict 化だけを
snapshot overlay-aware にした。one-key snapshot と handoff 合計 p95 が
20.049 ms から 2.409 ms へ下がったため、worker matrix で上記着手条件を確認するまで
delta は停止する。

### 7.2 GL-04: real renderer matrix と resource soak

matrix:

- layers: 1 / 8 / 100
- topology: stable / changing
- style: same / alternating
- geometry: light / scene 合計 100k lines
- profile: fake GL / real offscreen / visible

line 数と GPU byte は scene 合計で固定して layer 間へ分配し、既定 2,000,000 line
resource limit 内で比較する。limit 超過は性能 case に混ぜず、別の rejection contract
case とする。

保存する metric:

- index build、VBO-only upload、full upload
- uploaded VBO / IBO bytes
- draw calls、uniform writes
- CPU submit、async GPU、flip-return present proxy
- mesh / candidate entries・bytes、GL create / release / live count

最初の候補は同一 style の redundant uniform write 除去である。同じ thickness / color が
連続する場合、現行は layer ごとに uniform を再送する。

採用条件:

- uniform write が CPU submit の 10% 以上
- same-style case の p95 が 20% 以上改善

acceptance:

- same style の uniform write は viewport/frame 当たり必要最小限
- alternating style は必要な変更を失わない
- draw call、draw order、checksum / image が一致
- context / viewport 切替で cache が漏れない

今回、program lifetime 内で uniform handle と直前 thickness / color を保持し、
同一 style の再送を省いた。Fake GL では same-style p95 が 20% 以上改善し、
alternating style、draw count/order、viewport invalidation、release を test した。
実 GL context を作れなかったため、real renderer matrix と正式な採用条件確認は未完了。

### 7.3 PIPE-03: many-layer Python 固定費

追加 case:

- layers: 1 / 10 / 100 / 500 / 2,000
- cache-hit geometry
- same / alternating layer style

分離する metric:

- `FrameParamRecord` / `ParameterKey` 生成
- style state lookup
- scene record allocation
- realize cache hit
- renderer submit

record / style 固定費が frame の 20% 以上なら、`FrameParamsBuffer` への直接 append と
既存 immutable state 参照を検討する。公開 mutable state、汎用 batching、複雑な
object pool は導入しない。

### 7.4 条件付き renderer / MP 案

以下は実測条件を満たす場合だけ試作する。

| 候補 | 着手条件 | 採用条件 |
| --- | --- | --- |
| adjacent same-style batching | submit + GPU が frame の 20% 以上 | p95 20% 以上改善、順序一致 |
| worker-side realize | main realize p95 2 ms 超または frame の 20% 以上 | transfer 込み p95 20% 以上改善 |
| shared-memory ring | pickle/copy が支配、1-worker prototype が有効 | generation/lifetime と slot が bounded |
| VBO multi-buffer / ring orphaning | 実 GL upload stall が支配 | p95 20% 以上改善、object plateau |
| persistent mapping | backend capability があり upload stall が支配 | capability 付き採用、未対応は skip |

## 8. Phase 4: autosave / capture / video / JIT

### 8.1 AUTO-03: immutable persistence payload の write-behind

現状:

- active drag 中の autosave は停止するため、操作中 stall は解消済み。
- debounce 後の serialize と atomic write は main thread 側の待ち時間になり得る。

方針:

1. serialize、write、fsync、publish を別 section で測る。
2. 現 `save_param_store()` が serialize 前に行う
   `prune_unknown_args_in_known_ops()` の時間と store mutation semantics を formal 化する。
3. `ParamSnapshot` とは別に、codec の全永続化対象を含む immutable persistence
   payload を定義する。
4. payload には parameters / meta / explicit、ordinal / effect-chain index、
   collapsed header、lock、favorite、variation 等を欠落なく含める。
5. prune は payload 確定前の明示 main-thread lifecycle へ移すか、同じ結果になる
   immutable persistence projection とする。worker から store を mutation しない。
6. main thread からの handoff は変更数に近い計算量にする。main thread で約 25 ms の
   JSON bytes を毎回生成してから渡す案は採用しない。
7. worker へ渡すのは、完全な immutable payload または既に cache 済みの immutable
   bytes だけにする。
8. bounded latest-wins queue と close flush を実装する。
9. atomic publish と failure recovery は現行 semantics を維持する。

acceptance:

- autosave 発火 frame の main-thread p95 1 ms 以下
- quiescence 後かつ I/O が成功する条件では latest revision が eventually saved
- close / shutdown は明示 timeout 内に flush 成功するか、未保存 revision を通知して
  last-good file と recovery 情報を維持する
- write failure 後も最後の正常ファイルを壊さない
- async encode 中の interactive p95 悪化 1 ms 以下
- JSON encode の GIL 競合を trace し、main-thread p95 / p99 を悪化させない
- persistence revision と published revision が一致

禁止:

- mutable `ParamStore` を background thread から直接 serialize する
- debounce を長くするだけで問題を隠す
- unbounded save queue を作る

完全な immutable persistence payload を安全に作れない、または handoff 自体が
1 ms guardrail を超える場合は、`PARAM-07` の採否にかかわらず async autosave を
停止する。`ParamSnapshot` を不完全な代用品にはしない。I/O hang 時に無期限待機する
同期 fallback も追加しない。

### 8.2 CAP-03: capture request と preview evaluation の分離

現状の重要点:

- capture key は final scene の同期再評価を行う。
- quality の draft → final → draft 遷移は MP epoch を進め、進行中 worker result を
  無効化し得る。
- 同じ `SceneRunner` retained output を final 評価で更新し、stateful draw を同じ
  `t` で再実行し得る。
- SVG encode / publish と variation thumbnail capture に同期経路がある。

まず製品 contract を決める。

- WYSIWYG displayed snapshot を capture する
- 現在 parameter の final quality を別 owner で再評価する
- 現行の同期 final 評価を維持する

計測 case:

- SVG / PNG / G-code
- variation thumbnail
- light / many-lines
- sync / 1-worker preview
- capture 中の slider input

metric:

- input callback / request intent
- final evaluation
- export job enqueue
- provenance / manifest
- snapshot serialization
- encode / publish
- `SceneRunner._mp_epoch` delta / MP generation / invalidated result count
- capture 直後の freshness / settle latency

hard contract:

- artifact token、source reload generation / builder identity / source hash、
  parameter revision、provenance が一致
- preview retained state と artifact final state を混同しない
- queue count / byte が bounded
- MP epoch delta と invalidated result count を必ず記録する

WYSIWYG または別 owner の final 評価を採用する場合は、capture intent による
preview MP epoch delta 0 を追加 contract とする。現行同期 final 評価を維持する場合は
delta 0 を共通 hard contract にせず、preview freshness の悪化を明示して採否判断する。

final 評価を別 owner へ安全に分離できない場合、無理に async 化せず、
WYSIWYG または現仕様維持を明示的に選ぶ。

### 8.3 VIDEO-03: readback と encoder backpressure

現状:

- `screen.read()` と ffmpeg `stdin.write()` が同じ frame 内で同期実行される。
- perf metric は video 一括で、どちらが支配しているか分からない。
- 現 API の `screen.read()` は GPU readback と bytes materialization を一体で返す。

追加 case:

- fake slow sink
- real GL 640 × 480
- real GL 1,920 × 1,080
- short recording / finalize / shutdown

着手条件:

- readback+materialize p95 2 ms 超または deadline miss 寄与 20% 超:
  - PBO ring を検討
- pipe write p95 2 ms 超:
  - bounded encoder queue を検討

先に queue full 時の製品 contract を決める。

- lossless block
- recording pause
- explicit drop と timeline 補正

raw frame を drop した後に同じ raw frame を encoder へ再投入するだけでは encoder
backpressure は減らない。duplicate は mux / encoder 側で低コストに表現できる場合だけ
候補にする。

video では latest-wins を使わず、frame index と `t` の順序を守る。

acceptance:

- `t = t0 + timeline_index / fps` とし、submitted / accepted / written / dropped /
  duplicated index の関係を固定する
- `written` は ffmpeg stdin write 成功、recording complete は ffmpeg exit 0 と定義する
- `RecordingManifest` の既存 frame count / dropped / duplicated / error を維持し、
  async queue 採用時は submitted / accepted / written の意味を追加する
- byte / frame / queue 上限
- shutdown drain と ffmpeg failure recovery
- under-capacity case の drop / error 0

### 8.4 JIT-02: 実ユーザー初回 activation

まず、直接 `@njit` を持つ全 operation を安価な compile-cold inventory に掛ける。
shared utility を重複して「別 compile」と数えず、operation 単位の first-call inclusive
latency と warm latency を一覧化する。500 ms を超えた operation だけ、次の詳細候補へ
絞る。

詳細候補:

- `jit.activation.dash`
- `jit.activation.displace`
- `jit.activation.fill`
- `jit.activation.weave`
- `jit.activation.warp`

各 case で次を分離する。

- import
- builtin registration
- first evaluator inclusive
- second warm evaluator

通常の lazy dispatcher では Numba compile が first evaluator 内部で起きるため、
compile 単独時間を常に直接計時できるとはみなさない。dispatcher hook / signature が
利用できる場合だけ compile metric を追加し、それ以外は first / second の差分を
補助値として表示する。

activation が 500 ms を超え、かつ small warm workload が十分軽い effect だけ、
NumPy small-input path との crossover を 3 サイズ以上で測る。

hard contract:

- output checksum / dtype / shape
- finite coordinates
- offsets invariant
- first-call と warm-call の semantic 一致

禁止:

- 全 effect の eager precompile
- startup 時の無条件 background compile
- crossover が不安定なサイズ dispatch
- checksum を黙って変える近似 path

## 9. Phase 5: 証拠が出た場合だけ行う core 改善

### 9.1 GEO-03: trusted offsets の再検証削減

`RealizedGeometry.__post_init__()` は出力ごとに `np.diff(offsets)` を行う。coords だけを
変換し offsets identity を維持する effect でも再検証される。

まず one-long / many-short で validation 占有率を測る。many-short p95 が 20% 以上
改善し、one-long の退行が 5% 以下なら、内部専用 `with_coords()` 相当を検討する。

hard contract:

- 公開 constructor の validation は維持
- trusted path は既に検証済みの同一 offsets identity に限定
- 新しい coords について shape `(N, 3)`、`float32`、write protection を維持
- trusted path でも `offsets[-1] == len(coords)` を確認する
- coords / offsets の immutable ownership
- exact checksum と error semantics

trusted 条件外の float64 coords、shape 変換、別 offsets 等は、現行 constructor の
通常 validation / conversion へ戻す。trusted fast path の条件を新しい入力拒否条件に
してはならない。

今回、同一 input geometry の offsets identity を effect がそのまま返し、新しい coords が
`(N, 3)` / `float32` / 同一長である場合だけ内部 `_with_coords()` を使う案を採用した。
公開 constructor と fallback の validation / conversion / error semantics は維持した。

### 9.2 CACHE-03: alias accounting / registry generation

次の場合だけ着手する。

- identity / no-op chain の array alias 二重計上で hit rate が 25% 以上低下する
- source reload 後の registry 世代差で再現可能な p95 spike が出る

refcount accounting または世代単位 clear の最小案に留める。2Q、ARC、複数世代保持などの
複雑な cache policy は導入しない。

### 9.3 effect final algorithm / transform dtype

- heavy effect の final が capture trace 上位を占める場合だけ algorithm を検討する
- transform float32 は tolerance の明示承認と 20% 以上の改善がある場合だけ検討する
- final exact checksum が必要な case では dtype を変更しない

## 10. Benchmark 追加順

case 数の直積増加を避け、次の順で追加する。

1. deterministic CPU:
   - group/layout
   - merge
   - snapshot
   - visibility/filter
   - causal backlog
2. reference GUI:
   - actual widget
   - visible slider
3. renderer / pipeline:
   - real GL layer matrix
   - many-layer Python fixed cost
4. MP:
   - worker × parameter scaling
5. capture / video:
   - fake slow sink
   - real GL profile
6. cold:
   - JIT activation
7. opt-in soak:
   - 10 分または 200,000 updates

各 case を全 suite に入れない。

- `smoke`: 代表 1 規模、checksum / contract
- `cpu`: 1,000 / 10,000 scaling
- `reference`: 実 GUI / 実 GL / visible
- `soak`: 最大規模、長時間

## 11. 主な変更候補ファイル

### benchmark / trace

- `src/grafix/devtools/benchmarks/runner.py`
- `src/grafix/devtools/benchmarks/schema.py`
- `src/grafix/devtools/benchmarks/compare.py`
- `src/grafix/devtools/benchmarks/report.py`
- `src/grafix/devtools/benchmarks/parameter_edit_benchmark.py`
- `src/grafix/devtools/benchmarks/interactive_scenario_benchmark.py`
- `src/grafix/devtools/benchmarks/mp_draw_benchmark.py`
- capture / video / JIT 用の専用 benchmark driver
- `src/grafix/interactive/runtime/perf.py`
- `docs/memo/performance.md`

### Parameter / GUI

- `src/grafix/core/parameters/store.py`
- `src/grafix/core/parameters/snapshot_ops.py`
- `src/grafix/core/parameters/merge_ops.py`
- `src/grafix/core/parameters/frame_params.py`
- `src/grafix/core/parameters/runtime.py`
- `src/grafix/core/parameters/favorites.py`
- `src/grafix/core/parameters/autosave.py`
- `src/grafix/core/parameters/persistence.py`
- `src/grafix/core/parameters/codec.py`
- `src/grafix/interactive/parameter_gui/table_model.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/table.py`
- `src/grafix/interactive/parameter_gui/group_blocks.py`
- `src/grafix/interactive/parameter_gui/parameter_filter.py`
- `src/grafix/interactive/parameter_gui/midi_learn.py`
- `src/grafix/interactive/parameter_gui/widgets.py`
- `src/grafix/interactive/parameter_gui/gui.py`

### runtime / renderer / capture

- `src/grafix/interactive/runtime/mp_draw.py`
- `src/grafix/interactive/runtime/scene_runner.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/interactive/runtime/export_job_system.py`
- `src/grafix/interactive/runtime/recording_system.py`
- `src/grafix/interactive/runtime/video_recorder.py`
- `src/grafix/interactive/gl/draw_renderer.py`
- `src/grafix/core/capture_manifest.py`
- `src/grafix/core/realized_geometry.py`
- `src/grafix/core/effect_registry.py`
- `src/grafix/core/parameters/layer_style.py`

対応する `tests/` を同じ Phase で追加する。

## 12. リスクと抑止策

| リスク | 抑止策 |
| --- | --- |
| cache が stale GUI model を返す | revision と hard equivalence test |
| merge fast path が rollback を壊す | failure injection と last-good checksum |
| snapshot が mutable state を alias する | canonical immutable type と old-frame test |
| virtualization が active widget を失う | app-owned active key、pinned row、実 GUI scenario |
| async autosave が古い revision を publish | token / revision と latest-wins |
| MP delta が gap で壊れる | base revision、ACK、checksum、full resync |
| uniform cache が context をまたぐ | viewport/context ownership と reset |
| capture が preview MP evaluation epoch を進める | artifact runner と preview runner の所有権分離 |
| video queue が時系列を壊す | ordered queue、manifest counts |
| timing gate が thermal noise を検出する | ABAB、MAD、environment fingerprint |
| trace 自身が frame を遅くする | overhead case、bounded queue、drop counter |

## 13. 実装しないこと

現時点では以下を実装しない。

- effect graph 全体の DAG fusion
- compute shader への全面移行
- renderer 全 layer の無条件 packing
- unbounded object / mesh / snapshot pool
- mutable store の background read
- active ID を持たない単純 row clipping
- shared memory の多 worker 一括導入
- 全 effect の eager JIT compile
- checksum を黙って変える float32 化
- 新規 dependency による persistent collection 導入
- hosted CI wall time の hard gate
- benchmark 数だけを増やし、artifact と判定を整備しない変更

## 14. 実装順と進捗

### Step 0: baseline

- [ ] BENCH-05 case capability / profile
- [x] BENCH-06 Parameter CPU case（候補のうち 12 deterministic cases）
- [ ] effect family × shape representative case
- [ ] TRACE-03 section / gauge
- [ ] 12,000 frame production trace overhead case
- [ ] BENCH-08 ABAB noise study
- [ ] formal before artifact 保存（旧 driver の参考 artifact のみ。同一 current driver
  は新 API に依存するため基準 commit で未取得）

### Step 1: deterministic CPU hot path

- [x] PARAM-05 group/layout model
- [x] PARAM-06 stable merge fast path
- [x] PERF-04 causal backlog prefix
- [x] PARAM-08 visibility/filter
- [x] PARAM-09 favorite immutable view
- [x] PARAM-07 snapshot prototypeと採否判断

### Step 2: real GUI

- [ ] 実 ImGui widget baseline
- [ ] MIDI/help/active state の描画外分離
- [ ] row height / pinned active row
- [ ] virtualization prototype
- [ ] 採否判断と実 GUI 回帰

### Step 3: scaling

- [ ] MP worker × parameter matrix
- [ ] real GL renderer matrix
- [ ] many-layer pipeline
- [ ] delta / uniform / batching の条件判定
- [ ] 10 分または 200,000 update soak

### Step 4: I/O と cold path

- [ ] autosave 用の完全な immutable persistence payload と handoff の採否
- [ ] handoff 採用時だけ autosave write-behind
- [ ] capture product contract と formal case
- [ ] capture / preview ownership分離の採否
- [ ] video readback / pipe benchmark
- [ ] PBO / encoder queue の条件判定
- [ ] 全 JIT operation の first-call inventory
- [ ] 500 ms 超 operation の activation / crossover

### Step 5: conditional core

- [x] trusted offsets の採否
- [ ] cache alias / registry generation の採否
- [ ] final effect / dtype の採否

## 15. Phase 共通の採用条件

最適化は、次をすべて満たす場合だけ採用する。

1. 同一 case / 同一 environment / 同一 output policy で比較できる。既定は exact
   checksum とし、明示承認された tolerance case だけ宣言済み tolerance を使う。
2. 対象区間の p95 が原則 20% 以上改善する。
3. end-to-end p95、p99、max に統計的に意味のある退行を作らない。候補ごとに
   事前宣言した上限がある場合だけ、その範囲を許容する。
4. startup、memory、queue、object count に新しい無制限増加を作らない。
5. exact policy では final quality、draw order、undo/redo、MIDI、capture provenance
   を変えない。tolerance policy は承認された数値表現だけに限定する。
6. 複雑さが局所的で、単純な停止条件と削除可能な境界を持つ。

各節の case-specific な acceptance / stopping condition は、この共通条件より優先する。
局所 counter が 99% 減っても、frame 全体が 20% 改善しない場合は「全般的に高速化した」
とは報告しない。局所効果、適用率、Amdahl 則を分けて報告する。

## 16. 全体の完了定義

次をすべて満たした時点で本計画を完了とする。

1. 現場の visible-window slider を input-to-flip-return で再現でき、物理 present を
   測れていない場合は present proxy と明記される。
2. trace から遅い frame の parameter revision、CPU section、GPU/flip、resource を
   追跡できる。
3. reference Mac の ABAB noise study と timing gate profile が利用できる。
4. 10,000 row stable grouping / merge は目標を達成するか、formal trace と停止理由を
   残して安全な不採用判断を完了する。
5. snapshot / visibility / favorite は目標を達成するか、immutability / semantics の
   停止条件に基づく不採用判断を完了する。
6. 実 GUI の 1,000 / 10,000 row 方針が計測に基づき確定し、virtualization は
   input 同値性を満たす場合だけ採用される。
7. MP 0 / 1 / 2 / 4 worker scaling の支配区間と delta 採否が確定する。
8. real GL の submit / GPU / flip-return proxy を分離し、取得可能なら physical
   present feedback も保存し、cache / queue / GL object が soak で
   plateau する。
9. autosave、capture、video の intent / evaluation / enqueue と backpressure contract が
   明示される。
10. JIT first activation の遅い operation と crossover 採否が確定する。
11. 全 exact checksum または宣言済み tolerance、既存 test、lint、type check、
    hard contract が通る。
12. 実装しなかった候補にも、計測値と停止理由が残る。
