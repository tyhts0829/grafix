# 後方互換・互換シム・実装美観の解消計画（2026-07-20）

作成日: 2026-07-20
基準 HEAD: `e2c7f53`
基準作業ツリー: clean
ステータス: **実装・全体検証済み（既知の full Ruff 違反のみ）**

## 1. 目的

`docs/review/backward_compatibility_shim_audit_2026-07-20.md` で確認した
A-01〜A-08、B-01〜B-08、C-01〜C-07 を、互換 wrapper、deprecated alias、
一時的 shim を追加せずに解消する。

単にコメントから `legacy` の語を消すのではなく、次を完了条件とする。

- 旧/新の二つの入力、状態、schema、publish 経路を一つの正規形へ統一する。
- test の不完全初期化を支える production fallback を、正しい fixture へ移したうえで削除する。
- 対応 dependency/version を明示し、version 差は UI ロジックでなく一つの境界へ閉じる。
- 使わない引数、alias、転送 import、未使用 field、推論 adapter を削除する。
- 数値処理は characterization test と benchmark を先に取り、共通化後の契約を明示する。
- 破壊的変更は repository 内の call site、test、stub、docs、example を同じ変更で更新する。

## 2. 実装方針として先に固定する決定

本計画の承認は、次の破壊的変更への承認も兼ねる。

### 2.1 互換層

- 互換 wrapper、旧名 alias、deprecated 期間は設けない。
- repository 内を一括更新し、旧 constructor、旧 keyword、旧 import 名は削除する。
- private/internal API も「test が直接使っている」ことを互換維持の理由にしない。

### 2.2 ParamStore

- runtime が受理するのは新しい現行 schema だけとする。
- versionless、v1、現行変更前の v2 は移行せず拒否する。
- one-shot migration tool も今回追加しない。
- unsupported schema は原本を quarantine/上書きせず、明示エラーで停止する。
- effect topology の正規化を含む変更後に schema version を一度だけ上げる。

### 2.3 runtime limit

- headless/core の正規入力は `RuntimeLimits`。
- interactive の正規入力は `RuntimeLimitProfiles`。
- `max_cache_bytes`、`max_cache_entries`、`resource_budget` の旧上位引数と、
  旧値から新 profile を作る helper は削除する。
- `ResourceBudget` 型自体は `RuntimeLimits` の構成要素として維持する。

### 2.4 capture/export/video

- export と video encode は常に staging へ出力する。
- final path への publish、no-clobber、manifest、rollback の所有者は
  capture transaction だけとする。
- capture manifest は新 schema の canonical section だけを出力し、provenance を必須にする。
- 出力形式は同期 `CaptureService` と非同期 `ExportJobSystem` の双方で
  `ExportFormat` 一形とし、実行方式を形式 enum に混ぜない。
- layer 別 G-code は `ExportFormat.GCODE` と `split_gcode_layers: bool` で表し、
  G-code 設定は core の `GCodeParams` 一形とする。
- 描画設定は core の `RenderOptions` を正本とし、preview 倍率の `render_scale` は
  別の実行時引数として保持する。

### 2.5 effect chain

- `FrameEffectChainRecord` と完全 topology を唯一の chain 入力にする。
- step index は topology と order override から導出する。
- parameter record 単独から legacy chain を再構成しない。

### 2.6 preset

- identity の正規構文は既存の B 形式
  `P(name=..., key=..., instance_key=..., shared=...).foo(...)` とする。
- `P.foo(..., name=..., key=...)` は受理しない。
- `name/key/instance_key/shared/activate` は preset wrapper 所有の予約名とし、
  元 preset 関数の signature ではすべて禁止する。
- identity は通常 kwargs へ再注入せず、registry の内部 invocation channel で渡す。
- semantic key は文字列を `str:{len}:{value}`、整数を `int:{value}` として符号化し、
  instance key は `|instance:` suffix に同じ token を付ける。旧 site ID は自動移行しない。

### 2.7 GUI dependency

- 対応範囲を `imgui>=2,<3`、`pyglet>=2.1,<3` とする。
- pyglet 2.x の programmable renderer を正規経路にし、
  deprecated `PygletRenderer` と旧 API fallback を削除する。
- metadata 上の version 制約変更だけを行い、依存 download/install は行わない。
  現在の検証環境 `imgui 2.0.0 / pyglet 2.1.11` は条件を満たしている。

### 2.8 typing

- `pyproject.toml` を唯一の mypy 設定源にする。
- ignored/untracked のローカル `mypy.ini` は削除する。
- `ignore_missing_imports=true` と全面 `__getattr__ -> Any` を削除する。
- project-local preset を型検査する正規手順は generated stub とする。

### 2.9 text dependency

- deprecated `fontTools.misc.py23` を読む `fontPens` 依存を削除する。
- fontTools の pen protocol 上に必要最小の曲線平坦化 helper を実装する。
- global warning filter を別の場所へ移すだけの対応はしない。

## 3. 非目標・維持する境界

- `workspace_state` の old/future schema fallback と診断は維持する。
- optional MIDI、未接続 device、OS clipboard、Retina、screen clamp は維持する。
- constructor 失敗中の cleanup 用 partial-state 検査は、test-only fallback と区別して維持する。
- user-defined operation/preset の runtime registry dispatch は維持する。
- `grafix.api.run()` の lazy import と root/API façade は今回変更しない。
- effect の公開数学、RNG consumption、packed geometry の決定性は、
  共通化対象でない限り変更しない。
- 新機能、GUI の見た目変更、commit、push、release は行わない。

## 4. 実施原則

- [x] 作業開始時に `git status --porcelain` が空であることを確認した。
- [x] 基準 HEAD `e2c7f53` と監査レポートの tracked 状態を確認した。
- [x] ユーザーの計画承認を得る。
- [x] 実装開始前の correctness/stub/performance baseline を採る。
- [x] 独立した Phase は並行化し、依存する Phase と同一ファイル群は順序付けて実施した。
- [x] 同じファイル群を複数担当が同時編集しないよう対象を分離した。
- [x] 各 Phase で focused test を通し、全体検証前にも追加の横断 test を行った。
- [x] 想定外の既存 failure は今回の差分と混ぜず、本ファイルへ記録した。
- [x] 互換層を戻さず、repository 内 call site を正規形へ一括更新した。

## 5. Phase 0 — baseline と破壊範囲の固定

### 5.1 correctness baseline

- [x] full pytest の基準結果を保存する。
- [x] `ruff check .` の基準結果を保存する。
- [x] 現在の mypy 実行 config と結果を記録する。
- [x] `src/grafix/api/__init__.pyi` を `/tmp` へ保存する。
- [x] capture manifest、ParamStore、effect order、text glyph の代表出力を fixture/checksum で固定する。
- [x] export/video の fault-injection test が基準 HEAD で通ることを確認する。

### 5.2 performance baseline

benchmark harness を B-08 で変更する前に、repository 外の `/tmp` へ次を保存する。

- [x] effects/pipeline/system short baseline
- [x] interactive/gui/mp short baseline
- [x] parameter hot-path baseline
- [x] buffer/partition/text の対象 benchmark/checksum

long suite は必須にせず、short で退行が疑われる場合だけ実行する。

実施記録:

- full pytest: `2234 passed, 1 skipped`。
- mypy: `229 source files`、error なし。
- ruff: 基準時点で既知 33 errors。主に既存 sketch の未使用 import と
  `.agents` 内の `E741` であり、今回差分との合否を分離する。
- core short benchmark: 57/57 case を保存。
- interactive/gui/mp short benchmark: 15 case 中 13 case 成功。
  `mp.draw.light` と `mp.draw.slider_churn` は既存の
  `BenchmarkSchemaError: non-empty distribution requires all statistics`。
  B-08 の typed metric 移行対象として記録し、他 Phase の退行とは扱わない。
- baseline:
  `/tmp/grafix-shim-resolution-benchmark/runs/shim-resolution-base-core.json`、
  `/tmp/grafix-shim-resolution-benchmark/runs/shim-resolution-base-interactive.json`。
- 基準 stub と基準 HEAD の展開:
  `/tmp/grafix-shim-resolution-baseline/api__init__.pyi`、
  `/tmp/grafix-shim-resolution-baseline/`。
- 基準 HEAD の export/video fault-injection focused test: 67 件成功。
- parameter hot-path short baseline: 12/12 case 成功。
  `/tmp/grafix-shim-resolution-benchmark/runs/shim-resolution-base-parameters.json`。

### 5.3 完了条件

- [x] 既知 failure と今回の合否判定を分離できる。
- [x] performance-sensitive な C-01 を比較できる baseline がある。
- [x] schema/output の意図的破壊点が test 名で明確になっている。

## 6. Phase 1 — 局所的な dead shim と転送の削除

対象: A-01、C-02 の一部、C-04

### 6.1 `ParamStoreMemento`

- [x] `explicit_by_key`、`labels`、`ordinals` constructor 引数を削除する。
- [x] `_ = explicit_by_key, labels, ordinals` を削除する。
- [x] `capture_param_store_memento()` を実際に保存する値だけ渡す形へ更新する。
- [x] 旧 constructor shape の test を削除し、復元結果の test へ置き換える。

### 6.2 private selector 転送

- [x] `api/_operation_selector.py` の未使用 core import 7 件を削除する。
- [x] 対応する `__all__` entry を削除する。
- [x] consumer は core の正規 module を直接 import していることを確認する。

### 6.3 旧 namespace/provenance fallback

- [x] primitive registry の `core.primitives.*` 判定を削除する。
- [x] effect registry の `core.effects.*` 判定を削除する。
- [x] stub generator の旧 module 命名推測 fallback を削除する。
- [x] provenance 解決失敗を broad catch で隠さず、明示的な invalid spec として扱う。

### 6.4 focused validation

- [x] `tests/core/parameters/test_memento.py`
- [x] `tests/core/parameters/test_history.py`
- [x] `tests/core/parameters/test_semantic_meta.py`
- [x] operation selector GUI tests
- [x] primitive/effect registry tests
- [x] stub generator tests
- [x] 変更対象の Ruff 差分確認（新規違反なし）

実施記録: focused test は 131 件成功。変更対象に新規 Ruff 違反はなく、
`git diff --check` も成功。

## 7. Phase 2 — alias、DTO、`ParamStoreRuntime` の正規化

対象: A-03、A-04、A-05

### 7.1 clock/session alias

- [x] production/test を `TransportClock` へ一括更新する。
- [x] `RealTimeClock` class を削除する。
- [x] `SceneRunner._realize_session` を削除する。
- [x] test は canonical quality session または観測可能な挙動を検証する。

### 7.2 internal DTO

- [x] `TransportSnapshot` を keyword-only にする。
- [x] `DrawResult` を keyword-only にする。
- [x] worker が生成する現行 metadata を明示指定する。
- [x] `ExportJobResult` を keyword-only にする。
- [x] field 順互換コメントと旧 positional constructor test を削除する。
- [x] genuine optional result field だけに `None`/空 tuple default を残す。

### 7.3 `ParamStoreRuntime`

- [x] dataclass を `slots=True, kw_only=True` にする。
- [x] `loaded_groups` / `observed_groups` を常に `_TrackedGroupSet` へ正規化して bind する。
- [x] plain `set` identity を維持する経路を削除する。
- [x] `visibility_cache_token()` を常に `tuple[int]` にする。
- [x] positional/plain-set 互換 test を canonical state/revision test へ更新する。

### 7.4 focused validation

- [x] frame clock tests
- [x] mp draw tests
- [x] operation diagnostic/profiler tests
- [x] export result tests
- [x] parameter runtime/revision/reconcile/GUI cache tests

実施記録: Phase 2 focused test は 100 件、parameter 関連追加検証は 67 件成功。
変更対象に新規 Ruff 違反はなく、`git diff --check` も成功。

## 8. Phase 3 — export/video を staging 契約へ統一

対象: A-02、B-04

### 8.1 export job

- [x] `ExportJob.svg_output_path` を削除する。
- [x] `ExportJobSystem.submit(svg_output_path=...)` を削除する。
- [x] accepted job ごとに staging directory を必ず作る。
- [x] `staging_dir` を required invariant にする。
- [x] `_job_work_output_path()`、commit、cleanup の `None` 分岐を削除する。
- [x] default/custom backend の publish 契約を一つにする。
- [x] backend は staging 内の path だけを返し、親 process だけが final publish する。
- [x] private direct-call semantics の test を pure encode/staging test へ置き換える。

### 8.2 video

- [x] `VideoRecorder.no_clobber` を削除する。
- [x] direct-publish `VideoRecorder.close()` を削除する。
- [x] 完成・fsync 済み staging path を返す `finish()` 一つにする。
- [x] `VideoRecordingSystem.stop()` を `StagedVideoCapture | None` 一契約にする。
- [x] `stop_to_staging()` との二重 API を削除する。
- [x] publish/no-clobber/manifest/rollback を DrawWindow/capture transaction へ集約する。
- [x] direct publish 専用 error/helper を削除する。

### 8.3 failure-path validation

- [x] success
- [x] encoder error
- [x] timeout
- [x] cancel
- [x] worker death/restart
- [x] queue teardown
- [x] parent commit failure
- [x] final-path collision
- [x] staging ownership transfer
- [x] shutdown/abort 時の temp 漏れなし
- [x] spawn pickle

実施記録: export/video/recording/capture-safety の focused test 63 件と
DrawWindow の transaction test 48 件、計 111 件が成功。変更対象に新規 Ruff 違反はなく、
`git diff --check` も成功。追加で録画出力先を `start(output_path=...)` の必須入力へ
統一し、constructor の既定出力先と `finish() -> Path | None` の二重状態も削除した。
video/recording/DrawWindow focused test 73 件、変更対象の Ruff 差分確認、対象 mypy が成功。

## 9. Phase 4 — runtime limit API を一つにする

対象: A-06、C-02 の cache alias

### 9.1 core/headless

- [x] `RealizeSession` の入力を `RuntimeLimits` と profiler だけにする。
- [x] `max_cache_bytes`、`max_cache_entries`、`resource_budget` 引数を削除する。
- [x] `DEFAULT_MAX_CACHE_BYTES/ENTRIES` alias を削除する。
- [x] `RenderSession` と `render()` を `RuntimeLimits` 入力へ統一する。

### 9.2 interactive

- [x] `run()` から `resource_budget` を削除する。
- [x] `SceneRunner` と `DrawWindowSystem` を `RuntimeLimitProfiles` 入力へ統一する。
- [x] `profiles_for_resource_budget()` を削除する。
- [x] preview/final の既定 profile を canonical constant から渡す。

### 9.3 consumer/stub/docs

- [x] benchmark と test の旧 scalar 引数を `RuntimeLimits(...)` construction へ更新する。
- [x] 公開 stub を再生成する。
- [x] README/API docstring/example を新 signature へ更新する。
- [x] 旧定数/旧 helper の import が repository に残っていないことを検索で確認する。

### 9.4 focused validation

- [x] realize/cache/resource-budget tests
- [x] render session/API tests
- [x] runner/runtime-limit tests
- [x] draw-window/export/cache tests
- [x] stub generation/sync tests

実施記録: core 59 件、render/runtime 109 件、runner/renderer 37 件、
benchmark 17 件、stub 13 件が成功。旧 API 名の残存は 0 件。

## 10. Phase 5 — ParamStore schema/parser と effect topology

対象: B-01、B-02

同じ codec/schema を二度変更しないため、一つの Phase で直列実施する。

### 10.1 strict current-schema parser

- [x] `PARAM_STORE_SCHEMA_VERSION` を新 version へ上げる。
- [x] versionless/旧/future を direction に関係なく unsupported として明示拒否する。
- [x] unsupported file を上書き/quarantine しない。
- [x] `_migrate_param_store_payload()` を削除する。
- [x] `migrated_legacy` と legacy migration diagnostic を削除する。
- [x] section ごとに canonical value と issue を同時生成する typed intermediate を作る。
- [x] `_find_decode_issues()` と decode の二重走査を一つにする。
- [x] partial-invalid entry の salvage/quarantine は一回の parse 結果から行う。
- [x] explicit metadata は新規 key 作成時に必ず初期化し、`prev_explicit is None` の旧 JSON 分岐を削除する。

### 10.2 topology-only effect chain

- [x] `_legacy_step_by_site` を削除する。
- [x] `record_step()` の legacy chain 作成を削除する。
- [x] `_topology_by_chain` を唯一の source of truth にする。
- [x] `_step_by_site` は topology/order から作る導出 cache に限定する。
- [x] prune/delete/generation/rebuild の dual-map 分岐を削除する。
- [x] codec は完全 topology 由来の `effect_steps` だけを保存する。
- [x] load 時に contiguous index、unique identity、`n_inputs` を検証する。
- [x] `FrameParamRecord` から `chain_id/step_index` を削除する。
- [x] API/selector/resolver は `FrameEffectChainRecord` を先に merge する。
- [x] parameter grouping は canonical topology から step 情報を読む。

### 10.3 test policy change

- [x] versionless/v1/v2 migration testを「unsupported・原本不変更」testへ置き換える。
- [x] topology のない legacy `effect_steps` testを削除する。
- [x] recovery/future/partial-corruption safety を新 strict parser で維持する。
- [x] effect order、memento、variation、reconcile、collapsed-header、mp transfer を検証する。

実施記録: ParamStore schema を v3 の一形へ統一し、versionless/v1/v2/future は
原本を変更せず拒否する strict typed parser に置換した。effect chain は完全 topology
だけを正本とし、parameter record 由来の legacy step 経路を削除した。core parameters
269 件、persistence/effect/memento/variation/reconcile/collapsed-header/mp の focused
157 件が成功した。変更対象に新規 Ruff 違反はなく、対象限定 mypy/diff-check も成功。
full suite は 2218 passed、
1 skipped まで確認し、並行作業中の Phase 1/2/10 に属する 25 failure は Phase 5
対象外であることを切り分けた。

## 11. Phase 6 — capture manifest と PNG scale の明示化

対象: A-08、C-03

### 11.1 capture manifest

- [x] capture manifest schema version を上げる。
- [x] `CaptureManifest.provenance` を required にする。
- [x] `unavailable_capture_provenance()` を削除する。
- [x] v1 top-level `t/canvas_size/format/artifact_paths` を削除する。
- [x] canonical `output` section だけを出力する。
- [x] variation batch の artifact path 更新を一箇所にする。
- [x] production capture/video call site は実 provenance を必ず渡す。

### 11.2 PNG scale

- [x] `png_output_size(..., scale: float)` を必須にする。
- [x] helper 内の `runtime_config()` 読み込みを削除する。
- [x] `default_png_output_path()` に effective scale を明示注入する。
- [x] headless、interactive、devtool は session/config 境界で一度解決した scale を渡す。

### 11.3 focused validation

- [x] capture manifest/provenance tests
- [x] capture service/variation batch tests
- [x] PNG/image export tests
- [x] DrawWindow capture/video tests
- [x] manifest JSON が新 schema 一形だけであること

実施記録: capture/export/variation/image の focused test と
DrawWindow capture/video 47 件が成功。manifest は schema v3 の一形へ統一した。

## 12. Phase 7 — Parameter GUI block と snippet を一つにする

対象: B-03、C-05

### 12.1 model

- [x] `GroupBlockLayout` / `GroupBlockLayoutItem` を唯一の block model にする。
- [x] `GroupBlock` / `GroupBlockItem` を削除する。
- [x] `group_blocks_from_layout()` / `group_blocks_from_rows()` を削除する。
- [x] table の Code button で旧 block を再構築しない。
- [x] snippet は layout と indexed model rows を受け取る。
- [x] benchmark も canonical layout を直接計測する。

### 12.2 snippet

- [x] 未使用 `layer_style_name_by_site_id` を削除する。
- [x] 旧 block 専用 helper を削除する。
- [x] group type を enum/exhaustive branch として扱う。
- [x] 未知 group type の dict fallback を削除し、invariant error にする。
- [x] effect order/selector/explicit key の code generation を新 model で維持する。

### 12.3 focused validation

- [x] group layout/filter tests
- [x] snippet tests
- [x] collapsed-header key tests
- [x] operation-selector/effect-order GUI tests
- [x] parameter hot-path benchmark checksum

実施記録: Parameter GUI/benchmark focused test は 292 件成功。変更対象に新規 Ruff
違反はなく、focused mypy、`git diff --check` も成功。

## 13. Phase 8 — preset invocation と generated stub の正規化

対象: B-06、C-06 の preset 部分

### 13.1 registry/invocation

- [x] preset registry entry に identity-aware internal invoker を持たせる。
- [x] `PresetNamespace.__getattr__` は pending identity を別 channel で invoker へ渡す。
- [x] decorated preset の通常 kwargs へ identity を再注入しない。
- [x] 元関数 signature の全予約名を登録時に拒否する。
- [x] `P.foo(..., name=...)` を unknown argument として拒否する。
- [x] `P(name=...).foo(...)` だけを identity 付き正規構文にする。
- [x] pending 値と直接 kwargs の優先順位分岐を削除する。

### 13.2 docs/snippet/stub

- [x] snippet は B 形式だけを生成する。
- [x] README、resource example、sketch、test を B 形式へ更新する。
- [x] stub generator は project-local preset を列挙する。
- [x] generated `_P.__getattr__` fallback を削除する。
- [x] 未生成/typo preset が mypy error になる test を追加する。

### 13.3 focused validation

- [x] component/preset namespace/explicit-site-key tests
- [x] preset registry/source reload tests
- [x] snippet tests
- [x] project-local preset stub generation/sync tests

実施記録: preset core/API/source reload 35 件、snippet/GUI 35 件、
stub 13 件と project-local typo の mypy error 検証が成功。

## 14. Phase 9 — test fixture 正規化と production fallback 除去

対象: A-07、B-07

Phase 3、4、8 で canonical interface が確定してから行う。

### 14.1 faithful test fixtures

- [x] `DrawWindowSystem.__init__` を通す fixture/factory を作る。
- [x] FakeWindow/Renderer/SceneRunner/ExportJobs/Recording は現行必須 interface を完全実装する。
- [x] `object.__new__(DrawWindowSystem)` 32 箇所を全廃する。
- [x] `ParameterGUI` の constructor bypass 15 箇所を初期化済み fixture へ移す。
- [x] `object.__new__(MpDraw)` 6 箇所を全廃する。
- [x] `ParameterGUIWindowSystem` の constructor bypass 4 箇所を実 constructor fixture へ移す。
- [x] MpDraw reducer は constructor 済み fixture で検証できるため、production state object は追加しない。
- [x] snapshot retained-byte test は本物の `RealizedGeometry/RealizedLayer` builder を使う。

### 14.2 production fallback

- [x] constructor が必ず作る属性への `getattr(..., default)` を直接参照へ変える。
- [x] provenance builder 欠落 fallback を削除する。
- [x] old SceneRunner の time/output/revision 推測を削除する。
- [x] concrete DrawWindow callback の optional 化を削除する。
- [x] old window requested-size/location/visible fallback を削除する。
- [x] old ExportJobs/MpDraw interface fallback を削除する。
- [x] optional MIDI/monitor/source reload と cleanup partial-state は維持する。
- [x] 削除/維持した capability branch の一覧を本計画へ記録する。
- [x] `ParameterGUI` / `MpDraw` の通常経路から constructor 属性の既定値 fallback を削除する。
- [x] `ParameterGUIWindowSystem` の store/callback 属性を直接参照へ統一する。
- [x] monitor 表示入力を `MonitorSnapshot` 一形にし、duck-typed field default を削除する。
- [x] ImGui keyboard capture の例外 fallback と MIDI cell の未使用互換返値/引数を削除する。
- [x] display order 欠落を reconcile orphan の現行契約として明記し、chain 内の到達不能 fallback を削除する。

### 14.3 renderer metadata

- [x] renderer の `scene_serial` と `snapshot_revision` を required `int` にする。
- [x] `_MeshAdmission` を non-optional にする。
- [x] metadata 両方なしの standalone mode を削除する。
- [x] 初回 mp 待機/empty scene では renderer を呼ばない invariant を明示する。
- [x] stale result 再表示、fresh scene、parameter revision の cache admission を検証する。

### 14.4 validation

- [x] runner window-layout tests
- [x] ParameterGUI tests
- [x] interactive runtime tests
- [x] draw renderer cache tests
- [x] `object.__new__` 対象 3 class の残存 0 件
- [x] test-only/old implementation コメントの残存確認

実施記録: `ParameterGUI.__init__` を通す共通 headless fixture と、
worker 起動だけを抑止して `MpDraw.__init__` を通す fixture へ移行した。
ParameterGUI 全 test、window layout、MpDraw の計 341 件が成功した。変更対象に新規
Ruff 違反はなく、対象 mypy、`git diff --check` も成功し、両 class の
constructor bypass は 0 件。
追加監査では `ParameterGUIWindowSystem` も実 constructor fixture へ移し、
`ParameterGUI` / monitor / system の 305 件と MpDraw 49 件が成功した。
通常経路の残存 scan は `ParameterGUI` が constructor 失敗 cleanup の 5 箇所、
`MpDraw` が cleanup の 2 箇所だけであり、いずれも 3. の維持対象である。
先行の複合実行で報告された `resource_tracker` warning 12 件は
hung-worker restart test に限定され、fixture が worker を起動したものではない。

残る DrawWindowSystem 側も、外部 GL/window/process 構築だけを差し替えて
`DrawWindowSystem.__init__` を必ず通る共通 factory へ移し、32 箇所の
constructor bypass を全廃した。fake は window、renderer、SceneRunner、
ExportJobs、recording の現行必須 interface を実装し、retained-byte test は実物の
`RealizedGeometry` / `RealizedLayer` と同一配列 identity の dedupe を検証する。
capture 境界は preview 用 `FrameExportSnapshot` と provenance 必須の
`CaptureExportSnapshot` を分離し、暗黙昇格を行わない。G-code job は
snapshot の `gcode_params: GCodeParams` 必須、PNG job は `output_size` 必須かつ
他形式では指定禁止とし、
いずれも worker 起動前に拒否する。export/renderer の resource limit は正規
`RuntimeLimits` 一形にし、DrawWindowSystem の effective config も呼出側が
必須 `RuntimeConfig` として一度だけ渡す契約へ統一した。描画設定は core の
`RenderOptions` 一形へ統一し、interactive 側の旧設定 class を削除して
`render_scale` を別引数にした。同期 `CaptureService` と非同期 `ExportJobSystem` は
形式軸に同じ `ExportFormat` だけを受け取り、layer 別 G-code は
`split_gcode_layers: bool` で表す。文字列から enum への暗黙変換は行わない。
final capture は public `final_capture_frame()` 一入口に統一した。

削除した capability branch は、constructor 属性の既定値、provenance builder 欠落、
SceneRunner の時刻/output/revision 推測、DrawWindow callback の optional 呼出し、
window の旧 size/location/visible 属性、ExportJobs/MpDraw/renderer の旧 interface、
renderer metadata 欠落時の standalone mode、ambient runtime config への暗黙 fallback
である。維持した分岐は capability
推測ではなく、値として optional な MIDI、monitor、source reload、diagnostic center、
recording state、constructor 失敗時に取得済み resource だけを解放する cleanup、
非 Cocoa screen で private adapter が存在しない場合に full screen bounds を使う
platform 境界、および invalid runtime config を利用者へ提示して既定設定へ戻す
明示的 recovery policy である。

renderer は `scene_serial` / `snapshot_revision` を必須 `int`、
`_MeshAdmission` と candidate 値を non-optional にし、初回 MP 結果待ちでは
layer render と snapshot 更新を行わない test を追加した。stale result 再表示、
fresh scene、parameter revision の cache admission は実 constructor fixture で検証した。
DrawWindow/export/provenance の focused 94 件、renderer cache 23 件、
runner/runtime focused 157 件、および source reload を含む Phase 9 runtime 複合
348 件が成功した。effective config 必須化後の関連 89 件も成功した。
`ExportFormat` 境界と final capture 一入口化後の focused 113 件も成功した。
変更対象に新規 Ruff 違反はなく、9 source file の mypy、`git diff --check`、
constructor bypass と
旧実装コメントの残存 scan も成功した。

## 15. Phase 10 — GUI backend と typing 境界

対象: B-05、C-06、C-07 の GUI/manual 部分

### 15.1 dependency/backend

- [x] `pyproject.toml` に `imgui>=2,<3`、`pyglet>=2.1,<3` を記載する。
- [x] programmable pyglet renderer を直接構築する一経路にする。
- [x] deprecated `PygletRenderer` fallback を削除する。
- [x] content-width helper を一実装にする。
- [x] `same_line`、button、tree/table API の旧 arity retry を削除する。
- [x] optional table flag/return-shape fallback を削除する。
- [x] GUI logic は canonical imgui API を直接使う。
- [x] fake imgui は canonical signature/return type を実装する。
- [x] devtool/manual harness は production backend helper を再利用する。

### 15.2 typing/config

- [x] `pyproject.toml` に `mypy_path = "typings"` を統合する。
- [x] global `ignore_missing_imports` を削除する。
- [x] ignored/untracked `mypy.ini` を削除する。
- [x] imgui stub の全面 `__getattr__ -> Any` を削除する。
- [x] 実利用 API だけの具体 stub/Protocol を定義する。
- [x] dependency ごとの未型付け箇所は限定 override にする。
- [x] generated preset stub と runtime API の同期を fresh CLI subprocess で検証する。

### 15.3 validation

- [x] responsive table/choice/toolbar/layout tests
- [x] backend factory test
- [x] manual harness import/smoke
- [x] full mypy
- [x] project-local generated stub を使う mypy test
- [x] 実 GUI smoke は自動検証後に別途 GUI 実行承認を得て行う。

実施記録: Parameter GUI 全 284 件、変更対象に新規 Ruff 違反なし、manual harness import smoke、
GUI/devtool 限定 mypy、project-local generated stub の mypy 検証が成功。
全 Phase 完了後の full mypy も 238 source files で成功した。実 GUI smoke は macOS の
GL context で `imgui 2.0.0 / pyglet 2.1.11` の demo window を1フレーム描画し、
renderer/context/window の終了まで成功した。

## 16. Phase 11 — effect 共通処理と text dependency

対象: C-01、C-07 の warning 根本原因

### 16.1 完全一致 helper

- [x] `_as_float_cycle` を共通 helper にする。
- [x] `_reflect_index` を共通 helper にする。
- [x] `_round_half_away_from_zero` を共通 helper にする。
- [x] 元 module の重複実装を削除する。
- [x] fill scanline kernel の未使用 `ex2` 引数を production/test から削除する。

### 16.2 planar frame

- [x] buffer/partition の XY、XZ、oblique、winding、seam、near-planar、
  non-planar、linear input oracle test を先に追加する。
- [x] `_PlaneBasis`、fit/project/lift の二実装を削除する。
- [x] `PlanarFrame` / `canonical_planar_frame()` を正規基盤にする。
- [x] buffer の linear input と partition の planarity tolerance を明示 policy にする。
- [x] 旧 XY 実装模倣の fallback は追加しない。
- [x] 新 canonical frame の出力を新契約として test/docstring に固定する。
- [x] buffer の close、fill/weave の planarity threshold も共通 helper へ統一する。

### 16.3 SDF kernel

- [x] growth/warp の共通部分と effect 固有 optimization policy を分離できるか測定する。
- [x] flag だらけの一般化をせずに純減できる場合は共通 kernel にする。
- [x] 共通化が複雑化する場合は、差異を明示した固有名・契約へ整理し、
  「偶然重複した legacy 実装」ではないことを記録する。

### 16.4 text flattening

- [x] 現在の glyph command/polyline checksum を representative font/文字で固定する。
- [x] fontTools pen protocol 上に必要最小の adaptive curve flatten helper を実装する。
- [x] `fontPens.flattenPen.FlattenPen` import を削除する。
- [x] `fontPens` dependency を `pyproject.toml` から削除する。
- [x] global `fontTools.misc.py23` warning filter を削除する。
- [x] ASCII、日本語、compound glyph、missing glyph、curve/line、cache を検証する。

### 16.5 performance validation

- [x] Phase 0 と同じ short benchmark/checksum を、benchmark harness 変更前に比較する。
- [x] 新しい不要 copy、dtype/layout drift、系統的性能退行がないことを確認する。
- [x] 退行時に旧互換分岐を戻さず、canonical implementation 自体を改善する。

実施記録:

- planar oracle を実装前に追加し、旧実装で linear/spatial の 2 件が新契約と異なる
  ことを確認してから、buffer/partition の独自 `_PlaneBasis` と fit/project/lift を削除した。
  `PlanarFrame.project()/lift()` を含む canonical frame へ統一し、axis-aligned の高速化も
  XY 専用 fallback ではなく X/Y/Z 共通の canonical 規則として実装した。
- growth と warp の同名 SDF kernel は、一 ring でも fastmath により最大
  `1.3e-14` の差があり bit 一致しなかった。離れた 8 ring では growth の bbox skip が
  `1.27 ms`、warp の基準 kernel が `9.06 ms` だったため、flag 付き共通 kernel にはせず
  `_evaluate_growth_sdf_points_numba` と `_evaluate_warp_sdf_points_numba` に改名し、
  fastmath/bbox skip と warp lens の bit-exact 基準という固有契約を docstring に固定した。
- text は Google Sans の ASCII/compound と Noto Sans JP の日本語について geometry と
  command checksum を先に固定した。fontTools pen protocol 上の弧長適応 flatten helper
  へ置換後も checksum、頂点数、line 数が完全一致し、`fontPens` と warning filter を
  tracked source/config から削除した。ASCII、日本語、compound/missing glyph、
  line/quadratic/cubic、bounded cache を検証した。
- effects 全体と text/font focused suite は 508 件成功。追加の最終 focused 59 件と
  text/growth/warp/weave 80 件が成功した。変更対象に新規 Ruff 違反はなく、
  対象 mypy、`git diff --check` も成功した。
  fill scanline の dead arg 削除後も focused 20 件、変更対象の Ruff 差分確認、
  対象 mypy が成功した。
- Phase 12 の benchmark harness 更新が並行して先に入ったため、実行順は計画から逸脱した。
  旧 baseline JSON と baseline checkout を正本に、case ID ごとの primary timing/checksum
  を手動比較し、typed metric serialization/compatibility key の差は性能差から除外した。
  現行 core short は 57 件中 54 件成功し、Phase 11 対象 effect は全成功。残る 3 件は
  Phase 12 の `typed metrics changed across warm samples` で、同 Phase 担当へ分離した。
  その後、workload 内部で timing/cache lifecycle を自己サンプルする 3 case
  (`micro.asemic`、`system.cold_import`、`system.parameter_snapshot_model`) だけを
  `self_sampling=True` とし、外側反復を重ねない正規契約へ修正した。
- 同時再計測では buffer benchmark が `2.147 -> 1.788 ms`、partition が
  `5.697 -> 6.048 ms`。buffer checksum は一致し、partition checksum の変更は
  canonical frame の意図的な新契約で、頂点/line 数は維持した。direct oblique buffer
  では正規の平面推定に `0.14 -> 0.29 ms` を要するが、不要な Nx3 中間 copy を除去し、
  short suite 全体に系統的退行がないことを確認した。
- text direct 計測は ASCII/compound が cold `36.5 -> 34.3 ms`、warm
  `0.115 -> 0.098 ms`、日本語が cold `62.4 -> 58.1 ms`、warm
  `0.135 -> 0.122 ms` で、全 checksum は一致した。

## 17. Phase 12 — benchmark schema と低優先度重複

対象: B-08、C-07 の残部

### 17.1 benchmark output / typed metric

- [x] workload の返却型を `schema.BenchmarkOutput` 一形にする。
- [x] 全 workload を明示 `Metric` producer へ更新する。
- [x] nested mapping の recursive normalization を削除する。
- [x] unit/phase/scope/name を各 producer が明示する。
- [x] `_distribution_from_summary`、推論 helper、legacy mapping test を削除する。
- [x] 重複 result DTO 7 型と runner の即時再包装を削除する。
- [x] JSON の vec3 配列は setup 境界で tuple へ一度だけ正規化する。
- [x] 現行の安定出力へ checksum contract を同期する。
- [x] metric name 重複を拒否する。
- [x] schema roundtrip と全 suite の smoke を行う。

### 17.2 example/manual

- [x] numbered example を正本とし、重複する `sketch/readme/readme.py` を削除する。
- [x] `sketch/readme/1.py` の run 設定を唯一の例として維持する。
- [x] `top_movie.py` 等の重複/未使用 import を対象限定で整理する。
- [x] manual renderer entry は Phase 10 の production helper へ統一する。

実施記録: 最終形の benchmark test 145 件と schema roundtrip/smoke が成功。
example 2 件の import smoke、変更対象の Ruff 差分確認、mypy、`git diff --check` も成功。
追加検証では上記 3 case を warm `samples=3` 指定で isolated 実行し、
いずれも実 sample 1 件、status `ok`、error なしとなった。renderer metadata
必須化の反映後は benchmark runner 19 test と fresh-cache mypy も成功した。

## 18. Phase 13 — 全体検証と文書更新

### 18.1 static/correctness

- [x] 全 focused test 成功
- [x] full `PYTHONPATH=src pytest -q` 成功
- [ ] `ruff check .` 成功
- [x] `mypy src/grafix` 成功
- [x] fresh CLI subprocess による project-local stub generation/sync 成功
- [x] `git diff --check` 成功
- [x] tracked/untracked 差分が本計画の対象だけであること

### 18.2 behavior

- [x] headless render/export 成功
- [x] ParamStore current schema save/load/recovery 成功
- [x] old ParamStore が原本を変更せず明示拒否される
- [x] capture/video の staging publish、collision、rollback 成功
- [x] effect order の preview/final/mp/persistence 成功
- [x] GUI table/snippet/preset identity 成功
- [x] renderer cache admission 成功
- [x] text glyph output 成功

### 18.3 performance

- [x] Phase 11 までの short benchmark 比較を記録する。
- [x] typed metric 移行後の全 benchmark suite smoke が成功する。
- [x] checksum/hard contract の意図しない変更がない。

### 18.4 docs

- [x] README と API docstring を新しい破壊的契約へ更新する。
- [x] migration note に削除した旧 API/schema を列挙する。
- [x] 監査レポートの各 ID に「解消済み」または意図的契約の最終判定を追記する。
- [x] 本計画の checkbox と実施記録を最終状態へ更新する。
- [x] full Ruff の既知違反と checkbox を完了扱いにしない理由を明記する。

### 18.5 追跡監査で確認した実装

- [x] `ExportFormat`、`RenderOptions`、`ExportResult`、`GCodeParams` の正本を core に一つずつ置く。
- [x] site identity を型付き長さ prefix で衝突なく符号化し、旧 ID の読替えを置かない。
- [x] clock、runtime config、MP message、capture/export、variation batch、video、
  GUI model、source reload の入力を明示検証し、performance/benchmark の正規 policy を固定する。
- [x] exact string / bool / integer、有限実数、exact tuple / `Path` / enum の境界を共有化する。
- [x] history/autosave/recovery/window loop/workspace/output path/doctor、
  `PerfCollector`、`ResourceBudget`、selector でも共有 validator を適用する。
- [x] disabled 時の検証省略、負値 clamp、非有限値の黙殺、暗黙の
  `str` / `int` / `float` / `bool` coercion を削除する。
- [x] benchmark を単一 `BenchmarkOutput` へ統合し、stub 同期を test process から隔離する。
- [x] 正当な platform、optional subsystem、recovery、数値安定化の分岐を
  旧 API/test-double の互換 fallback と区別して記録する。

最終検証では full pytest が `3257 passed, 1 skipped in 105.85s`（warning summary なし）、
full mypy が
`238 source files` で成功した。fresh CLI subprocess での stub 再生成と checked-in stub の
比較、`git diff --check`、headless SVG/PNG/G-code、実 GUI smoke
（`imgui 2.0.0 / pyglet 2.1.11`）も成功した。benchmark は全 `162/162` case が
status `ok`、全 `887/887` contract が pass した。

full `ruff check .` は実行済みだが、基準時点の既知 33 件から 27 件へ減っただけで
exit 1 である。変更・新規 Python file の対象限定 Ruff は成功し、残る 27 件は今回の
監査対象外である `.agents` / sketch の既知問題だけなので、新規違反なしと判定する一方、
「全件成功」の checkbox だけは完了扱いにしない。

## 19. 監査 ID と Phase の対応

| 監査 ID | Phase |
|---|---:|
| A-01 | 1 |
| A-02 | 3 |
| A-03 | 2 |
| A-04 | 2 |
| A-05 | 2 |
| A-06 | 4 |
| A-07 | 9 |
| A-08 | 6 |
| B-01 | 5 |
| B-02 | 5 |
| B-03 | 7 |
| B-04 | 3 |
| B-05 | 10 |
| B-06 | 8 |
| B-07 | 9 |
| B-08 | 12 |
| C-01 | 11 |
| C-02 | 1, 4 |
| C-03 | 6 |
| C-04 | 1 |
| C-05 | 7 |
| C-06 | 8, 10 |
| C-07 | 10, 11, 12 |

## 20. 最終状態

実装、文書更新、Phase 13 の全体検証は完了した。full Ruff も実行しており、基準の
33 件から 27 件へ減少したが、今回の監査対象外である `.agents` / sketch の既知問題により
exit 1 のため、18.1 の Ruff checkbox だけを完了扱いにしていない。

監査対象内に互換 wrapper、deprecated alias、旧 schema migration、二重 DTO、
暗黙 coercion を戻す残作業はない。既知 Ruff 27 件は本計画と分離して扱う。
