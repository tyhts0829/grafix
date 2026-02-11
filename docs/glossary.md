<!--
どこで: `docs/glossary.md`。
何を: Grafix の主要用語（コア/parameters/interactive/export）を短く定義する用語集。
なぜ: 仕様変更やコードリーディング時の “言葉の対応” を最短で取れるようにするため。
-->

# Glossary（用語集）

## Core（データモデル/評価）

- `Geometry`: 配列そのものではなく「幾何のレシピ」を表す DAG ノード。`src/grafix/core/geometry.py:Geometry`
- `GeometryId`: `(op, inputs, args)` から計算される内容署名 ID。キャッシュキーとして使う。`src/grafix/core/geometry.py:compute_geometry_id`
- `RealizedGeometry`: `Geometry` を評価して得られる実体配列（`coords` + `offsets`）。`src/grafix/core/realized_geometry.py:RealizedGeometry`
- `GeomTuple`: `(coords, offsets)` タプルで表す最小実体表現。`@primitive` / `@effect` のユーザー定義 I/O に使う。`src/grafix/core/realized_geometry.py:GeomTuple`
- `realize`: `Geometry -> RealizedGeometry` を評価し、cache/inflight で重複計算を避ける。`src/grafix/core/realize.py:realize`
- `RealizedLayer`: 描画/出力用の「Layer + realize 済みジオメトリ + style」。`src/grafix/core/pipeline.py:RealizedLayer`

## Scene / Layer（描画単位）

- `Layer`: `Geometry` とスタイル（色/線幅）を束ねる描画単位。`src/grafix/core/layer.py:Layer`
- `SceneItem`: `draw(t)` が返せる型（Geometry/Layer/それらの列など）を正規化するための入力表現。`src/grafix/core/scene.py`
- `normalize_scene`: `SceneItem` を `Layer` 列へ正規化する関数。`src/grafix/core/scene.py:normalize_scene`

## Registry / builtins（拡張ポイント）

- `primitive_registry` / `effect_registry`: op 名 → 実体関数/メタ情報のレジストリ。`src/grafix/core/primitive_registry.py` / `src/grafix/core/effect_registry.py`
- `@primitive` / `@effect`: `(coords, offsets)` タプル I/O の関数をレジストリへ登録するデコレータ。組み込み op は `meta=...` 必須。内部では `RealizedGeometry` に包む。`src/grafix/core/primitive_registry.py:primitive` / `src/grafix/core/effect_registry.py:effect`
- built-in 登録: 組み込み primitive/effect を import して登録する入口。`src/grafix/core/builtins.py:ensure_builtin_ops_registered`

## parameters（GUI/CC と値解決・永続）

- `ParamStore`: パラメータ状態の永続ストア（state/meta/label/ordinal/effect chain）。`src/grafix/core/parameters/store.py:ParamStore`
- `ParamMeta`: 引数の UI 種別・範囲などの最小メタ。`src/grafix/core/parameters/meta.py:ParamMeta`
- `ParamState`: UI 値・override・CC 割当などの状態。`src/grafix/core/parameters/state.py:ParamState`
- `ParameterKey`: `(op, site_id, arg)` で GUI 行を一意化するキー。`src/grafix/core/parameters/key.py:ParameterKey`
- `site_id`: 呼び出し箇所 ID。既定は `"{abs_filename}:{co_firstlineno}:{f_lasti}"`。`src/grafix/core/parameters/key.py:make_site_id`
- `ParamSnapshot`: `ParamStore` を読み取り用に固めた辞書。`src/grafix/core/parameters/snapshot_ops.py:ParamSnapshot`
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
