# Grafix 性能改善 実装計画

- 作成日: 2026-07-17
- 状態: 実装・統合検証完了
- 元資料: [`grafix_performance_improvement_ideas_2026-07-17.md`](grafix_performance_improvement_ideas_2026-07-17.md)
- 実装方針: 新しい計測基盤を先に固定し、その同じ case で before/after を測る

## 1. この実装単位の目的

最初の実装単位では、元資料の全案を一括実装せず、根拠が強く、互いの検証に必要な次の 5 件を完了させる。

1. **BENCH-01**: 比較可能な benchmark schema v3、isolated runner、checksum、compare、CI artifact
2. **RT-01**: parameter provenance の revision cache
3. **GUI-01**: parameter table の不要な activity 判定と行コピーの除去
4. **GEO-01**: bulk concat、反復 `+` の二乗時間解消、iterative DAG 評価
5. **GL-01**: 座標だけが変わる geometry の topology/index/IBO 再利用

この 5 件により、計測の信頼性、preview の毎フレーム固定費、大規模 recipe の構築、動的 geometry の renderer 固定費を同じ変更単位で改善する。

## 2. 今回は実装しない項目

以下は schema v3 の測定結果を見て、別の実装計画に分ける。

- `RT-02`: 同じ MP result / pause 中の realized scene 再利用
- `RT-03`: scene-level mesh packing と本格的な draw batching
- `FX-01` / `FX-02`: `PlanarFrame`、reaction diffusion、metaball、relax の algorithm 変更
- `CACHE-01`: alias-aware byte accounting、2Q cache
- `MP-01`: worker-side realize、shared memory
- `PERF-01` のうち asynchronous trace writer、実 GPU timer query
- `GL-02`: stroke backend / MSAA の比較と renderer 全面変更

理由は、これらが正しさ、memory lifetime、描画順、process failure semantics に大きく影響するためである。今回の runner で支配項と効果量を確定してから着手する。

## 3. 共通の設計判断

### 3.1 互換性

- benchmark CLI と JSON は schema v3 へ破壊的に変更する。
- schema v2 reader、旧 CLI flag の互換 wrapper、変換 shim は作らない。
- report は schema v2 を黙って無視せず、非対応 run として件数・path を表示する。
- geometry の描画結果、leaf 順、layer 順、capture manifest の JSON 構造と hash semantics は維持する。

### 3.2 依存

- 新規依存は追加しない。
- timing は `time.perf_counter_ns()`、隔離は `subprocess` / `multiprocessing`、memory は標準ライブラリと既存依存で実装する。
- `pyperf`、`pytest-benchmark`、ASV は今回導入しない。

### 3.3 比較可能性

benchmark JSON では、次を別概念として保存する。

- **source identity**: git commit、dirty flag、diff hash。base/head で異なることを許す。
- **environment compatibility**: Python、依存、OS、machine、CPU/GPU、thread/Numba 環境。異なる場合は既定で比較拒否する。
- **case identity**: case ID/version、fixture、parameter、seed、case source hash。異なる場合はその case を比較拒否する。

source identity を environment compatibility key に含めない。含めると、比較対象である base/head が常に非互換になるためである。

### 3.4 性能 gate

- hosted CI の wall time は artifact と soft warning に留める。
- hard failure は checksum、不変条件、cache/memory 上限、error/drop など決定的な項目を優先する。
- ローカル before/after は同一 machine、同一 environment、同一 case source で比較する。
- n が少ない smoke result では p95/p99 を判定に使わない。

## 4. 変更予定ファイル

### 4.1 benchmark

新規候補:

- `src/grafix/devtools/benchmarks/schema.py`
  - schema v3 の dataclass、JSON 化、raw sample、統計
- `src/grafix/devtools/benchmarks/environment.py`
  - source/environment/case fingerprint
- `src/grafix/devtools/benchmarks/runner.py`
  - case registry、calibration、isolated child protocol、RSS delta、checksum
- `src/grafix/devtools/benchmarks/cli.py`
  - `list` / `run` / `compare` / `report`

既存変更:

- `src/grafix/devtools/benchmarks/__init__.py`
- `src/grafix/devtools/benchmarks/cases.py`
- `src/grafix/devtools/benchmarks/effect_benchmark.py`
- `src/grafix/devtools/benchmarks/system_benchmark.py`
- `src/grafix/devtools/benchmarks/mp_draw_benchmark.py`
- `src/grafix/devtools/benchmarks/generate_report.py`
- `src/grafix/__main__.py`
- `.github/workflows/ci.yml`
- `docs/memo/performance.md`

テスト:

- `tests/devtools/benchmarks/test_schema.py`（新規）
- `tests/devtools/benchmarks/test_runner.py`（新規）
- `tests/devtools/benchmarks/test_compare.py`（新規）
- 既存 `tests/devtools/benchmarks/`
- CLI dispatch test

### 4.2 provenance / parameter GUI

- `src/grafix/core/parameters/runtime.py`
- `src/grafix/core/parameters/merge_ops.py`
- `src/grafix/core/capture_provenance.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/visibility.py`
- `tests/core/parameters/test_merge_ops.py` または既存 merge test
- `tests/core/test_capture_provenance.py`
- `tests/interactive/parameter_gui/test_parameter_gui_visibility.py`
- `tests/interactive/parameter_gui/test_parameter_filter.py`
- `tests/interactive/parameter_gui/test_parameter_table_model.py`

### 4.3 Geometry / renderer

- `src/grafix/core/geometry.py`
- `src/grafix/core/realize.py`
- Grafix 内部で反復 `+` を使う呼び出し元
- `src/grafix/interactive/gl/line_mesh.py`
- `src/grafix/interactive/gl/draw_renderer.py`
- `tests/core/test_geometry_add.py`
- `tests/core/test_realize_cache.py`
- `tests/interactive/test_draw_renderer_cache.py`
- `tests/interactive/test_index_buffer.py`

## 5. 実装手順

### Phase 0: 現行挙動の固定

- [x] `git status --porcelain` を記録し、依頼外差分があれば触らない。
- [x] provenance、parameter GUI、Geometry、RealizeSession、renderer、benchmark の対象テストを実行する。
- [x] 現行 schema v2 の短い system benchmark を `/tmp` に保存する。
- [x] capture manifest hash、concat leaf 順、cache hit/miss、renderer upload 回数の現行値を test fixture として確認する。
- [x] 新規依存を追加しないことを確認する。

Phase 0 の値は参考記録とし、性能比較用の正式 baseline は Phase 1 完了後に schema v3 で取り直す。

### Phase 1: BENCH-01 schema v3

#### 1A. 型と統計

- [x] `RunMeta`、`EnvironmentFingerprint`、`SourceIdentity`、`CaseSpec`、`Sample`、`CaseResult`、`BenchmarkRun` を dataclass で定義する。
- [x] raw nanoseconds から median、MAD、min/max、必要 sample 数を満たす場合だけ tail percentile を計算する。
- [x] JSON encoder/decoder を 1 箇所に集約し、不明 field、欠落 field、非対応 schema を明示的に拒否する。
- [x] run ID を timestamp + suffix とし、既存 JSON を上書きしない。
- [x] atomic writer は既存 `atomic_write` を再利用する。

#### 1B. fingerprint

- [x] git commit、dirty flag、diff hash を source identity に保存する。
- [x] Python、Grafix、NumPy、Numba、moderngl、pyglet、macOS build、machine、CPU core、RAM、GPU、関連 environment variable を収集する。
- [x] 取得不能な項目は `unavailable` と理由を保存し、架空値で埋めない。
- [x] environment compatibility key と source identity を分離する。
- [x] case ID/version、fixture、parameter、seed、case implementation source hash を case identity にする。

#### 1C. isolated runner

- [x] public case ID と serializable 設定だけを child へ渡し、closure や大きな NumPy array を pickle しない。
- [x] child 内で setup、warmup、calibration、timed loop、output 検査を行う。
- [x] setup 直後を `setup_rss_bytes`、warmup/calibration 後を `baseline_rss_bytes` とし、timed loop 後の high-water 差を `peak_rss_delta_bytes` とする。
- [x] `compile_cold` は空の一時 `NUMBA_CACHE_DIR`、`process_cold` は通常 disk cache、`warm` は同じ child の校正後として区別する。
- [x] effect/system case を 1 case ずつ fresh child で実行可能にする。
- [x] child crash、timeout、unsupported dependency、resource limit を構造化 result にする。

#### 1D. fixture と正しさ

- [x] geometry の coordinates/offsets を dtype・shape・bytes とともに canonical checksum 化する。
- [x] exact checksum と量子化/tolerance invariant を case ごとに明示する。
- [x] arity だけで effect case を選ばず、effect と fixture の互換 tag を registry に定義する。
- [x] provenance 100/1,000/5,000 parameters を追加する。
- [x] parameter GUI 100/1,000/10,000 rows を追加する。
- [x] concat 10〜10,000 parts、深い DAG を追加する。
- [x] renderer の static、animated coordinates/static offsets、animated topology を追加する。
- [x] existing effect/system/MP case は同じ schema へ載せ、複合平均ではなく子 metric を保持する。

#### 1E. CLI / compare / report

- [x] `benchmark list` を実装する。
- [x] `benchmark run --suite ... --case ... --profile ...` を実装する。
- [x] `benchmark compare BASE HEAD` を実装し、environment/case 非互換を既定で拒否する。
- [x] `benchmark report` を offline HTML として生成する。
- [x] 壊れた JSON、schema 不一致、比較不能 case を warning 一覧へ出す。
- [x] effect だけでなく system/MP/runtime case を report に載せる。
- [x] 現在受理して無視している引数をなくし、対応するか parser で拒否する。

#### 1F. CI / docs

- [x] performance smoke を新 CLI へ更新する。
- [x] JSON、HTML、warning summary を GitHub Actions artifact として upload する。
- [x] hosted runner では wall-time hard gate を置かない。
- [x] `docs/memo/performance.md` を packaged benchmark scenario に更新し、存在しない `sketch/perf_sketch.py` 参照を削除する。
- [x] schema v3 runner 完了時点で、最適化前の正式 baseline を `/tmp` に保存する。

#### Phase 1 完了条件

- case ごとの RSS delta が実行順に依存しない。
- raw sample、checksum、source/environment/case identity が JSON に残る。
- compare が異なる source を比較でき、異なる environment/case を拒否できる。
- smoke と report が network/CDN 無しで完了する。
- 旧 schema/壊れた run が黙って消えない。

### Phase 2: RT-01 と GUI-01

#### 2A. effective revision

- [x] `ParamStoreRuntime` の末尾に内部 `effective_revision` を追加する。
- [x] `merge_frame_params()` で effective 値または source が実際に変わった frame だけ、merge 終了時に 1 回進める。
- [x] 同じ record の再 merge、failed frame、値の不変な再評価では revision を進めない。
- [x] runtime effective 値は scalar/immutable tuple の既存契約を維持し、mutable object の in-place 変更を導入しない。

#### 2B. provenance cache

- [x] `CaptureProvenanceBuilder` に直近 1 件の `(store identity, store revision, effective revision)` cache を持たせる。
- [x] cache miss 時だけ既存 `_parameter_snapshot()` を実行する。
- [x] canonical JSON、SHA-256、manifest field、`parameters.revision` は変更しない。
- [x] source reload では builder ごと交換され、旧 source の cache を引き継がない。
- [x] stable/changed parameter case を別々に測る。

真の lazy token 化は今回行わない。まず 1-entry revision cache で preview の残存 cost を測り、具体的な `CaptureProvenance` を要求する `Frame` / recording / export の契約変更が必要か判断する。

#### 2C. parameter GUI fast path

- [x] `show_inactive_params=True` かつ activity filter が `all` の場合、`active_mask_for_rows()` を呼ばない。
- [x] search/favorite/error のみの filter でも activity mask を省略する。
- [x] `show_inactive_params=False`、`activity=active/inactive` では現行判定を維持する。
- [x] immutable model rows / visible mask の不要な list copy を除去する。
- [x] `rows_after` と全行への編集復元は `changed=True` の場合だけ実行する。
- [x] loaded だが未observedの group、collapse、MIDI、favorite、error、編集の semantics を維持する。
- [x] activity-mask cache は fast path だけで目標達成したため追加しない。

#### Phase 2 完了条件

- stable provenance は 1,000 parameters で現状比 90% 以上短縮する。
- cache 前後の manifest hash が完全一致する。
- 古い frame を後から export しても、その frame の provenance を保持する。
- parameter GUI 1,000 rows、検索無し、編集無しの steady median を 0.5 ms 以下にする。
- 10,000 rows の増加が概ね線形である。

### Phase 3: GEO-01

#### 3A. bulk concat

- [x] `Geometry.concat(iterable)` を追加し、generator を 1 pass で受ける。
- [x] empty、single、nested concat、leaf 順の契約を明示する。
- [x] Grafix 内部の反復 `+` producer を bulk API へ移す。
- [x] `Geometry._concat()` と公開 `+` の責務を整理する。

#### 3B. 反復 `+`

- [x] `+` を O(1) の binary concat recipe に変更する。
- [x] parenthesization により recipe ID が変わることを破壊的変更として受け入れ、旧 flat-input ID の互換処理は作らない。
- [x] realize 時は nested concat leaf を iterative に集め、各中間 concat ごとに packed array を作らない。
- [x] `sum()`、left/right association、empty/single の出力順を維持する。

#### 3C. iterative DAG evaluator

- [x] 既に iterative な operation registration は作り直さない。
- [x] `_is_geometry_cacheable()` を explicit post-order stack にする。
- [x] `_realize()` / node evaluation を explicit frame stack にする。
- [x] content-cacheable な共有 child は key ごとに 1 回評価する。
- [x] `cache_policy="none"` の共有 child は現行どおり必要な occurrence ごとに評価し、誤って dedupe しない。
- [x] inflight leader/waiter、例外通知、`BaseException`、cache transaction、resource budget、operation profiler を維持する。
- [x] nested concat は leaf を一括 packing し、評価側へ O(n²) を移さない。

#### Phase 3 完了条件

- 2,000 parts の recipe 構築を 5 ms 以下にし、10,000 parts で二乗曲線にならない。
- 深さ 10,000 の合法な unary/concat DAG を `RecursionError` 無しで評価する。
- coordinates、offsets、leaf 順、cache hit/miss、inflight failure semantics が既存 test と一致する。
- non-cacheable shared child の評価回数を意図せず減らさない。

### Phase 4: GL-01

#### 4A. mesh upload の分離

- [x] `LineMesh` に VBO だけを更新する `upload_vertices()` を追加する。
- [x] 既存の全 upload は VBO/IBO capacity growth と byte accounting を維持する。
- [x] empty geometry、empty indices、buffer grow を test する。

#### 4B. scratch topology

- [x] `DrawRenderer` に 1 件の scratch topology record を持たせる。
- [x] record は offsets への strong reference、indices、`LineIndexStats` を保持する。
- [x] `record.offsets is realized.offsets` の時だけ topology hit とする。
- [x] `id(offsets)` 単独、毎 frame の offsets 全量 hash は使わない。
- [x] topology hit は index build と IBO upload を省き、VBO だけ更新する。
- [x] offsets object が変われば、同内容でも安全側で miss とする。

#### 4C. candidate / full cache

- [x] 2-hit candidate を ndarray payload 保持型から bounded key/count admission へ簡素化する。
- [x] static geometry の 2 回目は scratch topology から full GPU cache へ昇格できるようにする。
- [x] `_MeshCacheEntry.indices` が参照されていないことを test で固定した上で削除する。
- [x] full cache byte budget は実際の VBO/IBO bytes を数える。
- [x] candidate は明示的な最大件数を持ち、cache limit の意味を曖昧にしない。
- [x] renderer close/release 時に scratch strong reference と GPU resource を解放する。

#### Phase 4 完了条件

- 異なる geometry key・同じ offsets object の 3 frames で、index build 1 回、IBO write 1 回、VBO write 3 回となる。
- offsets object 変更時は index build / IBO write が増える。
- static full-cache hit の現行性能と upload 回数を悪化させない。
- 100k / 1M polylines で CPU time、VBO/IBO upload bytes、candidate metadata 数を schema v3 に保存する。
- 実 pipeline で offsets identity が維持されず hit しない場合、内容 hash cacheを追加せず、GL-01 をそこで止めて結果を記録する。

### Phase 5: 統合検証

- [x] Phase 1 で保存した schema v3 baseline と同じ case source で head を測る。
- [x] `benchmark compare` で環境互換と checksum parity を確認する。
- [x] provenance、GUI、concat/DAG、renderer の個別 test を実行する。
- [x] `PYTHONPATH=src pytest -q` を実行する。
- [x] `ruff check src/grafix tests` を実行する。
- [x] `mypy src/grafix` を実行する。
- [x] `git diff --check` を実行する。
- [x] `docs/memo/performance.md` に新 CLI、metric の意味、再現手順を反映する。
- [x] 本ファイルの完了項目を更新し、未達値と見送った optional step を明記する。

## 6. 停止条件

次の場合は、複雑な代案へ自動的に進まず、その phase を未完了として記録する。

- checksum、描画順、capture hash、last-good semantics が維持できない。
- cache/inflight の正しさを保つために互換層や二重実装が必要になる。
- activity cache、offsets hash、shared memory など、測定で必要性が出ていない機構が必要になる。
- hosted CI の時間ノイズしか改善根拠がない。
- memory 使用量または tail latency が、median 改善以上に悪化する。
- full test、ruff、mypy の既存失敗と今回の失敗を区別できない。

## 7. 実装完了時に報告する内容

- 変更した public/internal 契約
- schema v3 の実行例と artifact path
- case ごとの before / after / ratio / checksum
- provenance、GUI、concat/DAG、renderer の受け入れ基準結果
- full test、ruff、mypy の結果
- 未達・見送り・次段へ回した項目

## 8. 進捗

- [x] 改善アイデアの調査
- [x] 実装計画の作成
- [x] 計画承認（2026-07-17）
- [x] Phase 0
- [x] Phase 1
- [x] Phase 2
- [x] Phase 3
- [x] Phase 4
- [x] Phase 5

## 9. 実装結果

### 9.1 正式 before / after

最適化前の `HEAD` core に最終 schema v3 harness を重ねた baseline と、変更後
head を、同一 machine・environment key・case compatibility key・計測設定で比較した。
保存先は `/tmp/grafix-performance-v3-final/`。

| case | baseline median | head median | head / baseline | checksum |
|---|---:|---:|---:|---|
| stable provenance / 1,000 | 10.765 ms | 0.00167 ms | 0.000155 | 一致 |
| changed provenance / 1,000 | 21.593 ms | 21.543 ms | 0.9977 | 一致 |
| parameter GUI / 1,000 | 0.943 ms | 0.033 ms | 0.0350 | 一致 |
| repeated `+` / 10,000 | 7,600.947 ms | 24.582 ms | 0.00323 | 一致 |
| animated coords / static offsets / 100k | 3.639 ms | 0.235 ms | 0.0646 | 一致 |
| animated topology / 100k | 3.700 ms | 3.790 ms | 1.024 | 一致 |
| static renderer / 100k | 0.227 ms | 0.231 ms | 1.015 | 一致 |

`compare` は exit code 0、environment compatible、全 7 case で
checksum/checksum kind/case identity が一致した。深さ 5,000 の DAG は baseline が
`RecursionError`、head が 90.49 ms で完走したため、別 artifact へ capability
comparison として保存した。

### 9.2 受け入れ基準

- stable provenance は 1,000 parameters で 99.98% 以上短縮した。
- GUI は 1,000 rows で 0.033 ms、10,000 rows で 0.293 ms。
- 反復 `+` は 2,000 parts の直接計測で median 4.638 ms、10,000 parts でも二乗化しない。
- 100k animated coordinates/static offsets は index build 1 回、full upload 1 回、
  VBO-only upload 11 回。animated topology control は 12/12/0 回。
- 1M lines / 3 frames でも static offsets は index build 1 回、full upload 1 回、
  VBO-only upload 2 回。animated topology は index build/full upload とも 3 回。
- target test は core/parameter 245 件、interactive 471 件、benchmark 45 件が成功した。
- full test は 1,417 passed、ruff は成功、mypy は 211 files で成功、
  `git diff --check` も成功した。

### 9.3 見送り・制約

- GL case は fake mesh による CPU/index/upload-byte 検証であり、実 GPU timer query
  や driver latency は今回のスコープ外。
- activity-mask cache は fast path だけで目標を満たしたため追加していない。
- RT-02/RT-03、FX-01/FX-02、CACHE-01、MP-01、GL-02 は第 2 節どおり見送った。
- 深い DAG の baseline error は想定した改善対象であり、report の warning に明示される。
