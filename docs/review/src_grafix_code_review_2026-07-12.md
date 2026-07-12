# `src/grafix` 全体コードレビュー（2026-07-12）

## 1. 結論

Grafix の中心設計である **Geometry DAG → realize → RealizedGeometry → pipeline** は明快で、
interactive/export の共通化、packed な `coords/offsets` 表現、parameter snapshot の考え方も良い。
全面的な再設計は不要である。

一方、現状は次の 3 点が全体品質を制限している。

1. **キャッシュの前提となる `GeometryId` が一意ではない。**
   異なる引数が同じ ID になり、誤った座標を黙って返し得る。これは最優先で直すべき P0。
2. **上限・寿命・所有者が曖昧な状態がある。**
   realize cache、GPU cache、平面グリッド、再サンプル、worker、永続ファイルが該当する。
3. **同じ低レベル処理が複数実装され、既に挙動差と性能差が生じている。**
   平面推定、grid/EDT、polyline packing、low/high-pass、registry が代表例。

最も効果的な方針は、大きな抽象化を追加することではなく、次の少数の概念へ寄せることだと考える。

- 1 op = 1 immutable `OpSpec`
- unambiguous な Geometry 署名
- session-owned / byte-budgeted cache
- robust `PlanarFrame` と bounded `GridSpec`
- packed output builder
- revision 付き `ParamStore` view
- 1 本化した非同期 `ExportJobSystem`

## 2. 対象と検証

- 対象 commit: `4249ed7e81a7` (`main`)
- 対象: `src/grafix/**/*.py` 156 files、34,939 lines
- 主な内訳:
  - `api`: 1,243 lines
  - `core`: 23,062 lines
  - `core/effects`: 14,016 lines
  - `core/primitives`: 3,212 lines
  - `interactive`: 6,046 lines
  - `export`: 1,120 lines
  - `devtools`: 3,262 lines

実施内容:

- `README.md`、`architecture.md`、各 `AGENTS.md` の確認
- 全 Python file の AST parse、import graph、長大関数、重複関数、未定義名の走査
- Geometry 署名、registry overwrite、interrupt、context cleanup の再現 probe
- callsite ID、index cache、G-code stroke ordering の microbenchmark
- ffmpeg 奇数寸法の実コマンド確認
- full test:

```text
522 passed in 23.27s
```

- static checks:

```text
ruff check src/grafix: 8 errors
mypy src/grafix: 5 errors in 5 files
```

`ruff` と `mypy` はどちらも `src/grafix/core/effects/drop.py:291` の未定義 `base` を検出した。
既存 test が全件成功しても、未実行分岐とキャッシュ不変条件の欠陥は残っている。

優先度は次の意味で用いる。

- **P0**: 誤結果を黙って返す、基盤の正しさを破る
- **P1**: crash / OOM / data loss / 明確な user-facing failure
- **P2**: 有力な速度・可読性・保守性改善
- **P3**: 小さな cleanup / documentation drift

## 3. Findings summary

| ID | 優先度 | 要約 |
|---|---:|---|
| GFX-001 | P0 | Geometry 署名が delimiter/type-safe でなく、異なる引数が同じ ID になる |
| GFX-002 | P1 | registry overwrite 後も旧 realized result と旧 metadata が残る |
| GFX-003 | P1 | `realize_cache` が無制限で、animation 中の RSS が時間比例で増える |
| GFX-004 | P1 | `drop(by="face")` が line-only 入力で `NameError` |
| GFX-005 | P1 | 平面推定が先頭 3 点だけに依存し、正しい傾斜平面を拒否する |
| GFX-006 | P1 | grid/resample の安全上限が無い、または大規模確保の後にしか確認しない |
| GFX-007 | P2 | `subdivide` は頂点上限到達時に入力末尾を黙って削る |
| GFX-008 | P1 | 壊れた ParamStore を空扱いし、正常終了時に原本を上書きし得る |
| GFX-009 | P2 | interrupt/context/inflight の cleanup と例外契約が不完全 |
| GFX-010 | P2 | `@preset` の generic return type と `activate=False` の戻り値が矛盾する |
| GFX-011 | P1 | CLI `--run-id` と読み込む ParamStore が一致しない |
| GFX-012 | P1 | 奇数 framebuffer の H.264 recording が必ず失敗する |
| GFX-013 | P1 | 矩形 canvas で preview の線幅が方向依存し、SVG と一致しない |
| GFX-014 | P1 | mp-draw worker の異常終了を検知しない |
| GFX-015 | P1 | G-code の既定 travel optimization が Python の二乗時間 |
| GFX-016 | P2 | PNG 保存が event loop 内で同期実行される |
| GFX-017 | P2 | parameter/callsite/reconcile/view-model の不変処理を毎 frame 再実行する |
| GFX-018 | P2 | CPU index / GPU mesh cache が分断され、buffer growth も exact-size |
| GFX-019 | P2 | planar-grid、fill、affine、concat に batch 化・共通化余地が大きい |
| GFX-020 | P3 | eager import、重複 helper、未使用旧実装、長大 orchestration が残る |
| GFX-021 | P2 | benchmark が multi-input effect と memory/end-to-end cost を測れていない |

## 4. 正しさ・安全性

### GFX-001 [P0] Geometry 署名が衝突する

**箇所:** `src/grafix/core/geometry.py:19-63`, `87-118`, `121-163`

現行 serializer は string の長さを入れず、tuple 要素を comma で連結する。そのため、例えば次が同じ
`GeometryId` になる。

```python
("a", "b")
("a,sb",)
```

実 probe でも次を確認した。

```text
tuple_collision True
numeric_collision True   # 1 と 1.0
```

さらに `int` を一度 `float` に変換してから戻すため、`2**53 + 1` は
`9007199254740992` に変化する。つまり ID だけでなく、実装へ渡る値自体も壊れる。

`realize_cache` と GPU mesh cache はこの ID を真実としているため、衝突すると別の Geometry の
座標を黙って再利用する。これは確率的な hash collision ではなく、現在の encoding で決定的に再現する。

**提案:**

1. `bool`、`int`、`float`、`str`、tuple を型付きの canonical tree として保つ。
2. `int` は float を経由させない。
3. `_update_hash_with_value()` の手製 delimiter protocol を削除する。
4. 最小案として、対応型を限定した canonical tuple
   `(schema_version, op, input_ids, args)` の `repr()` を 1 回だけ hash する。
   基本 built-in の `repr` は区切りと escape を保持し、現在の閉じた型集合では十分明確である。
   より厳密にするなら tag + byte-length framing を使う。

同じ典型引数での probe では、現行の複数 `hasher.update()` が約 3.40 us/call、canonical tuple の
一括 hash が約 2.70 us/call だった。正しさを直しつつ短くできる。

**必須 test:** string delimiter、nested tuple、`1`/`1.0`、`2**53+1`、`-0.0`、Enum、dict key。
同じ ID なら「実装が観測する型付き引数が同一」であることを property test にする。

### GFX-002 [P1] registry overwrite が atomic でなく cache と同期しない

**箇所:**

- `src/grafix/core/primitive_registry.py:34-71,128-229`
- `src/grafix/core/effect_registry.py:37-77,138-267`
- `src/grafix/core/realize.py:98-130`

`overwrite=True` が既定だが、再登録しても `realize_cache` は無効化されない。実 probe では、同名 primitive を
`value` から `value + 10` へ再登録しても、同じ Geometry は旧結果 `1.0` を返した。

また registry は function / meta / defaults / order / visibility を別々の dict に保存し、`None` の field は
旧値を消さない。meta 付き op を meta 無しで上書きすると、旧 defaults が残ることも再現した。

**提案:** 既存 `PresetSpec` を手本に、primitive/effect を 1 op = 1 frozen
`OpSpec(func, meta, defaults, param_order, ui_visible, n_inputs, revision)` へ統合する。

- `overwrite=False` を既定にする。
- 明示的 replace だけ revision を進め、関連 cache を invalidate する。
- reserved op `concat` は登録時に拒否する。
- primitive/effect の共通 signature/default validation も 1 箇所へ寄せる。

これにより stale field と並行 dict の混成を同時に消せる。

### GFX-003 [P1] realize cache に寿命も容量上限もない

**箇所:** `src/grafix/core/realize.py:30-57,98-130`

`GeometryId -> RealizedGeometry` を process-global dict に永久保存する。README の
`rotation=(t * 6, ...)` のような animation は毎 frame 新しい ID となり、最終 effect の配列を保持し続ける。
test も private `_items.clear()` を直接呼んでおり、正式な lifecycle API がない。

**提案:**

- `coords.nbytes + offsets.nbytes` を重みとする byte-budget LRU
- `clear()` / `stats()` / hit-miss-eviction counters
- process-global ではなく `SceneRunner` または run session 所有
- GPU cache も同じ byte-budget policy に揃える

item 数だけの上限では、巨大 geometry 1 件と小 geometry 1 件を同じ重さに扱うため不十分である。

**検証:** 時刻だけ変える数千 frame で entry/RSS が頭打ちになり、静的な上流 node の hit 率が維持されること。

### GFX-004 [P1] `drop(by="face")` の未定義変数

**箇所:** `src/grafix/core/effects/drop.py:283-291`

face が 0 本なら `return base` を通るが `base` は未定義。次で再現した。

```python
realize(E.drop(by="face", interval=1)(G.line()))
# RealizeError <- NameError: name 'base' is not defined
```

**提案:** `return coords, offsets`。line-only + `by="face"` の regression test を追加する。

### GFX-005 [P1] planar frame が先頭 3 点だけで決まる

**箇所:** `src/grafix/core/effects/util.py:50-63`

**影響先:** `clip.py:174`, `growth.py:999`, `reaction_diffusion.py:493`, `isocontour.py:1170`,
`metaball.py:602`, `warp.py:420`, `weave.py:151`, `fill.py:945`

法線を `vertices[0:3]` の cross product だけで作り、その 3 点が共線なら identity を返す。
subdivide 済み輪郭のように最初の 3 点が同じ辺上にある正しい傾斜平面は、no-op/empty/歪んだ投影になる。

**提案:** 全点 PCA または Newell 法による robust `PlanarFrame` を `effects/util.py` に 1 つだけ置く。
法線、面内軸、原点、forward/inverse transform、planarity residual を同じ結果 object で返す。
`fill.py` の PCA と `text.py` の開始点 workaround も同じ実装へ統合する。

**検証:** 先頭 3 点共線、明示 close、重複点、法線 ±Z、非常に小さい/大きい座標、往復誤差。

### GFX-006 [P1] safety guard が確保前に効かない

**箇所:**

- `metaball.py:620-640`（`nx * ny` 上限なし。実確保は `137-208`）
- `lowpass.py:92-98,178-182,400-402`
- `highpass.py:93-99,179-183,412-414`

`metaball` は小さい `grid_pitch` と大きい bbox で無制限の float64 grid を確保する。
low/high-pass は 10,000,000 頂点 guard があるが、再サンプル配列を作った後で確認するため OOM 防止にならない。

**提案:** 共通 `GridSpec.from_bbox(..., max_cells=...)` と resample の preflight count を導入する。
上限超過時は一部だけ返さず、pitch/step を一様に拡大して品質を落とすか、入力全体を no-op とする。

`isocontour.py:1199` と `reaction_diffusion.py:520-521` に既存の 4,000,000 cell guard があるため、
その考え方を共通化すればよい。

### GFX-007 [P2] `subdivide` の上限処理が形状を途中で切る

**箇所:** `src/grafix/core/effects/subdivide.py:74-89`

残予算が次の line に足りないと `break` し、それまでの lines だけを返す。安全上限が入力末尾の消失を起こす。

**提案:** 全 line を先に count し、収まらなければ subdivisions を全 line で一様に下げる。
少なくとも「完全成功または完全 no-op」とし、部分結果は返さない。

### GFX-008 [P1] ParamStore の破損・部分書き込みで調整値を失う

**箇所:**

- `src/grafix/core/parameters/persistence.py:34-69`
- `src/grafix/api/runner.py:221-226`

read/decode error を無警告で空 store にし、終了時に同じ path へ `write_text()` する。壊れた原本を空 store で
上書きでき、save 中断でも正式 path が部分 file になり得る。

**提案:** sibling temp へ write + flush + `os.replace()`、decode error は warning と `.corrupt` 退避。
同じ atomic writer を SVG/G-code/MIDI にも使う。巨大 SVG/G-code は全行 list 化せず逐次書き込む。

### GFX-009 [P2] realize/context の failure path が状態を壊す

**箇所:**

- `src/grafix/core/realize.py:100-145`
- `src/grafix/core/parameters/context.py:83-92`

確認できた問題:

1. `BaseException` を捕捉して `KeyboardInterrupt` / `SystemExit` まで `RealizeError` に変える。
2. cache miss と inflight 登録が別 lock なので、その間に他 thread が完了すると再計算する TOCTOU がある。
3. `merge_frame_params()` が失敗すると ContextVar reset へ到達せず、frame/store context が漏れる。

**提案:** cache/inflight を 1 coordinator state machine にし、leader 決定時に cache を二重確認する。
通知・inflight cleanup・ContextVar reset は必ず `finally`。cancel 系 `BaseException` は waiter へ通知後、leader では
元の型のまま再送出する。

### GFX-010〜014 [P1/P2] public/runtime contract の小さい不整合

| ID | 箇所 | 問題 | 最小修正 |
|---|---|---|---|
| GFX-010 P2 | `api/preset.py:89-93,245-248` | 任意 `R` を返す型なのに `activate=False` は常に空 `Geometry` | preset を `SceneItem` 専用にするか、非Scene preset には activate を追加しない |
| GFX-011 P1 | `devtools/export_frame.py:120-135` | `--run-id` を output 名にだけ使い、`Export(..., run_id=...)` に渡さない | 単一/複数 frame の両方で run_id を渡す |
| GFX-012 P1 | `runtime/video_recorder.py:51-58,81-98` | libx264 + yuv420p に奇数 width/height を渡す | ffmpeg filter で偶数へ 1 px pad |
| GFX-013 P1 | `interactive/gl/shader.py:24-37`, `export/svg.py:90-104` | clip-space の一定 offset により矩形 canvas で方向別線幅になる | world/pixel-space で法線を作り、線幅 unit を preview/export で統一 |
| GFX-014 P1 | `runtime/mp_draw.py:181-197,230-265` | Queue だけを見て process `exitcode` を見ない | submit/poll で health check、全滅時は明示 error または sync fallback |

ffmpeg は 3x3 frame で `width not divisible by 2` を実際に再現した。worker は import failure、
`SystemExit`、native crash で結果を返さず死ねるため、現状は古い frame/空画面のまま無言で継続する。

## 5. 性能と簡素化

### GFX-015 [P1] G-code travel optimization が二乗時間

**箇所:** `src/grafix/export/gcode.py:465-503`

残り stroke を毎回 Python で全走査し、`list.pop(best_i)` も線形である。実測:

| strokes | time |
|---:|---:|
| 250 | 0.018 s |
| 500 | 0.071 s |
| 1,000 | 0.285 s |
| 2,000 | 1.195 s |

二乗則から 10,000 strokes は約 29 秒、50,000 は約 12 分。`optimize_travel=True` が既定で、interactive close は
2 秒後に export process を terminate するため、高密度 hatch ほど保存できない。

**提案:** endpoint を packed NumPy 配列にし、決定的 tie-break を保った spatial grid / nearest-neighbor index へ置換する。
まず vectorized scan で Python loop を消し、次に 1k/10k/50k benchmark を見て spatial index を入れる段階案が安全。

### GFX-016 [P2] PNG export は event loop 内で同期する

**箇所:** `interactive/runtime/draw_window_system.py:478-489`, `export/image.py:163-172`

P key は flag 化されているだけで、SVG 全生成と `subprocess.run(resvg)` は `draw_frame()` 内で同期する。
高解像度 export 中は draw、GUI、MIDI、window event が止まる。

**提案:** PNG/G-code を 1 つの長寿命 `ExportJobSystem` へ統合する。immutable frame snapshot を渡し、
同種の連打は latest-wins、timeout/cancel/status を共通化する。現在の format ごとに異なる process 管理も短くできる。

### GFX-017 [P2] parameter hot path が不変作業を繰り返す

**箇所:**

- callsite: `core/parameters/key.py:22-60`
- snapshot/IPC: `parameters/snapshot_ops.py:18-43`, `runtime/scene_runner.py:73-95`
- reconcile: `parameters/reconcile_ops.py:32-55`, `parameters/merge_ops.py:101-106`
- GUI model: `parameter_gui/gui.py:310-321,372-377`, `store_bridge.py:391-558`

具体例:

- 各 G/E/L call で同じ `Path.resolve()` を実行する。
- callsite は bytecode location だけなので、loop 内の複数 instance が同じ GUI group に潰れる。
- mp mode は full ParamSnapshot を毎 frame Queue へ送る。
- reconcile 後も `loaded_groups` が旧 group のままで、fingerprint/matching を毎 frame再実行する。
- GUI は font 解決、registry 照合、group/sort を値が変わらなくても再構築する。

実ファイル path の site ID probe は約 16.8 us/call、`(code, f_lasti)` cache 版は約 0.32 us/call だった。

**提案:**

1. G/E/L に P と同じ explicit `key=` を設ける。
2. callsite path は code object 単位に cacheし、project-relative key を永続化する。
3. ParamStore に monotonic revision を持たせ、snapshot と GUI `ParameterTableModel` を revision ごとに cacheする。
4. worker は revision が変わった時だけ snapshot を受け取る。
5. reconcile 済み group は fresh 集合から先に除外する。
6. `run(..., n_worker=4)` の既定は、軽い sketch の spawn/IPC cost を考え `1` または profile-based auto を再検討する。

### GFX-018 [P2] render cache と buffer growth が別々の無駄を作る

**箇所:**

- `interactive/gl/index_buffer.py:38-68`
- `interactive/gl/draw_renderer.py:29-35,78-100`
- `interactive/gl/line_mesh.py:54-76`
- `interactive/runtime/draw_window_system.py:455-467`

GPU mesh が geometry ID で hit しても、その前に offsets を `tobytes()` へコピーし、別の CPU LRU を引く。
cache は CPU 64 items、GPU 256 items で別管理、GPU は実 bytes を見ない。

cache-hit の `offsets -> bytes` は 1k/10k/100k polylines で約 1.6/13.8/144 us/call。
また `LineMesh._ensure_capacity()` は required size ぴったりに再確保するため、8 MB 超で少しずつ成長する geometry は
毎 frame VBO/IBO release、allocate、VAO rebuild を起こす。

**提案:** `geometry_id -> {indices, stats, mesh, byte_size}` の統合 byte-LRU。buffer は
`max(required, current * 1.5〜2)` の geometric growth とする。

### GFX-019 [P2] packed/batched kernel を既存実装から横展開する

以下は別々の局所最適化ではなく、同じ方向で直せる。

1. **Planar grid backend**
   - 遅い側: `reaction_diffusion.py:121-159`, `growth.py:317-324,398-493`,
     `metaball.py:137-208` は最大 `O(grid_points * edges)`。
   - 良い既存例: `isocontour.py:232-546` の scanline mask + boundary raster + 2-pass EDT。
   - packed rings / mask / EDT / marching squares を `effects/util.py` の小さな backend へ寄せる。

2. **fill output**
   - `fill.py:724-748,924-927,987-990` は hatch ごとに小配列を作り、1 本ずつ
     `transform_back()` を呼ぶ。
   - 全端点を 1 packed array に書き、inverse transform も 1 回。2点線の offsets は `arange` で作れる。

3. **identity fast path**
   - `rotate.py:47-83`, `scale.py:70-118` は identity でも O(N) float64 copy。
   - `affine.py:70-81` と同じ早期 return を入れれば registry wrapper が元 `RealizedGeometry` を再利用できる。

4. **concat**
   - `realized_geometry.py:131-201` は offsets を `.tolist()` して Python int 化する実装が二重にある。
   - 最終長を preflight した `np.empty(int32)` へ slice 書き込みする共通関数にする。

5. **asemic glyph**
   - `primitives/asemic.py:96-119,557-596` の graph 構築は pair ごとに長さ n の mask を作り O(n^3)。
   - topology generation を layout から分離し、bounded cache + compiled loop にする。

## 6. 可読性・構造

### GFX-020 [P3] 小さな共通語彙を作り、旧実装を削除する

静的集計では 100 lines 超の関数が 62、200 lines 超が 14。代表例:

- `displace._apply_noise_to_coords`: 316 lines
- `export_gcode`: 306 lines
- `drop`: 299 lines
- `partition`: 291 lines
- `runtime_config`: 284 lines
- `render_parameter_table`: 250 lines

また完全同一の `_empty_geometry` が effects 内だけで 26 箇所、low/high-pass の resampling 群は約 260 lines が
重複している。未使用旧実装も `collapse.py:101-201`, `mirror.py:401-465,713-727`,
`fill.py:150-158` などに残る。

**提案:** 無条件に関数を細切れにせず、次だけを共有語彙にする。

- `empty_geom()`
- `pack_polylines()` / `PackedPolylineBuilder`
- `PlanarFrame`
- `GridSpec`
- resample kernel
- `OpSpec`

effect 同士は import せず `effects/util.py` だけを使うため、`core/effects/AGENTS.md` の境界を維持できる。
未使用旧実装は compatibility wrapper を残さず削除する。

追加の構造改善:

- `DrawWindowSystem` から export job/process lifecycle を抜き、frame rendering に寄せる。
- `export_gcode` を clipping / path planning / ordering / dialect emission に分ける。
- root `import grafix` で 11 primitive + 32 effect を eager import せず、`op -> module` manifest から lazy loadする。
- `runtime_config` は nested dataclass ごとの小さい parser に分け、mapping は再帰 mergeする。
- `api/export.py` の「未実装スタブ」という docstring は実装済み現状へ直す。

### GFX-021 [P2] benchmark と CI gate を実際の failure mode に合わせる

**箇所:** `devtools/benchmarks/effect_benchmark.py:107-140,234-284`

現在の effect benchmark は常に `inputs=[case.geometry]` なので、`n_inputs=2` の `clip` と `warp` は必ず error となり、
性能を一度も測れない。また wall time 中心で、peak RSS、cache hit、cold JIT、end-to-end frame を gate しない。

**提案:**

- unary / binary / mask-grid / many-short-lines / huge-single-line の case family
- warm/cold、wall time、peak RSS、output vertices、cache hit の記録
- Geometry signature property tests
- long-running animated cache soak test
- odd video、worker death、run-id、atomic save failure injection
- ruff と mypy を CI gate に追加

現状 test は 522 件成功する一方、ruff/mypy は未定義 `base` を即座に検出した。test と static check は両方必要。

## 7. 推奨実施順

| Phase | 内容 | 完了条件 |
|---|---|---|
| A: correctness | GFX-001, 002, 004, 005, 008, 011〜014 | 再現 test が追加され、ruff/mypy/test が全成功 |
| B: bounds/lifecycle | GFX-003, 006, 007, 009, 014 | cache/RSS が上限で安定し、全 failure path で cleanup |
| C: measured hot paths | GFX-015〜018 | 10k strokes、1k GUI rows、多数 hatch の benchmark で改善 |
| D: shared kernels | GFX-019 | PlanarFrame/GridSpec/packing の実装が 1 つになり重複削除 |
| E: structural cleanup | GFX-020, 021 | dead code/compat shim なし、lazy import、CI performance report |

最初の実装単位としては、次の順が小さく安全である。

1. Geometry serializer と regression/property tests
2. `drop`, CLI run-id, ffmpeg pad, preset contract
3. atomic ParamStore save と corrupt backup
4. `OpSpec` registry + cache invalidation
5. bounded realize cache
6. robust PlanarFrame + preflight GridSpec

## 8. 維持すべき良い点

- `Geometry` の frozen/slots DAG と concat flattening
- `RealizedGeometry` に shape/dtype/offset invariant を集約したこと
- `RealizedLayer` を interactive/SVG/PNG/G-code で共有する依存方向
- parameter snapshot と worker の `FrameParamsBuffer` 分離
- effect 間の直接 import を禁止し `.util` のみに寄せた境界
- `isocontour` の scanline + EDT + two-pass contour
- `dash`, `collapse`, `repeat` の count → preallocate → fill パターン
- GL mesh の scratch reuse と 2 回目 cache promotion
- G-code の clipping、bed validation、deterministic tie-break
- architecture dependency test と、effects/GUI/parameter の広い unit test 群

## 9. 避けるべき改善

- 互換 shim を足して旧 registry/cache API を二重に維持すること
- 単に file を分割し、data flow は同じままにすること
- 全 effect を 1 つの巨大共通 framework に載せること
- correctness test なしに approximate geometry kernel へ置換すること
- item-count cache、無制限 global cache、format ごとの独自 worker を増やすこと

「typed canonical data」「preflight count」「packed batch」「bounded ownership」の 4 原則に揃えると、
コード量を減らしながら正しさ・速度・読みやすさを同時に上げられる。
