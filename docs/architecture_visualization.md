<!--
どこで: `docs/architecture_visualization.md`。
何を: 現行 `src/grafix/` の依存方向、snapshot、resource ownership、主要 flow の Mermaid 図。
なぜ: 実装を読む前に、state と変更理由の境界を視覚的に確認できるようにするため。
-->

# Grafix アーキテクチャ可視化

## 1. レイヤと依存方向

矢印は compile/runtime dependency の許可方向を表す。user sketch への callback と、decorator が
scoped registration target へ declaration を渡す流れだけはラベルで区別する。

```mermaid
flowchart LR
    sketch["User sketch / draw(t)"]
    api["grafix.api<br/>G / E / L / P / run / render / export"]
    core["grafix.core<br/>domain contracts"]
    kernels["grafix.core.geometry_kernels<br/>pure numeric kernels"]
    export["grafix.export<br/>encode / staging / publish"]
    runtime["grafix.interactive.runtime<br/>composition / window loop"]
    leaf["grafix.interactive leaf<br/>GL / MIDI / Parameter GUI"]
    neutral["grafix.interactive<br/>diagnostics / transport / telemetry"]
    tools["grafix.devtools<br/>CLI / stub / benchmark"]

    sketch -->|"public DSL"| api
    api --> core
    api --> runtime
    api --> export
    runtime --> core
    runtime --> export
    runtime --> leaf
    runtime --> neutral
    leaf --> core
    leaf --> neutral
    core --> kernels
    export --> core
    tools --> api
    tools --> core
    tools --> export
    runtime -.->|"invoke draw"| sketch
```

禁止する逆依存:

- `core -> api/export/interactive`
- `export -> api/interactive`
- `interactive -> api`
- `interactive` の GL/MIDI/GUI leaf `-> interactive.runtime`
- `core -> subprocess/fsync/publish/output-path policy`

`tests/architecture/test_dependency_boundaries.py` が import と主要 private reach-through を検査する。

## 2. Authoring から immutable catalog まで

```mermaid
flowchart TB
    builtin["Builtin manifest"]
    module["Normal imported module"]
    candidate["Config / source-reload candidate"]
    decorators["@primitive / @effect / @preset"]
    attached["Callable-attached immutable declaration"]
    defaults["DefaultAuthoringDefinitions<br/>authoring convenience only"]
    target["Scoped RegistrationTarget"]
    snapshot["AuthoringDefinitionsSnapshot"]
    opcat["OperationCatalog<br/>evaluator + evaluation fingerprint"]
    presetcat["PresetCatalog<br/>preset declaration"]
    guicat["ParameterGuiCatalog<br/>evaluator-free schema projection"]
    session["RenderSession / SceneRunner generation"]

    builtin --> decorators
    module --> decorators
    candidate --> decorators
    decorators --> attached
    module -->|"no scoped target"| defaults
    candidate -->|"registration_scope"| target
    builtin -->|"manifest bootstrap recovers attached declaration"| opcat
    defaults --> snapshot
    target --> snapshot
    snapshot --> opcat
    snapshot --> presetcat
    opcat --> guicat
    presetcat --> guicat
    opcat --> session
    presetcat --> session
```

重要な規則:

- decorator は live evaluator registry を変更しない。
- builtin declaration は default authoring store に入らず、manifest だけが bootstrap する。
- candidate は隔離した target 内で全体を構築し、成功時だけ snapshot を採用する。
- draw の外側の `P` は default authoring preset だけを参照し、config directory を暗黙 load しない。
- session/generation は構築後に default store の変更を観測しない。

## 3. Geometry identity と評価 cache

```mermaid
flowchart LR
    declaration["OpDeclaration"]
    evalfp["EvaluationSpecFingerprint"]
    schemafp["ParameterSchemaFingerprint"]
    g["G operation lookup"]
    estep["E step construction"]
    opref["EvaluationOpRef"]
    stepref["EffectStepRef"]
    dag["Geometry DAG / GeometryId"]
    context["EvaluationContext<br/>catalog + quality + config"]
    ext["External dependency preflight"]
    key["GeometryCacheKey"]
    cache["RealizeCacheStore<br/>bounded CPU LRU"]
    rs["RealizeSession<br/>inflight + transaction"]
    realized["RealizedGeometry / RealizedLayer"]
    gpu["DrawRenderer GPU cache"]

    declaration --> evalfp
    declaration --> schemafp
    g --> opref
    evalfp --> opref
    estep --> stepref
    evalfp --> stepref
    schemafp --> stepref
    opref --> dag
    stepref --> dag
    dag --> key
    context --> key
    ext -->|"ExternalDependenciesFingerprint"| key
    key --> cache
    context --> rs
    cache --> rs
    rs --> realized
    key --> realized
    realized --> gpu
```

`GeometryId` は使用した operation ref を推移的に含む。realize は catalog の exact ref を検証し、
同名別 version へ fallback しない。schema だけの変更や未使用 operation の変更は geometry cache
identity に含めない。

## 4. Session / generation の resource ownership

### Headless composition

```mermaid
flowchart TB
    render["RenderSession"]
    defs["AuthoringDefinitionsSnapshot"]
    context["EvaluationContext(final)"]
    store["ParamStore / StyleResolver"]
    cache["RealizeCacheStore"]
    resources["EvaluationResources<br/>FontResources / provider memo"]
    child["RealizeSession<br/>explicit-dependency borrower"]

    render --> defs
    render --> context
    render --> store
    render --> cache
    render --> resources
    render --> child
    context -.->|"borrowed"| child
    cache -.->|"borrowed"| child
    resources -.->|"borrowed"| child
```

close 順は `RealizeSession -> EvaluationResources -> RealizeCacheStore`。

### Low-level RealizeSession

```mermaid
flowchart LR
    ctor["RealizeSession constructor"]
    omitted["Omitted resources / cache_store"]
    injected["Explicit resources / cache_store"]
    owned["Session-owned<br/>close resources then cache"]
    borrowed["Borrowed<br/>caller remains owner"]
    active["Active realization"]
    deferred["Deferred owned cleanup<br/>by last caller"]

    ctor --> omitted --> owned
    ctor --> injected --> borrowed
    owned --> active -->|"close requested"| deferred
```

`resources` と `cache_store` はそれぞれ独立に owned/borrowed を選ぶ。active caller がなければ
owned cleanup は `close()` で直ちに行う。`EvaluationContext` は immutable value で close 対象ではない。
constructor/body/close の `BaseException` でも後続 owned cleanup を試し、最初の error を保持する。

### Interactive reload

```mermaid
flowchart TB
    runner["SceneRunner"]
    cache["Shared RealizeCacheStore"]
    genA["Generation A"]
    genB["Candidate generation B"]
    ares["EvaluationResources A"]
    asessions["draft / final RealizeSession A"]
    bres["EvaluationResources B"]
    bsessions["draft / final RealizeSession B"]

    runner --> cache
    runner --> genA
    runner -.->|"build and validate"| genB
    genA --> ares
    genA --> asessions
    genB --> bres
    genB --> bsessions
    cache -.->|"borrowed with typed keys"| asessions
    cache -.->|"borrowed with typed keys"| bsessions
    genB -->|"atomic adopt after success"| runner
```

新 generation の構築に失敗した場合は A を維持する。採用後に旧子 session、旧 resource を閉じ、
共有 cache は `SceneRunner` 終了時だけ閉じる。

## 5. Parameter の読み取りと更新

```mermaid
sequenceDiagram
    participant App as "SceneRunner / RenderSession"
    participant Ctx as "parameter_context"
    participant Store as "ParamStore"
    participant DSL as "G / E / P / Layer style"
    participant Buffer as "FrameParamsBuffer"
    participant GUI as "Parameter GUI renderer"
    participant Bridge as "store_bridge / controllers"

    App->>Ctx: enter(store, cc snapshot)
    Ctx->>Store: capture immutable ParamSnapshot
    Ctx->>Buffer: create frame observation buffer
    App->>DSL: draw(t)
    DSL->>Ctx: read fixed snapshot
    DSL->>Buffer: record parameter / label / topology
    Ctx->>Store: merge successful frame records
    Ctx-->>App: exit

    Store->>Bridge: immutable query / ParameterTableView
    Bridge->>GUI: TableRenderInput
    GUI-->>Bridge: immutable TableEdits
    Bridge->>Store: narrow command
```

通常 command:

```mermaid
flowchart LR
    intent["Immutable edit intent"]
    command["Core command"]
    check["Validate + detect no-op"]
    state["Logical state"]
    rev["One revision/history/observer update"]

    intent --> command --> check
    check -->|"changed"| state --> rev
    check -->|"no-op"| done["No state or revision change"]
```

一時 rollback:

```mermaid
flowchart LR
    begin["begin_transient_rollback"]
    token["Owner-bound opaque snapshot"]
    temporary["Temporary variation edits / render"]
    restore["Exact logical state + counters restore"]
    invalidate["Invalidate derived caches"]
    silent["No history / observer notification"]

    begin --> token --> temporary --> restore --> invalidate --> silent
```

API/interactive が `ParamStore` の live/private container を取得する経路はない。
`ParamRuntimeView` は生成時に runtime mapping を浅く copy した時点固定 snapshot であり、後続 frame の
mutation を既存 view が観測しない。mapping 内の key/value/source は canonical immutable value である。

## 6. Interactive の一 frame

```mermaid
sequenceDiagram
    participant Loop as "MultiWindowLoop"
    participant DWS as "DrawWindowSystem"
    participant Transport as "TransportClock"
    participant MIDI as "MidiSession"
    participant SR as "SceneRunner"
    participant Pipe as "realize_scene"
    participant GL as "DrawRenderer"
    participant Rec as "RecordingSession"
    participant Capture as "CaptureQueue"
    participant GUI as "ParameterGUIWindowSystem"

    loop every frame
        par Preview window
            Loop->>DWS: draw_frame()
            DWS->>Transport: sample time
            DWS->>MIDI: poll and immutable snapshot
            DWS->>SR: run(t, quality, ParamStore, MIDI)
            SR->>Pipe: draw / normalize / style / realize
            Pipe-->>SR: RealizedLayer tuple
            SR-->>DWS: last-good or fresh scene
            DWS->>GL: begin_frame + render layers
            DWS->>Rec: optional RGB24 frame
            DWS->>Capture: admit / poll export work
        and Inspector window
            Loop->>GUI: draw_frame()
            GUI->>GUI: backend begin_frame -> panels -> render
        end
    end
```

`DrawWindowSystem` は順序と配線を担当し、capture path/publish、recording restore、workspace policy は
それぞれ `CaptureQueue`、`RecordingSession`、`WorkspaceWindowController` が所有する。

## 7. Render と capture publish

```mermaid
flowchart LR
    draw["draw(t) + config + parameter source"]
    render["RenderSession<br/>final evaluation"]
    frame["Immutable Frame"]
    adapter["grafix.export API adapter"]
    service["CaptureService"]
    encoder["SVG / PNG / G-code encoder"]
    staging["CaptureStaging"]
    publish["Atomic no-clobber publish"]
    files["Artifact family + capture manifest"]

    draw --> render --> frame
    frame --> adapter --> service
    service --> encoder --> staging --> publish --> files
```

`RenderSession.render()` はファイル I/O を行わない。publish は完成済み private staging を使い、
late collision では再 encode せず別 version を試す。失敗時は今回の generation だけを rollback する。

## 8. G-code の semantic boundary

```mermaid
flowchart LR
    source["Input polyline in original order"]
    clip["Clipping"]
    fragments["Fragments tagged by source polyline"]
    local["Reorder / reverse / bridge within one source only"]
    emit["Deterministic G-code"]

    source --> clip --> fragments --> local --> emit
```

異なる input polyline 間は並べ替え、向き反転、pen-down bridge の対象にしない。頂点数や閉曲線
らしさから face/group を推測しない。

## 9. Benchmark harness の一方向 DAG

矢印は compile dependency の向き（依存元から依存先）を表す。

```mermaid
flowchart TB
    schema["schema.py<br/>immutable result / JSON contract"]
    definition["definition.py<br/>CaseDefinition / source identity"]
    metrics["metrics.py<br/>checksum / typed aggregation"]
    workloads["workload providers<br/>setup / workload / postprocess"]
    catalog["catalog.py<br/>collect / validate / stable select"]
    executor["executor.py<br/>measure / calibrate / child lifecycle"]
    runner["runner.py<br/>composition / child entrypoint"]

    definition --> schema
    metrics --> schema
    workloads --> definition
    workloads --> metrics
    workloads --> schema
    catalog --> definition
    catalog --> workloads
    executor --> definition
    executor --> metrics
    executor --> schema
    runner --> catalog
    runner --> executor
    runner --> definition
    runner --> schema
```

`runner.py` の公開 symbol は `run_case_isolated` だけである。親側は definition と executor を配線し、
child entrypoint は catalog で case ID を解決して executor へ渡す。executor は catalog/workload を
知らず、workload は catalog/executor/runner を知らない。workload layer 内で許可する依存は
`interactive_scenario -> parameter_hotpath / renderer` と `parameter_edit -> parameter_hotpath` の
public helperだけで、private provider symbol参照をarchitecture testが拒否する。旧runner symbolの
re-export shimはない。

## 10. 主な source of truth

| 概念 | 正本 |
|---|---|
| operation authoring | `core/operation_authoring.py`, `core/operation_declaration.py` |
| registration/snapshot | `core/authoring_definitions.py`, `core/authoring_loader.py` |
| operation/preset catalog | `core/operation_catalog.py`, `core/preset_catalog.py` |
| evaluation/cache/resource | `core/evaluation_context.py`, `core/realize.py`, `core/font_resources.py` |
| parameters | `core/parameters/` |
| scene pipeline | `core/pipeline.py` |
| interactive composition | `api/runner.py`, `interactive/runtime/` |
| GUI schema projection | `interactive/parameter_gui/catalog.py` |
| capture lifecycle | `export/capture.py`, `export/capture_staging.py`, `export/capture_publish.py` |
| numeric kernels | `core/geometry_kernels/` |
| benchmark definition/catalog/metrics/execution | `devtools/benchmarks/definition.py`, `catalog.py`, `metrics.py`, `executor.py` |
| benchmark workload/composition | `devtools/benchmarks/*_benchmark.py`, `devtools/benchmarks/runner.py` |
