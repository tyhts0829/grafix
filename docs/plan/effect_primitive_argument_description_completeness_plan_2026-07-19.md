# Effect / Primitive 引数 Description 完全化計画

## 1. 目的

- 組み込み primitive / effect のすべての公開引数に、用途が分かる説明を持たせる。
- Parameter GUI、IDE の生成 stub、operation catalog / CLI で同じ説明を利用できる状態にする。
- 今後 primitive / effect を追加したとき、引数や説明の追加漏れを自動検出する。
- first-party の説明を必須にしつつ、ユーザー定義 operation では従来どおり
  `description` を任意に保つ。

## 2. 現状監査

- [x] 作業開始時の `git status --porcelain` が空であることを確認した。
- [x] 組み込み primitive 17 件、effect 32 件が builtin manifest、decorator、
  registry catalog で一致することを確認した。
- [x] GUI 対象の primitive 引数 129 件と自動 `activate` 17 件は、
  146 / 146 件すべてに非空の `ParamMeta.description` がある。
- [x] GUI 対象の effect 引数 176 件と自動 `activate` 32 件は、
  208 / 208 件すべてに非空の `ParamMeta.description` がある。
- [x] primitive / effect 自体の短い operation description は 49 / 49 件そろっている。
- [x] Global Style 3 件、Layer Style 2 件、first-party preset metadata、
  preset の自動 `activate` にも description があり、既存 completeness test は
  5 件すべて成功する。
- [x] GUI に出さない code-owned 引数のうち、次の 5 件だけは個別説明がない。
  - `bezier.p0`
  - `bezier.p1`
  - `bezier.p2`
  - `bezier.p3`
  - `polyline.points`
- [x] 上記 5 件は `ParamMeta` に含めない設計がテストで明示されている。
  現状は NumPy docstring の `Parameters` にも説明がないため、生成 stub の Help でも
  引数説明が欠落する。
- [x] 既存 completeness test は「存在する `spec.meta`」だけを検査するため、
  callable 引数そのものを metadata へ追加し忘れた場合を検出できない。
- [x] `python -m grafix describe` は metadata の kind/range/choices を表示するが、
  `description` は表示しない。
- [x] README と同梱 custom operation 例の meta spec は、
  `description` を書く推奨形をまだ示していない。
- [x] 公開 `@primitive` / `@effect` デコレータの docstring は、
  `meta` / `ui_visible`、および effect の `n_inputs` の個別説明が欠けている。

## 3. 実装方針

### 3.1 説明の source of truth

- [x] Parameter GUI 対象引数は、現在どおり `ParamMeta.description` を source of truth にする。
- [x] `bezier` の制御点と `polyline.points` は code-owned のまま維持し、
  GUI 対象へ変えるためだけの新しい `ParamMeta.kind` や互換層は追加しない。
- [x] code-owned 引数は、公開 API 規約に沿った NumPy スタイル `Parameters`
  docstring を source of truth にする。
- [x] `activate` は primitive / effect / preset ごとの共通 metadata を引き続き使う。
- [x] `key` / `instance_key` / `shared` は Parameter GUI の行ではないため
  `ParamMeta` の対象外とし、共通 API 引数として生成 stub の Help に一度だけ定義した
  共通説明を反映する。

### 3.2 欠落している引数説明

- [x] `bezier.p0`〜`p3` に、始点・第 1 / 第 2 制御点・終点であることを明記する。
- [x] `polyline.points` に、2D / 3D 点列、入力順、空列の扱いが分かる説明を書く。
- [x] `@primitive` の `meta` / `ui_visible` と `@effect` の
  `n_inputs` / `meta` / `ui_visible` を公開 docstring に追記する。
- [x] 角度を度で受け取る `mirror3d.phi0`、`repeat.rotation_step`、
  `twist.angle`、`warp.angle` の description に単位を明記する。
- [x] 0 や負値が「無効」を意味する `drop.interval` / `min_length` / `max_length`、
  `partition.site_density_*`、`warp.band` / `snap_band` / `falloff` の
  sentinel semantics を description に明記する。
- [x] `mirror.n_mirror`、`mirror3d.n_azimuth`、`warp.profile` は、
  値・選択肢と結果の対応が Help だけで分かる説明へ補う。
- [x] 既存 description 全件を再監査し、実装・default・choices と矛盾する説明だけを修正する。
  単なる表記統一のための大量変更は行わない。
- [x] 監査で見つかった `mirror3d.center` の負座標を許さない GUI range を、
  実装および他の center / pivot metadata と整合させる。
- [x] `unit` / `recommended_range` / `display_name` / `category` の全面補完は、
  description 完全化とは分離し、今回の変更へ混在させない。

### 3.3 利用者向け導線

- [x] 生成 stub が GUI 対象引数、code-owned 引数、
  `key` / `instance_key` / `shared` の説明をすべて出力するようにする。
- [x] `src/grafix/api/__init__.pyi` を正規 generator から再生成する。
- [x] `python -m grafix describe` の metadata 表示へ `description` を追加する。
- [x] README の custom primitive / effect / preset 例へ具体的な `description` を追加する。
- [x] `src/grafix/resource/examples/custom_operation.py` の公開 meta に説明を追加する。
- [x] `docs/agent_docs/documentation.md` に、
  first-party の GUI 対象 metadata は非空 description 必須、
  code-owned 公開引数は NumPy `Parameters` で説明する、という最小ルールを追記する。

### 3.4 回帰防止

- [x] builtin manifest、registry、公開 operation 集合の一致を検証する。
- [x] 各 built-in の `accepted_args` が、意図的 code-owned 引数を除いて
  `spec.meta` に過不足なく含まれることを検証する。
- [x] GUI 対象引数と `activate` の `ParamMeta.description` が非空であることを検証する。
- [x] code-owned 引数が NumPy `Parameters` に非空説明を持つことを検証する。
- [x] operation 自体の短い description が非空であることを検証する。
- [x] 生成 stub に code-owned 引数と共通 identity 引数の説明が含まれることを検証する。
- [x] describe CLI が引数 description を表示することを検証する。
- [x] ユーザー定義 operation では空の description も引き続き受理する既存契約を維持する。

## 4. 主な変更候補

- `src/grafix/core/primitives/bezier.py`
- `src/grafix/core/primitives/polyline.py`
- `src/grafix/core/effects/drop.py`
- `src/grafix/core/effects/mirror.py`
- `src/grafix/core/effects/mirror3d.py`
- `src/grafix/core/effects/partition.py`
- `src/grafix/core/effects/repeat.py`
- `src/grafix/core/effects/twist.py`
- `src/grafix/core/effects/warp.py`
- `src/grafix/core/primitive_registry.py`
- `src/grafix/core/effect_registry.py`
- `src/grafix/devtools/generate_stub.py`
- `src/grafix/devtools/describe_op.py`
- `src/grafix/api/__init__.pyi`
- `src/grafix/resource/examples/custom_operation.py`
- `README.md`
- `docs/agent_docs/documentation.md`
- `tests/core/parameters/test_description_completeness.py`
- `tests/devtools/test_generate_stub_semantic_meta.py`
- `tests/devtools/test_describe_op.py`
- `tests/stubs/test_api_stub_sync.py`

## 5. 検証

- [x] description completeness の対象限定テストを実行する。
- [x] stub generator / stub sync の対象限定テストを実行する。
- [x] describe CLI の対象限定テストを実行する。
- [x] primitive / effect registry と operation catalog の対象限定テストを実行する。
- [x] `ruff check` を変更対象へ実行する。
- [x] `mypy src/grafix` を実行する。
- [x] `PYTHONPATH=src pytest -q` を実行する。
- [x] `git diff --check` を実行する。

## 6. 完了条件

- [x] built-in primitive 17 件 / effect 32 件の全公開 callable 引数に、
  `ParamMeta.description` または NumPy `Parameters` のいずれかで非空説明がある。
- [x] GUI Help、生成 stub、describe CLI から該当説明を参照できる。
- [x] Style / Layer Style / first-party preset の既存 completeness 契約を維持する。
- [x] 新しい built-in 引数や operation の登録漏れ・説明漏れをテストが検出する。
- [x] 挙動、既定値、GUI 対象範囲、ユーザー定義 operation の互換契約を変えない。

## 7. 実施結果

2026-07-19 に全項目を実装した。

- primitive 17 件の公開引数 134 / 134 件、effect 32 件の公開引数
  176 / 176 件に、`ParamMeta.description` または code-owned 引数用の
  NumPy `Parameters` 説明があることを registry から再監査した。
- GUI metadata は primitive 146 行、effect 208 行の全件で非空 description を維持した。
- `bezier.p0`〜`p3` と `polyline.points` は code-owned のまま個別説明を追加した。
- 生成 stub は非空 `ParamMeta.description` を優先し、description がない
  ユーザー定義 metadata と code-owned 引数では従来どおり callable docstring を使う。
- `key` / `instance_key` / `shared` の共通説明を generator に一元化し、
  operation ごとの IDE Help へ反映した。
- describe CLI、README、同梱 custom operation 例、documentation 規約を同期した。
- effect の単位、sentinel semantics、分割数と結果の対応を補い、
  `mirror3d.center` の GUI range を `-300.0`〜`300.0` へ整合させた。

検証結果:

- description / stub / CLI / primitive focused tests: 26 passed
- registry / catalog focused tests: 23 passed
- effect focused tests: 51 passed
- `ruff check`（変更対象）: success
- `mypy src/grafix`: success（216 source files）
- full pytest: 1691 passed、既存 multiprocessing resource tracker warning 6 件
- `git diff --check`: success

## 8. GUI 表示フィードバックへの追補

実施後、保存済み Parameter Store を使う GUI では、多くの引数が
`No description is available for this parameter.` のままになるという
フィードバックを受けたため、完了条件を再確認する。

- [x] fresh store では built-in primitive / effect の description が
  `ParameterRow` と Help pane まで届くことを確認した。
- [x] Help pane の選択・hover・focus 処理は description を欠落させないことを確認した。
- [x] 保存済みの同一 `kind` の `ParamMeta(description=None)` が、現在の registry
  metadata を `resolve_params` と `merge_frame_params` の両方で遮蔽することを特定した。
- [x] 値解決に使う保存済み metadata と GUI が所有する `ui_min` / `ui_max` は
  保持しつつ、同じ `kind` / `choices` の現在の `description` をフレーム観測時に反映する。
- [x] 保存済み旧 metadata、worker snapshot、stable merge cache、
  実 built-in から GUI Help までを対象にした回帰テストを追加する。
- [x] 対象テスト、ruff、mypy、full pytest、`git diff --check` を再実行する。

追補実施結果:

- 旧保存データの metadata を値解決の source としたまま、同じ `kind` / `choices`
  の現在の `description` だけを合成し、worker / main-process の
  `FrameParamRecord` と ParamStore へ反映するようにした。
- stable merge cache は `kind` / `choices` / `description` の変化を検出し、
  description 更新時だけ table revision を進める。以後の安定フレームでは
  revision を進めない。
- 実 built-in の `G.line` / `E.scale` を使い、description のない旧 payload の
  decode、更新前 GUI model cache、現行 operation の観測、model cache 再構築、
  `ParameterRow`、Help pane までを一続きで検証した。
- GUI が編集した range の保持、worker snapshot での更新、stable frame の
  no-op も回帰テストへ含めた。

検証結果:

- follow-up focused tests: 32 passed
- parameters / Parameter GUI / MP / hot-path focused tests: 524 passed
- `ruff check src/grafix tests`
  （並行作業中の `remaining_effect_benchmark.py` だけ除外）: success
- follow-up 3 source filesの mypy: success
- 10,000 行 steady merge benchmark: p95 5.738 ms、hard contracts passed
- full pytest: 1792 passed、1 skipped、並行作業中の remaining-effect benchmark
  1 件のみ失敗
- 上記並行作業中テストを除く全テスト: 1788 passed、1 skipped
- full mypy: 本追補外で並行編集中の `drop.py` に 1 件のみエラー
- `git diff --check`（追補対象）: success

未完了項目: 本追補の対象内はなし。
