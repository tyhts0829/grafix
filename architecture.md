<!--
どこで: `architecture.md`。
何を: `src/` 配下の実装を基に、Grafix のアーキテクチャ（責務境界・依存方向・実行フロー）を整理した設計メモ。
なぜ: 機能追加やリファクタのときに「どこを触るべきか」「どこに依存させないか」を迷わないため。
-->

# Grafix アーキテクチャ

## 1. 目的と中心アイデア

Grafix は「線（ポリライン列）を **生成** し、effect を **チェーン** して **変形** し、リアルタイムに **プレビュー** する」ための小さなツールキット。

中心アイデアは次の 3 つ。

1) **Geometry は“配列そのもの”ではなくレシピ（DAG ノード）**
`src/grafix/core/geometry.py` の `Geometry` は `(op, inputs, args)` を持つ不変ノードで、`id` は内容署名（content signature）。
`draw(t)` は配列ではなく Geometry レシピを返す。

2) **実体配列は session-owned な realize で遅延生成する**
`src/grafix/core/realize.py` の `RealizeSession` が `Geometry -> RealizedGeometry` の評価、同時計算の集約、byte 上限付き LRU を所有する。cache key は `GeometryId` と primitive/effect registry revision の組であり、実装の差し替え後に古い結果を再利用しない。
`RealizedGeometry` は `coords(float32, Nx3)` と `offsets(int32, M+1)` を持ち、配列は writeable=False で固定される（`src/grafix/core/realized_geometry.py`）。

3) **描画スタイル（色・線幅）は Geometry から分離し Layer に載せる**
`src/grafix/core/layer.py` の `Layer` が `Geometry + (color/thickness)` を束ねる。
同じ Geometry を色違いで描いても Geometry キャッシュを共有できる。

加えて、Parameter GUI は「実行中に発見した引数」を ParamStore に蓄積し、GUI/CC から値を上書きして **次フレーム以降の Geometry 生成** に反映する（配列を後から書き換えない）。

## 2. パッケージ構造（責務の分割）

`src/` 配下は概ね次の責務で分割されている。

- `src/grafix/api/`（公開 API / ファサード）
  - `G`（primitive 生成）、`E`（effect チェーン）、`L`（Layer 化）、`run`（プレビュー起動）
  - 内部の core/export/interactive を直接触らせないための入口
- `src/grafix/core/`（ドメインコア）
  - `Geometry`（レシピ DAG）と署名生成、`RealizedGeometry`（配列表現）
  - immutable `OpSpec` レジストリ、`RealizeSession`（評価 + bounded cache + inflight 排除）
- `src/grafix/core/primitives/`（組み込み primitive 実装）
  - `@primitive` デコレータでレジストリ登録される “実体生成関数” 群
- `src/grafix/core/effects/`（組み込み effect 実装）
  - `@effect` デコレータでレジストリ登録される “実体変換関数” 群
- `src/grafix/core/parameters/`（パラメータ解決・ストア）
  - `parameter_context`（フレーム単位の snapshot 固定）
  - `resolve_params`（base/GUI/CC の統合 + 量子化 + 観測レコード化）
  - `ParamStore`（状態・メタ・ラベル・表示順序の永続）
- `src/grafix/export/`（ヘッドレス出力）
  - SVG/PNG/G-code などの encoder と、transactional publish を担う `CaptureService`
- `src/grafix/api/render.py`（headless render 契約）
  - immutable `RenderOptions` / `Frame` と、長寿命 `RenderSession`
- `src/grafix/interactive/`（ランタイム / ウィンドウ / GUI / GL）
  - `runtime/`：複数ウィンドウを 1 ループで回す・各サブシステムを分離
  - `parameter_gui/`：pyimgui + pyglet で `ParamStore` を編集する GUI
  - `gl/`：ModernGL を使った実描画（インデックス生成・シェーダ・VBO/IBO 管理）

## 3. 依存方向（レイヤ）と “呼び出し” の流れ

依存は「外側 → 内側」を基本にし、逆流はレジストリ登録（副作用 import）に限定する。

```
user sketch (main.py の draw(t))
  |
  v
src/grafix/api            : G/E/L/run（書き味の層）
  |  Geometry.create() を呼ぶ / resolve_params() を呼ぶ
  v
src/grafix/core           : Geometry / realize / registries（ドメイン核）
  ^\
  | \__ src/grafix/core/primitives, src/grafix/core/effects : @primitive/@effect で登録（実装の“プラグイン”）
  |
  +--> src/grafix/core/parameters : ParamStore / parameter_context / resolve_params（入力解決）
  |
  v
src/grafix/core/pipeline   : Scene 正規化 / Layer style 解決 / realize（出力・描画の共通パイプライン）
  |\
  | \__ src/grafix/export        : RealizedLayer -> ファイル（ヘッドレス出力）
  |
  v
src/grafix/interactive     : pyglet + ModernGL + Parameter GUI（対話プレビュー）
        |
        +--> src/grafix/interactive/parameter_gui : ParamStore 編集 UI（pyimgui）
```

重要な「呼び出し順」は次。

1. `src/grafix/api/runner.py:run()` が `ParamStore` とウィンドウサブシステムを作る
2. `src/grafix/interactive/runtime/window_loop.py:MultiWindowLoop.run()` がフレームループを回す
3. 毎フレーム `DrawWindowSystem.draw_frame()` が
   - Style（背景色/線幅/線色）を `ParamStore` から解決し
   - `parameter_context(store)` の中で、所有する `RealizeSession` を渡して `realize_scene(draw, t, defaults)` を呼ぶ
4. `realize_scene()`（`src/grafix/core/pipeline.py`）が
   - `normalize_scene(draw(t))`（`src/grafix/core/scene.py`）で Layer 列にし
   - Layer ごとに Layer style（line_thickness/line_color）を GUI 値で上書きし
   - session で `geometry` を評価し、配列と registry revision 付き cache key を得る
5. `DrawWindowSystem` が
   - `DrawRenderer.render_layer(...)`（`src/grafix/interactive/gl/draw_renderer.py`）へ描画依頼する
   - renderer が geometry 単位の byte-LRU 内で index 生成・mesh upload・resource 解放を一括管理する

GUI ウィンドウは同じループで `ParameterGUIWindowSystem.draw_frame()` が呼ばれ、`ParamStore` を更新する。
ただし draw 側は `parameter_context` の snapshot で “そのフレームの読み取り” が固定されるため、同一フレーム中に GUI が動いても `resolve_params` の結果はぶれない。

## 4. コアデータモデル

### 4.1 Geometry（レシピ DAG ノード）

- 実装: `src/grafix/core/geometry.py`
- 主な責務:
  - `params` を内容署名に入れられる形へ正規化（`normalize_args()`）
  - `(schema_version, op, inputs.id, args)` から `GeometryId` を計算（`compute_geometry_id()`）
  - `Geometry.create()` で「不変ノード」を生成する

`Geometry` は「何をするか」を表すだけで、実体配列（頂点配列）を持たない。

### 4.2 RealizedGeometry（評価結果）

- 実装: `src/grafix/core/realized_geometry.py`
- 形:
  - `coords: np.ndarray` … `(N,3)` float32
  - `offsets: np.ndarray` … `(M+1,)` int32（各ポリラインの開始 index。`offsets[0]=0`, `offsets[-1]=N`）
- 性質:
  - `__post_init__` で shape/dtype 整合性を検証し、`writeable=False` に固定する
  - 2D `(N,2)` 入力は `(N,3)`（z=0）へ補完する

### 4.3 Layer（Geometry とスタイルの分離）

- 実装: `src/grafix/core/layer.py`
- 形:
  - `Layer(geometry, site_id, color?, thickness?, name?)`
  - `LayerStyleDefaults(color, thickness)` … None 欠損を埋める既定値
- 重要点:
  - `site_id` は Layer style（GUI の line_color/line_thickness 行）のキーに使う
  - `resolve_layer_style()` は thickness が正でない場合に例外

### 4.4 Parameter 系（識別・状態・メタ）

- `src/grafix/core/parameters/key.py`
  - `ParameterKey(op, site_id, arg)` … GUI 行の一意キー
  - 自動 `site_id` は project-relative path と code location から生成する
  - G/E/L/P の `key=` を使うと、コード移動に依存しない明示 site ID になる
- `src/grafix/core/parameters/meta.py`
  - `ParamMeta(kind, ui_min, ui_max, choices)` … UI/検証の最低限メタ
- `src/grafix/core/parameters/state.py`
  - `ParamState(override, ui_value, cc_key)` … GUI 状態（値・上書きフラグ・CC 割当）
- `src/grafix/core/parameters/store.py`
  - `ParamStore` … 永続ストア（state/meta/label/ordinal/chain 情報）
  - snapshot に影響する永続状態の変更時だけ進む `revision` を持ち、同一 revision の snapshot 構築を再利用する

## 5. レジストリ（primitive / effect）と拡張ポイント

### 5.1 仕組み

`src/grafix/core/primitive_registry.py` と `src/grafix/core/effect_registry.py` は、op 名 → frozen `OpSpec` を単一 dict で保持する。`OpSpec` は evaluator、meta、defaults、parameter 順、arity を同じ世代として扱い、明示 replace 時だけ registry revision を進める。

- primitive 関数の契約（レジストリ側）:
  `func(args: tuple[tuple[str, Any], ...]) -> RealizedGeometry`
- effect 関数の契約（レジストリ側）:
  `func(inputs: Sequence[RealizedGeometry], args: tuple[tuple[str, Any], ...]) -> RealizedGeometry`

- primitive 関数の契約（デコレータで書く側）:
  `f(...)-> (coords, offsets)`（`coords` は shape `(N,3)` のみ）
- effect 関数の契約（デコレータで書く側）:
  `f(g1, ..., gk, *, ...)-> (coords, offsets)`（`g` は `(coords, offsets)`、`k` は `n_inputs`）

`@primitive` / `@effect` デコレータは “ユーザーが書く tuple I/O 関数” を “レジストリ契約の wrapper（内部は RealizedGeometry）” に変換して登録する。

### 5.2 組み込み primitive/effect の登録

組み込み module 自体は **import 時の副作用** で登録されるが、root import では全 module を読み込まない。

- `src/grafix/core/builtins.py` の明示 `op -> module` manifest を参照する
- `G.<op>` / `E.<op>` または realize 時の未登録 op lookup が、対象 module だけを読み込む
- list/stub generation のみ全 built-in を明示的に読み込む

この方式により、公開 API の内容を維持しながら cold import と worker spawn を軽くする。

### 5.3 新しい primitive/effect を追加する方法（最短）

1. `src/grafix/core/primitives/` か `src/grafix/core/effects/` に新モジュールを追加
2. `@primitive(meta=...)` または `@effect(meta=...)` で関数を登録
3. 必要時に import されるようにする（どちらか）
   - `src/grafix/core/builtins.py` の manifest へ追加する（組み込み lazy load）
   - あるいはスケッチ側でそのモジュールを import する（必要時だけ有効化）

## 6. realize（評価）とキャッシュ

実装: `src/grafix/core/realize.py`

`RealizeSession.realize(Geometry)` は次の手順で評価する。

1. DAG が参照する built-in だけを lazy load し、registry revision を確定する
2. `(GeometryId, registry revision)` の byte-LRU を参照し、ヒットなら返す
3. miss の場合、同じ session の inflight coordinator で同一 key の同時計算を 1 回に潰す
4. leader スレッドが `_evaluate_geometry_node()` で評価する
   - `op == "concat"` は inputs を realize して `concat_realized_geometries` で連結
   - inputs が空なら primitive（`primitive_registry[op]`）
   - それ以外は effect（`effect_registry[op]`）
5. 上限内の結果だけを LRU へ保存し、待機者へ通知して返す

通常例外は `RealizeError` で文脈を付けるが、`KeyboardInterrupt` / `SystemExit` は元の型で再送出する。interactive runtime、headless Export、pipeline の長寿命利用者が session を所有し、終了時に明示 close する。

## 7. パラメータ解決（GUI/CC との統合）

### 7.1 parameter_context（フレーム境界で固定するもの）

実装: `src/grafix/core/parameters/context.py`

`parameter_context(store, cc_snapshot)` は contextvars で次を固定する。

- `param_snapshot` … `store_snapshot(store)`（revision 単位で再利用する読み取りビュー）
- `frame_params` … `FrameParamsBuffer()`（この draw で観測した引数の収集先）
- `cc_snapshot` … 今フレームの CC 値辞書（現状 run 経路では None）
- `store` … ラベル設定等のために参照（`current_param_store()`）

`finally` で `merge_frame_params(store, frame_params.records)` を呼ぶため、**そのフレームで呼ばれた引数が次フレーム以降 GUI に出る**。

### 7.2 resolve_params（base/GUI/CC の統合と量子化）

実装: `src/grafix/core/parameters/resolver.py`

`resolve_params(op, params, meta, site_id, ...)` は引数ごとに次を行う。

- `ParameterKey(op, site_id, arg)` を作る
- snapshot に状態があればそれを使用（meta/state/ordinal/label）
- 無ければ `meta.get(arg)` がある引数のみ GUI 対象として扱う（meta が無い引数は観測しない）
- `MIDI > UI > CODE` で effective を選び、MIDI未採用時は全kind（boolを含む）が
  明示 `override` に従って UI/CODE を選ぶ
- sourceを `code | ui | midi_live | midi_frozen` として観測recordまで保持する
- 量子化（既定 `DEFAULT_QUANT_STEP=1e-3`）を **ここだけ** で行い、署名に入る値と実計算値を一致させる
- `FrameParamsBuffer` に観測レコードを積む（explicit/chain_id/step_index も記録）

### 7.3 初期 override ポリシー（“省略引数は GUI で動かしやすく”）

実装: `src/grafix/core/parameters/merge_ops.py:merge_frame_params()`

`FrameParamRecord.explicit`（ユーザーが kwargs を明示したか）を使い、

- 明示 kwargs（explicit=True）: `initial_override=False`（コードの base を優先）
- 省略 kwargs（explicit=False）: `initial_override=True`（GUI 値を優先）

という初期状態を作る（既に state がある場合は上書きしない）。

### 7.4 Style / Layer style の扱い（特殊キー）

Geometry の引数解決（`resolve_params`）とは別に、描画見た目のための “Style 行” を `ParamStore` に持つ。

- Global style: `src/grafix/core/parameters/style.py`
  - `STYLE_OP="__style__"`, `STYLE_SITE_ID="__global__"`
  - `background_color`, `global_thickness`, `global_line_color`
  - `DrawWindowSystem` がフレーム冒頭に `store.get_state()` で直接参照して適用する
- Layer style: `src/grafix/core/parameters/layer_style.py`
  - `LAYER_STYLE_OP="__layer_style__"`
  - `line_thickness`, `line_color`
  - `realize_scene()`（`src/grafix/core/pipeline.py`）が Layer ごとにエントリを確保し、override=True の場合だけ上書きして描画する

## 8. Parameter GUI（pyimgui）アーキテクチャ

GUI は「描画（imgui）」「データ変換（純粋関数）」「store 反映」を分離している。

- 入口（ライフサイクル）: `src/grafix/interactive/parameter_gui/gui.py`
  - ImGui context を生成し、毎フレーム `render_store_parameter_table(store)` を呼ぶ
- backend（pyglet 依存）: `src/grafix/interactive/parameter_gui/pyglet_backend.py`
  - window 生成、IO 同期、renderer 作成
- store ↔ rows ↔ UI の橋渡し: `src/grafix/interactive/parameter_gui/store_bridge.py`
  1) `ParamStore.revision` と primitive/effect/preset registry revision を cache key にする
  2) revision 変更時だけ `ParameterTableModel`（行・順序・ヘッダ）を構築する
  3) effective value、MIDI、active/loaded visibility を描画直前に合成する
  4) `render_parameter_table(rows)`（imgui 描画）を呼び、更新後 rows を受け取る
  5) 差分があれば `update_state_from_ui()` / `set_meta()` で store に反映
- “純粋なロジック” を集約:
  - `src/grafix/core/parameters/view.py` … 値正規化・rows 生成・state 反映 API（imgui 非依存）
  - `src/grafix/interactive/parameter_gui/grouping.py` / `group_blocks.py` / `labeling.py` … 表示名・ブロック化
  - `src/grafix/interactive/parameter_gui/rules.py` … kind/op ごとの列表示ルール
  - `src/grafix/interactive/parameter_gui/widgets.py` … kind→widget の対応（imgui 呼び出しはここに寄せる）

## 9. 描画（ModernGL）パイプライン

### 9.1 シーン正規化 → realize → 描画

実装: `src/grafix/core/pipeline.py` と `src/grafix/interactive/runtime/draw_window_system.py`

interactive の 1 フレーム描画は、概ね次の順で行う。

1) `DrawWindowSystem` が style（背景色/グローバル線幅/線色）を `ParamStore` から解決
2) `parameter_context(store)` の中で `realize_scene(draw, t, defaults)` を呼ぶ
   - `normalize_scene(draw(t))`（`src/grafix/core/scene.py`）
   - `resolve_layer_style(layer, defaults)`（`src/grafix/core/layer.py`）
   - layer_style（line_thickness/line_color）の GUI override
   - 所有する `RealizeSession` で geometry を評価
3) 各 `RealizedLayer` について
   - registry revision 付き cache key で `DrawRenderer.render_layer(...)`
   - renderer 内の統合 byte-LRU が index、統計、GPU mesh を再利用

### 9.2 GPU レンダラーの構成

- `src/grafix/interactive/gl/draw_renderer.py:DrawRenderer`
  - pyglet window の GL context 上で ModernGL context を生成
  - `Shader.create_shader()` でプログラム作成
  - `LineMesh` に頂点/インデックスを upload して `ctx.LINES` で描画
- `src/grafix/interactive/gl/shader.py`
  - vertex: 2D（xy）を `projection` で NDC に変換
  - geometry: line（2頂点）を太さ付き四角形（triangle_strip 4頂点）に展開
  - fragment: 単色
- `src/grafix/interactive/gl/utils.py:build_projection`
  - `canvas_size` に基づく正射影行列を生成（y 軸は画面座標系に合わせて反転）
- `src/grafix/interactive/gl/index_buffer.py:build_line_indices`
  - renderer cache miss 時だけ `offsets` から `GL_LINE_STRIP` + primitive restart の index 列を生成する

## 10. ランタイム（複数ウィンドウの統合ループ）

実装: `src/grafix/interactive/runtime/window_loop.py`

`MultiWindowLoop` は pyglet の複数 window を 1 ループで回す。

- 各 window について `dispatch_events()` → `draw_frame()` → `flip()` を 1 回ずつ実行する
- 目的:
  - flip の呼び出し箇所を 1 箇所に集約し、点滅や更新競合を避ける
  - GUI と描画を同一 FPS で同期させやすくする

`src/grafix/api/runner.py` はこのループの “配線” に徹し、

- 描画: `DrawWindowSystem`（`src/grafix/interactive/runtime/draw_window_system.py`）
- GUI: `ParameterGUIWindowSystem`（`src/grafix/interactive/runtime/parameter_gui_system.py`）

のサブシステムとして組み立てる。

mp-draw は frame task に ParamStore snapshot 本体を載せず revision だけを渡す。revision が変わった時だけ、worker ごとの bounded control queue へ snapshot を latest-wins で配信し、全 worker の適用 ack 後にその revision の task を実行する。

interactive の PNG/G-code は `ExportJobSystem` が共通の長寿命 spawn worker で処理する。
親はin-flight 1件と、件数/aggregate geometry byteで制限したpending FIFOを保持し、window
systemはimmutable frame snapshotのadmissionと結果表示に限定される。

## 11. 診断・render・capture の責務境界

### 11.1 `DiagnosticCenter`

`src/grafix/interactive/runtime/diagnostics.py` の `DiagnosticCenter` は、frame、reload、
export、save/recovery、config、operation/resource の失敗を同じ bounded event stream へ
集約する。イベントは immutable で、dedupe key、発生回数、severity、source、型付き action
を持つ。各 subsystem は例外を GUI 形式へ描画せず `DiagnosticEvent` を publish し、
Inspector の diagnostics panel が Copy/Open/Retry/Dismiss を表示する。

責務外なのは、Geometry の結果変更や暗黙 retry である。診断は失敗を可視化するが、
作品の評価契約は変更しない。

### 11.2 `RenderSession`

`src/grafix/api/render.py` の `RenderSession` は headless 評価期間を所有する。

- draw callable、ParamStore と明示的な parameter load mode
- effective runtime config と `RenderOptions`
- `StyleResolver` / `RealizeSession` の cache 寿命
- capture manifest に渡す session/frame provenance snapshot

`render(t) -> Frame` はファイル I/O を行わない。単発の公開 `render()` も内部で同じ
session 契約を使い、interactive preview の draft context に影響されず final 品質で評価する。

### 11.3 `CaptureService`

`src/grafix/export/capture.py` の `CaptureService` は完成済み `Frame` を受け取り、suffixで
SVG/PNG/G-code encoderを選択する。private stagingでencodeした後、artifactとmanifestを
同じgenerationとしてno-clobber publishする。late collision時は別versionへ進み、失敗時は
今回generationだけをrollbackする。PNGの中間SVGもprivateであり、public siblingを触らない。

`ExportJobSystem` はqueue/worker/deadlineだけを所有し、形式判定・manifest・publishを
重複実装しない。workerへ渡すprovenanceはmain processで固定済みのimmutable snapshotで、
workerがgit/config/sourceを再探索してはならない。

依存方向は次のとおり。

```text
draw + parameter source + config
             |
             v
        RenderSession --render(t)--> immutable Frame
                                      |
                                      v
                               CaptureService
                               encode -> stage
                               -> publish artifact + manifest

interactive errors -----------------> DiagnosticCenter -> Inspector
```

## 12. 外部依存と実行上の注意

Grafix は “core は Python だけで完結” を基本としつつ、いくつかの機能は外部コマンドに依存する。

- PNG export は `resvg`、動画録画は `ffmpeg` を外部コマンドとして要求する（見つからなければ実行時に例外）
- interactive PNG/G-code export は bounded な長寿命 worker へ渡すため、完了は非同期に通知される

このファイルは **現状の `src/` 実装** に合わせて記述しているため、README/spec と齟齬がある場合は `src/` を正として読み替える。
