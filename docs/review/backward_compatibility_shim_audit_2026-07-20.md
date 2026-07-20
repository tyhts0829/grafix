# 後方互換・互換シム・実装美観の監査結果（2026-07-20）

## 1. 結論

現状は「不要な後方互換やシムがない」とは判定できない。

特に、次の 8 クラスターはリポジトリ方針
（`AGENTS.md:10,52`、`docs/migration_2026-07-16.md:3`）と直接衝突する、
または衝突する可能性が非常に高い。

1. `ParamStoreMemento` が使わない旧引数を必須で受け取り、その場で捨てている。
2. `ExportJob.svg_output_path` が完全に未使用なのに旧呼び出しのため残っている。
3. `RealTimeClock`、`SceneRunner._realize_session` など、旧名称だけの alias が残っている。
4. 内部 DTO が旧 positional constructor の field 順と default を維持している。
5. `ParamStoreRuntime` が旧 positional/plain-set construction のため別実行経路を持つ。
6. 旧 resource-limit 引数と新 `RuntimeLimits` が全層で二重化されている。
7. constructor を通らない不完全な test object のため、production code に多数の
   `getattr` / `hasattr` fallback が残っている。
8. capture manifest v2 が v1 top-level schema も重複出力し、provenance 欠落時には
   実在しない代替 provenance を組み立てている。

このほか、ParamStore の旧 schema migration、effect topology の新旧二重表現、
Parameter GUI の新旧 block model、録画の二重 publish 契約など、移行途中の構造が
複数残っている。即時に消してよい局所シムと、保存データや公開 API の方針判断を要する
項目は分けて扱うべきである。

## 2. 監査条件

- 対象:
  - `src/grafix/**/*.py` 229 ファイル
  - `tests/**/*.py` 257 ファイル
  - `typings/`、`pyproject.toml`、`mypy.ini`
  - 関連する README、migration note、plan、既存 review
- 方法:
  1. `互換`、`legacy`、`従来`、`旧実装`、`old backend`、`test double`、
     `deprecated` 等の語彙検索
  2. alias、pass-through wrapper、optional attribute、複数 schema、複数 constructor
     形の静的探索
  3. production call site と test の突合
  4. 正当な platform/dependency 境界と、test-only/旧 API fallback の切り分け
- 監査対象は **2026-07-20 時点の未コミット差分を含む作業ツリー**。
  とくに effect order/topology 関連は現在の未コミット実装を含む。
- 既存の変更や未追跡ファイルには触れていない。本ファイルだけを新規作成した。
- コード変更をしていないため pytest/ruff/mypy は実行していない。

### 判定記号

| 記号 | 意味 |
|---|---|
| P1 | 方針違反が明確、または分岐・二重状態の実害が大きい。優先的な除去対象 |
| P2 | 構造的負債。正規形を決めて一括移行すべき |
| P3 | 局所的な美観・型安全性・保守性の負債 |
| 確定 | コメント、call site、test の三者から互換目的を確認できる |
| 要方針 | 保存データ、公開 UX、外部 backend などの意図的契約を含み得る |

## 3. 優先度一覧

| ID | 優先度 | 判定 | 概要 |
|---|---:|---|---|
| A-01 | P1 | 確定 | `ParamStoreMemento` の受け取って捨てる旧引数 |
| A-02 | P1 | 確定 | `ExportJob.svg_output_path` と private direct-call mode |
| A-03 | P1 | 確定 | `RealTimeClock` / `_realize_session` の旧名称 alias |
| A-04 | P1 | 確定 | `DrawResult` 等の旧 positional constructor 維持 |
| A-05 | P1 | 確定 | `ParamStoreRuntime` の positional/plain-set 互換経路 |
| A-06 | P1 | 確定 | resource limit の旧・新 API 二重化 |
| A-07 | P1 | 確定 | 不完全 test object を支える production fallback |
| A-08 | P1 | 確定 | capture manifest v1/v2 二重 schema と合成 provenance |
| B-01 | P1 | 要方針 | ParamStore legacy migration と parser 二重走査 |
| B-02 | P1 | 確定 | effect chain の topology/legacy step 二重表現 |
| B-03 | P2 | 確定 | Parameter GUI の新旧 GroupBlock model |
| B-04 | P2 | 確定 | VideoRecorder/RecordingSystem の二重 publish 契約 |
| B-05 | P2 | 要方針 | pyimgui/pyglet version 差の adapter が UI 全体へ分散 |
| B-06 | P2 | 要方針 | `@preset` の予約引数所有者と `P` 呼び出し形が二重 |
| B-07 | P2 | 確定 | `DrawRenderer` の旧 standalone mode |
| B-08 | P2 | 確定 | benchmark schema v4 への未完了 mapping adapter |
| C-01 | P2 | 確定/要検討 | core effect の平面基底・数値 helper 重複 |
| C-02 | P3 | 確定 | 旧 namespace/name 解決 fallback |
| C-03 | P3 | 確定 | `png_output_size(scale=None)` の旧 ambient-config 入口 |
| C-04 | P3 | 確定 | private module の未使用 symbol 転送 |
| C-05 | P3 | 確定 | snippet の未使用引数と invariant 隠蔽 fallback |
| C-06 | P2 | 確定/要方針 | 型 stub の全面 fallback と mypy 設定二重化 |
| C-07 | P3 | 確定 | manual harness、warning filter 等の重複・恒久逃げ道 |

## 4. P1: 明確な互換シム

### A-01. `ParamStoreMemento` が obsolete 引数を受け取って捨てる

**証拠**

- `src/grafix/core/parameters/memento.py:182-186`
  - constructor keyword を「従来 API と互換」に保つと明記。
- `src/grafix/core/parameters/memento.py:197-219`
  - `explicit_by_key`、`labels`、`ordinals` を必須で受ける。
  - 最後は `_ = explicit_by_key, labels, ordinals` として完全に破棄する。
- 通常の capture helper も `src/grafix/core/parameters/memento.py:256-267` で
  この 3 引数を渡している。

**判定**

使わない値を API shape のためだけに受け取る、最も明白な compatibility shim である。
class は core 内部実装であり、外部互換を維持する根拠も薄い。

**推奨**

- constructor を実際に保存する `states`、`meta`、`effects`、`collapsed_headers` のみにする。
- 可能なら public-like constructor をやめ、capture/restore 用 factory だけから作る。
- 旧 constructor を固定する test は削除し、memento の観測可能な復元結果だけをテストする。

### A-02. `ExportJob.svg_output_path` は完全な dead compatibility field

**証拠**

- `src/grafix/interactive/runtime/export_job_system.py:190-205`
  - 「後方互換のため request には残すが、使用しない」と明記。
- `src/grafix/interactive/runtime/export_job_system.py:217-218`
  - 実処理は値の `Path` 化だけ。
- `ExportJobSystem.submit()` にも不要な引数が残る:
  `src/grafix/interactive/runtime/export_job_system.py:839-868`。
- `tests/interactive/runtime/test_export_job_system.py:755-824`
  - 値を渡しても public SVG が触られないこと、すなわち「使われないこと」を契約化している。

同じ DTO の `staging_dir=None` も
`src/grafix/interactive/runtime/export_job_system.py:203-205,272-299` で
private `_execute_export_job()` の旧 direct-call semantics を維持する。
production の既定 backend は dispatch 時に staging directory を設定する
（同ファイル `:729-744`）。

**判定**

`svg_output_path` は即時削除候補である。`staging_dir=None` は完全な dead field ではないが、
production job と private helper test で異なる実行契約を持たせる不必要な二重モードである。

**推奨**

- `svg_output_path` を DTO、`submit()`、test から同時に削除する。
- 既定 backend job は常に staging を持つ一契約にする。
- encoder 単体テストには、job publish semantics を背負わない pure helper を用意する。

### A-03. 旧名称だけの alias

#### `RealTimeClock`

- `src/grafix/interactive/runtime/frame_clock.py:323-328`
  - 中身のない `RealTimeClock(TransportClock)` を「後方互換」と明記。
- production 自身も
  `src/grafix/interactive/runtime/draw_window_system.py:79,321` で旧名を使う。
- `tests/interactive/runtime/test_frame_clock.py:267-272` が旧名を固定する。

#### `SceneRunner._realize_session`

- canonical state は quality 別の `_realize_sessions`。
- `src/grafix/interactive/runtime/scene_runner.py:75-80` は
  既存 test/計測だけのため draft session を旧単数名にも保持する。
- repository 内の実質的利用は
  `tests/interactive/runtime/test_mp_draw.py:1458-1471` の private 属性参照だけ。

**推奨**

- production を `TransportClock` へ更新し `RealTimeClock` を削除する。
- test/benchmark を `_realize_sessions["draft"]` または観測可能な public property へ移し、
  `_realize_session` を削除する。
- alias を残して段階的 deprecated にするのではなく、一度に call site を更新する。

### A-04. 内部 DTO が旧 positional constructor を固定する

**証拠**

- `DrawResult`
  - `src/grafix/interactive/runtime/mp_draw.py:170-203`
  - `t`、`epoch`、`snapshot_revision` を旧 field の後ろへ default 付きで追加したと明記。
  - `tests/interactive/runtime/test_mp_draw.py:384-402` が
    `DrawResult(1, [], [], [], "legacy error")` を明示的に固定。
  - production construction は keyword 形式。
- `TransportSnapshot`
  - `src/grafix/interactive/runtime/frame_clock.py:25-35` の新 field は default 付き。
  - `tests/interactive/runtime/test_frame_clock.py:157-162` が旧 3 positional 引数を固定。
- `ExportJobResult`
  - `src/grafix/interactive/runtime/export_job_system.py:234-247`
  - 新 metadata を「既存 positional field」のため末尾へ追加すると明記。

**問題**

process 内部の message/状態 DTO にまで field 順の互換性を背負わせると、必須 metadata を
default で偽装し、schema の進化を dataclass field 順へ拘束する。

**推奨**

- 内部 DTO を `kw_only=True` にする。
- 現在の実行に必要な field は required にする。
- 旧 constructor shape を直接テストせず、serialize/queue/consumer の現行契約をテストする。

### A-05. `ParamStoreRuntime` の旧 positional/plain-set 互換経路

**証拠**

- `src/grafix/core/parameters/runtime.py:122-140`
  - field を旧 positional 順の末尾へ追加すると明記。
- `src/grafix/core/parameters/runtime.py:170-220`
  - 通常は `_TrackedGroupSet` による O(1) revision token。
  - 旧 positional construction で plain `set` が入った場合だけ、
    毎回 `frozenset` を作る別 token shape を返す。
- `tests/core/parameters/test_runtime.py:5-33,57-67`
  - 旧 7 positional field と plain-set identity/内容 token を明示的に固定。
- production は `src/grafix/core/parameters/store.py:80` の
  `ParamStoreRuntime()` construction だけであり、旧 positional path を必要としない。

**推奨**

- dataclass を keyword-only にする。
- `__post_init__` で常に `_TrackedGroupSet` へ正規化する。
- `visibility_cache_token()` の union return shape と O(n) fallback を削除する。

### A-06. resource limit の旧・新 API が全層で二重化

**証拠**

- `src/grafix/core/runtime_limits.py:99-108`
  - `profiles_for_resource_budget()` が旧 operation budget を新 profiles へ写像すると明記。
- `src/grafix/core/realize.py:140-176`
  - 旧 `max_cache_bytes`、`max_cache_entries`、`resource_budget` と
    新 `runtime_limits` を同時に受ける。
  - 新指定時は旧引数を上書きし、旧指定時は operation/scene を同じ budget で構築する。
- `src/grafix/api/render.py:396-447,615-661`
  - `RenderSession` と `render()` に同じ二重入力と優先順位がある。
- `src/grafix/api/runner.py:799-800,854-859`
  - `run()` も旧 `resource_budget` と新 `runtime_limit_profiles` を公開する。
- `SceneRunner` と `DrawWindowSystem` も同じ変換分岐を持つ。
- `src/grafix/core/realize.py:40-41` の
  `DEFAULT_MAX_CACHE_* = DEFAULT_CPU_CACHE_*` も旧名称 alias である。

**問題**

同じ上限を表す複数入口、黙った優先順位、quality 間の暗黙複製が API/core/runtime の
全層へ伝播している。単なる convenience より移行 shim の性格が強い。

**推奨**

- headless は `RuntimeLimits`、interactive は `RuntimeLimitProfiles` を唯一の入力にする。
- 旧 scalar/budget 引数、変換 helper、旧 constant alias を同時に削除する。
- 簡便な既定は `RuntimeLimits()` 自体に持たせ、旧引数を残す理由にしない。

### A-07. 不完全な test object を production code が受け入れる

**規模**

- `object.__new__(DrawWindowSystem)` を使う test: 32 箇所
- `ParameterGUI.__new__(ParameterGUI)`: 12 箇所
- `object.__new__(MpDraw)`: 6 箇所
- 既存 plan も
  `docs/plan/src_grafix_essential_refactoring_plan_2026-07-18.md:106-112,481-518`
  で同じ負債を認識している。

**代表例**

- runner/window:
  - `src/grafix/api/runner.py:311-337`
    - 古い backend/test double 用に `width/height` へ fallback。
  - `src/grafix/api/runner.py:621-639,1169-1171`
    - screen/size API のない stub では旧 config 座標へ fallback。
  - `src/grafix/api/runner.py:1147-1151,1219-1223`
    - concrete `DrawWindowSystem` の必須 callback を `getattr(..., None)` で optional 化。
- `DrawWindowSystem`:
  - `src/grafix/interactive/runtime/draw_window_system.py:541-545`
    - constructor を通らない test double だけ provenance builder 欠落を許す。
  - 同ファイル `:1076-1088`
    - 実 pyglet Window が持つ resize API を旧 backend/test double のため optional 化。
  - 同ファイル `:1455-1464,1666-1694`
    - 旧 SceneRunner/test double の欠落 metadata を推測で補う。
- `window_loop.py:124-130`
  - `visible` を持たない test double は表示中とみなす。
- `export_job_system.py:139-169`
  - 型上は `RealizedLayer` なのに、旧互換 object を duck typing して byte 数を推測する。
- `ParameterGUI` / `MpDraw`
  - constructor が作るはずの属性にも多数の既定値 fallback が残る。

**判定**

platform capability の検査ではなく、主に test が不正な部分初期化をしているため必要になった
production shim である。rename や state 欠落を例外にせず黙って機能停止・推測値へ変えるため、
保守性だけでなく correctness の問題でもある。

**推奨**

1. collaborator を明示する初期化済み fixture/factory を作る。
2. test-only と証明できた fallback を直接属性参照へ置換する。
3. 実 backend/optional subsystem の capability branch は Protocol/adapter 境界へ残す。
4. `getattr` を一括削除しない。OS、MIDI、cleanup 中の部分初期化は別物である。

### A-08. capture manifest が v1/v2 を重複出力する

**証拠**

- `src/grafix/core/capture_manifest.py:70-80`
  - v2 class なのに provenance は optional。
- 同ファイル `:117-143`
  - v2 `output` section と、v1 の top-level
    `t/canvas_size/format/artifact_paths` を二重出力。
  - `:135` で v1 identity を保持すると明記。
- provenance 欠落時は
  `src/grafix/core/capture_provenance.py:505-546` の
  `unavailable_capture_provenance()` が架空の session/frame provenance を構築する。
- production の capture 2 経路は
  `src/grafix/export/capture.py:303-310` と
  `src/grafix/interactive/runtime/draw_window_system.py:1197-1205` で実 provenance を渡す。
- 二重 schema の実害として
  `src/grafix/api/variation_batch.py:508-524` は artifact path を 2 箇所更新する。

**判定**

versioned schema を名乗りながら旧 key を同時出力する明確な互換層である。
欠落 provenance を「unavailable」と明示する意図は理解できるが、現行 production で必須なら
optional constructor を維持する理由にはならない。

**推奨**

- provenance を必須にする。
- v2 の canonical `output` 構造だけを出力する。
- top-level v1 key、`unavailable_capture_provenance()`、二重更新処理を削除する。
- 旧 manifest consumer が必要なら runtime 二重出力ではなく one-shot migration を用意する。

## 5. P1/P2: 移行途中または二重モデル

### B-01. ParamStore の legacy migration と parser 二重走査

**証拠**

- `src/grafix/core/parameters/codec.py:21-23,466-500`
  - versionless payload と schema v1 を v2 へコピー変換する。
- `src/grafix/core/parameters/codec.py:878-899`
  - migration、issue scan、decode の順に処理する。
- `tests/core/parameters/test_persistence.py:290,394-414`
  - v1/versionless migration を明示的に固定。
- `src/grafix/core/parameters/merge_ops.py:348-379`
  - explicit metadata のない旧 JSON 用に runtime policy も分岐する。
- `src/grafix/core/parameters/persistence.py:49-65`
  - legacy migration 診断を user-visible state に残す。

さらに、best-effort decoder と `_find_decode_issues()` が同じ section 群を別々に走査するため、
「受理できる値」と「issue と判定する値」の drift が起き得る。

**対照**

`src/grafix/interactive/runtime/workspace_state.py:215-242` は old/future schema を
現行形式へ読み替えず、fallback と診断を返す。こちらは no-shim 方針に整合する。

**判定**

保存済みユーザーデータ保護は API alias と同列ではないため、削除前に方針判断が必要。
ただし、runtime が無期限に旧 schema を読み、部分修復し、現行 policy まで分岐させる設計は
現在の「shim を置かない」方針と整合しない。

**推奨**

- 現行 schema を一度だけ strict parse する typed intermediate を作る。
- parse 結果から store と diagnostics を同時に生成し、二重走査をやめる。
- versionless/v1 を継続サポートしないなら、runtime migration を削除する。
- 既存データを救う場合は、明示的な一回限りの migration command/tool に分離する。

### B-02. effect chain の canonical topology と legacy step map が併存

この項目は現在の未コミット effect-order 作業を含む。

**証拠**

- `src/grafix/core/parameters/effects.py:118-129`
  - `_step_by_site`、`_legacy_step_by_site`、`_topology_by_chain` を同時保持。
- 同ファイル `:131-217`
  - 完全 topology 到着時に legacy entry を削除する一方、
    topology のない `record_step()` は legacy map へ保存する。
- 同ファイル `:445-590,679-690`
  - delete/prune/generation/rebuild が両表現を union・同期する。
- `src/grafix/core/parameters/codec.py:124-139`
  - 「移行途中に topology と混在する legacy step」も再 serialize する。
- canonical producer は `src/grafix/api/effects.py:128-158` の完全 topology。
  legacy producer は `FrameParamRecord(chain_id, step_index)` 由来である。

**問題**

派生 index、旧入力の pending state、canonical topology が三つの mutable source of truth に
なっている。保存まで行うため、移行状態が一時的でなく永続化される。

**推奨**

- `FrameEffectChainRecord` を唯一の chain 表現にする。
- step index は topology と order override から導出する。
- 旧 payload を読む場合も load 境界で一度だけ canonical topology へ変換し、
  runtime では dual map を保持しない。
- 未コミット実装を確定する前に解消するのが最も安価である。

### B-03. Parameter GUI に新旧 `GroupBlock` model がある

**証拠**

- canonical immutable layout:
  `src/grafix/interactive/parameter_gui/group_blocks.py:15-30`
  の `GroupBlockLayout` / `GroupBlockLayoutItem`。
- 旧 row-owning model:
  同ファイル `:33-48` の `GroupBlock` / `GroupBlockItem`。
- adapter:
  - `group_blocks_from_layout()` `:114-134`
  - `group_blocks_from_rows()` `:182-202`
  - docstring は「従来の block 表現」と明記。
- production も Code ボタン押下時に
  `src/grafix/interactive/parameter_gui/table.py:1887-1907` で旧 model を再構築する。

**推奨**

- snippet API を `GroupBlockLayout + indexed rows`、または単一 immutable view へ移す。
- `GroupBlock*`、adapter、旧 model 専用 helper/test を同時に削除する。
- performance 用 prebuilt layout と snippet 用 model を別々に持たない。

### B-04. 録画に direct publish と staging publish の二契約がある

**証拠**

- `src/grafix/interactive/runtime/video_recorder.py:362-407`
  - `close_to_staging()` は application transaction 用。
  - `close()` の `no_clobber=False` は「後方互換の直接利用」と明記し atomic replace。
- `src/grafix/interactive/runtime/recording_system.py:171-242`
  - `stop()` と `stop_to_staging()` が両契約を上位でも再公開。
- DrawWindow production は
  `src/grafix/interactive/runtime/draw_window_system.py:1156` で staging 契約を使う。
- direct publish は主に recorder/system 単体 test が固定する。

**推奨**

- `VideoRecorder` は常に完成 temp を返す staging encoder にする。
- publish/no-clobber/manifest は capture transaction owner だけが担当する。
- `close()`/`stop()` の旧 direct-publish API を削除する。

### B-05. GUI backend 互換 adapter が UI 全体へ分散

**証拠**

- `pyproject.toml:27-28` の `pyglet` / `imgui` に対応 version 下限がない。
- renderer factory:
  - production `parameter_gui/pyglet_backend.py:41-50`
  - `devtools/pyimgui_show_window.py:4-15`
  - manual harness にも同型 fallback。
- content-width adapter が少なくとも 3 実装:
  - `parameter_gui/gui.py:247-257`
  - `parameter_gui/widgets.py:63-83`
  - `parameter_gui/table.py:1241-1267`
- `table.py:1801-1810,1824-1832,1924-1933` は
  method/flag/arity/return-shape 差を描画ロジック内で直接吸収する。
- GUI test double が古い signature を意図的に実装し、production の `TypeError` retry を必要とする。

**判定**

Retina、clipboard、OS/window capability の adapter 自体は正当である。一方、対応 version が
不明なまま UI 本体の各所で version/test-double 差を吸収する構造は美しくない。

**推奨**

- 対応する pyimgui/pyglet の最低 version を決める。
- 実差異が残る場合は `pyglet_backend.py` の単一 adapter/Protocol に閉じ込める。
- UI 本体と fake は正規化済み interface だけを使う。
- `TypeError` を捕捉して別 signature を再試行する production code をなくす。

### B-06. `@preset` の予約引数所有者と `P` の呼び出し形が二重

**証拠**

- `src/grafix/api/preset.py:110-117,129-133`
  - `activate` は元関数 signature で禁止する。
- 同ファイル `:149-223`
  - `name/key/instance_key/shared` は wrapper 所有引数として pop する一方、
    元関数が同名 parameter を宣言していれば再注入する。
- `src/grafix/api/presets.py:65-98,100-125`
  - `P(name=..., key=...).foo(...)` の pending 値を closure で
    `foo(name=..., key=...)` へ転送する。
  - 直接 kwargs と pending kwargs の優先順位も必要になる。

**判定**

明示的な deprecated API ではないが、同じ identity metadata の所有者と入力構文が二重である。
README/test も両流儀を利用するため、公開 UX の方針判断が必要。

**推奨**

- 予約 identity 引数は decorator wrapper だけが所有すると決め、
  元 preset 関数 signature では全て禁止する。
- `P(name=...).foo()` と `P.foo(name=...)` の一方を canonical にする。
- 互換 wrapper を残さず README、example、test を一括更新する。

### B-07. `DrawRenderer` が旧 standalone mode を持つ

- `src/grafix/interactive/gl/draw_renderer.py:455-478`
  - `scene_serial` と `snapshot_revision` の双方 `None` を
    「renderer 単体利用との互換」として許す。
  - 片方だけ指定した場合はエラー、両方ない場合は admission を無効化する。

現行 runtime で fresh-scene metadata が correctness/cache-admission に必要なら、test/単体利用だけ
別契約にするべきではない。両値を必須にし、単体 test も canonical metadata を渡すべきである。

### B-08. benchmark schema v4 の mapping adapter が残る

- `src/grafix/devtools/benchmarks/runner.py:619-694`
  - 旧 workload の任意 nested mapping を再帰的に推論し、
    schema v4 の `Metric` tuple へ変換する。
- `tests/devtools/benchmarks/test_runner.py:222-249` が旧 mapping を固定する。
- 複数 workload がまだ mapping を返すため dead code ではなく、移行が未完了。

**推奨**

全 case を `tuple[Metric, ...]` へ更新し、recursive type/unit/phase/scope inference と
legacy test を削除する。benchmark 内部 schema に無期限の変換層を置かない。

## 6. P2/P3: その他の美観・保守性負債

### C-01. core effect の共通処理が重複

#### 平面基底

- canonical 共通基盤:
  `src/grafix/core/effects/util.py:574-815`
  の `PlanarFrame` / `canonical_planar_frame()`。
- 独自実装:
  - `buffer.py:48-182` の `_PlaneBasis` / fit / project / lift
  - `partition.py:70-193` の別 `_PlaneBasis` / fit / project / lift

tolerance、linear input、向き、dtype が別々であり、`buffer.py:97-100` には旧 XY 挙動へ寄せる
規則もある。統合時に出力が変わり得るので、共通契約を明示してから移す必要がある。

#### 完全一致する小 helper

- `fill.py:85-99` と `dash.py:42-56` の `_as_float_cycle`
- `highpass.py:51-58` と `lowpass.py:45-52` の `_reflect_index`
- `quantize.py:21-25` と `pixelate.py:30-34` の `_round_half_away_from_zero`

これらは同一実装であり、互換問題なしに共通 helper へ寄せられる。

#### 要統合検討

- `growth.py:324-418` と `warp.py:207-296` の SDF kernel は大部分が同型だが、
  optimization policy 差がある。無理に一般化せず、共通 kernel と effect 固有 policy を
  分けられる場合だけ統合する。

### C-02. 旧 namespace/name 解決 fallback

- `src/grafix/core/primitive_registry.py:86-90`
  - 現行 `grafix.core.primitives.*` に加えて不存在の旧 `core.primitives.*` も builtin 扱い。
- `src/grafix/core/effect_registry.py:98-102`
  - 同様に旧 `core.effects.*` を許す。
- `src/grafix/devtools/generate_stub.py:413-451`
  - provenance 解決に失敗すると旧 built-in module 命名規則へ戻る。
- `src/grafix/core/realize.py:40-41`
  - 新 cache constant への旧名 alias。

**推奨**

現行 namespace/provenance/name を唯一の正規形にし、旧 prefix 判定、broad exception 後の
命名規則 fallback、旧 constant alias を削除する。

### C-03. `png_output_size(scale=None)` が旧 ambient-config 入口

- `src/grafix/export/image.py:91-105`
  - `scale=None` の「従来入口」だけ process-global runtime config を再読込する。
- `default_png_output_path()` も `src/grafix/export/image.py:83-86` で scale を省略する。

session は effective config を開始時に固定する一方、この helper だけ ambient state を読む。
`scale` を必須にするか、固定済み config を明示的に注入し、同じ計算関数へ統一するべきである。

### C-04. private `_operation_selector` が未使用 symbol を転送

`src/grafix/api/_operation_selector.py:11-28,255-276` は core symbol を import/re-exportするが、
次の symbol はこの module 内で使われず、repository 内の他 consumer も core から直接 import する。

- `decode_selector_param_key`
- `ensure_selector_spec_registered`
- `selector_display_arg`
- `selector_effect_n_inputs`
- `selector_help_identity`
- `selector_kind`
- `selector_search_terms`

underscore module に互換 re-export を置く理由は薄い。不要 import/`__all__` を削除する。

### C-05. snippet の未使用引数と invariant 隠蔽

- `src/grafix/interactive/parameter_gui/snippet.py:314-345`
  - `layer_style_name_by_site_id` は「将来用・現在未使用」と明記。
  - production/test は毎回意味なく渡す。
- 同ファイル `:629-643`
  - canonical grouping に存在しない未知 group type を、例外にせず debug/test 用 dict snippet へ
    fallback する。

**推奨**

- 未使用引数を call site/test と同時に削除する。
- group type を enum/exhaustive match にし、内部 invariant 違反は明示的に失敗させる。

### C-06. 型安全性の逃げ道と設定二重化

**全面 fallback**

- `src/grafix/api/__init__.pyi:1666-1668`
  - 未知 preset attribute を任意 callable とする。
- `typings/imgui/__init__.pyi:5-8`
- `typings/imgui/integrations/__init__.pyi:5-8`
- `typings/imgui/integrations/pyglet.pyi:5-8`
  - 未知 attribute をすべて `Any` にする。

これは `P.<typo>` や imgui API typo を型検査から隠す。dynamic registry 自体は必要だが、
project-local stub generator で列挙した symbol の安全性まで全面 fallback で無効化している。

**mypy 設定**

- `pyproject.toml:74-76` は `ignore_missing_imports=true`。
- `mypy.ini:1-6` は `mypy_path=typings`。
- 設定源が二つあり、選ばれる config により検査強度が変わる。

**推奨**

- mypy 設定を一箇所へ統合する。
- broad `ignore_missing_imports` を削除し、必要なら dependency ごとの override にする。
- imgui は利用面を表す Protocol/具体 stub に絞る。
- generated preset stub を正規入口にするなら `_P.__getattr__` fallback は削除する。

### C-07. 低優先度の重複・恒久逃げ道

- `src/grafix/devtools/pyimgui_show_window.py:4-15` と manual harness が
  production renderer factory と同じ compatibility fallback を再実装する。
- `sketch/readme/readme.py` と `sketch/readme/1.py` は run 設定以外がほぼ重複する。
- `pyproject.toml:64-68` は第三者 `fontTools.misc.py23` の deprecated warning を
  全 test で恒久的に隠す。

いずれも単独では重大でないが、正規入口・対応 dependency version・削除条件が曖昧になる。
manual/example は production helper を再利用し、warning filter を残す場合は対象 test と
削除条件を明記するべきである。

## 7. 問題とは判定しなかったもの

次は検索上は wrapper/fallback に見えるが、直ちに互換シムとは判定しなかった。

### 7.1 `grafix.api.run()` の lazy wrapper

`src/grafix/api/__init__.py:61-66` の `run(*args, **kwargs)` は runtime signature、
annotation、identity、introspection を失い、stub に signature を複製する欠点がある。
一方で GUI dependency の cold import を避けるという明確な architecture 上の目的がある。

現時点では削除対象ではなく、将来 heavy import を `runner.run()` 内へ移せるなら
direct re-export に簡素化する候補とする。

### 7.2 root/API façade の re-export

`src/grafix/__init__.py` と `src/grafix/api/__init__.py` の re-export は通常の façade であり、
それだけでは compatibility shim ではない。公開契約を root `grafix` に限定する旨を
文書化すると境界はより明確になる。

### 7.3 dynamic registry の `G/E/P.__getattr__`

user-defined operation/preset の runtime dispatch に必要であり、旧名称 fallback ではない。
ただし型 stub の全面 fallbackは C-06 のとおり別問題である。

### 7.4 WorkspaceState、MIDI、OS/Retina 境界

- `workspace_state.py:180-242` は old/future schema を移行せず fallback+診断にする。
- optional MIDI dependency、未接続、`auto` port 選択は runtime capability/ユーザー指定の境界。
- Retina scale、screen clamp、OS clipboard、日本語フォント fallback は platform 境界。

これらは削除対象の後方互換シムではない。

### 7.5 effect の既存出力・RNG・数値 oracle

effect 内の「旧実装を踏襲」「従来の warning/bit pattern/RNG consumption を維持」という
コメントの多くは、公開 geometry 出力の決定性や最適化前後の同値性を守る specification である。
二重 API や wrapper が存在しないものは単独では指摘対象にしなかった。

ただし `buffer` / `partition` の平面基底や完全一致 helper の重複は C-01 のとおり、
出力契約を明示したうえで統合できる。

## 8. 推奨する除去順

### 第1段階: 局所的で影響が読みやすいもの

1. A-01 `ParamStoreMemento` の捨てる引数
2. A-02 `svg_output_path`
3. A-03 旧 alias
4. C-02 旧 namespace/name fallback
5. C-04 未使用 re-export
6. C-05 未使用 snippet 引数
7. C-06 mypy 設定の一元化

### 第2段階: test を先に正規化するもの

1. A-04 DTO を keyword-only 化
2. A-05 `ParamStoreRuntime` を常時 tracked-set 化
3. A-07 初期化済み fixture への移行と test-only fallback 除去
4. B-07 renderer metadata の必須化
5. B-08 benchmark workload の typed metric 化

### 第3段階: 正規モデルを一つにするもの

1. A-06 `RuntimeLimits` / `RuntimeLimitProfiles` への統一
2. A-08 capture manifest v2 への統一
3. B-02 effect topology への統一
4. B-03 immutable GroupBlock model への統一
5. B-04 staging publish への統一
6. B-05 GUI backend adapter の一箇所化

### 第4段階: 明示的な製品方針が必要なもの

1. B-01 旧 ParamStore を拒否するか one-shot migration にするか
2. B-06 preset identity の canonical syntax/owner
3. C-06 dynamic preset と generated typing のどちらを正規入口にするか

各段階とも、互換 wrapper/deprecated alias を追加して移行期間を設けるのではなく、
repository 内の consumer、test、docs、example を同じ変更で一括更新する。

## 9. 最終評価

- **明白な不要シムは複数存在する。**
- とくに「受け取って捨てる引数」「空 subclass alias」「旧 positional constructor test」
  「test double の欠落属性を production が推測する分岐」は、現在の repository 方針では
  残す根拠がない。
- より大きな問題は、旧/新の二つの表現を runtime state と永続化の両方に保持している点である。
  `RuntimeLimits`、capture manifest、effect topology、GroupBlock、video publish は、
  正規モデルを一つ決めれば分岐・test・文書をまとめて削減できる。
- 一方、保存済み ParamStore、公開 preset UX、実 backend version 差は product decision を含む。
  これらを「後方互換だから全部削除」と機械的に処理せず、runtime shim を残さない移行方法を
  選ぶのが妥当である。
