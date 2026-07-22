# `src/grafix` アーキテクチャ最終監査（2026-07-22）

## 1. 結論

AQ-001〜AQ-012 の原指摘は、現 working tree の production implementation と automated contract 上で
すべて解消した。特に暫定監査後に残っていた次の三点も解消済みである。

- `RealizeSession`: 省略 dependency は session-owned、明示注入は borrowed という close contractを固定。
- `ParamRuntimeView`: runtime mapping を生成時に浅く copy する時点固定 snapshotへ変更。
- benchmark runner: definition/catalog/metrics/executor/workload/runner の一方向 DAGへ分割し、Phase 9
  snapshotとの semantic equivalence と child cleanupを確認。

その後、unlock 済みmacOS実機で Preview/Inspector、reload、quality、capture/video、通常/recording
closeを確認し、real Cocoa/OpenGL windowの100 warmup + 100 measured soakも通過した。外部GUI/OS-GL
blockは解消している。利用できたdisplayはbacking scale 1.0だけだったため、計画上optionalの
Retina/non-Retina間移動だけは未実施である。

GUI受入で発見したwatch source site ID不一致と、その後のmanual pyglet lifecycle fixture修正を含む
post-manual full pytestも **3,824 passed in 324.30s**、failed 0、exit 0で確定した。最新treeのRuff、
mypy、fresh stub、collection、`git diff --check`、performance gateも通過している。したがって最終判定は
**AQ-001〜AQ-012、code/document/automated/performance/GUI/OS-GL gateをすべて完了** とする。

## 2. AQ traceability

### AQ-001 — preview quality と content cache identity: 解消

- 実装: `core/evaluation_context.py::EvaluationContext`、
  `core/realize.py::GeometryCacheKey` / `RealizeSession.realize_with_key()`、
  `core/geometry.py::compute_geometry_id()`。
- 契約: quality、effective config、使用 operation lineage、external dependency、uncached generation を
  typed keyへ集約し、CPU/inflight/`RealizedLayer`/GPUで同じ identityを使う。
- ownership follow-up: `RealizeSession` は省略した `EvaluationResources` / `RealizeCacheStore` だけを
  所有し、明示注入した dependencyを閉じない。active realization中の closeは最後の callerまで遅延する。
- 代表 test: `test_draft_and_final_use_distinct_typed_keys_in_both_orders`、
  `test_catalog_generations_share_only_compatible_per_operation_cache_entries`、
  `test_session_closes_only_resources_and_store_omitted_by_the_caller`、
  `test_close_allows_inflight_leader_to_finish_without_repopulating_cache`。
- 破壊的変更: 旧 `(GeometryId, registry_revision)` tupleと同名 latest evaluator fallbackを削除。

### AQ-002 — text の外部 font/config identity: 解消

- 実装: `core/font_resources.py::{FontAssetFingerprint,ResolvedFontLease,FontResources}`、
  `core/primitives/text.py::_text_font_dependency()`、external-dependency preflight。
- 契約: canonical path、face、stat、content digestをkeyに含め、preflightとevaluatorは同じbytes/leaseを
  使う。font/glyph cacheはgeneration-owned bounded resourceである。
- 代表 test: `test_preflight_and_evaluator_share_exact_lease_and_warm_lookup`、
  `test_same_session_observes_font_replacement_in_key_and_output`、
  `test_two_configs_with_same_font_name_are_isolated`、
  `test_repeated_resource_owner_close_releases_all_font_state`。
- 破壊的変更: class/module-global renderer/cacheと旧cache-clear helperを削除し、singleton shimはない。

### AQ-003 — RuntimeConfig / preset session isolation: 解消

- 実装: pure `core/runtime_config.py::load_runtime_config*()`、immutable
  `PresetCatalog` / `AuthoringDefinitionsSnapshot`、candidate-scoped `RegistrationTarget`。
- 契約: config/preset/operationはsession/generation構築時に固定し、draw/evaluator中だけ
  `ContextVar`へ束縛する。失敗candidateはlast-good/default definitionsを変更しない。
- 代表 test: `test_render_sessions_are_isolated_for_any_close_order`、
  `test_threaded_config_loads_do_not_mix_registration_targets`、
  `test_failed_candidate_does_not_publish_partial_catalog`。
- 意図した例外: `DefaultAuthoringDefinitions` はmodule-scope decorator convenience用の唯一の
  process-wide mutable authoring storeであり、live evaluation catalog/resourceは保持しない。
- 破壊的変更: process-global config cache/path scope、preset autoload、旧registryを削除。

### AQ-004 — ParamStore private layout ownership: 解消

- 実装: `ParamStoreRollback`、`ParameterEdit` / narrow command、immutable table DTO、
  `ParamStore.runtime_view()`。
- 契約: `ParamRuntimeView` はsetsを`frozenset`、三mappingを`dict(...)`で時点固定して
  `MappingProxyType`で公開する。key/value/sourceはcanonical immutable valueなのでdeep copyしない。
- 代表 test: `test_transient_rollback_restores_exact_state_after_base_exception`、
  `test_runtime_view_is_frozen_and_does_not_expose_mutable_sets`、
  `test_runtime_view_keeps_a_point_in_time_mapping_snapshot`、
  `test_multiple_row_edits_commit_as_one_revision_and_one_history_unit`。
- 破壊的変更: API/interactiveの`vars(store)`、private container access、manual revision/cache restoreを削除。

### AQ-005 — application coordinator の多責務: code contract 上は解消

- 実装 owner: `CaptureQueue`、`RecordingSession`、`WorkspaceWindowController`、
  `ParameterSession`、`ParameterGUIWindowSystem`、`VariationController`、
  `RangeEditController`、`ParameterGuiSessionState`。
- 契約: `DrawWindowSystem` / `ParameterGUI` / `api.runner.run()` はcall orderと配線に集中し、
  capture、recording、workspace、parameter mutationのstate lifetimeを各ownerへ委譲する。
- 代表 test/gate: `test_capture_intent_fifo_trace_matches_the_coordinator_contract`、
  `test_start_failure_restores_playing_transport_and_window_constraints`、
  `test_phase6_coordinators_do_not_reabsorb_extracted_policy`。
- 注意: GUI rendering surfaceはなお大きく、architecture gateも禁止symbol中心である。実機受入は
  完了したが、今後も肥大化をreviewで継続監視する。

### AQ-006 — `effects/util.py` catch-all: 解消

- 実装: `core/geometry_kernels/{packed,planar,grid,raster,marching,resample}.py`。
- 契約: packed builderを一実装にし、kernelはeffect/diagnosticsへ依存せず、effect間のsibling importもない。
- gate: `test_effect_modules_do_not_import_sibling_effects`、
  `test_geometry_kernel_import_graph_is_acyclic_and_does_not_depend_on_effects`、
  `test_packed_geometry_builders_have_one_canonical_implementation`。
- 破壊的変更: `core/effects/util.py` と旧helperを削除し、re-export shimはない。
- testも責務に合わせて`tests/core/test_geometry_kernels.py`へ移し、旧`test_effect_util.py`は残していない。

### AQ-007 — registry / selector / global revision: 解消

- 実装: `OpDeclaration` / `ParameterOpSchema`、単一registration target、immutable
  `OperationCatalog` / `PresetCatalog`、builtin manifest、`EvaluationOpRef` / `EffectStepRef`。
- 契約: evaluator catalogとselector/GUI schemaを分離し、per-operation fingerprintをDAGへ固定する。
  builtin direct import、import順、clean subprocess、別checkout pathでidentityを安定させる。
- 代表 test: `test_all_public_decorators_use_the_scoped_registration_target_only`、
  `test_direct_import_and_bootstrap_order_produce_the_same_catalog`、
  `test_fingerprints_and_serialized_dag_are_stable_across_clean_processes`。
- 破壊的変更: 四つの旧registry module、global revision、live replace/swap、旧`OpSpec` layoutを削除。

### AQ-008 — semantic package boundary: 解消

- 実装: coreはcapture provenance/manifestのimmutable value、exportはGit/filesystem/staging/publish、
  `interactive/`直下はdiagnostics/transport/telemetryのneutral contractを所有する。
- gate: `test_core_does_not_depend_on_api_export_or_interactive`、
  `test_core_does_not_implement_publish_or_path_allocation_policy`、
  `test_interactive_leaf_packages_do_not_depend_on_runtime_composition`。
- 破壊的変更: `core.output_paths`、`core.atomic_write`、
  `interactive.runtime.diagnostics/frame_clock`を削除/移動し、shimはない。
- 外部確認: static/import contractに加え、real OS/GL closeを100 warmup + 100 measuredで観測し、
  critical GL/Cocoa object、FD/thread/window、weakrefの残留0を確認した。

### AQ-009 — capture/export lifecycle 重複: automated contract 上は解消

- 実装: `CaptureStaging`、`publish_capture_generation()`、`CaptureService`、
  `ExportJobSystem`、`RecordingSession`。
- 契約: private staging、no-clobber allocation、late-collision retry、family commit/rollback、cleanupを
  一つのlifecycleへ集約し、completed stagingを再encodeしない。
- 代表 test: `test_late_collision_retries_without_reencoding_or_overwriting`、
  `test_gcode_layer_commit_failure_rolls_back_already_published_layers`、
  `test_publish_failure_retains_completed_staging_for_recovery`。
- 外部確認: GUI shortcut経由のSVG/PNG/G-code/split G-code/video、late collision、通常close、recording
  closeを実機で確認した。staging、worker、resource tracker、ffmpegの残留は0だった。

### AQ-010 — G-code face heuristic: 解消

- 実装: `export/gcode.py::_collect_layer_strokes()` / `_order_polyline_fragments()` /
  `_emit_polyline_fragments()`。
- 契約: producerのinput polyline順をsemantic boundaryとし、reorder/reverse/bridgeは一つのsource
  polylineがclippingで分かれたfragment内だけに限定する。
- 代表 test: `test_export_gcode_keeps_input_polyline_order_when_optimization_is_enabled`、
  `test_export_gcode_draw_bridge_never_crosses_input_polyline_boundary`。
- 破壊的変更: face推測とcross-polyline optimizationを削除。将来必要ならexport-side grouping artifactを
  別設計し、heuristicを復活させない。

### AQ-011 — GUI/GL frame order と context ownership: automated contract 上は解消

- 実装: `PygletImguiBackend.begin_frame()/render()/close()` と
  `DrawRenderer.begin_frame()/read_frame_rgb24()`。
- 契約: backendがImGui context/IO/new-frame/render/cleanup、rendererがGL context/framebuffer/readbackを
  所有し、runtimeはrenderer `.ctx`へ到達しない。
- 代表 test: `test_backend_syncs_current_window_io_before_new_frame_and_owns_render`、
  `test_partial_initialization_cleans_resources_and_preserves_root_error`、
  `test_renderer_owns_default_framebuffer_begin_and_rgb24_readback`。
- 外部確認: fake backend/Retina計算/cleanup/readbackに加え、実windowの表示・resize・Inspector
  close/hideと再表示・Preview close・real GL resource cleanupを確認した。利用可能displayがscale 1.0
  だけだったため、optionalなcross-scale移動は未実施である。

### AQ-012 — benchmark runner 多責務: 解消

- 実装: `benchmarks/{schema,definition,metrics,executor,catalog,runner}.py` と10 workload provider。
  162 caseを収集し、`runner.py`は76行、公開symbolは`run_case_isolated`だけである。
- DAG: definition/metrics→schema、provider→definition/metrics/schema、catalog→provider/definition、
  executor→definition/metrics/schema、runner→catalog/executor。executorはcatalog/workloadを知らない。
  provider内の許可辺は`interactive_scenario→parameter_hotpath/renderer`と
  `parameter_edit→parameter_hotpath`のpublic helperだけで、system/private helper残骸はない。
- gate: `test_benchmark_module_graph_is_acyclic`、`test_benchmark_layers_keep_one_way_dependencies`、
  `test_provider_dependencies_use_only_public_symbols`、
  `test_runner_is_only_the_catalog_executor_composition_root`。
- Phase 9 snapshot同値: list 162件byte exact。smoke/short/long/cold/renderer/MP/timeoutの
  status/checksum/hard contract/metric identity/semantic valueが一致。compare JSONはbyte-equivalent、
  report HTMLはbyte exact、最終orphanは0。
- intentional identity change: 責務移動により`source_sha256` / `compatibility_key`は162/162で変更。
  旧/new直接compareはexit 2で拒否し、`--allow-incompatible`は未使用。
- child lifecycle: `communicate()`の全`BaseException`でprocess group killを試み、`killpg`失敗時は
  child killへfallbackする。boundedな再`communicate()` / `wait()`でreapを試し、cleanup failureは
  元errorのnoteへ残して元`BaseException`を優先する。fake/実SIGINT testでchild/grandchild残留0。
- 詳細: `docs/review/src_grafix_architecture_phase10_benchmark_runner_result_2026-07-22.md`。

## 3. 共通 verification evidence

- Phase 9 production full suite: **3,787 passed in 275.49s**。
- Phase 9: `ruff check src/grafix tests` pass、`mypy src/grafix` 268 files pass、fresh stub byte exact。
- AQ-001〜AQ-006 focused audit: **413 passed**。
- AQ-007〜AQ-011 focused audit: **223 passed**。
- ownership/snapshot follow-up: **124 passed**、直接対象 **43 passed**、targeted Ruff/mypy pass。
- Phase 10 benchmark/architecture: **185 passed in 46.26s**、Ruff pass、mypy 274 files pass、
  `git diff --check` pass。
- Phase 10 cleanup hardening follow-up: **26 passed**、targeted Ruff/mypy pass。
- AQ-012追加修正後のbenchmark/architecture focused suite: **42 passed**。
- Phase 11 docs/architecture: **24 passed**、docs path check 8文書・90 path、
  `ruff check src/grafix tests` pass、mypy 274 files pass、`git diff --check` pass。

GUI追補前のroot automated gate:

- full pytest: **3,806 passed in 269.52s**。
- `ruff check src/grafix tests`: pass。`ruff check .`の22件は依頼範囲外`sketch/readme`の既知F401のみ。
- `mypy src/grafix`: **274 source files / no issues**。
- fresh stub: checked-in stubとbyte exact、SHA-256
  `fc19df83ae3310b2405d26754d1359567db886b8d7027d6921f2abdecce48575`。
- `git diff --check`: pass。

後続のGUI/site-ID/manual lifecycle修正を含むgate状態:

- watch sourceのsite ID修正後、manual fixtureの最後の修正前にfull pytestは **3,824 passed in
  316.38s**。その後`tests/manual/_runner.py`とpyglet lifecycle fixtureを変更したため、この値を
  最終treeのfull結果とは呼ばない。
- post-manual collectionは **3,824件**。`ruff check src/grafix tests` pass、`mypy src/grafix`は
  **275 source files / no issues**、fresh stubは **183,551 bytes**でchecked-in stubとbyte exact、
  SHA-256は上記と同じ、`git diff --check`もpassした。
- post-manual full pytest: **3,824 passed in 324.30s**、failed 0、exit 0。
- performanceの正式証跡は同一source identityの
  `/tmp/grafix-architecture-final-benchmarks/runs/architecture-final-short.json`。Phase 9 canonical比で
  status/checksum/hard contractは全件一致し、pipeline median **+8.21%**、p95 **+8.14%**で停止条件内。
  後続の高負荷観測はMADが採用値の **2.75〜6.72倍**、host load **4.15**、WindowServer **50.5%**
  だったため外乱tailと判定し、`/tmp/grafix-architecture-pipeline-noise-audit/`へ記録した。これを理由に
  production codeは変更していない。

## 4. macOS実機 GUI / resource evidence

- **window lifecycle:** Preview/Inspectorの表示とresizeを確認した。Inspectorのnative closeはPreviewを
  終了せずhideだけを行い、`Cmd+I`で再表示できた。証跡は
  `/tmp/grafix-architecture-final-gui-2026-07-22/920-fixed-fresh-launch.jpg`〜
  `923-fixed-inspector-resized.jpg`。利用できたdisplayはbacking scale **1.0だけ**で、optionalな
  Retina/non-Retina間移動は未実施である。
- **controls/history/persistence:** bool checkboxは実GUIで変更し、guide circleがPreviewから消えることを
  `932-preview-bool-off-fixed.jpg`で確認した。float/int/choiceはproduction GUIで表示とhover/helpを確認し、
  edit contractは **38件**のfocused/manual widget testで補完した。float/int/choiceをmouseで変更したとは
  主張しない。manual smokeの必須catalog欠落を修正後、主要7 fixtureはreal ImGui/pygletでone-frame
  構築できた。variation/Undo/Redoは実primary storeへ`VariationController`でsave → mutate → load →
  undo → redoを行ったもので、popupのmouse save/loadに成功したという主張ではない。通常closeでは
  primaryを残してsession fileを削除し、再起動時にcurrent **26/42**、hidden **16**、**Variations 1**を
  復元した（`947`〜`949`）。
- **source reload:** 同じ親runtimeのままaxis layerを除いたcandidateへ更新し、worker generationは
  設計どおり交代して、Previewからaxisが消えた（`940-reload-success-no-axis.png`）。syntax errorの
  失敗candidateでは現generationとlast-good sceneを維持し、Inspectorの
  Diagnostics **1件**を表示した（`941`〜`943`）。元sourceへ戻すとdiagnosticsは消え、SHA-256も
  `89fddbf55b93fd67fdd5c209f7034fe52f5c32c1203c5f274169fb428ade9ed7`へ復元した（`944`）。この確認で
  外部sourceの親/worker site ID不一致を発見し、`make_site_id()`が`__grafix_source_owner__`を優先する
  修正と回帰testを追加した。
- **quality:** growth Previewはdraft effective `iters=32`、8 polylines / **163 coords**。GUI shortcutで
  生成したfinal SVGはschema 3 / `quality=final`、**8 paths / 796 points**で、final PNGも1600×1600。
  draft表示は`946-growth-draft-preview.png`、final artifactは
  `/tmp/grafix-architecture-gui-acceptance/output/{svg,png}/`に保存した。
- **capture/video:** GUI shortcutからSVG、PNG、単一G-code、layer split G-code、videoを実生成し、全capture
  manifestがschema 3 / `origin=interactive` / `quality=final`であることを確認した。user-stop videoは
  H.264 / yuv420p / 800×800、**876 frames**、`stop_reason=user_stop`。recording開始後にbase manifestを
  `O_EXCL`で配置したlate collisionではsentinelのSHA-256を変えず`_001.mp4`へ再割当した。
- **normal/recording close:** recording中のPreview closeでも`_002.mp4`を **538 frames**、
  `stop_reason=shutdown`として確定した。通常closeとrecording closeの双方でparent/worker/resource
  tracker/ffmpeg残留0、全staging pattern 0だった。
- **real OS/GL soak:** production `close_pyglet_window()`でreal hidden Cocoa/OpenGL windowを **100回
  warmup + 100回 measured**。`real-window-soak-production.json`は`passed=true`で、`BufferObject`、
  `CocoaContext`、`CocoaDisplayConfig`、`CocoaWindow`、`ShaderProgram`、`UniformBufferObject`のdelta、
  FD/thread/Pyglet window delta、warmup/measured weakref aliveはすべて0。後半slopeはRSS
  **19,567 B/cycle**、tracemalloc **75.12 B/cycle**、GC **0.1 object/cycle**で定義済み上限内だった。
- 機械可読集約は
  `/tmp/grafix-architecture-final-gui-2026-07-22/gui-acceptance-summary.json`（SHA-256
  `86befaad19d6b7adc1791ac55dbd131421958ffbcc63791d9618b5c172cf50d6`）。`source.restored`、
  `staging_clean`、late-collision sentinel unchanged、soak passはすべてtrueである。

## 5. Ruff scope と既知範囲外差分

production/testの基準は`ruff check src/grafix tests`であり、Phase 9/10とpost-manual gateでpassした。repository全体の
`ruff check .`に残る22件は、すべて依頼範囲外の`sketch/readme`にある既知`F401`である。これを
production/test lint failureとして扱わず、本監査で依頼外fileを修正しない。

## 6. 最終判定

- **AQ-001〜AQ-012 code traceability:** 解消・記録済み。
- **architecture/docs同期:** 本監査とPhase 11 docsで実装contractへ同期。
- **外部GUI/real OS-GL:** 完了。利用できたdisplayがscale 1.0だけだったため、optionalのRetina/
  non-Retina間移動だけ未実施。
- **Phase 11 final automated gates:** post-manual full pytest、Ruff、mypy、stub、collection、diff、
  performanceはすべて完了。
- **project status:** 完了。コード、文書、自動検証、performance、実機GUI、real OS/GLを確認済み。
  optionalのRetina/non-Retina間移動だけは利用可能displayの制約で未実施。
