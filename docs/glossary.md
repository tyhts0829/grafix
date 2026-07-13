<!--
どこで: `docs/glossary.md`。
何を: Grafix の主要用語（コア/parameters/interactive/export）を短く定義する用語集。
なぜ: 仕様変更やコードリーディング時の “言葉の対応” を最短で取れるようにするため。
-->

# Glossary（用語集）

## Core（データモデル/評価）

- `Geometry`: 配列そのものではなく「幾何のレシピ」を表す DAG ノード。`src/grafix/core/geometry.py:Geometry`
- `GeometryId`: schema v2 の型付き canonical encoding `(op, inputs, args)` から計算される内容署名 ID。`src/grafix/core/geometry.py:compute_geometry_id`
- `RealizedGeometry`: `Geometry` を評価して得られる実体配列（`coords` + `offsets`）。`src/grafix/core/realized_geometry.py:RealizedGeometry`
- `GeomTuple`: `(coords, offsets)` タプルで表す最小実体表現。`@primitive` / `@effect` のユーザー定義 I/O に使う。`src/grafix/core/realized_geometry.py:GeomTuple`
- `RealizeSession`: `Geometry -> RealizedGeometry` の評価、byte-LRU、inflight 集約を所有する明示的な寿命単位。`src/grafix/core/realize.py:RealizeSession`
- `GeometryCacheKey`: `GeometryId` と primitive/effect registry revision の組。CPU/GPU cache で共有する。`src/grafix/core/realize.py:GeometryCacheKey`
- `RealizedLayer`: 描画/出力用の「Layer + realize 済みジオメトリ + cache key + style」。`src/grafix/core/pipeline.py:RealizedLayer`

## Scene / Layer（描画単位）

- `Layer`: `Geometry` とスタイル（色/線幅）を束ねる描画単位。`src/grafix/core/layer.py:Layer`
- `SceneItem`: `draw(t)` が返せる型（Geometry/Layer/それらの列など）を正規化するための入力表現。`src/grafix/core/scene.py`
- `normalize_scene`: `SceneItem` を `Layer` 列へ正規化する関数。`src/grafix/core/scene.py:normalize_scene`

## Registry / builtins（拡張ポイント）

- `OpSpec`: evaluator、meta、defaults、引数順、arity を同じ世代として保持する frozen registry entry。`src/grafix/core/op_registry.py:OpSpec`
- `primitive_registry` / `effect_registry`: op 名 → `OpSpec` の revision 付きレジストリ。`src/grafix/core/primitive_registry.py` / `src/grafix/core/effect_registry.py`
- `@primitive` / `@effect`: `(coords, offsets)` タプル I/O の関数をレジストリへ登録するデコレータ。組み込み op は `meta=...` 必須。内部では `RealizedGeometry` に包む。`src/grafix/core/primitive_registry.py:primitive` / `src/grafix/core/effect_registry.py:effect`
- built-in manifest: op 名から対象 module だけを lazy import する対応表。list/stub生成時だけ全件を読む。`src/grafix/core/builtins.py`

## parameters（GUI/CC と値解決・永続）

- `ParamStore`: パラメータ状態の永続ストア（state/meta/label/ordinal/effect chain）。`src/grafix/core/parameters/store.py:ParamStore`
- `ParamMeta`: 引数の UI 種別・範囲などの最小メタ。`src/grafix/core/parameters/meta.py:ParamMeta`
- `ParamState`: UI 値・override・CC 割当などの状態。`src/grafix/core/parameters/state.py:ParamState`
- `ParameterKey`: `(op, site_id, arg)` で GUI 行を一意化するキー。`src/grafix/core/parameters/key.py:ParameterKey`
- `site_id`: project-relative code location、または G/E/L/P の明示 `key=` から作る呼び出し箇所 ID。`src/grafix/core/parameters/key.py:make_site_id`
- `ParamSnapshot`: `ParamStore` を revision 単位で読み取り用に固定した mapping。`src/grafix/core/parameters/snapshot_ops.py:ParamSnapshot`
- `ParamStore.revision`: snapshot/GUI model/worker 同期を無効化する、snapshot に影響する永続状態の変更時だけ進む単調 revision。
- `parameter_context`: フレーム境界で `ParamSnapshot` と `FrameParamsBuffer`（観測バッファ）を固定し、終了時に store へマージする。`src/grafix/core/parameters/context.py:parameter_context`
- `FrameParamsBuffer`: そのフレームで観測・解決した引数を貯めるバッファ。`src/grafix/core/parameters/frame_params.py:FrameParamsBuffer`
- `resolve_params`: base/GUI/CC から effective 値を決め、観測を記録する関数。`src/grafix/core/parameters/resolver.py:resolve_params`
- `explicit_args`: 「ユーザーが明示指定した kwargs の集合」。初期 override ポリシー用に観測へ残す。`src/grafix/core/parameters/resolver.py:resolve_params`
- `chain_id` / `step_index`: effect チェーンのグルーピングと順序情報。`src/grafix/api/effects.py:EffectBuilder` / `src/grafix/core/parameters/effects.py:EffectChainIndex`

## API（スケッチ作者が触る）

- `G`: primitive の公開名前空間（`G.circle(...) -> Geometry`）。`src/grafix/api/primitives.py:G`
- `E`: effect チェーンの公開名前空間（`E.scale(...).rotate(...)(g)`）。`src/grafix/api/effects.py:E`
- `L`: Layer 化（スタイル付与/concat 等）の公開名前空間。`src/grafix/api/layers.py:L`
- `P` / `@preset`: preset 登録と呼び出しの公開導線。`src/grafix/api/presets.py:P` / `src/grafix/api/preset.py:preset`
- `run(draw)`: interactive ランナー。`src/grafix/api/runner.py:run`
- `Export`: headless export の入口。`src/grafix/api/export.py:Export`

## Effect math / runtime

- `PlanarFrame`: 3D の平面形状を決定的な2D座標へ写し、rank/residualも返す共通平面基底。`src/grafix/core/effects/util.py:PlanarFrame`
- `GridSpec`: bbox、pitch、cell上限から確保前に格子解像度を決める値。`src/grafix/core/effects/util.py:GridSpec`
- `ExportJobSystem`: PNG/G-code を bounded queue と latest-wins pending で処理する長寿命 spawn worker。`src/grafix/interactive/runtime/export_job_system.py:ExportJobSystem`
- `ParameterTableModel`: store/registry revision 内で不変なGUI行・順序・ヘッダを保持するcache単位。`src/grafix/interactive/parameter_gui/table_model.py:ParameterTableModel`
