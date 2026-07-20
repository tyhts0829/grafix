# Compatibility-shim removal migration notes (2026-07-20)

この変更は、旧 API・旧 schema・移行用分岐を残さず正規契約へ統一する破壊的変更である。
既存の sketch、tool、保存ファイルを更新するときは、以下を確認する。

## Render / export の共有型

- 旧 `RenderSettings` と `src/grafix/interactive/render_settings.py` は削除した。
  headless と interactive の描画設定は、`grafix.RenderOptions`（定義元は
  `grafix.core.render_options.RenderOptions`）だけを使用する。互換 alias はない。
- `RenderOptions` が持つのは論理キャンバス寸法、背景色、既定線色、既定線幅である。
  `render_scale` は preview window / framebuffer の倍率を表す別の実行時引数であり、
  `RenderOptions` には含めない。
- SVG、PNG、G-code の形式は、全層で単一の
  `grafix.ExportFormat`（`SVG` / `PNG` / `GCODE`）を使用する。
  path suffix を読む公開入口を除き、文字列から enum への暗黙変換は行わない。
- 保存結果は共有の `grafix.ExportResult` 一形である。constructor は keyword-only で、
  no-clobber 解決後の artifact `path`、suffix と一致する `format`、同じ generation の
  必須 `manifest_path` を持つ。

## Runtime limit

- headless の制限は `RuntimeLimits` で `RenderSession` / `render()` へ渡す。
- interactive の制限は `RuntimeLimitProfiles` で `run()` へ渡す。
- `max_cache_bytes`、`max_cache_entries`、`resource_budget` の旧上位引数、
  `profiles_for_resource_budget()`、`DEFAULT_MAX_CACHE_BYTES`、
  `DEFAULT_MAX_CACHE_ENTRIES` は削除した。
- `ResourceBudget` は `RuntimeLimits` の構成要素として使用できる。

## Parameter / effect topology

- ParamStore は schema v3 だけを受理する。versionless、v1、v2、future schema は
  変換せず明示的に拒否し、原本を上書き・隔離しない。
- decode は診断を保持する `decode_param_store_result()` /
  `loads_param_store_result()` だけを使用し、復元値は `.store` から取得する。
  partial-invalid entry の `issues` を黙って捨てる旧 convenience 関数は削除した。
- JSON の vec3/RGB/3要素 CC key は array 一形だけを受理する。Python tuple を
  decode へ直接渡す別入力はなく、encoder も JSON-native list を生成する。
- metadata の `kind` は `bool` / `int` / `float` / `str` / `font` /
  `choice` / `vec3` / `rgb` の8種だけを受理する。`choice` は重複のない
  非空の `Sequence[str]` が必須で、他 kind に `choices` は指定できない。
- `ui_min` / `ui_max` は数値 kind だけに指定でき、int/RGB は整数、
  float/vec3 は有限実数とする。両端を指定する場合は `ui_min < ui_max` が必要である。
- UI 更新は widget が返す canonical 値だけを受理する。数値文字列、bool から数値、
  float から int への切り捨て、NaN/Inf、範囲外 choice を暗黙変換せず、
  エラー時は ParamStore を変更しない。
- MIDI CC 番号は非 bool の整数 `0..127` に限定する。scalar CC は
  float/int/choice、3成分 CC は vec3 だけが対応し、RGB、bool、文字列、
  global/layer style への非機能 mapping は拒否する。JSON の
  `[null, null, null]` も `null` の別表現として受理しない。
- 現行 writer が必ず出力する parameter/effect-chain ordinal が欠損した v3 payload は、
  無診断で補わず decode issue として quarantine/recovery 経路へ送る。
- effect chain は完全な `effect_steps` topology を必須とする。parameter record 単独の
  `chain_id` / `step_index` から chain を復元する経路は削除した。
- step index は topology と現在の order override から導出する。
- effect order override は完全で重複のない exact permutation とし、未知 step や
  multi-input 制約違反を code order へ黙って戻さず拒否する。source reload で
  topology 自体が交換された場合だけ、旧 generation の override を一度破棄する。
- `merge_frame_effect_chains()` は、完全な成功観測かを示す
  `observation_complete` の明示指定を必須とする。
- `ParamStoreRuntime` は keyword-only であり、group set は常に追跡可能な内部集合へ
  正規化される。
- `FrameParamRecord` / `FrameParamsBuffer.record()` は
  `effective` / `source` / `explicit` を必須とし、欠落を `None` や code source として
  補う経路はない。

## Preset identity

- identity 付き preset の構文は
  `P(name=..., key=..., instance_key=..., shared=...).foo(...)` に統一した。
- `P.foo(..., name=..., key=...)` は使用できない。
- identity はすべて keyword-only であり、`P("label").foo(...)` も使用できない。
- `name`、`key`、`instance_key`、`shared`、`activate` は preset wrapper の予約名であり、
  `@preset` 対象関数の引数には使用できない。
- `activate` は wrapper が自動追加する唯一の direct preset 引数であり、
  `P.foo(activate=False)` として指定できる。identity 4 引数は namespace 側だけで指定する。
- project-local preset の型検査では `python -m grafix stub` が生成する stub を使用する。
  未生成名・typo を通す `_P.__getattr__` fallback はない。

## Parameter site identity

- 明示 `key` / `instance_key` は `str | int | None` だけを受理し、bool や任意 object の
  暗黙文字列化は行わない。`shared=True` と `instance_key` の併用も拒否する。
- 文字列 key は `str:{len}:{value}`、整数 key は `int:{value}` として型を含めて符号化する。
  instance key は同じ符号化を
  `|instance:str:{len}:{value}` または `|instance:int:{value}` として末尾へ付ける。
  したがって文字列 `"1"` と整数 `1`、区切り文字を含む文字列同士も衝突しない。
- 旧 site ID を新 encoding へ自動移行する対応表、読替え、互換 fallback はない。
  保存済み ParamStore の旧 ID は新 ID と同一視されないため、必要な値は明示的に
  作り直すか、保存データを repository 外で更新する。

## Capture / export / video

- capture manifest は schema v3 の `output` section 一形だけを出力し、
  `CaptureProvenance` と `output_size` を必須とする。旧 top-level artifact field は出力しない。
- PNG 出力寸法・既定ファイル名の計算には effective `scale` と `canvas_size` を明示的に
  渡す。既定 PNG 名には解決済み出力寸法 suffix が常に入る。
- `CaptureService` は `Frame.metadata` を推測しない。PNG は解決済み `output_size`、
  G-code は canonical `GCodeParams` を呼び出し側から必ず渡す。
- `CaptureService` は呼出 thread で同期的に encode / publish する。
  `ExportJobSystem` は process worker へ非同期 job を投入する。実行方式を別 enum にせず、
  両方とも形式軸には同じ `ExportFormat` だけを受け取る。
- layer 別 G-code は別形式ではなく、`ExportFormat.GCODE` と
  `split_gcode_layers: bool` の組合せで指定する。この bool は G-code 以外では拒否する。
- `ExportFormat.resolve()`、capture、export job、variation thumbnail は
  `ExportFormat` を受け取る。CLI の文字列は CLI 境界で enum に変換する。
- G-code 設定の定義元は `grafix.core.gcode_params.GCodeParams` であり、
  `grafix.export.gcode` から再公開する。runtime config の `export.gcode`、
  capture snapshot、encoder は同じ型を共有し、旧設定型や設定 relay は置かない。
- `export_svg()` は `canvas_size`、`export_gcode()` は `canvas_size` と `params` が必須である。
- layer 別 G-code capture は空 layer 列を拒否する。
- export/video encoder は staging 内だけへ書き出す。final path への no-clobber publish、
  manifest 作成、rollback は capture transaction が一括して行う。
- `ExportJob.svg_output_path`、任意 `staging_dir`、`VideoRecorder.no_clobber`、
  direct-publish `close()`、`stop_to_staging()` は削除した。
- `VideoRecordingSystem` の出力先は `start(output_path=...)` へ必ず渡す。
  constructor の既定出力先と start 時 override の二重入口はない。

## Interactive / GUI

- clock 名は `TransportClock` に統一し、`RealTimeClock` alias は削除した。
- internal message DTO は keyword-only で、現在の処理に必要な metadata を明示する。
- scene evaluation は `quality`、frame export snapshot は capture 時刻 `t` を必須とする。
  draft/時刻 0 を暗黙に補う経路はない。
- 対応 GUI dependency は `imgui>=2,<3`、`pyglet>=2.1,<3`。
  pyglet の programmable renderer を使用し、deprecated renderer と旧 arity fallback は
  使用しない。
- framebuffer scale は pyglet 2.1 の `window.scale` を直接使用し、
  deprecated pixel-ratio API や欠落時の scale=1 推測は行わない。
- renderer の cache admission では `scene_serial` と `snapshot_revision` を必須とする。
- parameter table は呼び出し側で構築した `ParameterTableView`、
  `GroupBlockLayout`、model rows を唯一の入力とし、render 中に同じ model を
  別引数から再構築する経路はない。

## Geometry / text / benchmark

- `Geometry.create()` と `compute_geometry_id()` から caller 指定の `schema_version` を削除した。
  Geometry ID は固定 schema v2 domain だけで計算する。
- buffer と partition の平面基底は `PlanarFrame` /
  `canonical_planar_frame()` を共通基盤とする。
  とくに spatial/linear input は旧 XY 寄せではなく canonical frame を使うため、
  partition の座標 checksum が変わり得る。
- text の曲線平坦化は fontTools pen protocol 上の実装を使用する。
  `fontPens` 依存と、その deprecated import を隠す global warning filter は削除した。
- benchmark workload の返却型は `schema.BenchmarkOutput` 一つに統合した。
  7 個の重複 result DTO と runner の即時再包装を削除し、各 workload が
  value、`tuple[Metric, ...]`、contract を直接返す。
- nested mapping から metric 名・unit・phase・scope を推論する adapter は削除した。
  JSON の vec3 配列は setup 境界で一度だけ tuple へ正規化し、checksum contract は
  現行の安定出力へ同期した。

## Effect 引数

- choice 引数は exact `str` と既知値だけを受理する。未知値を identity/no-op として
  扱わない。
- vec3 引数は3要素 tuple 一形の有限実数、整数引数は bool/float/数値文字列を除く
  整数スカラーとする。
- 非有限値、意味のない負値、無効な count/grid/range は明示的に拒否する。
  distance 0、repeat count 0 など、effect の意味として定義された identity だけを残す。
- probability clamp、数値アルゴリズム内部の安定化 clamp、Shapely geometry の
  best-effort 分解は入力互換シムではなく、各 effect の正規数値契約として維持する。

## Strict DTO / normalization 境界

- 文字列 identity、status、mode、choice は exact built-in `str` と既知値を検証し、
  `str(value)` で補わない。variation / batch 名は前後空白を値として保持し、
  空白だけの名前だけを拒否する。
- 実数は bool を除く有限な `numbers.Real` を受けて Python `float` へ正規化する。
  整数は bool、float、数値文字列を拒否し、整数 scalar だけを Python `int` へ正規化する。
- process message、capture snapshot、内部 export job/result、variation batch result などの
  内部 DTO は、必要箇所で keyword-only、exact tuple、`Path`、enum、要素型を検証する。
  list-to-tuple、文字列-to-`Path`、旧 positional field 順を DTO 内で救済しない。
- history、autosave、parameter recovery、window loop、workspace、output path、doctor の
  入口も同じ共有 validator を使用する。callable、exact bool/string/integer/tuple/`Path`、
  有限実数を入口で検証し、暗黙の `str` / `int` / `float` / `bool` 変換は行わない。
- `PerfCollector` は disabled 時も入力を検証する。負値の clamp や非有限値の黙殺はせず、
  不正な timestamp、lag、revision、record 名を明示的に拒否する。
  `ResourceBudget` と resource guard、operation selector も exact 型と範囲を要求する。
- stub 同期 test は fresh CLI subprocess で再生成する。先に実行された test が process 内の
  registry を変更しても、生成結果へ混入しない。
- 一方、公開 signature が明示する `str | Path`、`ExportResult` が保持 path を
  `Path` に揃える処理、config YAML の list/path、`RenderOptions` の色表現、
  有限実数 scalar の正規化は、仕様として所有者が一度だけ行う。これらは旧入力を
  推測する互換 fallback ではない。

## 削除した内部互換入口

- `ParamStoreMemento` の未使用 `explicit_by_key` / `labels` / `ordinals` 引数
- `SceneRunner._realize_session`
- `RealTimeClock`
- 旧 `RenderSettings` と interactive 側の設定複製
- private operation-selector module の未使用 registry symbol 転送
- partial-invalid 診断を捨てる `decode_param_store()` / `loads_param_store()`
- `core.primitives.*` / `core.effects.*` namespace provenance 推測
- Parameter GUI の旧 `GroupBlock` model と変換 helper
- index/monitor/label/widget/reconcile/effect-order/history/export の利用ゼロ relay
- constructor を通らない `DrawWindowSystem` / `ParameterGUI` / `MpDraw` test object を
  支える production fallback
- export 形式を二重化する旧 enum / 旧 G-code 設定 relay
- benchmark ごとの重複 result DTO と runner の `_CaseOutput`

互換 wrapper、deprecated alias、one-shot migration tool は追加していない。
