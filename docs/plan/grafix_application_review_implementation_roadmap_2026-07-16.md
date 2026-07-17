# Grafix アプリケーションレビュー改善ロードマップ（2026-07-16）

- 作成日: 2026-07-16
- ステータス: **完了**
- 根拠: `docs/review/grafix_application_review_2026-07-16.md`

## 1. 目的

ユーザー判断で採用された APP-002 / 004 / 006〜013 を、既存の良い設計を壊さず段階的に実装する。

- 成果物の消失を先に防ぐ。
- 制作中の状態を正しく、actionable に見せる。
- UI event loop を重い `draw` から隔離し、コード変更の反復を短くする。
- GUI/API/CLI の render/export 契約を一本化する。
- parameter 検索、operation discovery、named variation により探索力を高める。
- 過度な framework、互換 shim、新規依存を増やさない。
- 各実装単位の完了時に本ファイルへ `[x]` とテスト結果を追記する。

## 2. 採否と実装境界

### 2.1 採用

- [x] APP-002: PNG export が同名 SVG を中間物として上書きする問題
- [x] APP-004: 同期 `draw` 既定と source hot reload 不在
- [x] APP-006: parameter source / ownership / identity の境界
- [x] APP-007: parameter 検索と semantic metadata
- [x] APP-008: error / save / recovery / config 診断
- [x] APP-009: GUI / API / CLI の render/export 契約と再現情報
- [x] APP-010: silent quality degradation と resource limit の適用漏れ
- [x] APP-011: operation catalog、authoring API、基本造形語彙、拡張契約
- [x] APP-012: named variation と探索機能
- [x] APP-013: workspace、Inspector、accessibility、timeline 制作支援

### 2.2 却下・変更禁止

- [x] APP-001 は却下。G-code の profile、header/footer、単位、origin、bridge、bounds は変更しない。
- [x] APP-003 は却下。canvas default、primitive default、`FrameContext`、`Fit to content` は変更しない。
- [x] APP-005 は却下。preview の pan/zoom、canvas toolbar、capture command surface、focus 共有は変更しない。

APP-009 の共通 capture 化では G-code encoder を呼び出す入口だけ共通化し、G-code 内容は一切変えない。
APP-013 の shortcut/accessibility は Parameter GUI と workspace を対象とし、却下された preview command
surface は追加しない。

## 3. 実装時に固定する設計判断

1. **追加依存なし。** file watch は `stat` polling、候補提示は `difflib`、非同期評価は既存
   `multiprocessing` を使う。
2. **互換 wrapper / shim は作らない。** 公開 API を整理するときは internal consumer、stub、test を
   同じ実装単位で移行する。
3. **診断経路は一つにする。** scene/export/save/config/operation ごとに別 alert bus を作らず、bounded
   `DiagnosticCenter` へ集約する。
4. **実効値の source と load 由来を分ける。**
   - `ValueSource`: `code | ui | midi_live | midi_frozen`
   - `LoadProvenance`: `primary | session_recovery | quarantined`
5. **headless は暗黙状態を読まない。** parameter load mode は `code | saved | recovery | Path` を明示し、
   headless 既定は `code`、interactive 既定は現行どおり recovery 対応とする。
6. **`n_worker` の意味を単純化する。** `0` は明示 sync、`>=1` は background worker 数とし、既定 `1`
   は UI event loop を塞がない。
7. **render と export の寿命を分ける。** `RenderSession` は draw/store/config/cache、`CaptureService` は
   encode/no-clobber/manifest、`ExportJobSystem` は async queue/worker を所有する。
8. **format は path suffix を唯一の真実にする。** 明示 format を受ける箇所では不一致を書込前に拒否する。
9. **既存 `ResourceBudget` を先に徹底する。** 最初から巨大な limit framework を作らず、全 evaluator
   output の postflight と scene aggregate を追加してから必要な cache/queue limit を統合する。
10. **variation は ParamStore 所有にする。** store revision、autosave、schema migration、Undo と同じ寿命で
    管理し、別の永続化系を増やさない。
11. **workspace は別 JSON。** sketch/run 単位で window rect、Inspector visibility、UI scale を atomic 保存する。
12. **既定動作を変える箇所は明示する。** bool ownership、source 名、`n_worker=1`、config 相対 path、
    `L.layer()`、`Export` 廃止は破壊的変更として documentation と test を同時更新する。

## 4. 進行規則

- [x] 開始時に `git status --porcelain` を確認し、working tree が clean であることを確認した。
- [x] 採用 finding と現行コード・既存 test の対応を調査した。
- [x] APP-001 / 003 / 005 を実装対象から除外した。
- [x] 本ロードマップを新規作成した。
- [x] 本ロードマップについてユーザー確認を受ける。
- [x] 各挙動変更は先に regression test を追加し、失敗を固定する。
- [x] 各実装単位で対象 pytest と対象 ruff を実行する。
- [x] 公開型/API変更時は stub と API export test を同時に更新する。
- [x] 各 Phase 完了時に full pytest を実行し、本ファイルへ結果を追記する。
- [x] 最終 Phase で `ruff check src/grafix tests`、`mypy src/grafix`、full pytest を実行する。
- [x] 失敗・未完了・意図的な残余はチェックせず、「実施記録」に理由を残す。

## 5. Findings と Phase の対応

| Finding | 実装 Phase |
|---|---|
| APP-002 | Phase 1 |
| APP-008 | Phase 2 |
| APP-006 | Phase 3 |
| APP-007 | Phase 4 |
| APP-004 | Phase 5 |
| APP-009 | Phase 6 |
| APP-010 | Phase 7 |
| APP-011 | Phase 8 |
| APP-012 | Phase 9 |
| APP-013 | Phase 10 |

依存関係は `APP-008 → APP-006/004/009/010`、`APP-009 → APP-012 thumbnail/contact sheet`、
`APP-007 → APP-011 GUI catalog` とする。独立した小項目は同じ Phase 内で並行実装してよい。

## 6. Phase 0 — baseline と既存土台の固定

### 現行で完了済みの土台

- [x] APP-004: `MpDraw` に bounded/latest-wins queue、stale epoch 破棄、worker crash 検知がある。
- [x] APP-004: draw error 時に last-good frame を維持する。
- [x] APP-006: 非 bool parameter に CODE/UI selector と Reset to CODE がある。
- [x] APP-006: explicit `key=` と、一意 fingerprint による site 移動の自動 reconcile がある。
- [x] APP-007: operation grouping、折り畳み、Show inactive がある。
- [x] APP-007: `kind/ui_min/ui_max/choices` metadata がある。
- [x] APP-008: atomic autosave、session recovery、完全破損 file の quarantine がある。
- [x] APP-008: frame error の一行 alert と capture queue telemetry がある。
- [x] APP-009: interactive capture に bounded queue、private PNG intermediate、no-clobber publish がある。
- [x] APP-010: per-operation `ResourceBudget` と bounded realize cache がある。
- [x] APP-011: immutable `OpSpec` registry と G/E/P/L stub generator がある。
- [x] APP-012: bounded Undo/Redo と process 内 A/B slot がある。
- [x] APP-013: responsive initial layout、DPI/font fallback、basic transport がある。

これらは基盤としての完了であり、finding 全体の完了を意味しない。

### baseline

- [x] full pytest の開始時件数・時間・失敗を記録する。
- [x] `ruff check src/grafix tests` の開始時結果を記録する。
- [x] `mypy src/grafix` の開始時結果を記録する。
- [x] export、parameter、mp-draw、GUI toolbar の focused baseline を記録する。

Phase 0 完了条件:

- [x] 現行 failure と今回変更による regression を区別できる baseline がある。

## 7. Phase 1 — PNG sibling SVG 上書きの解消（APP-002）

対象:

- `src/grafix/export/image.py`
- `tests/export/test_image.py`
- `tests/api/test_export_style_background.py`

アクション:

- [x] PNG 分岐の SVG を `TemporaryDirectory/intermediate.svg` へ出す。
- [x] 明示 `.svg` export の挙動は変更しない。
- [x] 成功、SVG生成失敗、rasterize失敗の全経路で private intermediate を削除する。
- [x] 既存 sibling `art.svg` が byte-for-byte 不変である regression test を追加する。
- [x] rasterizer へ渡る SVG が public sibling でないことを test する。
- [x] 例外時にも temp が残らないことを test する。

Phase 1 完了条件:

- [x] `art.png` の生成で既存 `art.svg` が変更されない。
- [x] export/image と API export の focused test が成功する。

## 8. Phase 2 — 共通診断、保存状態、schema、config（APP-008）

### 2.1 bounded `DiagnosticCenter`

対象候補:

- 新規 `src/grafix/interactive/runtime/diagnostics.py`
- `src/grafix/interactive/runtime/monitor.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- 新規 `src/grafix/interactive/parameter_gui/diagnostics_panel.py`
- `src/grafix/interactive/parameter_gui/gui.py`

- [x] immutable `DiagnosticEvent(category, severity, summary, details, source, actions, count)` を定義する。
- [x] bounded 件数、同一 error dedupe、発生回数、dismiss を実装する。
- [x] frame/export/save/recovery/config/operation を同じ center へ publish する。
- [x] full traceback、file:line、Copy、Dismiss を持つ drawer を追加する。
- [x] Retry/Open action の dispatch を追加する。
- [x] 既存一行 monitor は重要 summary を残し、詳細を drawer へ移す。
- [x] dedupe、上限、action、同一 error 回数を unit test する。

### 2.2 autosave / recovery status

- [x] autosave に `clean | dirty | saving | failed` と `last_error` を持たせる。
- [x] GUI に Saved/Saving/Save failed を表示する。
- [x] GUI に Recovered session を表示する。
- [x] save failure 後の retry 成功を test する。
- [x] recovery の Keep/Discard/Compare を診断 action として扱う。

### 2.3 ParamStore schema

- [x] JSON top-level に `schema_version` を追加する。
- [x] version 無しを legacy migration として明示処理する。
- [x] future version は拒否し、黙って空 store にしない。
- [x] malformed entry を捨てる前に原本を backup/quarantine し、診断を返す。
- [x] `LoadProvenance(primary | session_recovery | quarantined)` を runtime state に保持する。
- [x] legacy migration、partial破損、future version、recovery provenance を test する。

### 2.4 strict runtime config

- [x] merge 前に既知 key tree を検証し、unknown key と近似候補を返す。
- [x] float の finite、正値、range 順、enum/MIDI mode を検証する。
- [x] config 内の相対 path を config file の親基準で絶対化する。
- [x] `python -m grafix config validate/show` を追加する。
- [x] `config show` に source、effective value、resolved path を表示する。
- [x] typo、NaN/Inf、逆range、CWD非依存path、CLI exit code を test する。

Phase 2 完了条件:

- [x] scene/export/save/recovery/config の失敗が console だけで終わらない。
- [x] ParamStore の部分修復と config fallback が無通知で起きない。
- [x] focused persistence/config/diagnostics test と full pytest が成功する。

## 9. Phase 3 — parameter source、bool ownership、identity（APP-006）

### 3.1 source と provenance

- [x] CC value と `midi_live | midi_frozen` を同じ immutable frame snapshot にする。
- [x] context、worker message、resolver、frame record、table badge まで型を一貫させる。
- [x] `ValueSource` と `LoadProvenance` を混同しない。
- [x] live/frozen badge、tooltip、worker roundtrip を test する。

### 3.2 bool ownership

- [x] bool も `override` に従って CODE/UI を選ぶ。
- [x] bool row に CODE/UI selector と Reset to CODE を出す。
- [x] checkbox 編集時だけ `override=True` にする。
- [x] clean launch では明示 code 値、現 session/recovery では UI 操作を保持する。
- [x] normal save と recovery の roundtrip test を追加する。

### 3.3 MIDI session

- [x] controller、frozen snapshot、接続状態を小さい `MidiSession` にまとめる。
- [x] 起動時 fallback は `MIDI FROZEN` と常設表示する。
- [x] mid-session poll error で frozen へ遷移し、診断を出す。
- [x] Reconnect、Clear frozen snapshot を提供する。
- [x] no-port、disconnect、reconnect成功/失敗を test する。

### 3.4 identity と反復構造

- [x] ambiguous reconcile candidate を orphan として runtime state に保持する。
- [x] orphan 一覧と手動 1:1 migrate を GUI に追加する。
- [x] snippet に重要/loop parameter の explicit `key=` を出す。
- [x] `instance_key` と `shared` で instance identity と共有 group を分ける。
- [x] loop/comprehension、tie、manual migration、Undo、persistence を test する。

Phase 3 完了条件:

- [x] MIDI未接続値を `LIVE` と表示しない。
- [x] clean launch の明示 bool code 値が保存済み UI 値に隠されない。
- [x] identity を自動移行できない場合に値を黙って孤立させない。
- [x] focused resolver/MIDI/reconcile/GUI test と full pytest が成功する。

## 10. Phase 4 — parameter 検索と意味情報（APP-007）

### 4.1 検索・filter

- [x] Unicode casefold、AND token の pure search function を追加する。
- [x] label/op/arg/source/MIDI CC を検索対象にする。
- [x] active/inactive、UI override、MIDI mapped、error、favorite filter を追加する。
- [x] filtered/total 件数を表示する。
- [x] query/filter と既存 inactive visibility の合成を test する。

### 4.2 semantic `ParamMeta`

- [x] optional `display_name`, `description`, `unit`, `step`, `format`, `scale`, `category`,
  `advanced`, `recommended_range` を追加する。
- [x] meta spec validation、codec roundtrip、row model、stub を更新する。
- [x] scale/step/range の不正値を明示拒否する。
- [x] metadata が無い user op の fallback を維持する。

### 4.3 navigation と Help

- [x] favorite/pin を ParamStore UI state として永続化する。
- [x] Expand all / Collapse all と hidden 件数を追加する。
- [x] selected/hover/focused row の Help pane に説明・単位・推奨範囲を出す。
- [x] favorite roundtrip、Help fallback、collapse操作を test する。

### 4.4 MIDI range edit

- [x] R/E/T の直接 commit を明示 Range Edit mode に置換する。
- [x] 対象 parameter、変更予定 range、linked edit を表示する。
- [x] Apply を一つの history transaction、Esc を非破壊 cancel にする。
- [x] preview/apply/cancel/複数対象を test する。

Phase 4 完了条件:

- [x] 大規模 scene で name/op/source/MIDI から目的行を絞り込める。
- [x] parameter の意味・単位・推奨範囲をコード外から確認できる。
- [x] focused GUI/model test と full pytest が成功する。

## 11. Phase 5 — responsive evaluator と transactional hot reload（APP-004）

### 5.1 background evaluation を既定化

- [x] `MpDraw` を 1 worker で動作可能にする。
- [x] `SceneRunner` は `n_worker>=1` で async、`0` のみ sync にする。
- [x] `run()` 既定 `n_worker=1` を background 1 worker として documentation/stub を更新する。
- [x] 1-worker latest-wins、queue drop、n_worker=0 sync、UI非blockを test する。

### 5.2 timeout / cancel / restart

- [x] worker generation 単位の `restart(reason)` を追加する。
- [x] evaluation deadline 超過時に hung worker を terminate/restart する。
- [x] restart 中も last-good frame と Inspector 応答を維持する。
- [x] child process leak、stale result不採用、restart後成功を test する。

### 5.3 preview quality

- [x] `PreviewQuality(draft | final)` context を追加する。
- [x] まず reaction-diffusion 等の重い grid/step effect だけ draft upper bound を使う。
- [x] capture/recording は final 固定にする。
- [x] draft で変わった実効値を APP-008 の診断へ出す。

### 5.4 source watch / reload

- [x] `python -m grafix run sketch.py --watch` を追加する。
- [x] watchdog を追加せず mtime polling を使う。
- [x] staging registry/preset registry へ module を load し、draw signature を検証する。
- [x] 成功時だけ registry/callable/worker generation を atomic swap する。
- [x] reload失敗時は last-good code/frame、ParamStore、worker を保持する。
- [x] syntax error、runtime error、成功swap、registry rollback、worker leak を test する。

Phase 5 完了条件:

- [x] 重い/hung draw でも Inspector と cancel/quit が応答する。
- [x] source 修正後に process restart 無しで last-good から回復する。
- [x] focused mp/reload test と full pytest が成功する。

## 12. Phase 6 — render/export 契約の一本化（APP-009）

### 6.1 共通型

- [x] immutable `RenderOptions`, `Frame`, `ExportResult`, `ExportFormat` を定義する。
- [x] line thickness を現実装どおり canvas短辺比として一つの名前/docstringへ統一する。
- [x] `run=0.001` と旧 `Export=0.01` の既定差を解消する。
- [x] `Color` 入口で hex/named/RGB8/RGB01 を内部 RGB01 へ正規化する。
- [x] suffix/format不一致、color、thickness validation を test する。

### 6.2 `RenderSession`

- [x] draw、ParamStore、config、StyleResolver、RealizeSession の寿命を一つにする。
- [x] `render(t) -> Frame` と `close()` / context manager を実装する。
- [x] parameter load mode `code | saved | recovery | Path` を明示する。
- [x] `config_path` と effective config を session metadata に保持する。
- [x] multi-frame で cache/store/config を再利用する test を追加する。

### 6.3 `CaptureService`

- [x] `export(frame, path, *, overwrite=False) -> ExportResult` を実装する。
- [x] suffix inference、private staging、no-clobber publish、rollback、manifest を一元化する。
- [x] existing `VersionedPathAllocator` と generation transaction を再利用する。
- [x] `ExportJobSystem` は queue/workerだけを所有し、format dispatch/publish を service へ委譲する。
- [x] late collision、encoder failure、cleanup、result path を test する。
- [x] G-code encoder の内容と既定値が不変である byte parity test を維持する。

### 6.4 公開 API / CLI

- [x] side-effect constructor `Export` を廃止する。
- [x] root から `RenderSession`, `RenderOptions`, `Frame`, `render`, `export`, `ExportResult` を公開する。
- [x] CLI export を SVG/PNG/G-code、parameter mode、config、overwrite に対応させる。
- [x] CLI は要求 path ではなく `ExportResult` の実保存 path/manifest を表示する。
- [x] stub と root export test を更新する。

### 6.5 manifest v2 と recording

- [x] manifest に Grafix/code/git/config/parameter/seed/output/frame provenance を追加する。
- [x] provenance は `RenderSession/Frame` で一度 snapshot し、workerで再探索しない。
- [x] recording scene error policy を pause または abort として固定する。
- [x] last-good frame を黙って動画へ書き、clockを進める挙動を廃止する。
- [x] frame/dropped/duplicated/error count と中止理由を manifest に記録する。

Phase 6 完了条件:

- [x] GUI/API/CLI が同じ render/capture/no-clobber/manifest 契約を使う。
- [x] headless output が暗黙 ParamStore に左右されない。
- [x] recording error を成功動画として隠さない。
- [x] focused export/CLI/recording test と full pytest が成功する。

## 13. Phase 7 — resource guard と actionable quality 診断（APP-010）

### 7.1 evaluator postflight

- [x] 全 evaluator output を cache 投入前に既存 `ensure_geometry_output()` で検査する。
- [x] custom primitive/effect の巨大 output も `ResourceLimitError` cause として拒否する。
- [x] 失敗 output を cache へ入れない。
- [x] 上限内 output と既存 built-in の結果が不変である test を追加する。

### 7.2 scene aggregate / runtime limits

- [x] scene 全 layer の頂点/line/byte aggregate を検査する。
- [x] per-op、scene、CPU cache、GPU cache、capture queue を `RuntimeLimits` から設定可能にする。
- [x] preview と final capture の limit profile を分ける。
- [x] limit 到達を APP-008 の診断へ出す。

### 7.3 silent degradation

- [x] small immutable operation diagnostic payload を定義する。
- [x] まず `subdivide` と `GridSpec.from_bbox` の clamp/reject/coarsen を通知する。
- [x] 続いて extrude/fill/weave/relax/sphere/trim/growth の silent fallback を整理する。
- [x] 元値、実効値、op、理由を表示する。
- [x] 通常時0件、degrade時1件を effect test で検証する。

### 7.4 profiler

- [x] operation/layerごとの時間、cache hit/eviction、worker lag を収集する。
- [x] slowest operations/layers を Inspector に表示する。
- [x] GUI無しでも structured JSON trace を出せるようにする。

Phase 7 完了条件:

- [x] custom op と scene aggregate が downstream/cache投入前に上限検査される。
- [x] clamp/reject/no-op の理由が作品結果と区別できる。
- [x] focused resource/effect/profiler test と full pytest が成功する。

## 14. Phase 8 — operation discovery と authoring API（APP-011）

### 8.1 catalog / describe

- [x] `OpSpec` に description/source/provenance と accepted/required args を持たせる。
- [x] registry を唯一の catalog 定義元にする。
- [x] `G.catalog()/G.describe()`、`E.catalog()/E.describe()` を追加する。
- [x] `python -m grafix describe {primitive|effect} NAME` を追加する。
- [x] name/kind/n_inputs/default/meta/doc/source を test する。

### 8.2 eager validation と意味名

- [x] G/E 呼び出し時に unknown kwargs と choice を検証する。
- [x] typo に近似候補を出す。
- [x] `type_index` 等を意味のある choice 名へ変更する。
- [x] generated stub の choice を `Literal[...]` にする。

### 8.3 基本 primitive / polyline model

- [x] `circle`, `ellipse`, `rect`, `arc` を追加する。
- [x] `bezier`, `polyline` を追加する。
- [x] points は無理にGUI化せず code-owned引数とする。
- [x] 複数線は `G.polyline(...)` の加算で低水準offset操作を避けられるため、追加modelは作らない。
- [x] builtins manifest、個別test、stub を更新する。

### 8.4 API cleanup / extension contract

- [x] `L.layer() -> Layer` に変更し、scene consumer/test/stubを同時移行する。
- [x] custom op は pure/deterministic、乱数は explicit seed を既定契約にする。
- [x] `cache_policy="content" | "none"` を追加し、`none` は cache/inflight を迂回する。
- [x] user op の callable/source/provenance を registry に保持する。

### 8.5 CLI onboarding / project-local typing

- [x] `grafix init`, `grafix doctor`, `grafix examples` を追加する。
- [x] doctor は GL、resvg、ffmpeg、MIDI、font、output write を検査する。
- [x] stub は project-local output を既定にし、installed package を直接上書きしない。
- [x] user op/preset を含む project-local G/E/P typing を生成する。

Phase 8 完了条件:

- [x] operation を名前、説明、引数、sourceから発見できる。
- [x] common 2D shape と独自 polyline を低水準 offsets 操作なしで作れる。
- [x] custom op の cache/seed 契約が明示される。
- [x] focused API/catalog/CLI/stub/primitive test と full pytest が成功する。

## 15. Phase 9 — named variation と探索機能（APP-012）

### 9.1 variation core / persistence

- [x] `Variation(name, created_at, note, seed, t, parameter_snapshot, thumbnail_path)` を定義する。
- [x] ParamStore に名前付き collection を持たせ、変更時に revision を進める。
- [x] create/rename/delete/list/diff/restore を pure operation として実装する。
- [x] codec schema と autosave/recovery に variations を含める。
- [x] restore は一つの undoable history transaction にする。
- [x] 新規 parameter を失わない merge restore を test する。

### 9.2 GUI

- [x] A/B toolbar を named variation popup/listへ置換する。
- [x] name、note、timestamp、seed、差分件数、empty state を表示する。
- [x] save/load/rename/delete/duplicate を実装する。
- [x] Phase 6 capture を使って thumbnail を生成・表示する。

### 9.3 randomize / lock / morph

- [x] favorite/現在filter対象を randomize scope にする。
- [x] lock を ParamStore UI state として永続化する。
- [x] numeric parameter を recommended/UI range 内で seed付き randomize する。
- [x] float/int/vec3/rgb の共通 parameterだけ A↔B morph する。
- [x] bool/choice/string/MIDI の morph policy を明示する。
- [x] deterministic randomize、lock、morph端点/中間を test する。

### 9.4 contact sheet / batch

- [x] named variations の batch render を Phase 6 `RenderSession/CaptureService` で行う。
- [x] thumbnail/contact sheet に variation名とseedを付ける。
- [x] partial failure summary と no-clobber を維持する。

Phase 9 完了条件:

- [x] 良い状態を名前付きで保存し、再起動後も比較・復元できる。
- [x] randomize/lock/morph で結果を失わず探索できる。
- [x] focused variation/codec/history/GUI/batch test と full pytest が成功する。

## 16. Phase 10 — workspace、Inspector、accessibility、timeline（APP-013）

### 10.1 close policy / Inspector visibility

- [x] window task に明示 close policy を持たせる。
- [x] preview close は app exit、Inspector close は hide にする。
- [x] hidden Inspector を再表示する `Cmd/Ctrl+I` を追加する。
- [x] hidden window は draw loop で skip する。
- [x] preview exit / Inspector hide / redisplay / hidden skip を test する。

### 10.2 workspace persistence

- [x] sketch/run単位の `WorkspaceState` JSON を追加する。
- [x] preview/Inspector rect、Inspector visibility、UI scale を atomic 保存する。
- [x] 起動時に保存rectを現在screen boundsへ clampする。
- [x] corrupt/old/missing state は既存 initial layout へ fallback し、診断を出す。
- [x] roundtrip、screen変更、corrupt fallback を test する。

### 10.3 accessibility

- [x] UI scale を既存 font size と spacing/target size に一貫適用する。
- [x] ImGui keyboard navigation を有効化し、Tab/Enter/Escを検証する。
- [x] tooltip/help を hover だけでなく focus でも表示する。
- [x] Parameter GUI shortcut の一覧と設定を workspace/config から読めるようにする。
- [x] 却下された preview command surface は変更しない。

### 10.4 timeline 制作支援

- [x] loop in/out と bookmark を `FrameClock` に追加する。
- [x] loop wrap で transport epoch を進め、古い async result を破棄する。
- [x] variation の optional `t` と bookmark を関連付ける。
- [x] play/pause/seek/recordingとの組合せを test する。

Phase 10 完了条件:

- [x] Inspector を閉じても作品とrecording/exportが終了しない。
- [x] workspaceが再起動・画面構成変更後も安全に復元される。
- [x] keyboard/large UIでParameter GUIの主要操作へ到達できる。
- [x] timeline区間を反復しながらvariationを比較できる。
- [x] focused workspace/window/accessibility/clock test と full pytest が成功する。

## 17. Phase 11 — 最終統合・検証・documentation

- [x] 生成 stub を更新し、runtime signature と一致させる。
- [x] README quick start、parameter、reload、export、variation、workspace、CLI を更新する。
- [x] architecture.md に DiagnosticCenter、RenderSession、CaptureService の責務境界を追記する。
- [x] APP-002/004/006〜013 の regression scenario を end-to-end で確認する。
- [x] `ruff check src/grafix tests` を成功させる。
- [x] `mypy src/grafix` を成功させる。
- [x] full pytest を成功させる。
- [x] GUI smoke test を実行し、画面・操作・保存結果を確認する。
- [x] 本ロードマップの全完了項目へ `[x]` を入れる。
- [x] 未完了・意図的な残余があれば理由と次アクションを記録する。

## 18. 破壊的変更一覧

実装時に release note と migration 記述を同時に追加する。

- `n_worker=1`: sync から background 1 worker へ変更。sync は `0`。
- parameter source: `base/gui/cc` から `code/ui/midi_live/midi_frozen` へ変更。
- bool: 保存済みUI値常時優先から、他kindと同じ明示overrideへ変更。
- config相対path: process CWD 基準から config file 基準へ変更。
- `Export`: side-effect constructor を廃止し `render/export` 関数へ変更。
- `L.layer()`: `list[Layer]` から `Layer` へ変更。
- stub: installed package 直接更新から project-local output へ変更。
- ParamStore/capture/workspace: versioned schema を導入。

互換 shim は作らず、repository 内の全 consumer と test を同時に更新する。

## 19. 実施記録

### 2026-07-16 — ロードマップ作成

- [x] working tree clean を確認した。
- [x] APP-001 / 003 / 005 の却下を反映した。
- [x] 採用10 findingを依存順の11 Phaseへ分解した。
- [x] 現行で完了済みの土台と未実装項目を分離した。
- [x] ユーザー確認済み。
- source code の変更を開始した。

Phase 0 baseline と Phase 1 APP-002 から開始し、各 Phase 完了時にこの節へ変更概要、
対象test、full test結果、残余を追記する。

### 2026-07-16 — Phase 0 baseline

- [x] clean HEAD `dbe01024df5d` を `/tmp` へ展開して baseline を分離計測した。
- [x] pytest: `954 passed, 1 failed in 39.95s`。
  - 既存失敗: `tests/stubs/test_api_stub_sync.py::test_api_stub_sync`
  - 原因: committed `src/grafix/api/__init__.pyi` と現 generator 出力の不一致。
- [x] ruff: `All checks passed!`
- [x] mypy: `Success: no issues found in 169 source files`

### 2026-07-16 — Phase 1 APP-002 完了

- [x] PNG の中間 SVG を `TemporaryDirectory` へ移した。
- [x] sibling SVG 不変、private path、例外 cleanup、明示 SVG 不変の regression test を追加した。
- [x] focused pytest: `10 passed in 0.11s`
- [x] 対象 ruff: `All checks passed!`
- [x] `git diff --check`: 問題なし。

### 2026-07-16 — Phase 7.1 evaluator postflight 完了

- [x] primitive/effect/concat の全 evaluator output を cache 前に検査するようにした。
- [x] custom op の超過拒否、未cache、上限丁度、built-in不変の test を追加した。
- [x] focused pytest: `32 passed in 0.40s`
- [x] 対象 ruff: `All checks passed!`
- [x] `git diff --check`: 問題なし。

### 2026-07-16 — Phase 10.1 Inspector close policy 完了

- [x] preview close と Inspector hide を task 固有 policy に分離した。
- [x] `Cmd/Ctrl+I` の再表示と hidden-window draw skip を追加した。
- [x] focused pytest: `21 passed`
- [x] interactive runtime pytest: `161 passed in 12.48s`
- [x] 対象 ruff / `git diff --check`: 問題なし。

### 2026-07-16 — Phase 2.1 診断基盤（進行中）

- [x] bounded/deduplicated `DiagnosticCenter` と immutable event/action を追加した。
- [x] RuntimeMonitor に scene/export diagnostics snapshot を統合した。
- [x] frame error の full traceback/source と Copy/Dismiss panel を追加した。
- [x] focused pytest: `46 passed`、panel/model追加test: `29 passed`
- [x] 対象 ruff: `All checks passed!`
- [x] autosave/recovery/config/operation の publish と action wiring は Phase 2 後続で完了した。

### 2026-07-16 — Phase 9.1 named variation core 完了

- [x] Variation model、CRUD、diff、merge restore、revision を実装した。
- [x] primary/recovery codec roundtrip と undoable restore を追加した。
- [x] parameters pytest: `142 passed`、focused再検証: `46 passed in 0.21s`
- [x] 対象 ruff / mypy / `git diff --check`: 問題なし。

### 2026-07-16 — Phase 8.1 operation catalog 完了

- [x] immutable `OpSpec` metadata と registry 起点の catalog/describe API を追加した。
- [x] `G/E.catalog()`、`G/E.describe()` と `python -m grafix describe` を追加した。
- [x] catalog/registry/CLI の focused pytest: `24 passed in 1.42s`
- [x] 対象 ruff: `All checks passed!`

### 2026-07-16 — Phase 5.1 background evaluation 完了

- [x] `MpDraw` を1 worker対応にし、`SceneRunner` を `0=sync / >=1=async` に変更した。
- [x] single-slot latest-wins、recording時sync、負値拒否を回帰testで固定した。
- [x] 担当範囲 pytest: `74 passed`、統合再検証: `40 passed in 4.38s`
- [x] 対象 ruff / `git diff --check`: 問題なし（既存由来のresource-tracker warningのみ）。

### 2026-07-16 — Phase 8.2 eager validation（進行中）

- [x] G/E の DAG 作成前に unknown keyword と choice 値を検証するようにした。
- [x] typo の近似候補と generated stub の `Literal[...]` を追加した。
- [x] focused pytest: `23 passed in 0.38s`、対象 ruff: `All checks passed!`
- [x] 静的なindex型parameterをsemantic choiceへ移行した（動的font一覧の`font_index`は意図的にindexを維持）。

### 2026-07-16 — Phase 8.3 basic shape vocabulary 完了

- [x] `circle/ellipse/rect/arc/bezier/polyline` をresource preflight付きで追加した。
- [x] Bezier制御点とpolyline pointsをcode-ownedのままstub/catalogへ公開した。
- [x] shape/catalog/lazy builtins/stub pytest: `19 passed in 1.57s`
- [x] 対象 ruff: `All checks passed!`

### 2026-07-16 — Phase 10.4 timeline core 完了

- [x] loop rangeとnamed bookmark（optional variation name）を`TransportClock`へ追加した。
- [x] loop wrapでepochを進め、paused recording同期ではloopを適用しない契約を固定した。
- [x] frame clock pytest: `25 passed in 0.11s`
- [x] 対象 ruff: `All checks passed!`

### 2026-07-16 — Phase 2.4 strict runtime config 完了

- [x] merge前key tree検証、近似候補、finite/positive/range/enum検証を追加した。
- [x] user config相対pathをconfig親基準にし、source/effective/resolved reportを追加した。
- [x] `grafix config validate/show` とexit code契約を追加した。
- [x] config/CLI/describe pytest: `25 passed in 0.25s`
- [x] 対象 ruff: `All checks passed!`

### 2026-07-16 — Phase 8.4 extension contract 完了

- [x] `L.layer()` を単数`Layer`返却へ移行し、consumer/test/stubを同期した。
- [x] custom opのpure/deterministic/explicit seed契約と`content | none` cache policyを追加した。
- [x] `none`をCPU cache/inflightから外し、GPU cache keyも評価ごとに分離した。
- [x] layer focused pytest: `14 passed`、registry/realize pytest: `48 passed in 1.68s`
- [x] 対象 ruff: `All checks passed!`

### 2026-07-16 — Phase 4.1 parameter search/filter 完了

- [x] Unicode casefold/AND-token検索と全structured filterのpure modelを追加した。
- [x] label/op/arg/site source/value source/MIDI CCを検索対象にした。
- [x] GUI検索欄、filter popup、既存inactive visibility、件数表示を統合した。
- [x] Parameter GUI全体 pytest: `136 passed`、統合再検証: `20 passed in 0.14s`
- [x] Parameter GUI全体 ruff/mypy: 成功。

### 2026-07-16 — Phase 2.3 ParamStore schema 完了

- [x] top-level schema version、versionless legacy migration、future version拒否を追加した。
- [x] 部分破損時は原本を quarantine して有効entryだけ復元し、診断と
  `LoadProvenance` を runtime state に保持するようにした。
- [x] named variation を primary/session recovery の同じ schema へ統合した。
- [x] persistence/variation focused pytest: `29 passed in 0.19s`。
- [x] 対象 ruff: `All checks passed!`。

### 2026-07-16 — Phase 10.2 WorkspaceState 完了

- [x] sketch/run単位のversioned WorkspaceState JSONとatomic saveを追加した。
- [x] preview/Inspector rect・visibility・UI scaleを復元し、現screen boundsへclampする。
- [x] missing/corrupt/old/future stateのfallbackと診断を追加した。
- [x] focused pytest: `53 passed`、対象 ruff/mypy/`git diff --check`: 成功。

### 2026-07-16 — Phase 8.2 eager validation / semantic choice 完了

- [x] unknown keyword/choiceのDAG作成前検証、typo候補、stub `Literal` を追加した。
- [x] `polyhedron.type_index` を意味名 `kind`、`sphere.type_index/mode` を
  `style/line_mode` choiceへ変更し、未知値を明示拒否するようにした。
- [x] primitive/reconcile/validation/stub focused pytest: `30 passed in 0.41s`。
- [x] 対象 ruff: `All checks passed!`。

### 2026-07-16 — Phase 3.2 bool ownership 完了

- [x] boolの特例を廃止し、他kindと同じ`override`によるCODE/UI選択へ統一した。
- [x] bool rowへCODE/UI selectorとResetを出し、checkbox編集時にUIへ切り替える。
- [x] normal loadでは明示code値、session recoveryではlive UI操作を保持する契約を固定した。
- [x] resolver/persistence/GUI focused pytest: `63 passed in 0.26s`。
- [x] 対象 ruff: `All checks passed!`。

### 2026-07-16 — Phase 4.2 semantic ParamMeta 完了

- [x] display name、説明、単位、step/format/scale、category、advanced、推奨rangeを追加した。
- [x] meta spec/codec/variation/memento/row/search/stubを同じ型へ同期した。
- [x] 不正step/scale/rangeを拒否し、metadata無しuser opのfallbackを維持した。
- [x] focused pytest: `311 passed`、関連回帰: `69 passed`。
- [x] 対象 ruff/mypy/`git diff --check`: 成功。

### 2026-07-16 — Phase 5.2 evaluator timeout/restart 完了

- [x] worker generation、公開restart、deadline超過時terminate/kill/re-spawnを追加した。
- [x] restart中はlast-goodを保持し、旧世代resultを破棄、close時にchildを回収する。
- [x] timeoutをSceneRunner/DrawWindowSystem/runへ配線し、stub/READMEを同期した。
- [x] MpDraw pytest: `36 passed`、window/runner: `56 passed`、stub sync: `1 passed`。
- [x] 対象 ruff/mypy: 成功。

### 2026-07-16 — Phase 3.1 ValueSource / MIDI frame snapshot 完了

- [x] CC値と`midi_live | midi_frozen`由来をpicklableなimmutable
  `MidiFrameSnapshot`へ統合した。
- [x] context、sync/worker task、resolver、FrameParamRecord、runtime badgeを
  `ValueSource(code | ui | midi_live | midi_frozen)`で一貫させた。
- [x] Parameter GUIに`MIDI LIVE`/`MIDI FROZEN` badgeと由来別tooltipを追加した。
- [x] focused pytest: `117 passed in 5.10s`、対象 ruff/mypy: 成功。

### 2026-07-16 — Phase 2.1/2.2 診断 action と recovery 導線

- [x] 診断actionを型付きdispatchへ統一し、Retry/Openと失敗時の再診断を追加した。
- [x] recoveryを`RECOVERED SESSION`として常設し、Keep/Discard/Compareを配線した。
- [x] save/recovery失敗を共通centerへpublishし、focused pytestは`40 passed`、
  runtime統合は`226 passed`、対象ruff/mypyは成功。
- [x] config/operationを含む全failure sourceの共通center統合は後続実装で完了した。

### 2026-07-16 — Phase 8.5 onboarding / project-local typing 完了

- [x] `grafix init/doctor/examples`、no-clobber scaffold/example copyを追加した。
- [x] GL/resvg/ffmpeg/MIDI/font/output writeをstructured doctor reportで検査する。
- [x] project-local stubを既定にし、sketch/user operation/presetのG/E/P型を生成する。
- [x] devtools/stub focused pytest: `32 passed`、対象ruff/mypyとproject-local mypy: 成功。

### 2026-07-16 — Phase 9.3 randomize / lock / morph core 完了

- [x] lockをParamStore UI stateへ永続化し、recovery/reconcile/pruneへ統合した。
- [x] parameter key別seedによるdeterministic randomizeと、recommended/UI range policyを追加した。
- [x] A/B morphの数値・離散・MIDI/override policyを固定し、1 Undo transactionにまとめた。
- [x] parameter core pytest: `185 passed`、対象ruff/mypy/`git diff --check`: 成功。
- [x] favorite/current filterとのGUI scope統合はPhase 9.2/9.3 GUIで完了した。

### 2026-07-16 — Phase 3.3 MIDI session 完了

- [x] controller、live/frozen snapshot、接続状態、reconnect、closeを`MidiSession`へ集約した。
- [x] poll errorをfrozen遷移と共通診断へ変換し、toolbar/popupに`MIDI FROZEN`、
  Reconnect、Clear frozen snapshotを追加した。
- [x] runner、DrawWindow、Parameter GUIを同じsessionへ配線した。
- [x] MIDI/DrawWindow/GUI/runner focused pytest: `107 passed in 0.72s`、対象ruff: 成功。

### 2026-07-16 — Phase 4.4 explicit MIDI Range Edit 完了

- [x] R/E/Tを押下中の直接commitから、store非破壊のShift/Min/Max preview modeへ変更した。
- [x] CC、linked parameter、変更予定rangeを表示し、Applyだけを1 Undo transactionで確定する。
- [x] Cancel/Esc/deactivateはpreviewを破棄し、storeを変更しない。
- [x] Parameter GUI pytest: `152 passed in 0.72s`、対象ruff/mypy: 成功。

### 2026-07-16 — Phase 10.3 accessibility 完了

- [x] workspaceの`ui_scale`をInspectorへ配線し、font、theme spacing、toolbar targetへ適用した。
- [x] ImGui keyboard navigationを有効化し、Tab/Enter navigation flagとEsc cancelを検証した。
- [x] tooltipをhover/focus両方から表示し、configurable shortcut一覧popupを追加した。
- [x] accessibility/config/GUI/runner focused pytest: `204 passed in 0.96s`、対象ruff/mypy: 成功。
- [x] preview側command surfaceは変更していない。

### 2026-07-16 — Phase 7.3 operation diagnostic 基盤

- [x] immutable/bounded/deduplicatedなoperation diagnosticをsync/worker評価から
  `SceneRunner`、共通`DiagnosticCenter`まで配線した。
- [x] `subdivide`と`GridSpec.from_bbox`のclamp/reject/coarsenに元値、実効値、理由を追加した。
- [x] focused pytest: `112 passed`、全体再検証: `1172 passed`。
- [x] `ruff check src/grafix tests`と`mypy src/grafix`: 成功。
- [x] 残るeffectのsilent fallback監査はPhase 7.3後続で完了した。

### 2026-07-16 — Phase 5.3 preview quality 完了

- [x] context-localな`draft | final`品質をsync/worker評価へ一貫して渡した。
- [x] reaction-diffusionのdraft grid/step上限と、実効値を示すoperation diagnosticを追加した。
- [x] interactive previewはdraft、capture/recordingとheadless既定はfinalに固定した。
- [x] focused pytest: `93 passed in 5.72s`、対象ruff/mypy: 成功。

### 2026-07-16 — Phase 6.1/6.2 render契約・RenderSession 完了

- [x] immutable `Color/RenderOptions/Frame/ExportFormat/ExportResult`を追加し、色・suffix・線幅を検証する。
- [x] headless `RenderSession`へdraw/store/config/style/cacheの寿命と明示parameter load modeを集約した。
- [x] root API、生成stub、stub generatorを同期した。
- [x] focused pytest: `141 passed`、full pytest: `1212 passed`。
- [x] `ruff check src/grafix tests`と`mypy src/grafix`（195 files）: 成功。

### 2026-07-16 — Phase 3.4 parameter identity core 完了

- [x] ambiguous candidateを`ReconcileOrphan`として保持し、一覧・手動1:1 migrate APIを追加した。
- [x] manual migrateをUndo/Redoとcodec persistenceへ統合し、旧groupの複数回自動利用を防いだ。
- [x] `key/instance_key/shared`をG/E/L/P/@presetへ一貫して追加し、snippet/stub/docsを同期した。
- [x] focused pytest: `44 passed`、対象ruff/mypy/`git diff --check`: 成功。
- [x] orphan一覧とmanual migrateのGUI導線はPhase 3.4後続で完了した。

### 2026-07-16 — Phase 7.3 silent degradation監査 完了

- [x] extrude/fill/weave/relax/sphere/trim/growthのclamp、reject、boundary-only/no-opを監査した。
- [x] 要求値、実効値、operation名、理由をframe単位のdeduplicated diagnosticへ追加した。
- [x] 通常経路0件、各degrade経路1件の回帰testを追加した。
- [x] focused pytest: `58 passed in 0.71s`、対象ruff/mypy: 成功。

### 2026-07-16 — Phase 7.2 RuntimeLimits / scene aggregate 完了

- [x] scene全layerのvertex/line/exact byteをGPU/cache commit前にaggregate検査する。
- [x] preview/final別のimmutable `RuntimeLimitProfiles`でper-op、scene、CPU/GPU cache、capture queueを統合した。
- [x] scene拒否時のCPU cache transaction rollbackと、共通resource diagnosticを追加した。
- [x] full pytest: `1246 passed in 43.09s`、ruff/mypy（197 files）/`git diff --check`: 成功。

### 2026-07-16 — Phase 6.3 CaptureService 完了

- [x] suffix推論、private staging、versioned no-clobber、late collision retry、manifestを`CaptureService`へ集約した。
- [x] overwrite時もartifact/manifestを一世代でrollback可能なtransactionにした。
- [x] `ExportJobSystem`をqueue/worker/staging lifecycleに限定し、encode/publishをserviceへ委譲した。
- [x] G-code既定値を変えず、既存encoderとのbyte parityを固定した。
- [x] focused pytest: `51 passed in 10.09s`、full pytest: `1247 passed in 43.22s`。
- [x] ruff/mypy（198 files）/`git diff --check`: 成功。

### 2026-07-16 — Phase 4.3 navigation / Help 完了

- [x] favorite/pinをParamStore UI stateとして永続化し、codec/reconcile/pruneへ統合した。
- [x] 行ごとのpin、Favorite filter、Expand all / Collapse all、hidden件数をGUIへ追加した。
- [x] selected/hover/focused rowのHelp paneへ説明・単位・推奨範囲とfallbackを表示した。
- [x] 新規12件、parameter core / GUI pytest: `355 passed`、対象ruff/mypy/`git diff --check`: 成功。

### 2026-07-16 — Phase 7.4 profiler 完了

- [x] operation/layer時間、cache hit/eviction、worker lagをbounded snapshotへ収集した。
- [x] Inspectorへslowest operation/layerとcache/worker統計を追加した。
- [x] GUI無しのstructured JSON trace出力と回帰testを追加した。
- [x] focused pytest: `154 passed`、全体ruff/mypy（201 files）: 成功。
- [x] 並行編集起因だったfull pytestの6件を最終統合後に再検証し、`1357 passed`を確認した。

### 2026-07-16 — Phase 3.4 orphan GUI 完了

- [x] Inspectorへ常設RELINK行と、current/new group・旧候補・理由・scoreの確認popupを追加した。
- [x] 候補の明示クリック時だけ1:1 migrateし、history/Undo/Redoと一覧即時更新へ統合した。
- [x] empty/未知理由/失敗fallbackを含むfocused pytest: `32 passed`、parameter core / GUI: `361 passed`。
- [x] 対象ruff/mypy/`git diff --check`: 成功。

### 2026-07-16 — Phase 6.4 公開render/export API・CLI 完了

- [x] side-effect `Export`をshim無しで廃止し、rootへRenderSession/Frame/render/export/ExportResultを公開した。
- [x] CLIをSVG/PNG/G-code、parameter source、config、overwriteへ対応し、実保存先とmanifestを表示する。
- [x] line thickness既定/単位、stub、README、内部consumerを共通契約へ同期した。
- [x] focused pytest: `58 passed`、full pytest: `1284 passed`、全体ruff/mypy（202 files）: 成功。
- [x] CLI no-clobber実動作で2回目が`_001`となることを確認した。

### 2026-07-16 — Phase 5.4 transactional source watch 完了

- [x] `python -m grafix run sketch.py --watch`と依存追加不要のmtime/size pollingを追加した。
- [x] effect/primitive/preset registryを隔離loadし、draw signature検証後だけliveへcommitする。
- [x] 検証済みsource bytesをspawn workerへ渡し、callable/registry/worker世代を同じframe境界で交換する。
- [x] worker swap失敗時のregistry/callable rollback、last-good frame/ParamStore保持、Retry/Open診断を追加した。
- [x] syntax/runtime error、成功swap、registry rollback、spawn roundtrip、worker cleanup、CLIを検証した。
- [x] focused pytest: `90 passed`、対象ruff/mypy: 成功。

### 2026-07-16 — Phase 2 共通診断の残件完了

- [x] invalid user configをinteractiveではpackaged defaultへ明示fallbackし、source/traceback/Open/Copy付き診断へ変換した。
- [x] fallback configをsession cacheへ固定し、各consumerが別configを参照しないようにした（CLI validateはstrict rejectを維持）。
- [x] final評価、同期SVG、非同期PNG/G-code、queue拒否/submit失敗を共通`export`診断へ統合した。
- [x] config/diagnostics focused pytest: `47 passed`、export/monitor focused pytest: `46 passed`、対象ruff/mypy: 成功。

### 2026-07-16 — Phase 9.2/9.3 named variation GUI・探索scope

- [x] A/B toolbarをnamed variation popupへ置換し、一覧/empty/name/note/UTC時刻/seed/diff/thumbnail pathを表示した。
- [x] save/load/rename/duplicate/deleteと、favorite/current filter scopeのrandomize/lock/morphをcore APIへ配線した。
- [x] load/randomize/morphを1 history transactionとしてUndo可能にした。
- [x] focused pytest: `36 passed`、parameter core / GUI: `372 passed`、batch互換: `14 passed`、対象ruff/mypy: 成功。
- [x] CaptureService adapterとDrawWindow最新final Frameとのruntime既定配線をPhase 6.5で完了した。

### 2026-07-16 — Phase 6.5 provenance・recording 契約完了

- [x] manifest schema v2へGrafix/code/git/config/parameter/seed/output/frame provenanceを追加し、
  `RenderSession/Frame`で固定したsnapshotだけをcapture workerへ渡すようにした。
- [x] public `render(config=...)`後の`export(frame, ...)`とinteractive async PNG/G-codeが、frame生成時の
  実効config・canvas size・G-code設定を使うように固定した。
- [x] recordingのscene errorをpause/abortとして可視化し、last-good frameを成功扱いで黙って記録しない。
- [x] frame/dropped/duplicated/error countと中止理由をcapture manifestへ記録する。
- [x] GUI/API/CLIを`RenderSession`・`CaptureService`・no-clobber・manifestの同じ契約へ統合した。

### 2026-07-16 — Phase 9.4 variation batch・thumbnail 完了

- [x] named variation batchを`RenderSession/CaptureService`へ統合し、variationごとのseedを
  frame provenanceとmanifestへ反映した。
- [x] variation名・seed付きthumbnailとcontact sheetを生成し、partial failure summaryとno-clobberを維持した。
- [x] DrawWindowの最新final Frameをvariation thumbnail captureへ渡すruntime既定配線を完了した。
- [x] GUI smokeで`GUI Smoke` variationの保存、一覧反映、thumbnail生成、manifest生成を確認した。

### 2026-07-16 — 最終コード監査での補正

- [x] `runtime_config_scope()`と`RenderSession`のclose/初期化失敗時に、明示config path・cache・reportを
  LIFOで復元するようにし、session中のconfigを固定した。
- [x] parameter recoveryのDiscardでlock/favoriteを正確に復元し、破損storeの部分復旧を即時journal化した。
  journal保存失敗時は元sourceへrollbackする。
- [x] variation batchがglobal random stateを変更せず、variation seedをcapture provenanceへ渡すようにした。
- [x] `RenderSession`がdraft contextを漏らさず、常にfinal品質で評価する回帰testを追加した。
- [x] config/export focused test `112 passed`、recovery focused test `223 passed`、seed focused test
  `92 passed`を確認した。

### 2026-07-16 — 最終検証

- [x] full pytest: `1357 passed in 42.57s`。
- [x] `ruff check src/grafix tests`: `All checks passed!`。
- [x] `mypy src/grafix`: `Success: no issues found in 207 source files`。
- [x] 生成stub focused test: `2 passed`、`git diff --check`: 成功。
- [x] CLI E2EでSVG no-clobber、実PNG 600x600、同名SVG非上書き、G-code設定・manifest一致、
  variation batch 2件・seed 7/11・contact sheet、config validate、operation describeを確認した。
- [x] GUI smokeでpreview描画、Inspectorの状態表示・parameter操作面、named variation popup、保存結果を確認した。
  テスト用に生成したthumbnail/manifestとGUIプロセスは確認後に片付けた。
- [x] APP-001/003/005の変更禁止範囲を再監査し、G-code encoder/default、canvas/primitive default、
  preview pan/zoom・canvas toolbar・共有capture surfaceを変更していないことを確認した。
- [x] 未完了項目なし。意図的な残余は却下済みAPP-001/003/005のみで、追加アクションは不要。

### 2026-07-17 — `sketch/readme/grn/6.py` 表示回帰の修正

- [x] `.grafix/config.yaml`のproject-root向け相対pathをconfig親基準の`../...`へ移行し、
  preset・font・sketch・outputの実効pathを復旧した。
- [x] `grn_a5_frame`が単一`Layer`同士を加算していた箇所を、正規化可能なSceneItem列へ修正した。
- [x] READMEのproject-local config例とpreset pathをconfig親基準へ訂正した。
- [x] GRN 6のpreset読込・draw正規化回帰testと、初期化configからのpreset autoload統合testを追加した。
- [x] installed stub同期testを開発者のproject-local configから隔離した。
- [x] headless final renderで3 layers・114077 vertices・45966 linesを確認した。
- [x] 実GUIで作品とInspectorの表示を確認し、終了後にtest processを片付けた。
- [x] focused pytest: `15 passed`、full pytest: `1359 passed in 23.36s`。
- [x] 対象ruffと`ruff check src/grafix tests`、`mypy src/grafix`、`git diff --check`: 成功。
