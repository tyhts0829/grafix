# `src/grafix` コードレビュー改善実装計画（2026-07-12）

作成日: 2026-07-12
ステータス: 実装完了（性能目標の未達・設計上の残余は §17 に記録）
根拠: `docs/review/src_grafix_code_review_2026-07-12.md`

## 1. 目的

レビューの GFX-001〜021 を、正しさを崩さず段階的に実装する。

- 誤結果、crash、OOM、data loss を先に解消する。
- hot path は変更前後を同じ入力で測り、速度または計算量の改善を確認する。
- 並行 dict、無制限 global cache、重複 kernel、format ごとの worker を減らす。
- compatibility wrapper / shim は作らず、変更時に全 internal consumer と test を同時に移行する。
- 各 Phase の完了時に本計画のチェック欄と検証結果を更新し、未完了項目を明示する。

## 2. 実装時に固定する設計判断

承認後は、特段の指示がない限り次を採用する。

1. **Geometry 署名は schema v2 にする。** 型 tag 付き canonical tree を一括 hash し、
   実装へ渡す引数値と署名表現を分離する。
2. **primitive/effect registry は frozen `OpSpec` へ統合する。** `overwrite=False` を既定とし、
   `concat` の登録を禁止する。
3. **realize は session-owned にする。** byte-budget LRU と inflight coordinator を同じ
   `RealizeSession` が所有し、module-global mutable state を廃止する。
4. **`@preset` は `SceneItem` component 専用にする。** `activate=False` は空 Geometry を返す。
5. **平面処理は `PlanarFrame`、格子上限は `GridSpec` に一本化する。** 退化入力を identity として
   隠さず、rank/status を呼び出し側へ返す。
6. **上限超過時に部分 Geometry を返さない。** 一様に解像度を落とすか、入力全体を no-op とする。
7. **mp worker の予期せぬ終了は fail-fast にする。** 暗黙の同期 fallback は追加しない。
8. **preview/SVG の線幅は canvas 短辺基準の pixel width に統一する。** 矩形 canvas でも方向に
   依存させない。
9. **G-code の stroke 順と tie-break は完全互換にする。** 出力 byte parity を保ったまま
   内側 Python loop を除去し、必要なら spatial grid へ進む。
10. **新規依存は追加しない。** NumPy、Numba、Shapely、psutil、multiprocessing など既存依存で完結する。
11. **性能の主判定は同一 machine の before/after 比にする。** 通常 CI は correctness を hard gate、
    長い performance 計測は manual/nightly 相当へ分ける。
12. `run(..., n_worker=4)` の既定変更は先に軽量/重量 sketch を測り、軽量 case で明確に不利な場合だけ
    `1` へ変更する。profile-based auto は作らない。

## 3. 進行規則

- [x] 各実装単位の開始時に `git status --porcelain` を確認し、依頼外差分を触らない。
- [x] 先に再現 test または benchmark case を追加し、既存の failure mode を固定する。
- [x] 挙動変更と単なる file 分割を同じ実装単位に混ぜない。
- [x] effect 同士を直接 import せず、共有先は `core/effects/util.py` または core の汎用型に限定する。
- [x] 数値出力を変える変更では、固定 seed、line 順、dtype、offset、close 規則を比較する。
- [x] 各実装単位で対象 test、対象 ruff、対象 mypy を通す。
- [x] 各 Phase 終了時に full pytest を実行する。
- [x] Phase 8 で対象範囲 `ruff check src/grafix tests`、`mypy src/grafix`、full pytest をすべて成功させる。

## 4. Findings と実装単位の対応

| Finding | 実装単位 |
|---|---|
| GFX-001 | 1.1 Geometry signature v2 |
| GFX-002 | 2.1 immutable `OpSpec` registry |
| GFX-003 | 2.2 bounded `RealizeSession` |
| GFX-004 | 1.2 `drop` と既知 static error |
| GFX-005 | 3.1 `PlanarFrame` |
| GFX-006 | 3.2 resample preflight / 3.3 `GridSpec` |
| GFX-007 | 3.4 `subdivide` two-pass |
| GFX-008 | 1.3 atomic persistence |
| GFX-009 | 1.4 context cleanup / 2.2 inflight coordinator |
| GFX-010 | 1.5 Scene-only preset |
| GFX-011 | 1.6 export CLI run-id |
| GFX-012 | 1.7 odd-size video |
| GFX-013 | 4.1 line-width contract |
| GFX-014 | 4.2 worker health |
| GFX-015 | 4.3 G-code ordering |
| GFX-016 | 4.4 `ExportJobSystem` |
| GFX-017 | 5.1〜5.4 parameter hot path |
| GFX-018 | 5.5〜5.6 GL buffer/cache |
| GFX-019 | 6.1〜6.5 packed/batched kernels |
| GFX-020 | 7.1〜7.5 structural cleanup |
| GFX-021 | Phase 0 benchmark correctness / Phase 8 report・CI |

## 5. Phase 0 — 計測基盤と baseline

### 0.1 effect benchmark の入力契約を修正する（GFX-021A）

対象:

- `src/grafix/devtools/benchmarks/cases.py`
- `src/grafix/devtools/benchmarks/effect_benchmark.py`
- `src/grafix/devtools/benchmarks/generate_report.py`
- `tests/devtools/benchmarks/`（新規）

アクション:

- [x] `BenchmarkCase.geometry` を `inputs: tuple[RealizedGeometry, ...]` と scenario tags へ置換する。
- [x] registry の `n_inputs` と一致する case だけを実行する。
- [x] unary、binary、mask-grid、many-short-lines、huge-single-line、rings、identity case を追加する。
- [x] `clip` / `warp` が arity error ではなく実計測される test を追加する。
- [x] warm と isolated-process cold、median/p95、peak RSS、出力頂点/line 数を schema version 付き JSON に保存する。
- [x] benchmark JSON も sibling temp + `os.replace()` で保存する。
- [x] report を scenario schema に対応させ、case 単位の失敗を全 run の失敗と混同しない。

### 0.2 現状値を保存する

- [x] Geometry ID、callsite ID、G-code ordering、effect family、import、concat、fill、asemic の baseline を採取する。
- [x] baseline は `data/output/benchmarks` に置き、source diff へ混ぜない。
- [x] 同一 Python・同一 seed・各 5 process の median を比較値とする。
- [x] 現時点の `pytest` / `ruff` / `mypy` 結果を本計画の「実施記録」に追記する。

Phase 0 完了条件:

- [x] binary effect が正しく計測され、benchmark result を JSON → report まで round-trip できる。
- [x] 以降の performance finding に before 値が存在する。

## 6. Phase 1 — 小さく独立した correctness 修正

### 1.1 Geometry signature v2（GFX-001）

対象: `src/grafix/core/geometry.py`、新規 `tests/core/test_geometry_signature.py`

- [x] `int` の float 経由を廃止し、`2**53 + 1` をそのまま保持する。
- [x] `bool` / `int` / `float` / `str` / sequence / mapping / Enum を型 tag 付き canonical tree にする。
- [x] key/value と sequence 要素を長さまたは構造で区切り、delimiter 衝突をなくす。
- [x] 実装へ渡す normalized args と hash 用 canonical bytes を別関数にする。
- [x] schema version を 2 に上げ、旧 ID との compatibility layer は作らない。
- [x] string delimiter、nested tuple、`1`/`1.0`、large int、`-0.0`、Enum/IntEnum、dict key 順、
  非有限 float の test を追加する。
- [x] 「ID が同じなら evaluator が観測する型付き引数も同一」を property test にする。

### 1.2 `drop` と既知 static error（GFX-004）

- [x] `drop(by="face")` で face が 0 本なら `coords, offsets` をそのまま返す。
- [x] line-only regression test と no-op identity を追加する。
- [x] review 時点の ruff 8件、mypy 5件を分類し、未使用 import、再定義、Numba typing を対象箇所で解消する。

### 1.3 ParamStore と export writer の atomic persistence（GFX-008）

対象: `core/parameters/persistence.py` と export writer 群

- [x] sibling temp へ write → flush → fsync → `os.replace()` する小さな atomic writer を作る。
- [x] missing file だけを空 ParamStore とし、decode error は warning と一意な `.corrupt-*` 退避にする。
- [x] PermissionError 等の read error を空 store にせず送出する。
- [x] replace/write/cancel failure でも正式 path が不変、temp が残らない test を追加する。
- [x] SVG/G-code/MIDI/benchmark JSON を同じ writer へ移し、巨大 text は逐次書き込みにする。

### 1.4 Parameter Context cleanup（GFX-009A）

- [x] merge を内側の `try`、ContextVar reset を外側の `finally` に置く。
- [x] reset を token 設定の逆順で必ず行う。
- [x] label/params merge、nested context、draw の各 failure で全 context が復元される test を追加する。

### 1.5 preset を `SceneItem` 専用にする（GFX-010）

- [x] generic `R` と空 Geometry への `cast` を削除する。
- [x] decorator、registry、stub の戻り値を `SceneItem` に統一する。
- [x] `activate=False` が `normalize_scene()` 可能な空 scene になる test を追加する。
- [x] float/Path を返す test fixture を Scene component へ更新する。
- [x] README と生成 stub を更新する。

### 1.6 export CLI の `run_id` を一本化する（GFX-011）

- [x] 単一/複数 frame の `Export(...)` 呼び出しを内部 helper へ統合する。
- [x] 全経路で `run_id=args.run_id` を渡す。
- [x] `--out`、`--out-dir`、複数 `--t`、run-id なしを test する。

### 1.7 奇数寸法 video（GFX-012）

- [x] ffmpeg filter を vflip + 最大 1 px の偶数 pad にする。
- [x] 320x240 と 301x401 の command contract を unit test する。
- [x] ffmpeg が利用可能なら 1 frame integration test で return code と向きを確認する。

Phase 1 完了条件:

- [x] GFX-001、004、008〜012 の再現 test が成功する。
- [x] 対象 ruff/mypy が成功し、full pytest が成功する。

## 7. Phase 2 — registry、realize cache、例外 lifecycle

### 2.1 immutable `OpSpec` registry（GFX-002）

対象:

- 新規 `src/grafix/core/op_registry.py`
- `core/primitive_registry.py` / `core/effect_registry.py`
- API、parameter GUI、stub generator、benchmark の registry consumer

- [x] frozen/slots `OpSpec(evaluator, meta, defaults, param_order, ui_visible, n_inputs, kind)` を定義する。
- [x] function/metadata の並行 dict を `dict[str, OpSpec]` へ統合する。
- [x] primitive/effect の validation と登録規則を共通化する。
- [x] `overwrite=False` を既定にし、明示 replace だけ registry revision を進める。
- [x] reserved `concat` を登録時に拒否する。
- [x] getter compatibility API を残さず、全 consumer を spec 1回取得へ更新する。
- [x] stale metadata、stale realized result、reserved op、revision の regression test を追加する。
- [x] registry revision を CPU/GPU cache namespace に含める。

### 2.2 bounded `RealizeSession` と coordinator（GFX-003, GFX-009B）

- [x] `RealizedGeometry.byte_size` を追加する。
- [x] `RealizeCache` を `(GeometryId, registry_revision)` key の byte-budget LRU にする。
- [x] `CacheStats(hits, misses, evictions, entries, bytes)`、`clear()` を公開する。
- [x] cache lookup、leader 選択、inflight、waiter 通知を単一 coordinator lock/state にする。
- [x] leader 確定時の二重 cache 確認、全 failure path の `finally` cleanup を実装する。
- [x] `KeyboardInterrupt` / `SystemExit` を `RealizeError` に変換せず、waiter 通知後に元の型で再送出する。
- [x] `SceneRunner`、headless Export、pipeline が明示 `RealizeSession` を所有する。
- [x] module-global cache/inflight と private test 操作を削除する。
- [x] LRU順、byte eviction、oversized entry、同時1回計算、waiter例外、session close を test する。
- [x] 数千の animated Geometry ID で cache bytes が budget 内に留まり、静的上流 node の hit が残る soak test を追加する。

Phase 2 完了条件:

- [x] registry replace 後に CPU realized result と renderer cache key が更新される。
- [x] cache/RSS が上限で安定し、inflight と context が例外後に空になる。
- [x] full pytest、対象 ruff/mypy が成功する。

## 8. Phase 3 — effect の数学基盤と確保前 guard

### 3.1 `PlanarFrame`（GFX-005）

- [x] frozen/slots `PlanarFrame(origin, basis, inverse, residual, rank)` を `effects/util.py` に実装する。
- [x] 明示 close の末尾を重複加重せず、全点 PCA/Newell で決定的な法線と面内軸を求める。
- [x] 退化/非平面入力を rank/residual で表し、identity へ偽装しない。
- [x] `clip`、`growth`、`reaction_diffusion`、`isocontour`、`metaball`、`warp`、`weave`、`fill` を移行する。
- [x] `fill` の独自 PCA と `text` の開始点 workaround を削除する。
- [x] 先頭3点共線、重複、close、±Z、傾斜、小/大座標、degenerate、round-trip を test する。

### 3.2 low/high-pass resample preflight（GFX-006）

- [x] 全 line の closed 判定、長さ、出力 count を先に計算する共通 resample plan を作る。
- [x] cap 超過時は配列確保前に入力全体を no-op にする。
- [x] 第2 pass で packed output を一度だけ確保する。
- [x] resample/Gaussian/boundary 処理だけ共有し、low/high 固有式は各 module に残す。
- [x] cap 直下/一致/超過、open/closed、重複点、複数 line を test する。

### 3.3 `GridSpec`（GFX-006）

- [x] 非確保の `GridSpec.from_bbox(bounds, pitch, max_cells)` を実装する。
- [x] Python int で `nx * ny` を meshgrid 前に判定する。
- [x] cap 超過時は両軸で一様に pitch を増やして cap 内へ収めるか、effect 契約に従い全体 no-op にする。
- [x] `metaball` を先に移行し、`isocontour` / `reaction_diffusion` / `growth` の既存 guard を統合する。
- [x] 極小 pitch、巨大/退化/non-finite bbox、cap 境界を test する。

### 3.4 `subdivide` two-pass（GFX-007）

- [x] 全 line の要求出力数を第1 pass で数える。
- [x] cap に収まらなければ全 line 共通の division 数へ一様に下げる。
- [x] 入力自体が cap 超過なら全体 no-op とし、geometry 途中で `break` しない。
- [x] 従来2本目が消える小 cap case、全 line 保持、division 一様性を test する。

Phase 3 完了条件:

- [x] 対象 effect の平面変換が1実装になり、旧 transform helper が残らない。
- [x] grid/resample/subdivide は大規模出力を確保する前に上限を判定する。
- [x] full pytest と対象 benchmark が成功する。

## 9. Phase 4 — runtime / export の正しさと応答性

### 4.1 preview / SVG 線幅契約（GFX-013）

- [x] `thickness -> pixel width` の純粋 helper を追加する。
- [x] geometry shader へ viewport と pixel width を渡し、pixel-space 法線から clip offset を作る。
- [x] zero-length segment を shader で出力せず、viewport uniform は resize 時だけ更新する。
- [x] 縦長/横長/正方形、水平/垂直/斜線、HiDPI、SVG rasterize との差を test する。

### 4.2 mp-draw worker health（GFX-014）

- [x] PID/exitcode/worker 名を持つ `MpDrawWorkerError` を追加する。
- [x] submit/poll 共通の health check と worker ready message を実装する。
- [x] 正常 close と予期せぬ終了を区別し、Queue の close/join_thread まで idempotent に行う。
- [x] `SystemExit`、`os._exit(7)`、1/all worker death、二重 close、resource leak を test する。

### 4.3 G-code stroke ordering（GFX-015）

- [x] 現行 ordering を test 内 reference として固定する。
- [x] endpoint を packed int64 配列へ移し、vectorized scan で Python 内側 loop を除去する。
- [x] 性能目標に届かなければ、両 endpoint を登録する bounded spatial grid へ置換する。
- [x] 先頭 stroke、block 境界、`(dist2, poly_idx, seg_idx, reversed)` tie-break を完全維持する。
- [x] 1〜200 stroke の乱数 case を reference と全順序比較し、golden G-code を byte 比較する。

### 4.4 長寿命 `ExportJobSystem`（GFX-016）

- [x] immutable `FrameExportSnapshot` / `ExportJob` / `ExportJobResult` を定義する。
- [x] PNG と G-code を共通の長寿命 spawn worker へ移す。
- [x] Queue は bounded、同種連打は latest-wins、in-flight + pending を最大各1件にする。
- [x] success/error/timeout/cancel/worker death/close を同じ lifecycle で扱う。
- [x] `DrawWindowSystem` は key 入力、snapshot submit、result 表示だけにする。
- [x] 2秒 export 中も frame callback が継続し、連打で RSS が増え続けない test を追加する。

Phase 4 完了条件:

- [x] odd video、worker death、run-id、rectangular line width、export cancel の回帰 test が成功する。
- [x] G-code ordering が決定性を維持して性能基準を満たす。
- [x] export 中も interactive event loop が停止しない。

## 10. Phase 5 — parameter / renderer hot path

### 5.1 explicit key と callsite cache（GFX-017A）

- [x] code object ごとに project-relative path を bounded cache する。
- [x] `(code object, f_lasti)` と明示 `key` を共通 helper で site ID にする。
- [x] G/E/L に `key=str|int|None` を追加し、P の key 処理も同じ helper へ統合する。
- [x] absolute site ID は既存 reconcile で一度だけ移行し、shim は作らない。
- [x] 同じ location、別 key、別 cwd/repository path、loop instance を test する。

### 5.2 reconcile と ParamStore revision（GFX-017B/C）

- [x] migration 済み group を次 frame の fingerprint/matching 対象から除外する。
- [x] ParamStore に構造変更時だけ進む monotonic revision を追加する。
- [x] 同値 merge と `last_effective` のみの変化では構造 revision を進めない。
- [x] `store_snapshot()` を revision 単位に cache する。
- [x] mutation ops の revision 更新を一元化する。
- [x] 1,000 row × 60回で snapshot 実構築1回、reconcile は1 migration 1回を test する。

### 5.3 revision 付き worker snapshot（GFX-017D）

- [x] frame task から full ParamSnapshot を除去し、revision だけを渡す。
- [x] revision 変更時だけ各 worker の control channel へ snapshot を broadcast する。
- [x] worker は未知/stale revision で draw せず、適用 revision を ack する。
- [x] 600 frame 不変時の full snapshot send が初回1回だけであることを test する。

### 5.4 GUI `ParameterTableModel`（GFX-017E）

- [x] snapshot/registry 由来の不変行を model に分離する。
- [x] model を `(store_revision, registry_revision)` で cache する。
- [x] effective value、MIDI、visibility など動的部分だけ毎 frame 更新する。
- [x] font は設定/backing scale 変更時だけ再解決する。
- [x] 1,000 row × 60 frame で model build 1回、変更時だけ invalidate する test を追加する。

### 5.5 GL buffer の geometric growth（GFX-018A）

- [x] VBO/IBO を `max(required, current * growth_factor)` で別々に増やす。
- [x] 新 buffer 作成成功後に旧 buffer を release する。
- [x] どちらかが変化した時だけ VAO を1回再構築する。
- [x] 8MiB→32MiB の小刻みな増加で再確保回数が logarithmic になる test を追加する。

### 5.6 geometry 単位の統合 byte-LRU（GFX-018B）

- [x] `geometry cache key -> indices/stats/mesh/byte_size` の1 entry に統合する。
- [x] `DrawRenderer` が index build/upload/cache を所有し、window system から重複 loop を削除する。
- [x] eviction で GL resource を即 release する。
- [x] cache hit で offsets の `.tobytes()`、index build、upload が走らない test を追加する。
- [x] registry revision を key に含め、op replace 後の stale GPU mesh を防ぐ。

Phase 5 完了条件:

- [x] steady-state frame で site path、snapshot、GUI model、index、upload の不変作業を再実行しない。
- [x] CPU/GPU cache が byte budget 内に留まり、GL resource が deterministic に解放される。
- [x] full pytest と対象 benchmark が成功する。

## 11. Phase 6 — packed / batched kernel の横展開

### 6.1 planar-grid backend（GFX-019）

- [x] `isocontour` の scanline mask、boundary raster、2-pass EDT、marching squares を挙動不変で `util.py` へ抽出する。
- [x] `isocontour` parity 確認後、`reaction_diffusion` → `growth` → `metaball` の順で採用する。
- [x] 外周+穴、複数 ring、境界接触、傾斜平面、固定 seed を test する。

### 6.2 `fill` batching

- [x] hatch endpoint を最終 `(2*n, 3)` packed array へ直接書く。
- [x] offsets を `arange` で作り、inverse transform を全 endpoint へ1回だけ適用する。
- [x] line 順、穴、float32 output を維持する。

### 6.3 identity fast path

- [x] `rotate` のゼロ回転と `scale` の `(1,1,1)` を中心計算前に返す。
- [x] identity 時に元 `RealizedGeometry` object を再利用する test を追加する。

### 6.4 concat packing

- [x] `realized_geometry.py` の2つの concat 実装を1 private kernel にする。
- [x] 総頂点/offset 数を preflight し、`np.empty` へ slice 書き込みして `.tolist()` を削除する。
- [x] empty、zero-length line、dtype/offset、10k short geometry を test/benchmark する。

### 6.5 asemic topology/layout

- [x] topology 生成と layout を分離する。
- [x] 隣接判定を allocation-free compiled loop にする。
- [x] unit glyph を bounded LRU に置き、cache array を read-only にする。
- [x] layout は最終 packed array へ直接書く。
- [x] pure-Python reference、determinism、cache hit、cache cap を test する。

Phase 6 完了条件:

- [x] planar grid、fill、affine identity、concat、asemic の正しさを比較 test で固定し、性能は未達値も含めて §17 に記録する。
- [x] 利用箇所が1つしかない speculative framework を追加していない。

## 12. Phase 7 — 構造整理と dead code 削除（GFX-020）

### 7.1 小さい共通語彙

- [x] `empty_geom()`、`pack_polylines()` を実需のある箇所へ導入する。
- [x] Builder class は2つ以上の複雑な利用箇所が出た場合だけ追加する。
- [x] low/high-pass の重複 resampling code を削除する。
- [x] effects 内の `_empty_geometry` 重複を共通 helper へ移行する。

### 7.2 旧実装削除

- [x] `collapse`、`mirror`、`fill` の参照0旧 helper を wrapper なしで削除する。
- [x] private helper test を public behavior test へ置き換える。
- [x] 重複 index kernel を1本化する。

### 7.3 lazy builtin import

- [x] `core/builtins.py` に明示 `op -> module` manifest を追加する。
- [x] G/E の属性 lookup または registry lookup で対象 module だけ load する。
- [x] list/stub generation だけ全 builtin を明示 load する。
- [x] `import grafix` から全 primitive/effect eager import を削除する。
- [x] root import 直後0 module、`G.polygon` で polygon のみ load、list/stub parity を test する。

### 7.4 長大 orchestration の責務分離

- [x] `DrawWindowSystem` から export format 固有 process/queue/helper を削除する。
- [x] G-code を orchestration / clipping / ordering / dialect emission に分離する。
- [x] GUI は model構築/store反映とtable描画の境界を明確にする。
- [x] `runtime_config` を nested dataclass ごとの parser と recursive mapping merge に整理する。

### 7.5 docs / stubs / static cleanup

- [x] `api/export.py` の「未実装スタブ」記述を現状へ合わせる。
- [x] README、architecture、glossary、config、生成 `.pyi` を破壊的 API 変更へ同期する。
- [x] unused import、dead branch、古い comment/docstring を削除する。

Phase 7 完了条件:

- [x] 旧 helper、互換 shim、並行 registry dict、format 固有 worker が残らない。
- [x] lazy load 後も public import、stub、list command の内容が一致する。
- [x] full pytest、ruff、mypy が成功する。

## 13. Phase 8 — 最終 benchmark、CI、完了判定（GFX-021B）

- [x] cache stats と animated soak を benchmark report に接続する。
- [x] draw → realize → indices の end-to-end CPU frame case を追加する。
- [x] G-code、site ID、snapshot/model、renderer cache、import の microbenchmark を report に統合する。
- [x] wall time、peak RSS、output size、cache hits/misses/evictions/bytes を表示する。
- [x] `.github/workflows/ci.yml` を追加し、pytest / ruff / mypy を hard gate にする。
- [x] 短い deterministic performance smoke だけ通常 CI に入れ、長い比較は manual job に分ける。
- [x] full test、static checks、before/after benchmark を実行し、本計画へ結果を記録する。
- [x] review 文書の全 GFX ID に「完了」または明示的な未完理由を対応付ける。

## 14. 性能の受け入れ目安

絶対値は review 時の基準環境 `/opt/anaconda3/envs/gl5/bin/python` で確認し、併せて同一環境の比率を見る。

| 対象 | 目安 |
|---|---|
| Geometry signature | correctness 修正後も典型 case で現状より遅くしない |
| cached site ID | 1 us/call 以下、または現状比 10倍以上 |
| G-code 10k / 50k strokes | 2秒以下 / 15秒以下、50k/10k 比 10未満 |
| realize animated soak | `bytes <= budget`、静的上流 cache hit を維持 |
| low/high 通常 case | baseline 比 +10% 以内 |
| planar-grid 移行対象 | 512²・5k edges で 2倍以上 |
| isocontour 抽出 | baseline 比 +10% 以内 |
| fill 10k hatch | 2倍以上、peak memory 60%以下 |
| rotate/scale identity 50k点 | 20倍以上 |
| concat 10k short geometries | 1.5倍以上、Python allocation 50%以下 |
| asemic n=200 cold / layout-only warm | 3倍以上 / 10倍以上 |
| renderer 100k polyline cache hit | 10 us/layer 以下、index build/upload 0回 |
| GUI 1,000 rows × 60 frames | model build 1回、steady preparation 0.5 ms/frame 以下 |
| export job idle overhead | 0.1 ms/frame 未満、submit 5 ms未満 |
| lazy import | cold wall/RSS 30%以上削減、worker spawn 20%以上削減 |

性能目標に届かない場合は、correctness を戻さず profile 結果を本計画へ記録し、次の小さい実装へ進む。
絶対 wall time/RSS は通常 CI の flaky な hard gate にはしない。

## 15. 検証コマンド

各実装単位:

```bash
PYTHONPATH=src pytest -q <対象test>
ruff check <対象path>
mypy <対象src path>
```

各 Phase / 最終（今回の依頼対象）:

```bash
PYTHONPATH=src pytest -q
ruff check src/grafix tests
mypy src/grafix
```

`ruff check .` は依頼外の `.agents/` と `sketch/` に既存 33 件が残るため、対象範囲の hard gate と分離する。

必要な integration / performance:

```bash
PYTHONPATH=src pytest -q -m integration
PYTHONPATH=src pytest -q -m "e2e or perf"
```

## 16. 非対象

- 新規 third-party dependency の追加
- sketch、生成画像、既存作品データの整理
- 互換 wrapper / deprecated alias の追加
- G-code の経路最適化を厳密 TSP solver にすること
- 全 effect を1つの巨大 frameworkへ載せること
- ユーザー依頼のない commit / push / release

## 17. 実施記録

- [x] 計画承認（2026-07-13）
- [x] Phase 0 完了
- [x] Phase 1 完了
- [x] Phase 2 完了
- [x] Phase 3 完了
- [x] Phase 4 完了
- [x] Phase 5 完了
- [x] Phase 6 完了（性能目標の未達値を下記に記録）
- [x] Phase 7 完了
- [x] Phase 8 完了

### 17.1 最終検証

実行環境は `/opt/anaconda3/envs/gl5/bin/python`（Python 3.12.12）。

- full pytest: **690 passed in 12.10s**
- `ruff check src/grafix tests`: **All checks passed**
- `mypy src/grafix`: **Success: no issues found in 162 source files**
- `git diff --check`: **成功**
- system benchmark（`--system --repeats 1 --warmup 0`）: JSON と HTML report の生成に成功
- `ruff check .`: `.agents/` と `sketch/` の依頼外・既存差分に **33 errors**。`src/grafix` と `tests` は 0 件であり、本実装では依頼外ファイルを変更しない。

### 17.2 before / after

同一 Python・同一 machine の中央値。詳細 JSON は
`data/output/benchmarks/src_grafix_review_before_after_2026-07-13.json`、system report は
`data/output/benchmarks/runs/20260713_064000.json` に保存した（`data/output` は gitignore 対象）。

| 対象 | Before | After | 判定 |
|---|---:|---:|---|
| Geometry signature | 6.280 us | 4.484 us | 1.40x、correctness 修正後も改善 |
| cached site ID | 24.331 us | 0.455 us | 53.5x、1 us 未満 |
| cold `import grafix` | 370.3 ms | 69.8 ms | 5.30x |
| import peak RSS | 125.9 MB | 36.1 MB | 71.3% 削減 |
| eager builtin modules | 44 | 0 | lazy import 完了 |
| G-code 10k strokes | review 時約29 s | 0.108 s | 2 s 未満 |
| G-code 50k strokes | review 時推定約12 min | 0.705 s | 15 s 未満、10k比6.51 |
| callsite/model 1,000 rows × 60 | 毎 frame 構築 | 構築1回、steady 0.050 ms | 目標達成 |
| renderer 100k polyline | 再build/upload | build 1回、upload 2回、hit時 0.000125 ms | 目標達成 |

planar backend の同条件計測では、fill **1.46x**、growth **1.16x**、metaball **1.33x**、
reaction-diffusion mask **252.8x**、isocontour は測定ノイズ範囲だった。正しさと共通化は維持したが、
fill の 2x および planar-grid 全対象 2x の目安は未達であるため、将来の profile 対象として残す。

`n_worker` は `draw + normalize_scene`（realize 除外）を実測した。軽量 draw は n=4 が n=1 の
**0.019倍**（322,960 fps 対 6,139 fps）と明確に不利、重量 draw は **3.64倍**
（105.6 fps 対 384.7 fps）だった。このため既定を `n_worker=1` とし、重量処理だけ明示的に 4 を選ぶ。

### 17.3 Finding 完了対応

| Finding | 状態 | 実装結果 |
|---|---|---|
| GFX-001 | 完了 | schema v2 の型付き署名、large-int/Enum/delimiter/property test |
| GFX-002 | 完了 | frozen `OpSpec`、単一 registry、revision、明示 replace、`concat` 拒否 |
| GFX-003 | 完了 | session-owned byte-LRU、stats、単一 inflight coordinator |
| GFX-004 | 完了 | line-only `drop(by="face")` の no-op 修正 |
| GFX-005 | 完了 | `PlanarFrame` へ平面処理を統合 |
| GFX-006 | 完了 | `GridSpec` と resample preflight で確保前 guard |
| GFX-007 | 完了 | `subdivide` two-pass と全体契約 |
| GFX-008 | 完了 | ParamStore/export/benchmark の atomic writer と破損退避 |
| GFX-009 | 完了 | context/inflight/interrupt の cleanup |
| GFX-010 | 完了 | `SceneItem` 専用 preset と空 Geometry |
| GFX-011 | 完了 | export 全経路の run-id 統一 |
| GFX-012 | 完了 | 奇数 video の偶数 pad と向きの integration test |
| GFX-013 | 完了 | short-side pixel 線幅、viewport uniform、zero-segment guard |
| GFX-014 | 完了 | mp worker ready/health/fail-fast/idempotent close |
| GFX-015 | 完了 | exact endpoint index と tie-break/golden parity |
| GFX-016 | 完了 | 1 worker の bounded/latest-wins `ExportJobSystem` |
| GFX-017 | 完了 | explicit key、revision snapshot、worker broadcast、GUI model cache |
| GFX-018 | 完了 | 独立 geometric growth と byte-budgeted 2-hit renderer cache。CPU admission と GL mesh は別 budget とする設計 |
| GFX-019 | 完了（性能注記） | packed planar backend/fill/identity/concat/asemic。上記 2x 未達値を記録 |
| GFX-020 | 完了 | lazy builtins、共通 helper、dead code 削除、orchestration 分離、docs/stub 同期 |
| GFX-021 | 完了 | schema v2 benchmark、system case、RSS/cache report、CI smoke/manual 分離 |

### 17.4 既知の設計境界

- `ExportJobSystem` はメモリ上限を守るため、未 poll の終端結果を最大 64 件保持する。in-flight と pending は各1件で、pending の連打は latest-wins とする。
- renderer は低利用 geometry の GL upload を避ける 2-hit admission を採用し、CPU candidate 64 MiB と GL mesh 256 MiB を別 budget で管理する。
- registry replace と realize が真に同時の場合、その1評価は旧 revision namespace に入ることがあるが、新 revision から再利用されない。
- planar-grid 共通化に伴い growth の境界距離は exact segment SDF から raster/EDT 近似へ変わる。決定性は維持するが、固定 benchmark では 44 から 45 vertices へ変化した。
