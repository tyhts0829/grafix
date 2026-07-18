# `src/grafix` 本質的リファクタリング計画（2026-07-18）

作成日: 2026-07-18
基準 HEAD: `ead4d1d`
ステータス: **採用範囲の実装・自動検証完了
（意図的見送り、benchmark の既知 checksum 例外、macOS interactive smoke 未実施を記録済み）**

## 1. 目的

現在の Grafix の機能、公開 API、数値出力、描画結果、保存形式、対話操作、速度特性を
変えずに、次を達成する。

- アーキテクチャで意図した依存方向と、実際の import 方向を一致させる。
- 同じ状態や同じアルゴリズムを複数箇所で管理する構造をなくす。
- 巨大関数を単に別ファイルへ移すのではなく、責務と所有者を明確にする。
- test の都合だけで production code に残っている不完全初期化対応を減らす。
- production code の総量を、可読性を損なう code golf なしで純減させる。

本計画では「動くように直す」変更や最適化を同時に行わない。既存の正常動作を
characterization test と checksum で固定し、構造だけを段階的に置き換える。

## 2. 調査した現在のアーキテクチャ

### 2.1 維持する中心設計

`architecture.md` と実装を照合した結果、次の中心設計は合理的であり、今回変更しない。

1. `Geometry` は配列ではなく immutable なレシピ DAG である。
2. `RealizeSession` が評価、inflight 集約、byte 上限付き LRU を所有する。
3. `RealizedGeometry` は `coords(float32, Nx3)` と
   `offsets(int32, M+1)` の immutable packed representation である。
4. Geometry と描画スタイルは `Layer` で分離する。
5. パラメータは frame snapshot の中で解決し、次フレームから GUI/CC の変更を反映する。
6. built-in primitive/effect は manifest を使って必要なものだけ lazy load する。
7. interactive と headless export は同じ `realize_scene()` を利用する。
8. renderer、worker、capture は明示的な resource owner が close する。

したがって、Geometry 署名、realize の評価順、cache 方針、parameter hot path、
renderer/GL、Numba kernel を作り直すことは本計画の対象外とする。

### 2.2 現在の規模と集中箇所

調査時点の `src/grafix/**/*.py` は 215 ファイル、71,993 行である。特に大きい箇所は
次の通り。

| ファイル | 行数 | 主な責務 |
|---|---:|---|
| `interactive/parameter_gui/gui.py` | 2,141 | GUI 構築、同期、終了処理 |
| `interactive/runtime/draw_window_system.py` | 2,048 | preview runtime の統合 |
| `core/effects/util.py` | 1,895 | 平面、grid、resample、packed geometry |
| `api/runner.py` | 1,256 | 公開 `run()` と workspace/window 組み立て |
| `interactive/runtime/export_job_system.py` | 1,031 | 非同期 capture worker |
| `api/render.py` | 681 | headless render の公開契約 |
| `interactive/runtime/source_reload.py` | 620 | source reload と registry transaction |

ファイルの大きさだけを理由に分割はしない。重複した状態、逆向き依存、同じ終了規則の
再実装を減らした結果として、責務境界と行数を改善する。

### 2.3 確認した構造上の問題

#### RF-001: 外側の公開 API を内側が import している

意図する依存方向は `api -> export / interactive -> core` だが、現在は次が存在する。

- `export/capture.py -> api/render.py`
- `interactive/runtime/draw_window_system.py -> api/render.py`
- `interactive/parameter_gui/variation_panel.py -> api/render.py`

`CaptureService` には既に最小の `CaptureFrame` protocol がある一方、公開 `Frame`、
`ExportFormat`、`ExportResult` にも直接依存している。これにより `api <-> export`、
`api <-> interactive` の package cycle が生じる。

#### RF-002: 同じ packed/ring 処理が effect・primitive 内に複製されている

以下の helper は 4〜6 箇所に同一またはほぼ同一の実装がある。

- `_planarity_threshold`
- `_close_curve`
- `_extract_rings_xy`
- `_pack_rings`
- `_empty_geometry`
- `_lines_to_realized`

主な対象は `metaball.py`、`growth.py`、`warp.py`、`isocontour.py`、
`reaction_diffusion.py`、`clip.py`、`laplace_field_grid.py`、`lsystem.py` である。
重複は修正漏れを生む一方、数値処理なので安易な一般化は出力順や性能を変え得る。

#### RF-003: preset が二つの mutable registry に分かれている

現在は次を別々に管理している。

- `PresetRegistry`: `preset.<name>` ごとの GUI metadata
- `PresetFuncRegistry`: `<name>` ごとの callable

`@preset` は一つの preset を二度登録する。source reload は effect、primitive、
preset spec、preset func の四つを stage/commit/rollback し、core と API に複製された
registry 参照を合計 9 箇所差し替える。これは同じ世代であるべき情報を別状態にした結果の
複雑さである。

#### RF-004: 同じ cleanup 規則が複数箇所に再実装されている

「全 cleanup を順に試し、最初の例外を最後に再送出する」という処理が
`api.runner`、`DrawWindowSystem`、`ExportJobSystem`、`ParameterGUI` に繰り返されている。
特に `ExportJobSystem` 内には同型の局所関数が複数ある。

#### RF-005: test の不完全な object が production 分岐を増やしている

`DrawWindowSystem` の test では `object.__new__(DrawWindowSystem)` が 31 回使われる。
その結果、production code に constructor を通らない object 向けの `getattr` /
`hasattr` fallback が残る。実際の optional backend 対応と test 専用 fallback を
区別せず一括削除することは危険なので、初期化済み test fixture へ移行した後に、
test 以外から到達しない分岐だけを削除する。

## 3. 変更してはならない契約

### 3.1 公開 API

- `grafix` と `grafix.api` の `__all__`
- import path、関数・method signature、既定値、例外型、例外発生条件
- `Frame`、`RenderOptions`、`ExportFormat`、`ExportResult` など公開 class の
  `__module__`、型 identity、pickle/import compatibility
- `src/grafix/api/__init__.pyi` の公開内容
- `G` / `E` / `P` の lookup、lazy import、decorator の戻り値

公開 class を下位 package へ移して API から re-export する案は採用しない。
re-export だけでも `__module__` や pickle の観測値を変えるためである。

### 3.2 Geometry と数値出力

- Geometry ID、cache key、registry revision の意味と更新回数
- primitive/effect の line 順、vertex 順、dtype、shape、offset 値
- close 判定の `rtol=0`, `atol=1e-12`、退化入力、空入力の扱い
- `coords` / `offsets` の immutable 性
- renderer cache が利用する配列 identity。特に、単一 Geometry の concat 等で
  同じ `offsets` object を返す契約を不要な copy で壊さない
- SVG、PNG、G-code、manifest の内容と path/versioning 規則

### 3.3 runtime

- parameter load/persistence/recovery と revision
- source reload の candidate 隔離、原子的 commit、失敗時 rollback
- worker generation、timeout、cancel、late result の扱い
- window/workspace restore、capture、MIDI、video、renderer の close 順
- cleanup 中に複数の失敗が起きても、全 step を試して最初の例外を送出する規則
- Retina/resize、GUI slider、thumbnail、final-quality capture の動作

### 3.4 性能

「速度不変」は単発値の完全一致ではなく、同一 machine・同一 environment・同一 case の
before/after で系統的な退行がないこととして検証する。

- benchmark status、checksum、hard contract は完全一致を必須とする。
- `benchmark compare` に `--allow-incompatible` を使わない。
- median が 10% 超悪化し、かつ差が base/head の揺らぎの 3 MAD を超えた場合は不合格。
- p95 が 15% 超悪化した場合は同条件で再計測し、再現すれば不合格。
- hot path に新しい配列 copy、registry scan、ContextVar lookup、動的 dispatch を増やさない。
- 不合格の Phase は原因を解消できなければ、その Phase の実装を戻す。

## 4. 非目標

今回は次を行わない。

- 新機能、公開 API 変更、既定値変更、エラーメッセージの整理
- Geometry、RealizeSession、ParamStore schema、renderer/GL の再設計
- Numba/SDF/filter kernel の共通化や高速化
- GUI layout や見た目の変更
- `RenderSettings` / `RenderOptions` の統合
  - 現在は線幅の既定値など意味が異なり、単なる重複ではないため
- `buffer` / `partition` の平面 basis 統合
  - 退化時と向きの契約が異なるため
- `ParamStore` の tracked set wrapper 廃止
  - 直近の performance 改善と重なる高リスク領域のため
- benchmark case/harness 自体のリファクタリング
  - case source が compatibility key に含まれ、同時変更すると比較不能になるため
- 行数を移動するだけの巨大ファイル分割
- compatibility wrapper、shim、新規外部依存

## 5. 実施原則

- [x] 実装前に現在の architecture、依存、重複、test、benchmark を静的調査した。
- [x] 実装計画を本ファイルへ作成した。
- [x] ユーザーの承認を得るまで production code を変更しない。
- [x] 各 Phase 開始時に `git status --porcelain` と HEAD を記録する。
- [x] 並行作業の依頼外差分を変更、移動、削除、stage しない。
- [x] 先に characterization test を追加し、その後に実装を置換する。
- [x] 一度に一つの状態所有者または一つの exact clone family だけを変更する。
- [x] 各 Phase で対象 test、ruff、mypy、benchmark を実行する。
- [x] Phase 完了ごとに本ファイルの checkbox と実測結果を更新する。
- [x] 失敗した Phase を次の Phase の変更で覆い隠さない。

## 6. Phase 0 — baseline と同値性の固定

### 0.1 変更前の状態を保存する

- [x] 実装開始直前の HEAD、Python、NumPy、Numba、OS、CPU、git status を記録する。
- [x] `src/grafix/api/__init__.pyi` を `/tmp` へコピーし、最終時に byte compare する。
- [x] `grafix.__all__`、`grafix.api.__all__`、公開 object の import path/signature/
  `__module__` を機械可読な baseline として保存する。
- [x] `src/grafix` の production LOC、import edge、registry 数、duplicate helper 数を記録する。
- [x] full pytest、ruff、mypy の変更前結果を記録する。

### 0.2 出力同値性を固定する

- [x] 固定 seed で、対象 ring effect の open/closed、傾斜平面、退化、空入力、
  複数 line の `coords` / `offsets` exact checksum を保存する。
- [x] preset の登録、重複、lookup、revision、catalog 順、autoload、reload rollback を
  characterization test で固定する。
- [x] cleanup の実行順、全 step 実行、最初の例外の再送出、secondary error の扱いを
  fault injection test で固定する。
- [x] headless render を `t=0` と非 0 で実行し、layer/site/style、Geometry/cache key、
  packed array、SVG/G-code/manifest を比較可能にする。
- [x] 同じ `resvg` executable/version で PNG の byte または decoded pixel を保存する。

### 0.3 性能 baseline を採る

benchmark source は before/after の間で変更しない。出力は repository 外の `/tmp` に置く。

```bash
PY=/opt/anaconda3/envs/gl5/bin/python

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite effects --suite pipeline --suite system \
  --profile short --run-id refactor-base-core \
  --out /tmp/grafix-refactor-benchmark

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite interactive --suite gui --suite mp \
  --profile short --run-id refactor-base-interactive \
  --out /tmp/grafix-refactor-benchmark

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite all --profile long --run-id refactor-base-all-long \
  --out /tmp/grafix-refactor-benchmark
```

Phase 0 完了条件:

- [x] 変更前の correctness と performance baseline が揃っている。
- [x] baseline 自体に既知 failure があれば、今回直さず本ファイルへ明記して判定から分離する。
- [x] baseline 取得後、benchmark harness を最終比較まで変更しない。

Phase 0 実施記録:

- HEAD `ead4d1d`、Python 3.12.12、NumPy 2.3.5、Numba 0.63.1、
  macOS 26.5.1 arm64 で取得した。
- `pytest`: 1,607 passed（57.19 秒）。
- `ruff`: success。
- `mypy`: 215 source files、error 0。
- benchmark: core short 48 case、interactive short 15 case、all long 86 case を
  `/tmp/grafix-refactor-benchmark` に保存した。
- 既知 baseline failure: `mp.draw.light` と `mp.draw.slider_churn` は
  distribution statistics の schema validation error。今回のリファクタリングでは
  benchmark harness を変更せず、head でも同じ status/error であることを確認する。
- 公開 API baseline、stub、LOC、逆向き import、headless packed array、
  SVG/G-code/PNG checksum、G/E/P/packing の repository 外 micro benchmark を
  `/tmp` に保存した。

## 7. Phase 1 — API / export / interactive の依存方向を正す

対象:

- `src/grafix/api/export.py`
- `src/grafix/api/render.py`
- `src/grafix/api/variation_batch.py`
- `src/grafix/export/capture.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/interactive/runtime/export_job_system.py`
- `src/grafix/interactive/parameter_gui/variation_panel.py`
- `tests/architecture/test_dependency_boundaries.py`

アクション:

- [x] `CaptureService` の入力を既存 `CaptureFrame` protocol に限定し、公開 `Frame` の
  `isinstance` validation と公開 `ExportResult` の生成を `api` 側へ移す。
- [x] export 層の suffix/mode と publish 結果を内部型で表し、`ExportFormat` /
  `ExportResult` を import しない。
- [x] `api.export()` で従来どおり公開 `Frame` を検証し、内部 publish 結果を公開
  `ExportResult` へ一度だけ変換する。
- [x] `variation_batch` は `CaptureFrame` を受ける service 境界を利用し、
  capture backend の既存注入契約を維持する。
- [x] thumbnail/final capture は公開 `Frame` を組み立てず、既存
  `FrameExportSnapshot` または同じ最小 snapshot を `CaptureFrame` として渡す。
- [x] `ParameterLoadMode` のような下位層も必要とする type alias だけを core の適切な
  所有場所へ移し、`api.render` から同名で re-export する。
- [x] 公開 class 本体は `api.render` に残し、型 identity と `__module__` を維持する。
- [x] architecture test に「`export` と `interactive` は `grafix.api` を import しない」を追加する。
- [x] `architecture.md` の依存図と実装を一致させる。

Phase 1 完了条件:

- [ ] Phase 1 単独完了時点で、`src/grafix/export` と `src/grafix/interactive` から
  `grafix.api` import が 0 件。
- [x] 公開 API/stub、Frame validation、format/suffix error、path versioning、manifest が同一。
- [x] capture checksum と対象 benchmark に退行がない。
- [ ] 新しい facade/shim を増やさず、依存 edge と production LOC が純減する。

Phase 1 実施記録:

- `CaptureService` を公開 API 型から切り離し、公開 `Frame` の検証と
  `ExportResult` 生成を `grafix.export()` 側へ移した。
- 通常の static import は 0 件になった。一方、`source_reload.py` に registry staging
  用の `importlib.import_module("grafix.api.*")` が 4 件残るため、完全な 0 件判定は
  Phase 3 の registry 統合と architecture test 強化後に 0 件になった。
- `variation_batch` の注入 backend は従来どおり
  `export(frame, path, overwrite=..., output_size=...)` と `.path` /
  `.manifest_path` の契約を維持した。
- 公開 class identity、`__module__`、signature、pickle、`__all__`、stub は baseline と一致。
- full pytest: 1,609 passed。ruff、mypy、diff check も成功。
- interactive/gui/mp short は正常 13 case の checksum/hard contract が一致し、
  最大 median ratio は 1.016。既知 mp 2 case は base/head とも同じ error。
- 新しい facade/shim は追加せず依存 edge は削減した。固定 config fallback と公開
  export 契約を厳密に維持した結果、Phase 1 単独の production LOC は 11 行増となった。
  LOC は後続の重複状態・重複 helper 削減を含む全体で純減させた。

## 8. Phase 2 — 数値的に同一な helper だけを一本化する

### 2.1 planar ring helper

対象:

- `src/grafix/core/effects/util.py`
- `metaball.py`
- `growth.py`
- `warp.py`
- `isocontour.py`
- 必要な範囲だけ `reaction_diffusion.py`、`clip.py`

アクション:

- [x] AST/body と characterization test の双方で同一と確認した
  `_planarity_threshold`、`_close_curve`、`_extract_rings_xy`、`_pack_rings` を共通化する。
- [x] `core/effects/AGENTS.md` に従い、effect 同士を import せず、共有先は
  `effects/util.py` の内部 helper に限定する。
- [x] effect 固有の validation、grid/SDF 処理、退化時 policy は各 effect に残す。
- [x] `buffer`、`fill`、`weave` の見かけが似ていても意味が異なる処理は統合しない。
- [x] float64 での中間計算、iteration 順、close endpoint、float32/int32 への
  pack 順を変更しない。

### 2.2 packed geometry helper

対象:

- `src/grafix/core/realized_geometry.py`
- `src/grafix/core/primitives/laplace_field_grid.py`
- `src/grafix/core/primitives/lsystem.py`
- 必要な範囲だけ `text.py`、`asemic.py`

アクション:

- [x] 完全に同一な `_lines_to_realized` と空 geometry 生成だけを既存 core 型の近くへ集約する。
- [x] `np.concatenate` 後 cast と事前 float32 確保など、allocation 特性が違う実装は
  benchmark なしに統合しない。
- [x] 最小頂点数、2D/3D、empty line、exception、copy/identity の違いを吸収する
  option-heavy helper は作らない。
- [x] 共通化後の helper 本体と呼び出し側の合計行数・分岐数が減らない場合は統合しない。

Phase 2 完了条件:

- [x] 対象の exact clone family が一実装になっている。
- [x] 全対象 case の packed array checksum が完全一致する。
- [x] effects/pipeline/system benchmark に退行がない。
- [x] production code を 120〜200 行程度純減する。ただし行数のための圧縮はしない。

Phase 2 実施記録:

- `PlanarRing` と ring の判定・抽出・pack を `effects/util.py` に集約し、
  `metaball`、`growth`、`warp`、`isocontour` の 4 重実装を削除した。
- `clip` と `reaction_diffusion` は完全同一の planarity threshold だけを共有し、
  意味の異なる mask ring pack は残した。
- `empty_geom_tuple()` と `lines_to_geom_tuple()` を
  `core/realized_geometry.py` に置き、同一実装だけを移行した。
- `growth` / `warp` の offsets 確保は `zeros` から `empty` + 全要素代入へ統一した。
  出力は完全一致し、対象 benchmark に退行はなかった。
- full pytest: 1,616 passed。ruff、mypy、diff check も成功。
- core short 48 case は checksum/hard contract が全一致。変更対象 case の
  median/p95 は gate 内で、packed helper の repository 外 micro benchmark は
  median ratio 1.034 だった。
- Phase 2 対象 production 12 ファイルは 302 行純減した。

## 9. Phase 3 — preset の状態所有者を一つにする

対象:

- `src/grafix/core/preset_registry.py`
- `src/grafix/api/preset.py`
- `src/grafix/api/presets.py`
- `src/grafix/interactive/runtime/source_reload.py`
- preset、source reload、catalog、stub 関連 test

アクション:

- [x] callable、display name、meta、param order、ui visibility を一つの immutable
  `PresetSpec` にまとめる。
- [x] canonical key を `preset.<name>` に統一し、`P.<name>` 解決は registry 内の
  一つの canonicalization だけを通す。
- [x] `PresetFuncRegistry` と二度登録を削除し、一つの `PresetRegistry` を
  一回の操作で原子的に更新する。
- [x] 一登録につき preset revision が従来と同じ回数だけ進むよう固定する。
- [x] API module が registry object のコピーを保持せず、core registry module を
  module-qualified に参照するよう変更する。
- [x] source reload の staged bundle を effect/primitive/preset の三つにし、
  core module の三つの registry だけを一時差し替える。
- [x] candidate import 失敗、validation 失敗、worker swap 失敗時の rollback と、
  成功時だけの commit を維持する。
- [x] primitive/effect registry は evaluator 契約が異なるため統合しない。

Phase 3 完了条件:

- [x] preset の mutable registry が 2 個から 1 個になる。
- [x] source reload の staged registry が 4 個から 3 個になる。
- [x] staged registry の module-global 差し替えが 9 箇所から core の 3 箇所になる。
- [x] duplicate error、`P` lookup、autoload、catalog/stub 順、revision、rollback が同一。
- [x] G/E/P と source reload の benchmark に退行がない。
- [ ] production code を 80〜140 行程度純減する。

Phase 3 実施記録:

- callable と GUI metadata を immutable な `PresetSpec` にまとめ、
  `PresetFuncRegistry` と二重登録を削除した。
- API の G/E/P は core registry module を module-qualified に参照する。
  source reload の staged registry は 4 個から 3 個、module-global の一時差し替えは
  9 箇所から core の 3 箇所になり、`grafix.api` への動的逆向き import も削除した。
- candidate import、validation、worker swap の各失敗に対する rollback と、
  成功時だけ live registry を一括更新する契約を fault injection test で固定した。
- full pytest: 1,629 passed。ruff、mypy、diff check も成功し、公開 stub は
  baseline と byte-identical だった。
- core short 48 case は checksum/hard contract が全一致した。G/E/P micro benchmark
  も checksum が一致し、P lookup の余分な helper call を除いた再計測では
  `P.<name>` attribute lookup の median ratio は 1.002 だった。
- Phase 3 対象 production code は 73 行純減した。見積もり下限には 7 行届かなかったが、
  hot path を複雑化して行数だけを合わせず、状態所有者・差し替え箇所・依存 edge の
  削減を優先した。

## 10. Phase 4 — lifecycle と interactive composition を単純化する

### 4.1 cleanup 規則を一実装にする

対象:

- 新規候補 `src/grafix/core/lifecycle.py`
- `src/grafix/api/runner.py`
- `src/grafix/interactive/runtime/draw_window_system.py`
- `src/grafix/interactive/runtime/export_job_system.py`
- `src/grafix/interactive/parameter_gui/gui.py`

アクション:

- [x] Phase 0 の fault injection test で固定した
  「全 step 実行・最初の例外を再送出」を小さな内部 helper にする。
- [x] 各 owner は step の内容と順序だけを宣言し、例外蓄積 loop を再実装しない。
- [x] worker join/terminate、queue close/join、GL context 切替など順序依存処理は、
  無理に一つの汎用 resource abstraction へ入れない。
- [x] secondary error の logging 有無を現在の call site ごとに維持する。

### 4.2 `run()` を composition root に戻す

対象:

- `src/grafix/api/runner.py`
- `src/grafix/interactive/runtime/` の workspace/window 関連 module

アクション:

- [ ] `run()` 内の構築順、所有権、終了順を characterization test で明示する。
- [ ] macOS workspace/window の機構を interactive 側の既存 owner へ寄せ、
  `api.runner` は公開引数の検証と component composition に集中させる。
- [ ] 小関数を別ファイルへ移すだけでは実施せず、重複する状態または pass-through
  call が消える単位で移す。
- [x] `run()` の cleanup 順を、parameter/workspace persistence、video、export、
  MIDI、scene/perf、GL context、renderer、window の現在の契約から変えない。

### 4.3 test-only partial state を除く

- [ ] `object.__new__(DrawWindowSystem)` を使う test を、必要な collaborator を明示する
  初期化済み fixture/factory へ移行する。
- [x] 各 `getattr` / `hasattr` fallback を、実 runtime の optional backend 用か、
  constructor を通らない test 専用か分類する。
- [ ] test 専用と証明できた fallback だけを production code から削除する。
- [x] 実 runtime の optional MIDI、GUI、video、capture、platform 差の fallback は維持する。

Phase 4 完了条件:

- [x] cleanup の例外蓄積 loop が一実装になり、全 fault injection test が同一結果になる。
- [ ] `api.runner` の責務と import が減り、単なる行移動ではなく全体 LOC が純減する。
- [ ] test の不完全初期化を支える production 分岐が残らない。
- [x] interactive/gui/mp benchmark に退行がない。
- [ ] macOS 実ウィンドウで起動、Retina resize、slider、reload、capture、close を確認する。

Phase 4 実施記録:

- `core/lifecycle.py` に、全 cleanup を実行しながら最初の `BaseException` を保持する
  `CleanupErrors` を追加した。runner、`DrawWindowSystem`、`ExportJobSystem`、
  `ParameterGUI` の例外蓄積をこの一実装へ統合した。
- worker の `queue.Full` 制御、`is_alive()` 失敗時の強制停止継続、
  terminate/join/kill 順、staging cleanup、GL context 切替順を変更していない。
  runner/DWS の secondary error だけを記録し、GUI/export worker は無記録のままにした。
- fault injection を追加・強化し、対象 91 test が成功した。ruff、mypy、
  tracked/untracked の diff check も成功した。
- Phase 4 時点の interactive/gui/mp short は正常 13 case の checksum/hard contract が
  全一致した。
  最大 median ratio は 1.045、最大 p95 ratio は 1.114 で gate 内だった。
  既知 mp 2 case は base/head とも同一 status/error だった。
- 対象 production code は 35 行純減した。
- `api.runner` の workspace/window block は、既存 owner へ移しても状態や pass-through が
  消えず単なる行移動になるため実施しなかった。
- `object.__new__(DrawWindowSystem)` 31 箇所と 35 個の存在確認を分類したが、
  capture/provenance fixture を全面再設計してまで分岐を除く費用対効果が低いため、
  今回は test/production とも変更しなかった。framebuffer、window capability、
  optional subsystem の fallback は実 runtime に必要なので維持した。

## 11. Phase 5 — 全体検証、文書更新、削減結果の記録

### 5.1 静的・機能検証

```bash
PY=/opt/anaconda3/envs/gl5/bin/python

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-tests \
PYTHONPATH=src \
$PY -m pytest -q -p no:cacheprovider

$PY -m ruff check src/grafix tests
$PY -m mypy --cache-dir /tmp/grafix-mypy-refactor src/grafix
git diff --check
cmp /tmp/grafix-api-init-before.pyi src/grafix/api/__init__.pyi
```

- [x] full pytest 成功。
- [x] ruff、mypy、`git diff --check` 成功。
- [x] 公開 stub baseline が byte-identical。
- [x] architecture dependency test 成功。
- [x] SVG/G-code checksum と PNG pixel が一致し、manifest 契約 test が成功。
- [ ] macOS interactive smoke test 成功。

### 5.2 performance 比較

Phase 0 と同じ profile、suite、seed、environment で head を採り、次を実行する。
`NUMBA_CACHE_DIR` の path も environment compatibility key に含まれるため、base/head で
同じ path を使う。

```bash
PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite effects --suite pipeline --suite system \
  --profile short --run-id refactor-head-core \
  --out /tmp/grafix-refactor-benchmark

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite interactive --suite gui --suite mp \
  --profile short --run-id refactor-head-interactive \
  --out /tmp/grafix-refactor-benchmark

PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/grafix-numba-refactor-bench \
PYTHONPATH=src \
$PY -m grafix benchmark run \
  --suite all --profile long --run-id refactor-head-all-long \
  --out /tmp/grafix-refactor-benchmark

$PY -m grafix benchmark compare \
  /tmp/grafix-refactor-benchmark/runs/refactor-base-core.json \
  /tmp/grafix-refactor-benchmark/runs/refactor-head-core.json

$PY -m grafix benchmark compare \
  /tmp/grafix-refactor-benchmark/runs/refactor-base-interactive.json \
  /tmp/grafix-refactor-benchmark/runs/refactor-head-interactive.json

$PY -m grafix benchmark compare \
  /tmp/grafix-refactor-benchmark/runs/refactor-base-all-long.json \
  /tmp/grafix-refactor-benchmark/runs/refactor-head-all-long.json
```

上記 run ID は初回比較用である。最終の同時点比較では、基準 HEAD の clone 側を
`refactor-base-current-machine-all-long`、現作業 tree 側を
`refactor-head-all-long-final2` として同じ all-long command を実行した。
p95 再確認は `refactor-base/head-relax-current-machine-100` に `--samples 100`、
timeout case の再確認は `refactor-base-reaction-current-machine-long` と
`refactor-head-reaction-final-long` に `--timeout 180` を指定した。

- [x] environment/case compatibility key が一致。
- [ ] status/checksum/hard contract が一致。
- [x] §3.4 の median/p95 gate を満たす。
- [x] RSS delta に再現する悪化がない。
- [x] `--suite all --profile long` を同一 machine の before/after で比較する。

### 5.3 定量目標

tests、docs、generated stub を除く production code について次を目標とする。

- [x] API への逆向き import: 3 ファイルから 0 ファイル
- [x] planar ring exact clone: 4 系統から 1 系統
- [x] preset mutable registry: 2 個から 1 個
- [x] staged registry global patch: 9 箇所から 3 箇所
- [x] first-error cleanup loop: 複数実装から 1 実装
- [x] production LOC: **純減 250〜450 行**

LOC は品質の hard gate ではない。ただし、抽象化を追加したのに重複状態、分岐、
import edge、総行数のいずれも減らない Phase は採用しない。

### 5.4 文書と実施記録

- [x] `architecture.md` を最終実装に合わせて更新する。
- [x] 各 Phase の変更ファイル、削減行数、test、benchmark 結果を本ファイルへ追記する。
- [x] 未実施、保留、取り消した項目と理由を明記する。
- [x] 依頼外差分を含めていないことを最終 `git status` と diff で確認する。

### 5.5 最終実施記録

- full pytest は **1,637 passed**。ruff、mypy（216 source files、error 0）、
  tracked/untracked の diff check、architecture dependency test はすべて成功した。
- 公開 API snapshot と生成 stub は baseline と完全一致した。固定 seed の packed
  geometry、SVG、G-code、PNG は exact compare、manifest は契約 test に成功した。
- core short は 48/48 case、interactive/gui/mp short は正常 13/13 case で
  checksum と hard contract が一致した。既知 mp 2 case は base/head とも同じ
  schema validation error だった。core short の初回比較では
  `effect.mirror.polyline_long` の median と `effect.relax.rings_2` の p95 に閾値超過が
  見えたが、対象の追加再計測では再現せず、系統的な退行ではないことを確認した。
- final production tree の計測時間帯では host 全体が変更前の保存 baseline より遅く
  なっていたため、基準 HEAD `ead4d1d` を `/tmp` の git clone に展開し、package
  metadata も 0.0.6 に揃えて all long を同じ現在状態で再取得した。final production
  tree との environment/case compatibility key は完全一致した。
- この同時点 all-long 比較は 86/86 case で status が一致した。内訳は双方とも
  83 ok、`effect.reaction_diffusion.final.rings_2` が 120 秒 timeout、既知 mp 2 case
  が同一 error である。83 ok case は全 hard contract、81/83 checksum が一致した。
  checksum 不一致 2 case は、既存 harness が実測 `initial_merge_ms` を semantic
  checksum に含める `runtime.parameter_merge.rows_1000/10000.change_steady` であり、
  state digest、revision、hard contract は一致した。このため「全 checksum 一致」の
  checkbox は意図的に未完了のままとする。
- reaction-diffusion final は base/head とも timeout を 180 秒へ揃えた単独 long で
  再計測し、status、exact checksum、hard contract が一致した。median/p95 ratio は
  1.002/1.001 だった。
- 同時点 all-long 比較の最大 median ratio は 1.087 で gate 内だった。p95 は
  `effect.relax.rings_2` の一標本の外れ値だけが 1.336 となったため、base/head を
  100 samples で再計測し、median/p95 ratio 1.008/1.030 で非再現を確認した。
- RSS の大きな差も、同じ case を反復し実行順を変えた base/head 再計測で反転または
  消失した。例えば `interactive.renderer.animated_topology_100k` の RSS delta は
  反復時に head 109.9 MiB、base 143.4 MiB となり、系統的な悪化はなかった。
- production code は 215 ファイル・71,993 行から 216 ファイル・71,594 行へ、
  **399 行純減**した。内訳は Phase 1 が 11 行増、Phase 2 が 302 行減、
  Phase 3 が 73 行減、Phase 4 が 35 行減である。
- macOS 実ウィンドウ smoke は、非 GUI 実行環境では display を取得できず、
  GUI 経由の再試行時は Mac がロックされたため完了していない。起動 process は停止済みで、
  この一項だけを未実施として明記する。

## 12. 中止・切り戻し条件

次のいずれかが起きた Phase は、後続 Phase へ進む前に修正または当該 Phase の実装を
切り戻す。

- 公開 API、stub、class identity、例外契約が変わる。
- Geometry/output checksum、line 順、dtype、offset、manifest が変わる。
- source reload の原子性または cleanup 順が変わる。
- 同条件で性能退行が再現する。
- 共通 helper に mode flag や optional 引数が増え、元の重複より理解しにくくなる。
- 新しい registry/cache/global mutable state が増える。
- ファイル移動だけで production LOC または依存 edge が減らない。

## 13. 承認後の実施順

`Phase 0 -> 1 -> 2 -> 3 -> 4 -> 5` の順に進める。各 Phase は独立して検証し、
完了結果を本ファイルへ記録してから次へ進む。

Phase 0 から Phase 5 まで順に実施し、採用した構造変更と自動検証は完了した。
未実施・未達は、Phase 4 で費用対効果から意図的に見送った項目、既存 harness の
volatile timing による checksum 2例、外部環境上の理由による macOS interactive
smoke であり、いずれも上記に理由と検証範囲を記録した。
