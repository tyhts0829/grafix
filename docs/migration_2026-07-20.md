# Compatibility-shim removal migration notes (2026-07-20)

> **後続変更:** operation/preset registry、evaluation cache、resource ownership は
> 2026-07-22 に immutable catalog/session contract へ置き換えた。本書中の旧 registry
> 記述を現行実装へ適用せず、`docs/migration_2026-07-22.md` を優先する。

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

- ParamStore は schema v4 だけを受理する。versionless、v1、v2、v3、future schema は
  変換せず明示的に拒否し、原本を上書き・隔離しない。
- 折りたたみヘッダは prefix 文字列でなく、`style` / `primitive` / `preset` /
  `effect_chain` の tagged record として保存する。variation snapshot も同じ key record と
  exact bool の `collapsed` を持つ record 列を使用する。
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
- RGB255 は exact 3-tuple の整数 `0..255` だけを受理する。list、数値文字列、bool、float、
  範囲外値を `int()` 化や clamp で修復しない。
- MIDI CC 番号は非 bool の整数 `0..127` に限定する。scalar CC は
  float/int/choice、3成分 CC は vec3 だけが対応し、RGB、bool、文字列、
  global/layer style への非機能 mapping は拒否する。JSON の
  `[null, null, null]` も `null` の別表現として受理しない。
- 現行 writer が必ず出力する parameter/effect-chain ordinal が欠損した v4 payload は、
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
- Python frame/stack を取得できない場合は衝突する固定 site ID を生成せず、即時に失敗する。

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
- `ExportJob` も keyword-only であり、旧 positional field 順は受理しない。
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
- `retain_rollback=True` の source reload は、成功 generation ごとに
  `accept_generation()` または `rollback_generation()` で明示的に完結させる。
  pending transaction のまま次の `poll()` を呼ぶと失敗し、自動 accept は行わない。

## MIDI snapshot / runtime dependency

- MIDI CC snapshot は schema v1 の
  `{schema_version, values: [{cc, value}, ...]}` 一形だけを受理する。record は CC 昇順かつ
  一意、CC は exact built-in `int` `0..127`、value は exact built-in `float` の有限値
  `0.0..1.0` である。JSON の重複 key、過大整数、
  parser の再帰上限も corrupt として診断する。
- missing file だけを空 snapshot とする。versionless、old/future、JSON破損、部分不正、
  I/O error は診断付きで全体を拒否し、旧 flat dict の decoder や部分復元はない。
- 拒否した原本は終了時の自動保存で上書きせず、skip を診断して通常終了する。
  Inspector の `Clear saved snapshot` などの明示 discard は原本を空の現行 schema へ置き換え、
  接続中 controller の live CC 値は保持する。
- `MidiSession` は controller と同一 instance の load result、または未接続時の load result と
  永続 discard callback を構築時にまとめて受け取る。後付け activation や値だけの別系統はない。
- port の pending 取得と iterator 失敗だけを `MidiConnectionError` として frozen 遷移させる。
  message の strict validation error や controller 内部の不具合は切断として握りつぶさず伝播する。
- 切断時の controller は最新 live CC の shutdown save 所有者として保持する。
  frozen snapshot を明示 clear した後は所有を破棄し、shutdown で値を書き戻さない。
- retry/discard 診断 action は現在の event、controller、load result の同一性を検査する。
  controller の snapshot load は constructor 内の private 操作であり、後から診断を stale 化する public `load()` はない。
- shutdown は snapshot save が `BaseException` で失敗しても port close を試み、
  二重失敗時は最初の例外 identity と後続 cleanup 診断を保持する。
- GUI の reconnect は「未接続かつ reconnect factory あり」の場合だけ有効になる。
  MIDI 明示無効は reconnect 失敗診断を発生させない。
- 注入する MIDI input port は `iter_pending()` と `close()` の両方を実装する必要がある。
  不完全な test double を補う production fallback はない。
- `mido` / `python-rtmidi` は required dependency であり、import 失敗や backend error を
  MIDI 無効として握りつぶさず伝播する。
- 対応 Shapely は `shapely>=2,<3` であり、Shapely 1.x の `shapely.geos` fallback はない。
  required dependency の `psutil` も正規 API を直接使用し、API mismatch を CPU 0 や
  欠測へ読み替えない。

## CLI

- `python -m grafix config validate|show [PATH]` の config path は positional だけである。
  同義の `--config` は削除した。
- `python -m grafix run ... --midi-port none` だけが MIDI を無効化する。空文字、`off`、
  大小違い、前後空白付き token は alias として扱わない。
- subcommand の引数で先頭に区切りの `--` を置く場合は一度だけ除去する。

## Geometry / text / benchmark

- `Geometry.create()` と `compute_geometry_id()` から caller 指定の `schema_version` を削除した。
  Geometry ID は固定 schema v2 domain だけで計算する。
- `Geometry` の ID は canonical `op` / `inputs` / `args` からだけ生成する。constructor や
  pickle payload から任意 ID を注入する入口はなく、復元時も recipe から再計算する。
- `RealizedGeometry` は exact float32 `(N,3)` coords と exact int32 offsets の
  C-contiguous・有限・整合済み配列だけを受理する。2D 補完、dtype cast、整数切り捨ては行わず、
  外部配列と共有しない bytes-backed immutable snapshot を保持する。
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
- JSON 系 benchmark checksum は `canonical_json_sha256_v2` へ更新した。mapping、bytes、
  ndarray、nested `Geometry` / `RealizedGeometry` は型 tag 付きの owned encoding を使い、
  unknown 値、非文字列 key、非有限値、structured/object dtype を拒否する。
- JSON array の checksum 入力は exact `list` 一形であり、任意 tuple を配列へ読み替えない。
  v1 と v2 の checksum は直接比較できないため、旧 benchmark baseline は再計測する。
- benchmark の case 定義、primitive/effect case、environment/spec、比較 row は
  `FrozenJsonObject` で深く固定する。setup/CLI JSON の境界だけが独立した plain
  `dict` / `list` tree を materialize する。

## Effect 引数

- G/E の `meta` 付き引数は Parameter 記録 context の有無にかかわらず、factory で同じ
  validator を通り、型・shape・choice を検証する。値域や引数間の相関などの意味検証は
  evaluator が空入力・identity/no-op 判定より先に行う。
- choice 引数は exact `str` と既知値だけを受理する。未知値を identity/no-op として
  扱わない。
- vec3 引数は3要素 tuple 一形の有限実数、整数引数は bool/float/数値文字列を除く
  整数スカラーとする。
- `E` の通常 step と selector step は frozen DTO と immutable tuple 引数を保持する。
  builder は nested mapping を公開せず、値として比較・hash 化できる。
- `dash` と `fill` の引数は scalar 一形である。旧 list/sequence の cycle 指定は削除した。
- raw builtin も canonical `(coords, offsets)` と現在の scalar/tuple 引数だけを前提とする。
  `drop` / `clip` / `mirror3d` の旧 layout 分岐や、`polyhedron` の旧配列 schema は受理しない。
- 非有限値、意味のない負値、無効な count/grid/range は明示的に拒否する。
  distance 0、repeat count 0 など、effect の意味として定義された identity だけを残す。
- probability clamp、数値アルゴリズム内部の安定化 clamp、Shapely geometry の
  best-effort 分解は入力互換シムではなく、各 effect の正規数値契約として維持する。

## Strict DTO / normalization 境界

- `polyline`、`spline`、`bezier` の code-owned point は immutable tuple 列を使用する。
  ndarray 専用 fast path や raw Sequence 変換はなく、公開 G 経路では ndarray を拒否する。
- builtin primitive/effect は append-only catalog と live registry を分離する。
  live registry の clear/replace 後は import reload や互換 wrapperを使わず、catalog に記録した
  同一 `OpSpec` を不足時だけ再登録する。明示的な live override は上書きしない。
- 文字列 identity、status、mode、choice は exact built-in `str` と既知値を検証し、
  `str(value)` で補わない。variation / batch 名は前後空白を値として保持し、
  空白だけの名前だけを拒否する。
- 実数は bool を除く有限な `numbers.Real` を受けて Python `float` へ正規化する。
  整数は bool、float、数値文字列を拒否し、整数 scalar だけを Python `int` へ正規化する。
- process message、capture snapshot、内部 export job/result、variation batch result などの
  内部 DTO は、必要箇所で keyword-only、exact tuple、`Path`、enum、要素型を検証する。
  list-to-tuple、文字列-to-`Path`、旧 positional field 順を DTO 内で救済しない。
- worker の `DrawResult` は layers/records/labels/effect chain を immutable tuple で保持する。
  ParamState snapshot、reconcile fingerprint、selector 解決結果、GUI snapshot も nested mutable
  mapping/value を外へ公開しない。
- Parameter GUI の Copy Code は canonical scalar/tuple/plain dict だけを Python literal 化し、
  unknown object を `repr()` や `str()` へ落として実行不能コードを生成しない。
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
