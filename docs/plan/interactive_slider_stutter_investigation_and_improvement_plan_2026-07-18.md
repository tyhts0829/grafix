# Interactive slider カクつき 原因調査・改善計画

- 作成日: 2026-07-18
- 状態: 主回帰と P1 増幅要因の実装・検証完了。Phase 5 は条件付き後続課題
- 対象: Parameter GUI で平行移動・スケール等の値を連続変更したときの preview 応答
- 関連計画:
  - `docs/plan/grafix_performance_improvement_ideas_2026-07-17.md`
  - `docs/plan/grafix_performance_improvement_implementation_plan_2026-07-17.md`

## 1. 結論

主原因は、Geometry の平行移動・スケール演算そのものではない。

**既定の 1-worker 非同期描画で、parameter revision の ACK を待つ間に draw task が
毎フレーム新しい revision へ置き換えられ、スライダー操作中の評価が一度も開始
されない revision starvation が発生している。**

実プロセス、1 worker、60 Hz、軽量な `G.line`、120 frame の再現結果は次の通りだった。

| 条件 | 操作中の fresh result | snapshot broadcast | 備考 |
| --- | ---: | ---: | --- |
| revision 固定 | 118 / 120 | 1 | ほぼ毎 frame 更新 |
| 毎 frame revision 変更 | **0 / 120** | 120 | 操作中は更新せず、release 後に再開 |

これは「軽い描画でも、スライダーを動かすと freeze / jump / カクつき、止めると
追いつく」という症状を直接説明する。単なる性能推測ではなく、現在の既定条件で
再現できた回帰である。

加えて、主原因の修正後にカクつきを再発させ得る次の増幅要因も確認した。

1. 通常 preview でも changed parameter provenance を同期生成する。
2. 小さい一度きりの Geometry を CPU cache がエントリ数無制限で保持する。
3. 同じ MP 結果の再表示を GPU mesh admission の「2 回目」と数え、一時値を昇格する。
4. 大規模 ParamStore では history、table model、merge が値変更ごとに全件処理する。
5. autosave が main thread 上で同期実行される。

したがって、実装は次の順で行う。

1. **P0: MpDraw revision starvation の根治**
2. **P0: 実操作を模した benchmark / trace の追加**
3. **P1: CPU/GPU cache の transient 値対策**
4. **P1: 通常 preview から provenance 具体化を除外**
5. **P2: 大規模 ParamStore の slider hot path を差分処理化**

### 1.1 実装後の結果

既定 1 worker、60 Hz、120 frame の同一実プロセス probe:

| 条件 | 修正前 fresh result | 修正後 fresh result |
| --- | ---: | ---: |
| revision 固定 | 118 / 120 | 119 / 120 |
| 毎 frame revision 変更 | **0 / 120** | **118〜119 / 120** |

正式 benchmark `mp.draw.slider_churn` の changing case:

| case | fresh ratio | stale max | revision lag p95 | input-to-result p95 | final revision |
| --- | ---: | ---: | ---: | ---: | ---: |
| translate | 99.17% | 1 frame | 1 | 26.47 ms | 23.88 ms |
| scale | 99.17% | 1 frame | 1 | 26.99 ms | 23.83 ms |

両 case とも sync checksum 一致、rejected task 0、queue drop 0 だった。

CPU cache の 200,000 unique translate soak:

- entries: 4,096 で固定
- cache bytes: 131,072 bytes で固定
- RSS: 40.11 MiB → 51.41 MiB。最後の 50,000 件では +0.31 MiB
- hot base Geometry: 200,000 hit、最後まで同一 object を維持
- throughput: 約 44,765 件/秒

通常 preview の changed frame 120 回では provenance materialization 0 回を確認した。

## 2. 症状が起きる処理順

既定値は `n_worker=1` であり、回帰導入後の `SceneRunner` は 1 worker でも
`MpDraw` を使っていた。

- `src/grafix/api/runner.py:796`
- `src/grafix/interactive/runtime/scene_runner.py:81-89`

修正前の `MpDraw.submit()` は次の手順を取っていた。

1. 新しい store revision の snapshot を control queue へ送る。
2. 全 worker がその revision を ACK するまで draw task を enqueue しない。
3. ACK 待ち中の task は `_pending_task` 1 件だけに保ち、次の submit で上書きする。

関連箇所:

- `src/grafix/interactive/runtime/mp_draw.py:756-791`
- `src/grafix/interactive/runtime/mp_draw.py:814-819`
- `src/grafix/interactive/runtime/mp_draw.py:873-941`

preview window と Parameter GUI は同じ event loop で、preview、GUI の順に描画される。

- `src/grafix/api/runner.py`
- `src/grafix/interactive/runtime/window_loop.py:83-95`

このため、修正前の連続 drag 中は次の starvation になっていた。

```text
frame n preview:
  revision R の snapshot を送る
  ACK 未到着なので task R は pending

frame n GUI:
  slider edit により store revision が R+1 へ進む

frame n+1 preview:
  ACK R を回収する
  しかし要求 revision は既に R+1
  snapshot R+1 を送り、pending task を R+1 で上書き

frame n+1 GUI:
  store revision が R+2 へ進む

以後繰り返し:
  worker は常に 1 revision 以上遅れ、draw task が実行されない
```

修正前の `SceneRunner` は fresh result が無い間、直近成功 scene を表示し続けるため、画面上は
「止まる」「飛ぶ」「release 後に追いつく」と見える。

## 3. 回帰の導入点

commit `5eeb7f7` で `SceneRunner` の MP 有効条件が変更された。

```diff
- MpDraw(...) if int(n_worker) > 1 else None
+ MpDraw(...) if worker_count >= 1 else None
```

`run()` の既定 `n_worker=1` 自体は維持されたため、既定ユーザーの実動作が次のように
変わった。

- 変更前: `n_worker=1` は main process で同期評価
- 変更後: `n_worker=1` は 1 worker の非同期評価

snapshot/task protocol は revision が短時間に変わらない workload では動作するが、
毎 GUI frame revision が進む slider drag を処理できない。以前は既定経路が同期
評価だったため、この欠陥が表面化していなかった。

## 4. 既存テスト・benchmark が見逃した理由

### 4.1 MP test

`tests/interactive/runtime/test_mp_draw.py:1317-1340` は 200 revision を連投し、次だけを
確認している。

- control queue / pending update が bounded
- 最終 revision が最終的に ACK される
- rejection が無い

変更中に `DrawResult` が 1 件でも返ったかは確認していない。そのため、今回の
`0 / 120 fresh results` でも test は通る。

### 4.2 MP benchmark

`src/grafix/devtools/benchmarks/mp_draw_benchmark.py` は次の性質を持つ。

- 全 submit で `snapshot_revision=0` 固定
- `worker_count=max(2, n_worker)` として 1-worker を測らない
- throughput を主指標とし、input-to-present freshness を測らない

現在の既定条件と revision churn の組合せを全く通らない。

### 4.3 Renderer benchmark

animated renderer case は毎 frame 必ず unique な cache key を使うため、2-hit admission
を一度も通らない。

- `src/grafix/devtools/benchmarks/runner.py:1410-1414`

static case は candidate から full mesh へ昇格する先頭 frame を steady timing から
外すため、GPU object allocation spike を測らない。

### 4.4 Realize soak

既存 animated soak は短い frame 数で session を閉じる。長寿命 session に one-hit
entry が蓄積したときの RSS と GC tail を検出できない。

## 5. 調査結果の詳細

### 5.1 単発の translate / scale miss は主原因ではない

`0e94f05` の直前版と現行を同一環境で比較した。

| シナリオ | 直前版 | 現行 | 差 |
| --- | ---: | ---: | ---: |
| translate、Geometry.create + realize | 22.760 µs | 22.993 µs | +1.0% |
| scale、Geometry.create + realize | 28.172 µs | 28.854 µs | +2.4% |
| 既存 animated soak | 43.001 µs/frame | 43.103 µs/frame | +0.24% |

現行 iterative evaluator の shallow miss 固定費は µs 級であり、目視できる freeze の
原因ではない。ここへ先に fast path を追加すると、複雑化する一方で症状は直らない。

### 5.2 changed provenance は描画量と無関係な同期固定費

fresh frame ごとに `DrawWindowSystem.draw_frame()` が `_frame_provenance()` を呼ぶ。

- `src/grafix/interactive/runtime/draw_window_system.py:1506-1512`

cache miss 時は全 effective entry の sort、全 ParamStore encode、canonical JSON、
SHA-256 を同期実行する。

- `src/grafix/core/capture_provenance.py:372-402`
- `src/grafix/core/capture_provenance.py:444-464`

`0e94f05` の revision cache は stable frame には効くが、slider edit では
`store.revision` と `effective_revision` が進むため毎回 miss する。

測定値:

- `runtime.provenance_changed.rows_1000`
  - median: 20.87 ms / benchmark workload
  - p95: 22.20 ms
  - workload は changed snapshot を 2 回具体化するため、1 回あたり約 10〜11 ms
- 現在の `sketch/main.py` 相当 32 parameters
  - median: 0.407 ms
  - p95: 0.508 ms

少数 parameter では主原因ではないが、大規模 scene や frame budget 境界では増幅要因に
なる。通常 preview で毎 frame manifest 用 hash を作る必要もない。

### 5.3 大規模 ParamStore の changed-frame 固定費

1,000 parameter の synthetic slider sequence で、Geometry/ImGui/GPU 描画を除く
同期処理を測定した。

| 区間 | median | p95 |
| --- | ---: | ---: |
| GUI apply + history | 12.57 ms | 22.49 ms |
| store snapshot | 1.00 ms | 1.24 ms |
| frame merge | 2.00 ms | 2.23 ms |
| changed provenance | 11.19 ms | 11.72 ms |
| table model rebuild | 9.26 ms | 10.06 ms |
| 合計 | 36.34 ms | 47.06 ms |

主な理由:

- history が変更 frame ごとに全 states/meta を `deepcopy`
  - `src/grafix/core/parameters/history.py:109-136`
  - `src/grafix/core/parameters/memento.py:65-82`
- table model cache key が値変更でも進む `store.revision`
  - `src/grafix/interactive/parameter_gui/table_model.py:58-84`
- `merge_frame_params()` が全 record key の before/after を走査
  - `src/grafix/core/parameters/merge_ops.py:18-51`

32 parameter ではこれらを合わせても中央値約 1.35 ms であり、今回の `0 / 120`
freeze の説明にはならない。ただし規模依存のカクつきとして別途改善する。

### 5.4 CPU cache の entry 数無制限

`RealizeSession` の CPU cache は byte 上限しか持たない。

- `src/grafix/core/realize.py:167-171`
- `src/grafix/core/realize.py:709-750`

`RealizedGeometry.byte_size` は NumPy array の `nbytes` だけで、Geometry key、文字列、
`OrderedDict` node、NumPy/Python object の overhead を含まない。

- `src/grafix/core/realized_geometry.py:86-90`

2頂点 translate を 200,000 unique 値流した測定:

- cache stats: 200,002 entries / 6.4 MB
- RSS: 47.7 MiB → 159.6 MiB
- gen2 GC pause: 4.48 ms → 15.18 ms
- frame max: 最終的に約 15.26 ms

4,096 entry 上限を仮適用した同じ測定:

- entries: 4,096
- RSS: 約 45 MiB → 52 MiB で plateau
- 計測中の gen2 GC: 0 回
- max: ほぼ 0.4 ms 未満、例外 1 回も 1.34 ms

軽い描画ほど array byte が小さく、実 object overhead が過小計上されるため、
長時間の slider 操作・animation で周期的な GC hitch を起こしやすい。

### 5.5 GPU mesh の transient promotion

`DrawRenderer` は同じ cache key の 2 回目で専用 `LineMesh` を作る。

- `src/grafix/interactive/gl/draw_renderer.py:241-279`
- `src/grafix/interactive/gl/draw_renderer.py:299-338`

同じ MP success を複数 display frame で再表示した場合も「2 回目」に数えるため、
slider の一時値が VBO + IBO + VAO を持つ full mesh へ昇格する。

同じ offsets を持つ軽量 Geometry、300 値の fake GL 測定:

| シーケンス | index build | mesh promotion | mesh object |
| --- | ---: | ---: | ---: |
| 各値を 1 frame | 1 | 0 | 1 |
| 各値を 2 display frame | 1 | 300 | 301 |
| forward → reverse | 1 | 300 | 301 |

直近の topology reuse 自体は index/IBO update を削減しており、回帰原因ではない。
問題は stale display と fresh scene を区別しない admission 条件である。

## 6. 改善方針

### Phase 0: 再現を正式な test / benchmark に固定

- [x] `mp.draw.slider_churn.light_translate` を追加する。
- [x] `mp.draw.slider_churn.light_scale` を追加する。
- [x] 1 worker、60 Hz、120-step、毎 step revision 更新を既定 fixture にする。
- [x] stable revision control と同じ run で比較する。
- [ ] 30 frame warmup、120 frame drag、30 frame settle の phase を分けて保存する。
- [x] `DrawResult` に実際に適用した `snapshot_revision` を持たせる。
- [x] 次の metric を schema v3 result に保存する。
  - `fresh_result_ratio`
  - `max_consecutive_stale_frames`
  - `revision_lag` の median / p95 / p99 / max
  - input revision 作成から result 採用までの latency
  - release 後に最終 revision が採用されるまでの latency
  - snapshot broadcast / ACK / task enqueue / task drop / result count
- [x] final Geometry checksum と最終 revision を正しさ判定に使う。
- [x] 現行コードで `fresh_result_ratio=0` を再現し、test が失敗することを確認する。
- [x] `test_rapid_revision_changes_keep_snapshot_control_backlog_bounded` に
      「変更中にも result が前進する」契約を追加する。

Phase 0 では wall time のみを hard gate にしない。CI の hard invariant は次とする。

- result revision が単調に前進する。
- drag 中に少なくとも複数回 result が返る。
- queue/pending 件数が上限内に留まる。
- settle 後に最終 revision が必ず返る。
- stale snapshot で評価した result を current result として採用しない。

### Phase 1: MpDraw revision starvation の根治

snapshot update と draw task を別々の correctness barrier として扱わず、評価に必要な
状態を 1 つの latest-wins work item として結合する。

#### 1A. Work item

- [x] `_DrawTask` を、必要時の parameter snapshot を同梱できる work item に整理する。
- [x] work item に `frame_id`、`snapshot_revision`、snapshot、`t`、MIDI snapshot、
      quality、epoch、generation を一緒に持たせる。
- [x] parent が worker の revision 適用を確認できていない場合、work item 自体に
      snapshot を同梱する。
- [x] stable revision で全 worker が適用済みなら snapshot を省略し、既存の
      「毎 frame 大きな snapshot を pickle しない」利点を維持する。
- [x] control queue は stable snapshot の事前配布に残してもよいが、ACK を
      task enqueue の前提にはしない。

#### 1B. Worker

- [x] worker は取得した最新 work item の snapshot を先に適用する。
- [x] 同じ work item の `snapshot_revision` で直ちに draw を評価する。
- [x] 古い control update は適用せず、revision を巻き戻さない。
- [ ] task queue に複数候補がある場合は最新まで drain し、中間値を捨てる。
- [x] `DrawResult` に `snapshot_revision` を含める。
- [x] ACK は観測・snapshot 省略最適化に使い、描画進捗の barrier にはしない。

#### 1C. SceneRunner

- [x] result の revision と current store revision を区別して保持する。
- [x] `last_evaluation_succeeded`、last-good、epoch、source reload の既存契約を維持する。
- [x] worker result の parameter records は、その result を実際に採用したときだけ merge する。
- [x] timeout/restart 後の最初の work item は必ず snapshot を同梱する。
- [x] sync / MP を実行中に暗黙切替する adaptive fallback は追加しない。

最終目標は既定 `n_worker=1` を維持したまま protocol を直すことである。実装中に
正しさ・freshness 基準を満たせない場合だけ、安全策として既定を `n_worker=0` に
戻す。これは一時 fallback であり、実行中の暗黙切替にはしない。

#### Phase 1 完了条件

同一 machine の light / 60 Hz / 120-step benchmark で次を満たす。

- fresh result ratio: 90% 以上
- max consecutive stale display frames: 2 以下
- revision lag p95: 2 revision 以下
- input-to-present p95: 50 ms 以下
- release 後の最終 revision 到達: 100 ms 以下
- queue/pending memory: frame 数に対して増加しない
- sync と MP の最終 Geometry checksum: 一致

hosted CI では時間閾値を soft warning とし、進捗・最終 revision・boundedness・checksum
を hard gate にする。

### Phase 2: 長寿命 CPU cache を bounded にする

- [x] `RealizeSession` に `max_cache_entries` を追加する。
- [x] 初期値は 4,096 とし、byte 上限と entry 上限の両方を満たす LRU にする。
- [x] `RuntimeLimits` に CPU cache entry limit を集約する。
- [x] transaction commit 後にも両上限を適用する。
- [x] one-hit slider entry が増えても毎 frame使う base Geometry が LRU に残ることを確認する。
- [x] entry-limit eviction は通常の streaming 挙動として stats に記録し、毎 eviction の
      user-facing diagnostic は出さない。
- [ ] byte limit diagnostic も連続発生時は集約する。
- [ ] registry revision 更新後の再利用不能 entry を一括破棄するか、世代単位で
      回収できるようにする。

まず単純な entry cap を実装し、2Q/probation-protected cache は entry cap 後も hot
entry の eviction が実測問題になる場合だけ検討する。

#### Phase 2 benchmark

- [x] 20,000 / 200,000 unique translate stream を short / soak case に分ける。
- [ ] scale stream も追加する。
- [ ] Geometry.create → realize → renderer の frame sample を保存する。
- [x] RSS delta、cache entries/bytes/evictions を計測する。
- [x] entry 数と RSS が plateau することを確認する。

#### Phase 2 完了条件

- cache entries が常に上限以下
- 200,000 light stream 後も RSS が継続増加しない
- GC pause max 2 ms 未満
- hot base Geometry の cache hit を維持
- output checksum 不変

### Phase 3: GPU mesh admission を fresh scene 基準にする

- [x] `SceneRunner` から renderer へ fresh scene serial と適用 parameter revision を渡す。
- [x] 同じ MP result の stale 再表示は candidate hit に数えない。
- [x] 同じ cache key が異なる fresh scene で安定した場合だけ full mesh へ昇格する。
- [x] parameter revision が連続変更中なら一時値を昇格しない。
- [x] release 後に revision と key が安定した最終値だけを昇格する。
- [ ] scratch mesh が同じ fresh result を再表示する場合、別 layer に上書きされて
      いないことを確認できる場合だけ VBO upload も省略する。
- [ ] candidate/full mesh の entry 数上限を byte 上限と併用する。

#### Phase 3 benchmark

fake GL の deterministic state test と、任意実行の実 GL trace を分ける。

- [x] unique sweep
- [x] 各値を複数 display frame 保持
- [x] forward → reverse
- [x] drag release 後の idle
- [ ] multi-layer で scratch が上書きされるケース
- [ ] promotion、GL object allocation、VBO/IBO upload bytes、eviction を記録
- [ ] 実 GL では frame p95/p99/max と driver stall を観測

#### Phase 3 完了条件

- drag 中の transient mesh promotion: 0
- stale MP result の再表示による promotion: 0
- static final value: 安定確認後に 1 回だけ promotion
- translate/scale の同一 offsets では index build: 初回 1 回
- GPU cache entry/RSS が slider step 数に比例して増えない

### Phase 4: Preview から provenance 具体化を外す

通常 preview の `_last_export_snapshot` は provenance を `None` のまま保持し、必要な
境界だけで具体化する。

具体化が必要な境界:

1. 初回 draw 前に受けた pending capture intent を最初の fresh frameへ結合するとき
2. recording capture の最初の fresh frame
3. `final_capture_frame()`、thumbnail、明示 export
4. shutdown fallback
5. provenance 無しの snapshot を direct `save_svg()` する直前

通常の key capture は既に `final_capture_frame()` で final 再評価し、そこで
provenance を生成している。

- `src/grafix/interactive/runtime/draw_window_system.py:425-446`
- `src/grafix/interactive/runtime/draw_window_system.py:1335-1363`

したがって、通常 preview の毎 fresh frame で hash を作る必要はない。

- [x] 通常 preview で `_frame_provenance()` を呼ばない。
- [x] capture/recording に必要な frame では従来と同じ hash を生成する。
- [x] capture request と parameter snapshot の対応を test する。
- [x] source reload、final quality、recording first frame の provenance を test する。
- [x] preview benchmark で provenance materialization count が 0 であることを assert する。

#### Phase 4 完了条件

- 通常 preview 120 changed framesの provenance materialization: 0
- export manifest hash: 変更前と完全一致
- capture が表示/再評価した revision と manifest revision: 一致
- 1,000 parameter changed preview から約 10〜11 ms/frame の同期固定費を除去

### Phase 5: 大規模 ParamStore の slider hot path

Phase 1〜4 後の統合 benchmark で 1,000 parameter の input-to-present p95 が目標を
超える場合に実装する。単発の小規模 scene のために先に複雑化しない。

今回報告された軽量 scene の回帰は Phase 1 で解消し、正式 benchmark も freshness と
latency の目標を満たしたため、Phase 5 は実装していない。1,000 parameter 固有の
改善は本修正へ混ぜず、統合 GUI benchmark を追加したうえで別タスクとして判断する。

#### 5A. History

- [ ] slider row の変更 key と before/after だけを patch として記録する。
- [ ] 同じ drag の patch は after 値だけを更新して coalesce する。
- [ ] Undo/Redo は現在も存在し、meta kind が一致する key だけへ patch を適用する。
- [ ] bulk variation/A-B snapshot は hot path ではないため full memento を維持してよい。
- [ ] drag 中の全-store `deepcopy` を 0 回にする。

#### 5B. Table model

- [ ] structure revision と value revision を分離する。
- [ ] row order、header、registry、meta kind が変わった場合だけ structure model を再構築する。
- [ ] `ui_value`、override、MIDI値、effective/source は描画時の value overlay に分離する。
- [ ] 1 key の slider change で全 row の sort/dataclass rebuild を行わない。

#### 5C. Parameter merge

- [ ] effective/source の変更検出と適用を 1 pass にまとめる。
- [ ] failed frame rollback に必要な key だけを staging する。
- [ ] 全 key の事前 dict と事後 `any()` scan を除去する。
- [ ] effective revision は 1 frame につき最大 1 回だけ進める。

#### 5D. Autosave

- [ ] autosave serialize/write の span を trace する。
- [ ] active drag 中は最大間隔 save を main-thread critical pathで実行しない。
- [ ] immutable snapshot を作って background writer へ渡す。
- [ ] latest-wins、atomic publish、終了時 flush、失敗通知の契約を維持する。

## 7. Performance trace の改善

現場で「平均は速いが操作中だけ止まる」を分解できるよう、次を追加する。

- [ ] `parameter_revision_created`
- [ ] `mp_snapshot_sent`
- [ ] `mp_snapshot_applied`
- [ ] `mp_task_started`
- [ ] `mp_result_received`
- [ ] `mp_result_presented`
- [x] current/applied revision lag
- [x] consecutive stale display frames
- [ ] provenance materialization
- [ ] parameter snapshot / merge
- [ ] GUI history / table model
- [ ] autosave
- [ ] CPU cache entries/RSS/GC pause
- [ ] GPU candidate/promotion/allocation/upload

trace は通常無効、`GRAFIX_PERF=1` または benchmark 時だけ収集する。計測のために通常
previewへ高頻度 allocationや同期 I/Oを追加しない。

## 8. 変更予定ファイル

### P0 / MP

- `src/grafix/interactive/runtime/mp_draw.py`
- `src/grafix/interactive/runtime/scene_runner.py`
- `src/grafix/interactive/runtime/perf.py`
- `src/grafix/interactive/runtime/monitor.py`
- `tests/interactive/runtime/test_mp_draw.py`
- `tests/interactive/runtime/test_scene_runner.py`
- `src/grafix/devtools/benchmarks/mp_draw_benchmark.py`
- `src/grafix/devtools/benchmarks/runner.py`
- `tests/devtools/benchmarks/test_runner.py`

### Cache / renderer

- `src/grafix/core/runtime_limits.py`
- `src/grafix/core/realize.py`
- `src/grafix/interactive/gl/draw_renderer.py`
- `src/grafix/interactive/gl/line_mesh.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `tests/core/test_realize_cache.py`
- `tests/interactive/test_draw_renderer_cache.py`

### Provenance / parameter hot path

- `src/grafix/core/capture_provenance.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/core/parameters/history.py`
- `src/grafix/core/parameters/merge_ops.py`
- `src/grafix/core/parameters/store.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/table_model.py`
- 対応する `tests/core/parameters/`、`tests/interactive/parameter_gui/`

## 9. 実装しないこと

- iterative evaluator を今回の主修正として作り直さない。
- frame途中で sync/MP を自動切替しない。
- slider値を丸めて見かけ上 cache hit にする変更は行わない。
- 描画結果、parameter解決、capture hash の意味を変えない。
- queueを無制限にして全中間 frame を処理しない。最新値優先を維持する。
- 依存ライブラリを追加しない。
- 互換 wrapper / shim は作らない。

## 10. 最終検証

- [x] 対象 unit/integration test
- [x] `PYTHONPATH=src pytest -q`（1,452 passed）
- [ ] `ruff check .`
- [x] 変更対象への `ruff check`
- [x] `mypy src/grafix`
- [x] benchmark schema/checksum test
- [x] current vs fixed の同一 machine comparison
- [ ] 実 GUI で軽量 translate を 10 秒 drag
- [ ] 実 GUI で軽量 scale を 10 秒 drag
- [ ] forward/reverse、slow drag、fast drag、release後 idle
- [x] 1 worker、2 workers、sync 0 worker
- [ ] source reload 後の最初の drag
- [ ] 10分以上の長寿命 slider/animation soak
- [x] PNG/SVG/G-code/video/thumbnail provenance

## 11. 完了定義

次をすべて満たした時点で完了とする。

1. [x] 既定 1-worker の連続 slider 操作中にも fresh result が継続する。
2. [x] 最終 slider 値と表示結果、capture manifest revision が一致する。
3. [x] input-to-result の tail が定義した目標内に入る。
4. [x] CPU cache entry と RSS が操作時間に比例して増え続けず、GPU transient 値を昇格しない。
5. [x] 通常 preview では provenance を具体化しない。
6. 1,000 parameter でも changed-frame 固定費が 16.7 ms frame budget を単独で超えない。
7. [x] benchmark が今回の `0 / 120 fresh results` 回帰を自動検出する。
8. [x] 既存テスト、変更対象 lint、型検査、capture checksum がすべて通る。

`ruff check .` は今回変更していない `.agents/skills/` と `sketch/` の既存 33 件で失敗する。
今回の変更対象ファイルへの Ruff、全 `src/grafix` の mypy、全 pytest は成功した。
