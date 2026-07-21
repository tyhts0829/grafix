# `src/grafix` アーキテクチャ品質改善 実装計画（2026-07-21）

作成日: 2026-07-21

基準 HEAD: `74a8643`

根拠レビュー:
`docs/review/src_grafix_architecture_quality_review_2026-07-21.md`

ステータス: **承認待ち・実装未着手**

作成開始時の依頼外差分:

- `?? .agents/skills/grafix-art-loop/`
- `?? docs/plan/grafix_art_loop_llm_simplification_plan_2026-07-21.md`
- `?? docs/review/src_grafix_architecture_quality_review_2026-07-21.md`

上記は本計画の対象外とし、移動、削除、上書き、stage を行わない。

計画作成中には、別作業による以下の tracked deletion も追加で出現した。

- `.agents/skills/grafix-art-loop-artist/` 配下
- `.agents/skills/grafix-art-loop-critic/` 配下
- `.agents/skills/grafix-art-loop-ideaman/` 配下
- `.agents/skills/grafix-art-loop-orchestrator/` 配下

これらも本計画では一切変更せず、最終 status で依頼対象差分と分離する。

## 1. 目的

レビューの AQ-001〜AQ-012 を、局所的な workaround や互換 shim を追加せず、依存関係に沿って段階的に解消する。

最終的に、次の状態を実現する。

- 評価結果へ影響する quality、config、font asset、operation spec が cache identity に明示されている。
- `RenderSession` / `SceneRunner` が評価期間の immutable state と、明示的な lifetime を持つ cache/resource を所有し、子 `RealizeSession` はそれらを借用する。session lifetime を process-global state で表さない。
- config A/B、同名 preset A/B、draft/final、font asset A/B を同一 process で安全に共存させられる。
- `ParamStore` の mutation、history、revision、transactional rollback を `core.parameters` が所有し、API/GUI は private layout を知らない。
- `DrawWindowSystem`、`ParameterGUI`、`api.runner` は順序と composition を担当し、I/O や個別 state machine の詳細を持たない。
- effect 共通 kernel、capture infrastructure、interactive contract、benchmark runner が概念単位で分かれている。
- registry 登録経路が一つで、selector metadata と evaluator catalog が分離され、cache invalidation が参照 operation に限定される。
- G-code exporter が face/group を形状から推測せず、意味情報がない入力では元の polyline 順を保持する。
- 公開 DSL の `G` / `E` / `L` / `P` と、既存作品の数値・描画結果は、意図した破壊的変更を除き維持される。

## 2. 本計画の承認で固定する設計判断

### 2.1 評価 identity と session ownership

- `EvaluationContext` を immutable value として導入し、catalog generation ごとに固定する。
- filesystem 上で変更され得る font asset は `EvaluationContext` 自体へ固定せず、各 cache lookup で解決する external dependency fingerprint として分離する。
- bounded `RealizeCacheStore` は parent session/runtime が所有し、異なる immutable catalog generation 間でも安全な key によって共有できる。
- `RealizeSession` は `EvaluationContext`、`EvaluationResources`、`RealizeCacheStore` を借用し、自身の in-flight 評価だけを close する。
- headless `RenderSession` は cache store、resources、子 `RealizeSession` を所有する。interactive は親 `SceneRunner` が generation 間で共有する cache store を所有し、各 generation は resources と draft/final の子 session を所有する。generation 終了は子 session→resources、`SceneRunner` 終了時だけ最後に cache store を一度 close する。
- preview quality は `EvaluationContext` の必須 field とし、caller ambient state だけで結果を変えない。
- cache key は型付き `GeometryCacheKey` へ変更し、旧 `(geometry_id, registry_revision)` tuple は残さない。
- `G` / `E` が node を確定する時点で、operation 名だけでなく解決済み `EvaluationOpRef` を immutable DAG に記録する。`EvaluationOpRef` は kind、name、評価 fingerprint を持ち、`GeometryId` に推移的に含まれる。
- 遅延適用される通常の `E.<name>(...)` step は、作成時に `EffectStepRef` として `EvaluationOpRef` と schema fingerprint の両方を固定する。適用時は同じ entry で引数解決と node 化を行い、同名 latest entry を取り直さない。
- realization は session catalog に同じ `EvaluationOpRef` が存在することを検証し、同名の別 version へ黙って差し替えない。catalog をまたいだ古い DAG が一致しない場合は、cache lookup 前に明示的な version mismatch とする。
- evaluation/schema fingerprint は canonical declaration signature から決定的に導出し、process-local counter、absolute path、import 順を identity にしない。
- `ContextVar` を使う場合は、draw/evaluator 呼び出し中の短い束縛だけに限定する。session constructor から `close()` まで process-global 値を差し替えない。
- context を `dict[str, Any]` にせず、意味を持つ frozen dataclass と typed fingerprint で表す。

### 2.2 config、font、catalog

- runtime config は pure loader で一度解決し、composition root から明示的に渡す。
- `runtime_config_scope()`、`_EXPLICIT_CONFIG_PATH`、process-global config cache を評価経路から削除する。
- font 探索は確定済み `RuntimeConfig` を受け取り、評価中に process-global config を再参照しない。
- font file は path だけでなく face index と内容 fingerprint を持つ asset として扱う。
- TTFont/glyph cache は session-owned、bounded LRU、close 可能にする。module/class-global cache は削除し、上限到達を新しい user-facing error にはしない。
- font resource は immutable snapshot ではなく session-owned の mutable cache とする。同一 session の後続評価で font file が置換された場合は、その変更を正式に観測し、新 fingerprint と新 geometry を返す。これは意図した hot-reload contract とする。
- 一回の評価では dependency preflight が fingerprint と同じ bytes から構築した resolved font lease を返し、evaluator はその lease だけを使う。preflight と evaluator の間で path を再 open しない。
- preset と operation は session/generation ごとの immutable catalog snapshot として評価する。
- `@effect` / `@primitive` / `@preset` は live catalog を直接変更せず、immutable declaration を作る。declaration の登録は `RegistrationTarget.register()` の一経路に統一する。
- 通常の Python module scope で実行された公開 decorator の使い勝手を保つため、process-level の `DefaultAuthoringDefinitions` を唯一の authoring convenience として残す。これは kind/name ごとの最新 operation/preset declaration を持つ定義 store であり、live evaluator/preset catalog ではない。
- decorator 実行時に scoped registration target があればそこだけへ登録し、なければ `DefaultAuthoringDefinitions` へ登録する。duplicate は同一 target 内で拒否し、operation の `overwrite=True` は該当 name の declaration だけを置換する。
- builtin operation は例外なく builtin manifest 所有とし、direct import でも default authoring definitions へ登録しない。decorator は declaration を callable に付与し、bootstrap は module が import 済みでも manifest の callable attribute から回収して同じ builder へ渡す。
- source reload/config preset load は scoped candidate builder だけへ登録する。reload/import failure が default authoring definitions や既存 catalog を変更することを禁止する。
- `G` / `E` は draw/evaluator 中は束縛された immutable operation catalog、束縛外では builtin catalog と `DefaultAuthoringDefinitions` の operation snapshot を参照する。`RealizeSession()` / `RenderSession` も構築時に同じ規則で snapshot を確定し、以後 default definitions を再参照しない。
- `P` は draw 中は束縛された session-local `PresetCatalog`、束縛外では default authoring preset snapshot だけを参照する。束縛外で default runtime config の preset path を暗黙 autoload する現行挙動は削除し、config-scoped preset は `RenderSession` / runner の catalog 構築時にだけ読む。
- import 済みの通常 module にある custom declaration は、decorator 実行時に default authoring definitions へ既に記録されているため module の再実行を要求しない。source-loader/config-loader 管理 module は default definitions を使わず、generation/session ごとに candidate を構築する。

### 2.3 状態変更の所有権

- variation batch の一時変更には owner-bound で opaque な `ParamStoreRollback` を使う。
- rollback snapshot は論理 state と revision/runtime counter を保持し、lock、observer、derived cache、live container を外へ公開しない。
- transactional rollback は開始時の論理 state と revision/runtime counter を戻し、observer notification を発生させず、derived cache だけを破棄する。
- 通常の GUI command は rollback と分け、変更時だけ revision/history/observer を一度更新する。
- collapsed state、variation、range、MIDI、effect order は狭い command/query で操作する。
- GUI renderer は immutable view を受け取り、変更意図を返す。live `set` / `dict` を直接変更しない。

### 2.4 application orchestration

- class の行数ではなく、state/resource lifetime と変更理由で分割する。
- coordinator は call order と ownership だけを表し、format encode、path allocation、GUI domain mutation を実装しない。
- capture と video を万能 service に統合しない。既存の atomic publish primitive の周辺 lifecycle だけを共有する。
- panel ごとに class を量産せず、既存の pure panel/model を再利用する。
- GL/ImGui backend は context、frame begin/render、resource close の唯一の owner とする。

### 2.5 geometry kernel と export semantics

- `effects/util.py` は数値領域別の `core/geometry_kernels/` へ分け、移行後に削除する。
- 旧 `util.py` を re-export shim として残さない。
- packed geometry helper は canonical implementation を一つだけ持つ。
- 今回は G-code のために core DAG、effect return、`RealizedGeometry` へ新しい grouping metadata を追加しない。
- face 意味論が存在しない現行 contract では input polyline 順を保持し、travel optimization/bridge は同一元 polyline の clipping fragment 内だけに限定する。
- 将来 cross-polyline optimization が必要になった場合は、export-side grouping artifact を別計画で設計する。

### 2.6 破壊的変更と互換性

- 旧/new 実装の二重保持、`legacy` / `v2`、feature flag、dual-write を行わない。
- compatibility wrapper、deprecated alias、旧 import path の re-export shim を作らない。
- 束縛外 `P` による default config preset directory の暗黙 autoload は削除する。通常 module-scope `@preset` は維持し、config-scoped preset は明示 session/catalog scope で使う。
- canonical fingerprint を作れない動的 operation は、`cache_policy="none"` と明示 `version` を要求する。content cache のまま曖昧な process identity へ fallback しない。
- 破壊的変更は repository 内 callsite、test、stub、docs と同じ change set で更新する。
- 依存パッケージは追加しない。必要になった場合は、その時点で別途承認を得る。
- commit、push、release は本計画に含めない。

## 3. 非目標・維持するもの

- `G` / `E` / `L` / `P` の作品記述体験を別 DSL へ置き換えない。
- `Geometry` の immutable DAG と `RealizedGeometry` の canonical packed representation を捨てない。
- 数値 kernel の最適化とファイル移動を同時に行わない。
- capture の fsync、no-overwrite、late collision、rollback を簡略化しない。
- source reload の candidate isolation、last-good rollback、worker generation safety を弱めない。
- G-code の bed bounds、安全 command、座標量子化、決定性を弱めない。
- 実プロッタへ自動送信しない。G-code は dry-run/parser/simulator までとする。
- MIDI 物理 device を必須条件にしない。fake/virtual port で自動検証し、実機は利用可能な場合だけ確認する。
- AQ-012 完了前に benchmark の workload semantics、JSON schema、case ID、checksum、measurement algorithm を変更しない。削除・移動された internal import への追随だけは許可し、変更を記録する。

## 4. 指摘と Phase の対応

| 指摘 | 主 Phase | 補助 Phase | 完了の要点 |
|---|---:|---:|---|
| AQ-001 | 2 | 1 | quality を含む評価 context/cache identity |
| AQ-002 | 2 | - | font asset fingerprint、session-owned resource |
| AQ-003 | 1, 2 | - | pure config、session-local preset catalog |
| AQ-004 | 3 | 6 | rollback/command/view、outer private access 0 |
| AQ-005 | 6 | 4, 5 | DWS/GUI/runner を lifecycle owner 単位で分割 |
| AQ-006 | 7 | 9 | kernel package、packed helper 一本化 |
| AQ-007 | 2 | 1 | 単一 bootstrap、schema 分離、per-op fingerprint |
| AQ-008 | 4, 5 | 6 | core infrastructure 移設、interactive contract 正方向化 |
| AQ-009 | 5 | 6 | staging/path/retry/cleanup lifecycle 共通化 |
| AQ-010 | 8 | - | heuristic 削除、input polyline order 保持 |
| AQ-011 | 1, 4 | 6 | `sync_io -> new_frame`、backend/context ownership |
| AQ-012 | 10 | 9, 11 | production 測定後に benchmark runner 分割 |

## 5. 依存順と並行可能範囲

```mermaid
flowchart TD
    P0["Phase 0: Baseline"] --> P1["Phase 1: Config / Immediate GUI Fix"]
    P1 --> P2["Phase 2: Catalog / Evaluation / Font / Preset"]
    P2 --> P3["Phase 3: ParamStore Boundary"]
    P1 --> P4["Phase 4: GUI / GL Backend and Contracts"]
    P0 --> P7["Phase 7: Geometry Kernels"]
    P4 --> P5["Phase 5: Capture Infrastructure"]
    P3 --> P6["Phase 6: Application Decomposition"]
    P4 --> P6
    P5 --> P6
    P7 --> P8["Phase 8: G-code Stroke Ordering"]
    P6 --> P9["Phase 9: Production Validation"]
    P8 --> P9
    P9 --> P10["Phase 10: Benchmark Runner"]
    P10 --> P11["Phase 11: Docs / Final Audit"]
```

- Phase 4 は Phase 1 の frame-order fix 後、Phase 7 は Phase 0 後に独立着手できる。
- Phase 3 は Phase 2 の catalog/evaluation contract 完了後に着手する。
- Phase 5 は Phase 4 の renderer/capture contract 固定後に行う。
- Phase 6 は Phase 3〜5 の state owner が揃ってから行う。
- Phase 10 までは benchmark の workload/metric/schema を変更しない。internal import 追随は許可するが、意味変更と分けて記録する。

## 6. 実施原則

- [x] 作業開始時に `git status --porcelain` を確認した。
- [x] レビュー内容へのユーザー同意を確認した。
- [x] AQ-001〜AQ-012 の対応、Phase 依存、decorator/catalog/cache/resource contract の計画内整合性を再確認した。
- [ ] 本実装計画へのユーザー承認を得る。
- [ ] 承認後にだけ production code を変更する。
- [ ] 各 Phase の最初に characterization/failing regression test を追加する。
- [ ] 一つの change set では state owner または概念境界を一つだけ変更する。
- [ ] 各 Phase を focused test、ruff、mypy が green の状態で終える。
- [ ] 数値移設では `coords`、`offsets`、dtype、順序、checksum を固定する。
- [ ] 依頼外差分を restore/reset/add/delete しない。
- [ ] 完了項目を本ファイルで逐次 `[x]` に更新し、実測結果を追記する。
- [ ] 長時間 benchmark、headed GUI、物理 device 検証は実行前に許可境界を再確認する。

## 7. Phase 0 — baseline と契約固定

### 7.1 作業ツリーと inventory

- [ ] 実装開始時の HEAD、`git status --porcelain`、対象外差分を本ファイルへ追記する。
- [ ] 基準 HEAD の tracked tree を `git archive` で `/tmp/grafix-architecture-base/` へ展開し、作業中の依頼外差分を含まない比較環境を固定する。
- [ ] AQ ごとの変更対象 file/test を再走査し、削除・移動予定 path を固定する。
- [ ] public root/API export、generated stub、CLI command、serialized schema の現状を記録する。
- [ ] `runtime_config()`、preset/operation registry、`ParamStore` private access、`.ctx.screen` の全 callsite inventory を `/tmp` に保存する。

### 7.2 correctness baseline

- [ ] `PYTHONPATH=src pytest -q` の結果を `/tmp` に保存する。
- [ ] `ruff check .`、`mypy src/grafix`、architecture test の結果を保存する。
- [ ] draft/final の heavy effect、text、preset A/B、variation batch の focused baseline を保存する。
- [ ] representative SVG/PNG/G-code/capture manifest の checksum と意味値を保存する。
- [ ] capture 成功、encode 失敗、publish 失敗、late collision、retry 枯渇、worker timeout の call trace を固定する。
- [ ] ImGui frame、window/renderer/worker/ffmpeg close 順序を fake で記録する。

### 7.3 performance baseline

- [ ] 現行 runner で effects、pipeline、text、registry lookup、parameter edit、interactive、capture publish の short benchmark を保存する。
- [ ] benchmark の case ID、status、checksum、hard contract、JSON schema を保存する。
- [ ] workload setup、measurement、aggregation、contract 判定を構成する source の hash/inventory を保存する。
- [ ] Phase 9 までは workload/metric/schema の意味を凍結する。
- [ ] production の internal path/API 削除に伴う import/callsite 追随だけは許可し、各差分が意味不変であることを benchmark test で確認する。
- [ ] performance 比較時は base/head に同じ harness revision を使う。API 差で同一 source が動かない場合は `/tmp` の version-specific adapter だけで同じ normalized workload contract へ合わせ、repository に互換 shim を追加しない。
- [ ] harness 追随が measurement 区間や setup 内容を変える場合は、当該 production Phase の直前に新 harness で base/head を再 baseline してから進む。

### 7.4 完了条件

- [ ] 既知 failure と今回の regression を区別できる。
- [ ] intentional change と保持すべき数値/出力を一覧化できる。
- [ ] Phase 10 で旧/new benchmark harness を比較できる基準 artifact がある。

## 8. Phase 1 — pure config と ImGui frame-order の先行修正

対象: AQ-003 の config 部分、AQ-011 の correctness 部分

### 8.1 pure RuntimeConfig loader

主対象:

- `src/grafix/core/runtime_config.py`
- `src/grafix/api/render.py`
- `src/grafix/api/runner.py`
- `src/grafix/core/font_resolver.py`
- `src/grafix/core/output_paths.py`
- `src/grafix/interactive/runtime/scene_runner.py`
- `src/grafix/interactive/runtime/mp_draw.py`
- benchmark を除く `src/grafix/devtools/`

実施:

- [ ] config path 探索、YAML parse、merge、validation を副作用のない `load_runtime_config(...)` / report API にする。
- [ ] `runtime_config()` は引数なし default-discovery の pure convenience として残してよいが、mutable path、process cache、session scope を持たせない。
- [ ] `RenderSession` は構築時に `RuntimeConfig` を一度だけ確定し、その object を全 consumer へ渡す。
- [ ] `runtime_config_scope()`、`RenderSession._config_stack`、`_EXPLICIT_CONFIG_PATH`、process-global config/report cache、`set_config_path()` を削除する。
- [ ] explicit config を使う CLI/doctor/stub generator は pure loader を直接呼ぶ。
- [ ] output path、capture、font、preset、worker が評価中に config を再探索しないよう、確定済み config を明示渡しする。
- [ ] `src/grafix/devtools/benchmarks/**` は workload/metric を変更せず、必要になった internal import 追随だけを別差分として記録する。

テスト:

- [ ] config A/B の session を交互、非 LIFO close、thread 実行し、metadata/output が混ざらない。
- [ ] config load failure が既存 session や別 session の config を変更しない。
- [ ] CLI、doctor、stub generation が明示 config で同じ結果を返す。
- [ ] default discovery の CWD/HOME precedence と diagnostic report を維持する。
- [ ] session create/close が process-wide config state を変更しない。

### 8.2 ImGui IO 同期順の最小修正

Phase 4 の backend 再編を待たず、現 frame の correctness だけを先に直す。

- [ ] `sync_io -> imgui.new_frame() -> render` の順へ変更する。
- [ ] 初回 frame の display size、framebuffer scale、delta time を fake backend で固定する。
- [ ] この change set では context owner や backend class の大規模移動を行わない。
- [ ] Phase 4 で同じ call-order test を新 backend contract へ移す。

### 8.3 Phase 1 完了条件

- [ ] process-global config scope/cache/path mutation が render/evaluation path から消える。
- [ ] config A/B session の任意 close 順/thread isolation が成立する。
- [ ] ImGui は現在 frame の IO 値で開始する。
- [ ] focused test、ruff、mypy が通る。

## 9. Phase 2 — catalog、評価 identity、font、preset

対象: AQ-001、AQ-002、AQ-003 の preset 部分、AQ-007

主対象:

- `src/grafix/core/op_registry.py`
- `src/grafix/core/effect_registry.py`
- `src/grafix/core/primitive_registry.py`
- `src/grafix/core/builtins.py`
- `src/grafix/core/operation_selector.py`
- `src/grafix/core/realize.py`
- `src/grafix/core/font_resolver.py`
- `src/grafix/core/primitives/text.py`
- `src/grafix/core/preset_registry.py`
- `src/grafix/api/effects.py`
- `src/grafix/api/primitives.py`
- `src/grafix/api/preset.py`
- `src/grafix/api/presets.py`
- `src/grafix/interactive/runtime/source_reload.py`

新規候補:

- `src/grafix/core/authoring_definitions.py`
- `src/grafix/core/operation_declaration.py`
- `src/grafix/core/operation_catalog.py`
- `src/grafix/core/evaluation_context.py`
- `src/grafix/core/font_resources.py`
- `src/grafix/core/preset_catalog.py`

### 9.1 neutral schema と immutable catalog

- [ ] meta/defaults/param_order/ui_visible を持つ immutable `ParameterOpSchema` を evaluator から分離する。
- [ ] immutable `OpDeclaration`、`EvaluationOpRef`、`EffectStepRef`、評価用 `OpSpec` を分ける。`OpDeclaration` は schema と evaluator/cache contract の構築材料、`EvaluationOpRef` は DAG が保持する kind/name/evaluation fingerprint、`EffectStepRef` は遅延 effect step が保持する evaluation/schema 両方の参照とする。
- [ ] catalog entry は geometry に影響する `EvaluationSpecFingerprint` と、selector/GUI にだけ影響する `ParameterSchemaFingerprint` を別々に持つ。
- [ ] mutable builder と immutable `OperationCatalog` snapshot の責務を分ける。
- [ ] catalog snapshot は generation 内で変更せず、既存 `RealizeSession` は後続 registration/reload を観測しない。
- [ ] bounded `RealizeCacheStore` を catalog generation の外側に置き、親 `RenderSession` / `SceneRunner` が所有する。
- [ ] 新 generation の `RealizeSession` は同じ cache store を借用できるが、参照 entry と evaluation context の fingerprint を含む key で安全性を保つ。

### 9.2 registration の単一路

- [ ] `@primitive` / `@effect` / `@preset` は immutable declaration を作り、`RegistrationTarget.register()` が受理する一経路へ統一する。decorator 自身は live evaluator/preset catalog を変更しない。
- [ ] scoped target がない通常 module import 用に、kind/name ごとの最新 operation/preset declaration だけを持つ `DefaultAuthoringDefinitions` を置く。これは公開 authoring convenience に限定し、評価中には参照しない。
- [ ] default authoring definitions の register/overwrite/snapshot は短い lock 内で atomic に行い、session/draw/evaluation はその lock も mutable mapping も保持しない。
- [ ] `overwrite=False` の同名 operation/preset 定義は target 内 duplicate error、operation の `overwrite=True` はその name の declaration だけを置換する。全 catalog の revision 更新や `replace_all()` は提供しない。
- [ ] builtin manifest は kind/name/module/callable attribute を持つ静的データにし、各 builtin decorator が作った declaration を元 callable へ付与する。
- [ ] builtin module は scoped target の有無や import 順に関係なく default authoring definitions へ登録しない。bootstrap は `import_module()` 後、module cache 上の callable attribute から付与済み declaration を回収して builder へ登録する。
- [ ] central name→module map と builtin declaration 回収をこの manifest 一つに統一し、decorator side effect と二重に live 登録しない。
- [ ] custom module/source reload と config preset load は scoped registration target に candidate を作り、成功時だけ immutable snapshot を確定する。
- [ ] draw/evaluator 呼び出し中は immutable catalog を短時間だけ束縛し、`G` / `E` / selector/parameter resolution は必ずその snapshot を使う。
- [ ] catalog 束縛外の `G.<name>` / `E.<name>` / `catalog()` / `describe()` は、builtin catalog と default authoring operation snapshot を使う。新 session も構築時に snapshot し、実行中の default 上書きを観測しない。
- [ ] `P` は draw 中に束縛された session `PresetCatalog`、束縛外では default authoring preset snapshot だけを使う。束縛外の config path autoload は削除し、config preset は session/runner の candidate load に限定する。
- [ ] `EvaluationOpRef` と session catalog の version が一致しない DAG は realization 前に失敗させ、同名 latest spec への暗黙 fallback を禁止する。
- [ ] 通常の `E.<name>(...)` は step 作成時の catalog entry で explicit kwargs を検証し、`EffectStepRef` と canonical raw args を固定する。適用時の default/parameter resolution もその exact entry で行い、entry がなければ node 化前に mismatch とする。
- [ ] effect selector は target-specific validation を適用時の bound catalog だけで完結させる。作成時 schema と適用時 schema を混ぜず、selector schema ref が不一致なら全体を現 catalog で再解決するのではなく明示 mismatch とする。
- [ ] source/config loader 管理 module の decorator は scoped candidate だけへ登録し、default authoring definitions へ漏らさない。通常 import 済み module は decorator 実行済みの default declaration を再利用する。
- [ ] 旧 global registry swap、旧登録 helper、互換 alias を削除する。

テスト:

- [ ] module scope の `@primitive` / `@effect` / `@preset` 定義直後に、session 束縛外で `G.<name>` / `E.<name>` / `P.<name>` を使える。
- [ ] custom 定義を持つ module を通常 import した後に作った `RealizeSession` が、その module を再実行せず definition snapshot を使える。
- [ ] session A の構築後に、意味を変更した同名 declaration を `overwrite=True` で登録しても A は旧 catalog を使い、新 session B だけが新 version を使う。
- [ ] 通常 module-scope preset と config-scoped preset を別 session へ合成でき、同一 catalog 内の同名衝突だけを deterministic duplicate error にする。
- [ ] builtin module を bootstrap 前に direct import しても default authoring definitions は不変であり、後の bootstrap が module 再実行なしで declaration を一度だけ回収する。
- [ ] builtin の direct-import→bootstrap、bootstrap→direct-import、全 builtin 一括 bootstrap の順序で catalog/fingerprint/stub が一致する。
- [ ] source reload/config preset load の成功/失敗、通常 import、builtin bootstrap の declaration が互いの registration target へ漏れない。
- [ ] `E` step 作成→definition overwrite→session A/B での適用を確認し、旧 schema の引数を新 evaluator へ渡さない。

### 9.3 per-operation fingerprint の lineage

- [ ] fingerprint は callable object id、process-local counter、catalog generation ID、全体 revision にせず、canonical declaration signature の bytes から SHA-256 等で決定的に導出した opaque な typed value とする。
- [ ] absolute path、source line、registration/import order を signature へ混ぜない。同じ code/config/dependency version は fresh process、別 checkout path、別 import orderでも同じ fingerprint にする。
- [ ] default authoring declaration は snapshot ごとに再発行しない。`overwrite=True` でも semantic signature が同じなら同じ fingerprint、signature が変わったときだけ該当 name の fingerprint が変わる。
- [ ] source reload の candidate builder は直前の成功 catalog を seed にし、`(kind, name, source owner)` と declaration signature が一致する entry の evaluation/schema fingerprint を継承する。evaluator/spec object は candidate callable から新しく作り、旧 module namespace を保持しない。
- [ ] declaration signature は、位置情報を除いた callable code/定数、canonical 化可能な defaults・kwdefaults・closure、decorator option、schema、および evaluator ABI version から作る。`ui_visible` callable は schema signature 側、external-dependency hook は evaluation signature 側へ含める。
- [ ] code が実際に参照する global/callable も canonical fingerprint 化する。参照した module dependency は version/source digest、module-local constant/helper は値/callable fingerprint を使い、owner file 全体の digest は混ぜない。
- [ ] canonical 化不能な動的 dependency を持つ content-cached declaration は登録時に拒否し、明示 args/external-dependency hook へ移す。`cache_policy="none"` で動的 state を意図する declaration は、stable な decorator `version` を必須にし、その version を definition fingerprint に含める。
- [ ] builtin/native/Numba helper で callable 本体から十分な signature を得られない場合は、manifest 側の明示 evaluator ABI version を使う。暗黙の object id や process nonce へ fallback しない。
- [ ] candidate 内の追加/削除/変更 name だけを差分として扱い、無関係 entry の fingerprint を継承する。candidate failure は lineage も catalog も publish しない。
- [ ] `EvaluationSpecFingerprint` が同じで schema だけ変わる場合は geometry cache を維持し、selector/schema cache だけを失効する。evaluator/cache policy/n_inputs/external dependency contract の変更は evaluation fingerprint を更新する。

テスト:

- [ ] source を同内容で再実行して新しい function object が生成されても、安定 signature の entry は fingerprint を継承する。
- [ ] operation B だけの追加/変更/削除では、operation A の `EvaluationOpRef`、`GeometryId`、warm cache hit が変わらない。
- [ ] closure/default/decorator option/evaluator ABI/external dependency hook の変更は該当 entry だけ miss にする。
- [ ] canonical 化不能な content dependency は登録 error、`cache_policy="none"` で version 指定済みの dynamic operation は CPU/GPU cache を迂回する。
- [ ] clean subprocess と import 順を変えた subprocess で builtin/custom の evaluation/schema fingerprint、`GeometryId`、serialized DAG/checksum が一致する。

### 9.4 `EvaluationContext`、cache key、resource ownership

実施:

- [ ] frozen `EvaluationContext` と `EvaluationFingerprint` を定義する。
- [ ] `EvaluationFingerprint` は generation 中に固定される quality と effective config を持ち、可変な external asset fingerprint は `GeometryCacheKey` の別 field として lookup ごとに合成する。
- [ ] `GeometryCacheKey` を frozen/hashable dataclass にし、CPU cache、inflight、`RealizedLayer`、GPU cache key を一括更新する。
- [ ] `G` / `E` が解決した `EvaluationOpRef` を各 node と `GeometryId` に含め、root id が参照 operation fingerprint を推移的に表すようにする。全 registry revision と毎 frame の全 DAG operation 走査を削除する。
- [ ] external-dependency provider の一覧だけを geometry ごとに memoize し、毎 frame 全 DAG を無条件走査しない。
- [ ] external asset 自体は root cache lookup 前に軽量 stat で再検証し、stat 変更時だけ content digest を再計算する。
- [ ] evaluator 呼び出し中だけ quality/context を束縛し、caller ambient state を cache contract にしない。
- [ ] `RealizeSession` は context/resources/cache store を借用し、in-flight 評価だけを close する。
- [ ] headless と interactive の owner/close 順を contract test で固定し、double-close を禁止する。

テスト:

- [ ] 同一 DAG を draft→final、final→draft の両順で評価し、key と結果が混ざらない。
- [ ] generation A/B が cache store を共有した状態で、無関係 op 変更は hit、使用 op 変更は miss になる。
- [ ] immutable catalog A を使う既存 session は catalog B 作成後も A の結果を返す。
- [ ] same context の warm hit、inflight、LRU、transaction rollback を維持する。
- [ ] heavy effect の draft/final checksum と resource limit を確認する。

### 9.5 selector と parameters/registry cycle

- [ ] selector は `ParameterOpSchema` だけを合成し、fake evaluator を evaluation catalog へ登録しない。
- [ ] selector catalog/cache は evaluator catalog と別 fingerprint を持つ。
- [ ] parameters prune/save finalization は registry module を importせず、known-operation snapshot を application 境界から受け取る。
- [ ] direct persistence writer と session finalization/prune を別責務にする。
- [ ] API の import-order comment と遅延 import workaround を削除する。

### 9.6 font asset identity と bounded resource

実施:

- [ ] frozen `FontAssetFingerprint` を canonical path、face index、file stat、content digest から作る。
- [ ] font request は固定済み config から lookup ごとに解決し、探索候補と最終 canonical path を fingerprint 前段で確定する。新しい優先 path の出現や既存 path の消失も再解決で観測する。
- [ ] `OpSpec` の最終 cache contract に external dependency hook を一つだけ追加し、text が font fingerprint を返す。
- [ ] cache lookup 前の dependency preflight は、fingerprint と同じ bytes から作った `ResolvedFontLease` を返し、evaluator は path を再解決せず同じ lease を使う。
- [ ] child text dependency を root key に反映する。
- [ ] `TextRenderer` singleton/class cache を削除し、`EvaluationResources` 配下の bounded LRU instance にする。
- [ ] LRU eviction 後は asset を再 fingerprint して安全に再解決し、上限到達を user-facing error にしない。
- [ ] `clear()` / `close()` で TTFont/glyph resource を解放する。
- [ ] 同一 session 中の font file 変更を許容し、後続 lookup で新 lease/key/output を使う。session の immutable evaluation context を変更したことにはしない。

テスト:

- [ ] config A/B の同名 font、face index 違い、探索優先 path の出現/消失、同一路径の内容差替えで別 key になる。
- [ ] 同一 session で同一路径の font を置換すると後続評価が新 fingerprint/output を返し、置換がなければ warm hit する。
- [ ] preflight asset と evaluator asset が一致する。
- [ ] LRU eviction、clear、close、例外 cleanup、反復 session で resource が線形増加しない。
- [ ] 同一 font/context の glyph geometry と layout は baseline と一致する。

### 9.7 immutable `PresetCatalog`

実施:

- [ ] frozen `PresetCatalog` を同じ declaration/registration-target 基盤で構築し、default authoring preset snapshot と config/source candidate を session composition root で合成する。
- [ ] `_AUTOLOAD_KEY`、process-global preset registry、既ロード path の process 累積判定を削除する。
- [ ] preset module を config/source fingerprint ごとの candidate namespace で実行し、成功時だけ catalog を確定する。
- [ ] duplicate は一 catalog 内だけで検出し、別 session の同名 preset を許可する。
- [ ] `P` は draw 呼び出し中に束縛された catalog snapshot、束縛外では default authoring preset snapshot を参照する。
- [ ] 束縛外 `P` の config-directory 暗黙 autoload を削除する。config-scoped preset を直接使う必要がある tool/test は explicit catalog/session を作り、その scope で呼ぶ。
- [ ] source reload/worker は generation 固有 catalog を所有し、既存 session を in-place 変更しない。

テスト:

- [ ] config A/B が同名 preset の別実装を同時に使える。
- [ ] 通常 module import の `@preset` は module 再実行なしで束縛外 `P` と新 session の双方から見える。
- [ ] default authoring preset と config candidate の同名は当該 session の構築だけを duplicate error にし、default store や別 session を変更しない。
- [ ] session A/B の任意 close 順、thread、worker で catalog が混ざらない。
- [ ] failed import、duplicate、source delete、reload rollback で部分 catalog が残らない。
- [ ] 既存 session は旧 snapshot、新 session/reload generation は新 snapshot を見る。

### 9.8 Phase 2 完了条件

- [ ] registration mechanism が一つで、selector schema と evaluator catalog が分離される。
- [ ] module-scope decorator、束縛外 `G` / `E` / `P`、session snapshot、source/config reload の catalog 選択規則が test で固定される。
- [ ] builtin direct import/import-cache/bootstrap の順序が default authoring definitions と catalog 結果へ影響しない。
- [ ] `E` step が evaluation/schema ref を作成時に固定し、置換後の別 entry と混成されない。
- [ ] per-op lineage により同内容 reload と無関係 op 変更では hit、使用 op 変更では miss になる。
- [ ] source reload が module-global registry 差替えなしで動く。
- [ ] cache invalidation が evaluation context と参照 operation/asset に限定される。
- [ ] process-global preset autoload と module-global font cache がない。
- [ ] parameters 配下から effect/primitive registry import が 0 件である。
- [ ] focused test、ruff、mypy が通る。

## 10. Phase 3 — `ParamStore` の transactional rollback、command、read view

対象: AQ-004

主対象:

- `src/grafix/core/parameters/store.py`
- `src/grafix/core/parameters/memento.py`
- `src/grafix/core/parameters/variations.py`
- `src/grafix/api/variation_batch.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/table.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/interactive/parameter_gui/variation_panel.py`

### 10.1 exact transactional rollback

- [ ] owner-bound、one-shot、opaque な `ParamStoreRollback` を core に定義する。
- [ ] `ParamStore.begin_transient_rollback()` の context manager を、variation batch 用の唯一の全体退避・rollback API にする。
- [ ] rollback snapshot は persisted/runtime の論理 state、revision counter、change log を独立 copyし、observer/lock/derived cache/live container を含めない。
- [ ] 正常終了・例外終了の双方で開始時の論理 state と counter を exact に戻し、observer/history notification は発生させない。
- [ ] rollback 後は restored state と一致していても derived snapshot/model cache を破棄し、次回 query で再構築する。
- [ ] active history transaction 中、別 store、二重使用、rollback scope の不正 nesting を拒否する。
- [ ] `variation_batch.py` の `_ExactParamStoreSnapshot`、`vars(store)`、`_variations_ref()`、`_snapshot_cache` 参照を削除する。
- [ ] batch item failure と batch-level failure の双方で logical state/revision/runtime counter を復元する。

### 10.2 immutable query と狭い command

- [ ] `ParamRuntimeView` などの frozen/read-only view を用意し、outer layer の `_runtime_ref()` を置き換える。
- [ ] collapsed headers は `frozenset` snapshot で読み、`set_collapsed(...)` / `set_all_collapsed(...)` command で変更する。
- [ ] command 内部で history observation と revision 更新を一度だけ行う。
- [ ] variation、locked/favorite keys、effect order、range/MIDI update に必要な batch query/command を列挙し、必要なものだけ追加する。
- [ ] private container を返す別名 accessor は作らない。

### 10.3 pure table boundary

- [ ] table renderer は immutable row/runtime/collapse snapshot を受け取る。
- [ ] renderer は `TableEdits` のような immutable result を返し、描画中に store を変更しない。
- [ ] store bridge は result を core command で commit する。
- [ ] no-op、複数 edit、collapse、MIDI learn、effect-order command の history 単位を固定する。

テスト/architecture gate:

- [ ] batch 成功、unknown variation、item exception、publish exception 後の state を比較する。
- [ ] rollback 後に state/revision counter は開始時と一致し、stale derived cache は再利用されない。
- [ ] rollback は observer/history event を増やさず、通常 command だけが変更時に一度通知する。
- [ ] collapsed command の no-op は revision 不変、変更は一度だけ進む。
- [ ] undo/redo、variation、persistence/recovery、reconcile が通る。
- [ ] `src/grafix/api` / `interactive` から `vars(store)`、`_variations_ref`、`_collapsed_headers_ref`、`_snapshot_cache`、private `_touch` を禁止する test を追加する。

完了条件:

- [ ] API/interactive の `ParamStore` private state access が 0 件である。
- [ ] GUI renderer が live mutable store container を受け取らない。
- [ ] variation batch が core-owned rollback scope 以外で全体復元しない。

## 11. Phase 4 — ImGui/GL backend と interactive contract

対象: AQ-011、AQ-008 の interactive 部分

主対象:

- `src/grafix/interactive/parameter_gui/pyglet_backend.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/interactive/gl/draw_renderer.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/interactive/runtime/recording_system.py`
- `src/grafix/interactive/runtime/diagnostics.py`
- `src/grafix/interactive/runtime/frame_clock.py`
- `src/grafix/interactive/runtime/monitor.py`

### 11.1 backend correctness

- [ ] `PygletImguiBackend` を context/renderer/font-texture/frame lifecycle の owner にする。
- [ ] `begin_frame(dt)` が context 選択、IO 同期、wheel 正規化、`imgui.new_frame()` をこの順で行う。
- [ ] `render()` が `imgui.render()`、GL clear、backend render を所有する。
- [ ] `ParameterGUI` から ImGui context create/destroy、renderer、pyglet GL clear を削除する。
- [ ] 旧 private/free backend helper を削除し、shim を残さない。

### 11.2 GL context ownership

- [ ] `DrawRenderer.ctx` を private にする。
- [ ] `begin_frame(...)`、framebuffer bind/viewport、`read_frame_rgb24(...)` を renderer API にする。
- [ ] recording system は untyped `screen: object` ではなく、明示 bytes/frame object を受け取る。
- [ ] runtime から `.ctx.screen` への到達をなくす。

### 11.3 neutral interactive contracts

- [ ] diagnostics event/center contract を `interactive/diagnostics.py` へ置く。
- [ ] clock/transport contract を `interactive/transport.py` へ置く。
- [ ] immutable telemetry snapshot と Protocol を `interactive/telemetry.py` へ置き、collector/monitor 実装は runtime に残す。
- [ ] GL/MIDI/GUI は runtime concrete class でなく neutral contract に依存する。
- [ ] 旧 runtime import path は削除し、re-export shim を作らない。

テスト:

- [ ] fake backend で `sync_io -> new_frame -> render` の順序を固定する。
- [ ] 初回 frame の display size、framebuffer scale、delta time が現在 frame に反映される。
- [ ] Retina/non-Retina resize、font texture refresh、close failure の全 cleanup を確認する。
- [ ] renderer readback、recording frame、resource close を focused test する。
- [ ] `interactive/gl`、`midi`、`parameter_gui` から `interactive.runtime` import を禁止する architecture test を追加する。

完了条件:

- [ ] GUI に backend context/GL clear の詳細がない。
- [ ] runtime に renderer context 内部参照がない。
- [ ] interactive sibling から composition layer への逆依存がない。

## 12. Phase 5 — capture infrastructure と publish lifecycle

対象: AQ-008 の capture 部分、AQ-009

主対象:

- `src/grafix/core/capture_provenance.py`
- `src/grafix/core/capture_manifest.py`
- `src/grafix/core/output_paths.py`
- `src/grafix/export/capture.py`
- `src/grafix/interactive/runtime/export_job_system.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/interactive/runtime/recording_system.py`

### 12.1 domain value と infrastructure の分離

- [ ] Frame が必要とする immutable provenance/manifest value だけを core-neutral な module に残す。
- [ ] `inspect`、filesystem、Git subprocess を使う provenance collection を API/export infrastructure へ移す。
- [ ] staging、fsync、link、rollback、publish を export infrastructure へ移す。
- [ ] output path/version family policy を export/application 側へ移す。
- [ ] core から subprocess、fsync、publish/path allocation policy をなくし、core→export dependency は作らない。

### 12.2 staging と late-collision lifecycle

新規候補:

- `src/grafix/export/capture_staging.py`
- `src/grafix/export/capture_publish.py`

実施:

- [ ] staging directory/work path の作成、validation、cleanup を一 owner にする。
- [ ] artifact+manifest+split-G-code family の path allocation を一実装にする。
- [ ] allocation→既存 atomic publish→late-collision retry を一つの狭い helper にする。
- [ ] `CaptureService.export`、worker parent commit、同期 SVG、video completed staging を同 lifecycle へ寄せる。
- [ ] video は完成済み staging を再 encode せず、候補 path だけを変えて retry する。
- [ ] format encode と manifest factory は format owner に残す。

テスト:

- [ ] broken symlink、artifact/manifest/split family collision、late collision、retry 上限を確認する。
- [ ] encode/publish/cleanup failure、rollback、worker late result、cancel/timeout を確認する。
- [ ] 成功/失敗後に不要 staging が残らない。recovery 用に残すべき video staging は明示される。
- [ ] output path、manifest JSON、artifact checksum を baseline と比較する。

完了条件:

- [ ] atomic commit/rollback の実装が一つである。
- [ ] path family 判定と late-collision loop が一つである。
- [ ] `DrawWindowSystem` に `tempfile`、`shutil`、`publish_capture_generation` の直接利用がない。
- [ ] core domain に Git subprocess、fsync、publish/path policy がない。

## 13. Phase 6 — `DrawWindowSystem`、`ParameterGUI`、runner の分割

対象: AQ-005、および AQ-004/AQ-009/AQ-011 の composition

### 13.1 `DrawWindowSystem`

新規候補:

- `src/grafix/interactive/runtime/capture_queue.py`
- `src/grafix/interactive/runtime/recording_session.py`
- `src/grafix/interactive/runtime/workspace_window_controller.py`

実施:

- [ ] capture intent、admission、worker poll/drain、通知を `CaptureQueue` に移す。
- [ ] recording transport pause/restore、window size lock/restore、first provenance、completed staging を `RecordingSession` に移す。
- [ ] two-window placement、visibility、workspace persistence を `WorkspaceWindowController` に移す。
- [ ] 既存 `window_layout.py` は pure calculation のまま維持する。
- [ ] DWS は renderer、SceneRunner、input、reload と frame call order の composition に絞る。
- [ ] constructor partial failure と `close()` の resource ownership を各 owner に閉じる。

### 13.2 `ParameterGUI`

候補は class 数ではなく、state lifetime と変更理由で採否を決める:

- `VariationController`: named variation と morph session
- `RangeEditController`: range-edit transaction の開始、preview、commit/cancel
- `ParameterGuiSessionState`: filter、table view、help、popup など純粋な frame 間 UI state
- MIDI learn は既存 `MidiSession`、effect order/reconcile は既存 command/panel 境界を使い、総合 `ParameterEditController` を新設しない

実施:

- [ ] variation save/load/rename/duplicate/delete/randomize/morph を controller へ移す。
- [ ] range edit の history transaction は専用 controller、MIDI/effect-order/reconcile は各既存 owner へ移す。
- [ ] filter、table view、help、popup など frame 間 state を session state にまとめる。
- [ ] reconcile、diagnostics、variation など既存 panel module を使い、panel class を量産しない。
- [ ] `ParameterGUI.draw_frame()` は backend begin/render、toolbar/panel 順、changed 集約だけにする。
- [ ] controller は ImGui を import せず unit test できるようにする。

### 13.3 `api.runner`

- [ ] `run()` は public 引数 validation、pure config load、component composition、loop、final close 順だけを持つ。
- [ ] screen bounds、Cocoa query、window placement、inspector state を platform/window policy owner へ移す。
- [ ] parameter persistence、MIDI/session recovery、thumbnail/capture を各 owner の明示 API で配線する。
- [ ] private MIDI shutdown helper など sibling private import を削除する。

テスト:

- [ ] coordinator 分割前後の observable frame call trace を比較する。
- [ ] capture FIFO/byte admission/shutdown deadline、recording restore、workspace multi-screen を owner 単位で確認する。
- [ ] GUI controller の command/history/no-op/undo を ImGui なしで確認する。
- [ ] constructor partial cleanup、各 close 経路、reload failure を確認する。
- [ ] existing shortcuts、panel order、persistence、MIDI fake、source reload を integration test する。

完了条件:

- [ ] DWS に path allocation、publish、recording resize state の詳細がない。
- [ ] GUI に variation/reconcile/range/MIDI mutation の詳細がない。
- [ ] runner に Cocoa/screen geometry/inspector state の詳細がない。
- [ ] 三者とも順序・配線を読むだけで主要 control flow を追える。
- [ ] LOC は合否基準にしないが、DWS、GUI、`run()` が実質的に縮小している。

## 14. Phase 7 — effect 共通 geometry kernel の分割

対象: AQ-006

新規 package:

- `src/grafix/core/geometry_kernels/packed.py`
- `src/grafix/core/geometry_kernels/planar.py`
- `src/grafix/core/geometry_kernels/grid.py`
- `src/grafix/core/geometry_kernels/raster.py`
- `src/grafix/core/geometry_kernels/marching.py`
- `src/grafix/core/geometry_kernels/resample.py`

実施順:

1. resample/filter
2. raster/EDT/SDF と marching
3. grid と planar/PCA/ring
4. packed geometry canonicalization

各 slice:

- [ ] 先に empty、degenerate、open/closed、multi-line、3D、fixed seed の characterization test を固定する。
- [ ] 関数本体を変更せず移動し、22 effect の import だけを更新する。
- [ ] Numba cold compile と warm execution を確認する。
- [ ] focused effect test と short benchmark を通してから次 slice へ進む。
- [ ] 同時に algorithm optimization、dtype、iteration order を変更しない。

全関数の exact move 後に、別 change set で side effect を整理する:

- [ ] diagnostic emission を数値 kernel の外側へ移す。
- [ ] 移動前後の diagnostic event、source、effective value を focused test で比較する。
- [ ] この change set でも数値 algorithm、dtype、iteration order は変更しない。

packed helper:

- [ ] `util.empty_geom/pack_polylines` と `realized_geometry` 側 helper の保証差を test で固定する。
- [ ] strict canonical `pack_polylines` / empty representation を一実装へ統一する。
- [ ] option で旧挙動を抱えず、全 callsite を canonical contract へ更新する。
- [ ] 最後に `src/grafix/core/effects/util.py` を削除する。

完了条件:

- [ ] `effects/util.py` と duplicate packed helper が存在しない。
- [ ] effect 間直接 import が 0 件である。
- [ ] kernel import graph に cycle がない。
- [ ] intentional change 以外の coords/offsets/dtype/order/checksum が一致する。

## 15. Phase 8 — G-code の stroke-order contract 明示

対象: AQ-010

主対象:

- `src/grafix/export/gcode.py`
- `src/grafix/core/gcode_params.py`
- G-code tests/docs

設計判断:

- [ ] 現行 geometry contract に存在しない face/group metadata を core DAG へ追加しない。
- [ ] `_polyline_face_block_ids()` と「3頂点以上は ring」heuristic を削除する。
- [ ] clipping 前の input polyline 順を semantic boundary とし、異なる元 polyline を並べ替えない。
- [ ] `optimize_travel` は同じ元 polyline から clipping で生じた fragment の順序/向きだけを最適化する。
- [ ] `bridge_draw_distance` も異なる元 polyline 間には線を追加しない。
- [ ] 現在の cross-polyline optimization 低下は、誤った face 推測をなくすための intentional breaking change として docs/結果へ記録する。
- [ ] 将来 cross-polyline optimization が必要になった場合は、export-side grouping artifact を別計画で設計し、arbitrary core metadata で補わない。

テスト:

- [ ] 3点以上の open polyline を face と扱わない。
- [ ] multiple face、hole、`remove_boundary=True/False` で input polyline 順が保持される。
- [ ] optimizer と bridge が元 polyline 境界を横断しない。
- [ ] clipping で一つの polyline が複数 fragment になった場合だけ optimization が働く。
- [ ] `optimize_travel=False/True` の新しい明示 contract を確認する。
- [ ] pen-down path、bed bounds、安全 command、決定性を semantic compare する。
- [ ] 意図した stroke order 変更は plan 実施結果へ明記する。

完了条件:

- [ ] exporter が頂点数、閉曲線らしさ、producer 順から face を推測しない。
- [ ] G-code が input polyline 順を semantic boundary として保持する。
- [ ] custom geometry を含む optimizer/bridge の縮小 contract が文書化される。

## 16. Phase 9 — production 全体検証（pre-refactor benchmark contract）

Phase 10 で測定器の責務を変更する前に、production 改修を pre-refactor workload/metric contract で確定する。

### 16.1 automated gates

- [ ] `PYTHONPATH=src pytest -q`
- [ ] `ruff check .`
- [ ] `mypy src/grafix`
- [ ] generated stub を fresh subprocess で生成し、意図しない差分がない。
- [ ] architecture test、import clean-subprocess test、resource leak focused test を通す。
- [ ] SVG/PNG/G-code/manifest の intentional change 以外の checksum/semantic contract が一致する。

### 16.2 performance gates

- [ ] Phase 0 と同じ workload semantics、case、profile、measurement algorithm で short/long benchmark を実行する。
- [ ] internal import 追随以外の harness 差分がないことを Phase 0 source inventory と照合する。
- [ ] status、checksum、hard contract は intentional change 以外一致する。
- [ ] median が 10% 超悪化し、かつ baseline/head の揺らぎの 3 MAD を超えた場合は Phase を未完了に戻す。
- [ ] p95 が 15% 超悪化した場合は再測定し、再現すれば原因を解消する。
- [ ] `--allow-incompatible` で差分を隠さない。
- [ ] cache hit、font resolution、registry lookup、GUI frame、capture publish を focused measurement する。
- [ ] font/session/window の反復 create/close で memory/resource が線形増加しない。

### 16.3 macOS 実機 GUI

- [ ] `parameter_gui=False/True` の両方で起動する。
- [ ] draw/GUI window、resize、可能なら Retina/non-Retina 間移動を確認する。
- [ ] float/int/bool/choice、variation、undo/redo、persistence、source reload を確認する。
- [ ] draft preview と final capture の quality を確認する。
- [ ] SVG、PNG、G-code、短時間 video、late collision、staging cleanup を確認する。
- [ ] reload failure 時に last-good scene と diagnostics が維持される。
- [ ] GUI/draw window の各終了経路で worker/ffmpeg/GL resource が残らない。
- [ ] MIDI は fake/virtual port を必須、物理 device は利用可能時だけ確認する。

完了条件:

- [ ] production code の全 AQ 指摘が、pre-refactor benchmark contract で regression なく解消されている。
- [ ] 長時間/GUI/外部 tool の未実施項目を残したまま完了扱いにしない。
- [ ] Phase 10 の直前に実行に必要な tree（`src/`、benchmark tests/tools、`pyproject.toml`、必要 config）を `/tmp/grafix-architecture-phase9-reference/` へ相対 path のまま保存し、file hash manifest を作る。
- [ ] snapshot の `src/grafix/devtools/benchmarks` が snapshot 側 production code と独立 `PYTHONPATH` で実行できることを確認する。

## 17. Phase 10 — benchmark runner の責務分割

対象: AQ-012

現行 `src/grafix/devtools/benchmarks/runner.py` を次へ分ける。

- `definition.py`: `CaseDefinition` と静的 contract
- `catalog.py`: case collection、selection、stable ordering
- `executor.py`: in-process/fresh-process execution、timeout、child lifecycle
- `metrics.py`: aggregation、percentile、cache/custom metric
- existing workload modules: parameter/effect/primitive/renderer/mp/system の setup/workload/postprocess
- `runner.py`: composition と実行入口だけ

実施:

- [ ] `/tmp/grafix-architecture-phase9-reference/` を read-only な旧 harness/production 比較環境として使い、runner file 単体コピーには依存しない。
- [ ] import DAG を次に固定する。
  - `schema.py` / `definition.py`: 最下層の immutable model/contract
  - `metrics.py`: schema/model だけへ依存
  - workload modules: definition と対象 production API へ依存
  - `catalog.py`: definition と workload modules へ依存
  - `executor.py`: definition、schema、metrics へ依存し、catalog を知らない
  - `runner.py`: catalog と executor を composition する
- [ ] inline workload を既存 subsystem module へ移す。
- [ ] CLI/composition root に実責務がある場合だけ `runner.py` を残し、re-export shim にはしない。
- [ ] workload、metrics、process supervision を runner から削除する。
- [ ] public/devtools import と test を新 canonical path へ一括更新する。

同値検証:

- [ ] Phase 9 snapshot の旧 runner と working tree の新 runner で同一 workload を実行する。
- [ ] volatile な timestamp/PID/duration を除き、case ID、順序、status、checksum、hard contract、JSON schema、CLI exit code を比較する。
- [ ] timeout、exception、cancel、child cleanup、calibration、cold/warm を比較する。
- [ ] benchmark compare の判定結果を比較する。
- [ ] short suite 後に orphan child process が残らない。
- [ ] architecture test で runner に workload/metrics/executor 実装が戻らないようにする。

完了条件:

- [ ] runner の定義・実行・集計・workload 責務が分離されている。
- [ ] schema/case/checksum/CLI contract が旧 runner と一致する。
- [ ] 互換 re-export module を追加していない。

## 18. Phase 11 — 文書同期と最終監査

### 18.1 docs/stubs

- [ ] `architecture.md` の layer、composition root、session/cache contract を更新する。
- [ ] `docs/architecture_visualization.md` の依存矢印と ParamStore 更新規則を更新する。
- [ ] `README.md` の config、preset、render、custom operation、G-code contract を更新する。
- [ ] 公開 API docstring と generated stub を最終実装に同期する。
- [ ] 破壊的変更一覧を migration shim なしの更新手順として記録する。

### 18.2 final audit

- [ ] AQ-001〜AQ-012 の各根拠箇所を再読し、解消/非該当/未完了を記録する。
- [ ] `rg` と architecture test で削除対象 global/private/import pattern が 0 件であることを確認する。
- [ ] full pytest、ruff、mypy、stub、benchmark、GUI smoke の最終結果を本ファイルへ追記する。
- [ ] `git diff --check` を通す。
- [ ] 依頼外差分へ触れていないことを `git status --porcelain` で確認する。
- [ ] 未完了項目を隠さず、status を **完了** または **一部未完了** に更新する。

## 19. 性能・品質の停止条件

次の場合は後続 Phase へ進まず、当該 Phase 内で設計を修正する。

- 同一 evaluation context で cache hit または geometry checksum が意図せず変わる。
- config/preset/font/session の isolation test が一つでも失敗する。
- builtin/custom の import 順または fresh process で catalog、fingerprint、`GeometryId`、serialized DAG、stub が変わる。
- ParamStore rollback 後に state/revision counter が開始時と異なる、stale cache を再利用する、または observer/history event が増える。
- capture の no-overwrite、rollback、late-collision safety が弱くなる。
- kernel 移設だけの change set で数値/checksumが変わる。
- G-code が元 input polyline 境界を越えて optimize/bridge する。
- close failure 時に後続 resource cleanup が実行されない。
- performance gate を再測定しても超過する。
- `DefaultAuthoringDefinitions` 以外に、評価/session/config/preset/resource ownership のための新しい process-global mutable state が必要になる。

## 20. 避ける実装

- global state を隠す service locator、汎用 DI container、event bus。
- `DefaultAuthoringDefinitions` を session 評価中に読む、source/config reload の差替え target にする、または evaluator/catalog/cache/resource を保持させる。
- `EvaluationContext` や catalog を untyped dictionary にする。
- caller が session を二つ作る運用だけで cache bug を回避する。
- `ParamStore` private container を返す「公開 accessor」。
- coordinator method を一対一で別 class へ移すだけの分割。
- capture、recording、workspace、MIDI を一つの万能 manager に集約する。
- `effects/util.py` を同じ大きさの `common.py` / `misc.py` へ改名する。
- G-code 用 arbitrary metadata を geometry 全般へ無制限に追加する。
- production 改修と benchmark harness 改修を同じ Phase で行う。
- 行数削減だけを目的に protocol/value object/class を増やす。

## 21. 全体完了条件

- [ ] AQ-001〜AQ-012 が Phase、実装、test、結果へ一対一で追跡できる。
- [ ] quality/config/font/op spec を含む cache identity が一箇所に定義される。
- [ ] process-global runtime config/preset ownership が render/evaluation path から消える。
- [ ] external font change は同一 session でも再検証され、preflight fingerprint と evaluator が使う bytes が一致する。
- [ ] API/interactive から `ParamStore` private state access が 0 件になる。
- [ ] registration が単一方式で、selector schema と evaluator catalog が分離される。
- [ ] module-scope `@primitive` / `@effect` / `@preset` と builtin direct import の発見規則が deterministic で、config/source candidate へ漏れない。
- [ ] `EvaluationOpRef` / `EffectStepRef` の version mismatch を暗黙 fallback せず、per-op fingerprint lineage が同内容 reload と無関係 op 変更で安定する。
- [ ] evaluation/schema fingerprint と `GeometryId` が clean subprocess、別 checkout path、import 順をまたいで安定する。
- [ ] unrelated operation/selector 更新で geometry cache が失効しない。
- [ ] core domain に Git subprocess、fsync、publish/path allocation policy が残らない。
- [ ] interactive sibling から runtime composition layer への import が 0 件になる。
- [ ] `DrawWindowSystem`、`ParameterGUI`、runner が順序・配線だけを所有する。
- [ ] `effects/util.py` と packed helper 重複がなくなる。
- [ ] G-code face heuristic が削除され、input polyline order contract が使われる。
- [ ] GUI/runtime に backend の `.ctx.screen` などの内部到達がない。
- [ ] benchmark runner が definition/catalog/executor/metrics/workloads に分かれる。
- [ ] full pytest、ruff、mypy、stub、performance gate、macOS GUI smoke が完了する。
- [ ] compatibility shim、二重実装がなく、process-global mutable state は公開 decorator の `DefaultAuthoringDefinitions` だけに限定され、評価/session/config/preset/resource ownership には使われない。
- [ ] `architecture.md` と visualization が実装に一致する。
- [ ] 各 Phase の実測、intentional change、未実施事項が本ファイルに記録される。

## 22. 承認後の最初の実施単位

承認後は一度に全面改修せず、次の順で着手する。

1. Phase 0 の baseline を保存する。
2. config A/B isolation と ImGui IO 順序の failing regression test を追加する。
3. pure RuntimeConfig loader、`RenderSession` snapshot、frame-order 修正だけを実装して focused test を green にする。
4. その差分と実測を本ファイルへ記録する。
5. Phase 2 では先に schema/catalog/cache-store ownership を確定し、その後で draft/final、font A/B、preset A/B の test と実装へ進む。

この最初の単位が green になるまで、registry、GUI、capture、kernel の実装には着手しない。
