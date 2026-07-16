# Grafix アプリケーションレビュー（2026-07-16）

- 対象: `src/grafix/`
- 観点: ユーザーにとって使いやすく、創造性を高めるアプリケーションになっているか

## 1. 結論

Grafix は、**線を作るエンジン**としては既にかなり強い。`G / E / L / P` の短い合成 API、
immutable な Geometry DAG、Parameter GUI、Undo/Redo、A/B snapshot、last-good frame、atomic
autosave、bounded cache、非同期 capture は、創作中の試行錯誤を支える良い土台である。

一方、**一つの制作アプリケーション**として見ると、次の 3 点が体験の上限を決めている。

1. **出力の安全性と信頼性**
   - G-code は論理キャンバスを mm と解釈し、機種依存コマンドと個別環境らしい原点を既定で出す。
   - 公開 PNG export は同名の既存 SVG を中間ファイルとして上書きし得る。
2. **コードから結果までの反復速度**
   - 最小の primitive が既定キャンバス上でほぼ見えず、重い `draw` は GUI 全体を止め得る。
   - ソース変更の hot reload がなく、「ライブ」なのは主にパラメータ操作までである。
3. **探索・比較・理解のためのアプリ層**
   - 強力な機能が隠しショートカット、console、暗黙の ParamStore に分散している。
   - A/B は安全網としては良いが、名前付き variation、比較、randomize、morph には発展していない。

したがって、次の投資先は effect の追加より先に、**作品を守ること**と
**「試す → 見る → 比べる → 残す」の一周を短くすること**がよい。

## 2. 対象と方法

- 基準 HEAD: `d2445fe612e5`
- 対象: `src/grafix/**/*.py` 169 files
- `py / pyi / yaml` 合計: 45,087 lines
- 現在の working tree にはレビュー開始前から未コミット変更があったため、本書は commit 単体ではなく
  **2026-07-16 時点の working tree**を読んだ結果である。
- 主に確認した領域:
  - 公開 API: `api/`
  - Geometry、parameter、resource management: `core/`
  - preview、Parameter GUI、MIDI、recording: `interactive/`
  - SVG / PNG / G-code: `export/`
  - CLI、stub、benchmark: `devtools/`
  - 既定設定: `resource/default_config.yaml`
- CLI と registry の focused probe では、組み込みは **11 primitives、32 effects、合計 43 operations**、
  defaults は合計 **329 parameters**だった。
- bool parameter について、保存済み `False` とコード側の明示 `True` を同じ key で解決すると、
  現状は保存済み `False` が採用されることを最小 probe で確認した。

本レビューはコードリーディングと focused probe による**ヒューリスティックレビュー**である。
GUI のユーザーテスト、実機プロッタへの送信、長時間の制作セッションは実施していない。
コードの正しさ・性能そのものを扱った既存レビュー
`docs/review/src_grafix_code_review_2026-07-12.md` とは目的を分けている。

### 優先度

- **P0**: 物理機器または既存成果物を危険にさらす。通常利用へ出す前に止めるべき問題。
- **P1**: 中心的な制作フローを止める、またはユーザーの信頼を大きく損なう問題。
- **P2**: 発見性、創造性、再利用性、アクセシビリティを大きく改善する機会。

## 3. 目指すべきユーザーフロー

| 段階 | ユーザーが達成したいこと | Grafix が守るべき性質 |
|---|---|---|
| 始める | 数行で、画面中央に意味のある結果を出す | 既定値だけで成功する |
| 作る | コードとノブを行き来して形を育てる | UI が止まらず、変更がすぐ見える |
| 理解する | 何が結果を支配しているか知る | CODE / UI / MIDI の実効ソースと load/recovery 由来が正しい |
| 探す | 少し違う可能性を安全に試す | Undo、比較、variation、randomize、lock がある |
| 残す | 良い状態と成果物を失わず保存する | no-clobber、明確な保存状態、再現情報がある |
| 出す | SVG、PNG、動画、実機用データを予測どおり作る | preview と出力が一致し、実機前に検証できる |

## 4. 良い点

### 4.1 `G / E / L / P` は作品の意図を短く書ける

- `G` で形を作り、`E` で effect を左から右へ積み、`L` で表示属性を付ける構造は読みやすい。
- Geometry は immutable DAG で、合成と遅延 realize を自然に扱える。
- `@preset` は内部パラメータを隠し、作品固有の再利用単位を作れる。

根拠: `src/grafix/api/primitives.py:16-103`, `src/grafix/api/effects.py:16-212`,
`src/grafix/api/layers.py:16-123`, `src/grafix/api/preset.py:75-253`

### 4.2 GUI 調整をコードへ戻せる

- Parameter GUI は省略引数も観測し、CODE / UI / MIDI の実効ソースを扱う。
- group 単位で実効値の Python snippet を生成できるため、GUI だけの袋小路にならない。
- operation、effect chain、preset に沿う grouping と inactive parameter の制御も良い。

根拠: `src/grafix/interactive/parameter_gui/store_bridge.py:56-220`,
`src/grafix/interactive/parameter_gui/table.py:538-698`,
`src/grafix/interactive/parameter_gui/table.py:1330-1555`,
`src/grafix/interactive/parameter_gui/snippet.py:74-403`

### 4.3 失敗しても創作状態を守る基盤がある

- user `draw` が失敗しても last-good frame を保持する。
- Undo/Redo は bounded/coalesced で、A/B snapshot もある。
- debounced autosave、atomic write、recovery journal、corrupt file quarantine を備える。

根拠: `src/grafix/interactive/runtime/draw_window_system.py:864-965`,
`src/grafix/core/parameters/history.py:25-264`,
`src/grafix/core/parameters/autosave.py:18-114`,
`src/grafix/core/parameters/persistence.py:90-171`

### 4.4 実行状態を正直に見せようとしている

- FPS、CPU、RSS、頂点数、線数、capture queue を monitor できる。
- 非同期描画では要求時刻と表示時刻を分け、古い frame を待つ状態を `WAIT` と表示する。
- Retina scale、日本語 font fallback、画面内への二窓配置、responsive toolbar への配慮がある。

根拠: `src/grafix/interactive/runtime/monitor.py:12-205`,
`src/grafix/interactive/parameter_gui/monitor_bar.py:27-121`,
`src/grafix/interactive/runtime/window_layout.py:161-305`,
`src/grafix/interactive/parameter_gui/gui.py:88-120`,
`src/grafix/interactive/parameter_gui/gui.py:887-944`

### 4.5 interactive capture の内部設計は信頼できる

- bounded FIFO、件数/byte admission、worker death、timeout、cancel を扱う。
- 完成品を no-clobber で version 化し、PNG の中間 SVG を private temp に置く。
- 親 process で commit と manifest 生成を行うため、途中成果物が露出しにくい。

根拠: `src/grafix/interactive/runtime/export_job_system.py`,
`src/grafix/core/output_paths.py:17-74`, `src/grafix/core/capture_manifest.py`

## 5. Findings summary

| ID | 優先度 | 要約 | ユーザーへの主な影響 |
|---|---:|---|---|
| APP-001 | P0 | G-code の単位・機種 profile・安全範囲が暗黙 | 範囲外移動、機種不一致命令、意図しない描線 |
| APP-002 | P0 | PNG export が同名 SVG を中間物として上書き | 既存のベクター成果物を黙って失う |
| APP-003 | P2 | primitive の既定座標と canvas の既定値が噛み合わない | 最小例がほぼ空白に見える |
| APP-004 | P1 | 同期 `draw` が既定で、source hot reload がない | 重い作品で UI が止まり、コード反復に再起動が要る |
| APP-005 | P2 | preview が受動的で、主要 command が隠れかつ focus 依存 | capture、移動、検査機能を発見・実行しにくい |
| APP-006 | P1 | Parameter source と identity に誤解を生む境界がある | コードや MIDI が効かない理由を誤認する |
| APP-007 | P2 | 多数の parameter を探す検索・意味情報が不足 | 大きな作品ほど調整対象へ辿り着けない |
| APP-008 | P1 | error、save、recovery、export の状態が console/log 中心 | 作品が保存されたか、なぜ失敗したか判断しにくい |
| APP-009 | P1 | GUI と headless の render/export 契約と再現情報が分断 | 同じ作品でも入口により出力・上書き・状態が変わる |
| APP-010 | P1 | 一部の品質低下が無通知で、custom op / scene 総量に limit が一律適用されない | 空の結果や clamp の理由が分からず、拡張 op で OOM し得る |
| APP-011 | P2 | catalog、基本形、導入 CLI、拡張 typing が弱い | 何が作れるかを知り、自分の語彙を増やしにくい |
| APP-012 | P2 | A/B が一時的な二枠に留まる | 良い偶然を並べて比較・発展させにくい |
| APP-013 | P2 | workspace、shortcut、操作対象の設計が十分でない | Inspector 単独利用やキーボード操作がしにくい |

## 6. 詳細

### APP-001 [P0] G-code を生成する前提が安全な汎用アプリになっていない

**確認したこと**

- `run()` の既定 canvas は `(800, 800)` で、docstring は「任意単位」としている。
- OpenGL utility は同じ座標を「canvas mm」と説明し、G-code exporter は `canvas_size` を
  明示的に紙サイズ mm として扱う。
- 既定 G-code profile は `origin: [154.019, 14.195]`、`z_down: -1.0` で、
  X/Y bed range は無効である。
- header は `G28`、`M420 S1 Z10` を固定で出し、footer は `z_up + 20` へ移動する。
- `bridge_draw_distance: 0.5` が既定で、preview にはない stroke 間の描線を追加し得る。

根拠: `src/grafix/api/runner.py:387-425`, `src/grafix/interactive/gl/utils.py:10-20`,
`src/grafix/export/gcode.py:42-94`, `src/grafix/export/gcode.py:353-381`,
`src/grafix/export/gcode.py:642-650`, `src/grafix/export/gcode.py:742-867`,
`src/grafix/export/gcode.py:870-889`, `src/grafix/resource/default_config.yaml:46-84`

**問題**

論理 800 単位の作品を 800 mm として出す、異なる firmware に homing/bed-level command を送る、
X/Y/Z の安全範囲外へ動かす、作品にない bridge を描く、という失敗が成立する。
G-code file を生成するだけでも、それを実機へ送るユーザーにとっては release blocker である。

**推奨**

1. `CanvasSpec(unit, logical_size, physical_size)` を一つの公開契約にする。
2. `MachineProfile` 未設定時は G-code action を disabled にする。
3. machine dialect、prologue、footer、origin、X/Y/Z bounds、feed を profile 所有にする。
4. library default から機種依存の movement command と個別 origin を除く。
5. finite、正値、range 順序、出力全座標を preflight で検証する。
6. bridge は既定 off にし、draw/travel/bridge、紙範囲、推定時間を preview して明示 opt-in にする。

### APP-002 [P0] 公開 PNG export が既存の同名 SVG を上書きする

**確認したこと**

`export_image(..., "art.png")` は `art.svg` を中間物として生成してから rasterize する。
SVG 保存は atomic replace なので、既存 `art.svg` があれば置換される。中間 SVG も残る。
interactive async export は既に `TemporaryDirectory/intermediate.svg` を使っており、この問題を避けている。

根拠: `src/grafix/export/image.py:35-55`, `src/grafix/export/svg.py:105-130`,
`src/grafix/core/atomic_write.py:46-58`,
`src/grafix/interactive/runtime/export_job_system.py:379-410`

**問題**

PNG を作る操作が、別形式の既存作品を通知なく破壊する。これはデータ保全上 P0 と判断する。

**推奨**

- 公開/headless path も private temporary SVG を使う。
- PNG 成功時に残す public artifact は PNG と明示された sidecar だけにする。
- 「既存 `art.svg` が byte-for-byte 不変」を regression test にする。
- GUI/CLI/API で同じ no-clobber policy を使い、上書きは明示 opt-in にする。

### APP-003 [P2] 最小のコードが意味のある最初の画面を作らない

**確認したこと**

- `run()` の既定 canvas は 800 x 800。
- `G.polygon()` の既定は `center=(0, 0, 0)`, `scale=1`、実半径 0.5。
- 投影範囲は 0..width / 0..height なので、図形は原点で半分ずつ clip され、canvas の約 1/800
  しか占めない。
- `draw` が受け取るのは `t` だけで、canvas center や short side を知る標準経路がない。
- `center` の GUI range は 0..300 で、既定 800 canvas とも一致しない。

根拠: `src/grafix/api/runner.py:387-425`, `src/grafix/interactive/gl/utils.py:10-20`,
`src/grafix/core/primitives/polygon.py:17-34`, `src/grafix/core/primitives/polygon.py:102-115`

**問題**

初心者は「コードが動いていない」「線が出ない」と判断しやすい。既存ユーザーも毎作品で中心と scale を
手作業で再定義する。これは time-to-first-art を不必要に長くする。

**推奨**

- `draw(ctx)` を導入し、`ctx.t`, `ctx.canvas.center`, `ctx.canvas.short_side` を公開する。
- 論理 canvas、物理 canvas、preview pixel size を分離する。
- primitive の既定配置と推奨 UI range を canvas-relative にする。
- 初期表示に `Fit to content` を用意し、公式最小例は画面の 30〜70% を占めるよう検証する。

### APP-004 [P1] 重い表現ほど UI が止まり、コード変更の反復も途切れる

**確認したこと**

- `run(..., n_worker=1)` が既定で、`>=2` のときだけ multiprocessing 非同期評価になる。
- 同期時の `draw` は preview と Inspector と同じ event loop 上で評価される。
- `reaction_diffusion.steps` は最大 10,000 など、GUI から重い値へ到達できる effect がある。
- `SceneRunner` は起動時の callable を保持し、source watcher / transactional reload がない。
- CLI に `run sketch.py --watch` がない。

根拠: `src/grafix/api/runner.py:387-445`,
`src/grafix/interactive/runtime/scene_runner.py:24-40`,
`src/grafix/interactive/runtime/scene_runner.py:118-214`,
`src/grafix/interactive/runtime/window_loop.py:75-92`,
`src/grafix/core/effects/reaction_diffusion.py:29-42`, `src/grafix/__main__.py:21-89`

**問題**

表現の限界を探して値を上げるほど Inspector まで無反応になり、last-good frame や停止操作という
安全機構へ到達できない。コード修正には process restart が必要で、創作の注意がアプリ操作へ移る。

**推奨**

- UI から隔離した single latest-wins evaluator を既定にする。同期は明示 opt-in にする。
- cancel / timeout / worker restart と、preview 用 draft quality を設ける。
- `grafix run sketch.py --watch` を追加し、`new registry + callable` を検証後に atomic swap する。
- reload 失敗時は last-good code/frame と ParamStore を保持し、file/line を Inspector に表示する。

### APP-005 [P2] preview が「見る窓」に留まり、command が隠れている

**確認したこと**

- preview は aspect-fit viewport だが、pan、zoom、fit、1:1、cursor 座標、safe area 表示がない。
- S/P/G/Shift-G/V、space、Home、矢印、bracket などの主要操作は draw window の hard-coded key handler にある。
- 起動最後には Inspector が activate されるが、Inspector に capture shortcut はない。
- export の成功、失敗、保存先は主に `print` / log へ出る。
- どちらの window を閉じても `pyglet.app.exit()` になる。

根拠: `src/grafix/interactive/gl/draw_renderer.py:27-108`,
`src/grafix/interactive/runtime/draw_window_system.py:225-315`,
`src/grafix/interactive/runtime/draw_window_system.py:511-622`,
`src/grafix/interactive/parameter_gui/gui.py:431-548`,
`src/grafix/interactive/parameter_gui/gui.py:649-774`,
`src/grafix/interactive/runtime/window_loop.py:55-70`, `src/grafix/api/runner.py:608-614`

**問題**

通常は Inspector が最後に activate され、そこに focus がある間は S/P/V が効かない。
存在する機能も見つけにくい。キャンバス外、線の密度、
G-code travel などを視覚的に検査できないため、preview が制作判断の道具になり切っていない。

**推奨**

- 一つの `CommandRegistry` を preview / Inspector / menu / shortcut で共有する。
- canvas toolbar または command palette に Capture、Record、Fit、1:1、Inspector toggle、Help を置く。
- pan/zoom、座標、bounds、safe margin、stroke/travel overlay を追加する。
- queued → exporting → saved/failed を toast/history にし、path copy、Finder 表示、retry、cancel を付ける。
- Inspector close は hide、preview close または明示 Quit だけを全終了にする。

### APP-006 [P1] Parameter source 表示が実際の所有者と一致しない場合がある

**確認したこと**

1. 起動時に MIDI controller を確立できない場合も、保存済み CC snapshot を `current_cc_snapshot` として
   渡し、resolver は source を通常の `"cc"` とする。table は `last_source == "cc"` だけで `LIVE` を表示する。
   接続中の device が mid-session で切れた場合に frozen state へ遷移する処理も、poll 経路には見当たらない。
2. bool は `override` と code base に関係なく、常に保存済み `ui_value` / source `"gui"` を使う。
3. 自動 `site_id` は file、`co_firstlineno`、bytecode instruction offset から作られ、コード編集で変化し得る。
   ただし op、引数、型、label の fingerprint が一意なら、既存 reconcile が状態を自動移行する。
4. 同じ呼び出し命令を loop / comprehension で反復すると既定では同じ `site_id` を共有し、個別調整には
   `key=i` などを毎回指定する必要がある。

根拠: `src/grafix/interactive/midi/factory.py:82-114`,
`src/grafix/interactive/midi/midi_controller.py:121-138`,
`src/grafix/interactive/midi/midi_controller.py:228-249`,
`src/grafix/core/parameters/resolver.py:47-129`,
`src/grafix/api/primitives.py:66-85`,
`src/grafix/interactive/parameter_gui/table.py:949-1083`,
`src/grafix/core/parameters/key.py:23-67`, `src/grafix/core/parameters/reconcile.py:16-148`,
`src/grafix/core/parameters/reconcile_ops.py:16-114`

**問題**

- 起動時に MIDI へ接続できず保存 snapshot を使っているのに `LIVE` と見える。
- コードで bool を変更しても過去の UI 値が勝ち、コードが効かないように見える。
- コード編集による identity 変更は多くの場合自動再リンクされるが、同型 group が複数ある曖昧ケースでは
  安全のため対応付けられず orphan になり得る。
- 花弁や粒子のような反復構造で、「全要素が共有する値」と「各要素を個別調整する値」を自然に分けにくい。

**推奨**

- `ValueSource(code | ui | midi_live | midi_frozen)` と
  `LoadProvenance(primary | session_recovery)` を別軸で持つ。
- 「MIDI disconnected — saved CC snapshot を使用中」を常設し、Reconnect / Clear を用意する。
- bool は clean launch では明示 code 値を優先し、現 session と recovery 復元時は UI 操作を保持する。
  併せて Reset to CODE と code/UI 差分表示を用意する。
- stable semantic ID と migration UI を用意し、orphan を検出して新しい parameter へ再割り当てできるようにする。
- `parameter_scope`, `instance_key`, `shared` などで group identity と instance identity を分け、
  反復構造には array/group control を用意する。
- `key=` は例外的な回避策ではなく、重要 parameter へ付ける設計として生成 snippet と docs から案内する。

### APP-007 [P2] Parameter GUI に検索と「意味」が足りない

**確認したこと**

- catalog 全体では 43 operations、329 defaults がある。GUI に出るのは現在の scene で観測されたものだけだが、
  scene が大きくなるほどその数も増える。
- table は grouping と折り畳みを持つが、toolbar の絞り込みは主に `Show inactive` だけである。
- `ParamMeta` は kind、UI range、choices が中心で、説明、単位、step、precision、log scale、
  recommended range、advanced level を持たない。
- MIDI range 編集の R/E/T shortcut は画面上に mode/対象範囲を示さず、同じ CC の複数 parameter を更新する。

根拠: `src/grafix/interactive/parameter_gui/gui.py:398-412`,
`src/grafix/interactive/parameter_gui/gui.py:649-717`,
`src/grafix/interactive/parameter_gui/gui.py:719-885`,
`src/grafix/core/parameters/meta.py:11-21`,
`src/grafix/core/parameters/meta_spec.py:23-92`

**問題**

規模が増えるほど「どこにあるか」「何の単位か」「安全な範囲か」を覚える必要がある。
見つけた値を動かせても、意図を理解して選ぶための情報が足りない。

**推奨**

- label / operation / argument / source / MIDI CC を対象にした fuzzy search を追加する。
- filter chip: active、UI override、MIDI mapped、error、inactive、favorite。
- metadata に `display_name`, `description`, `unit`, `step`, `format`, `scale`, `category`,
  `advanced`, `recommended_range` を追加する。
- pin/favorite、Expand/Collapse all、hidden 件数、選択 parameter の Help pane を用意する。
- range edit は明示 mode にし、対象一覧、変更予定 range、Esc cancel を表示する。

### APP-008 [P1] 内部の回復力に対して、ユーザー向け診断が弱い

**確認したこと**

- frame error は last-good frame を守る一方、GUI には最大 180 文字程度の一行 summary だけを出す。
- full traceback、export 成否、autosave failure、recovery 採用は主に logger / console にある。
- 通常保存は explicit parameter の override を落とす一方、session recovery は保持するが、
  この ownership の違いは GUI から分からない。
- ParamStore decoder は壊れた entry を捨てて store 全体を成功扱いし、payload に schema version がない。
- runtime config は unknown key を余りとして報告せず、G-code を含む一部 float で finite/range 検証が弱い。
- config 内の相対 path は config file 基準へ resolve されず、起動 CWD により参照先が変わり得る。

根拠: `src/grafix/interactive/runtime/draw_window_system.py:864-906`,
`src/grafix/interactive/parameter_gui/monitor_bar.py:113-121`,
`src/grafix/interactive/runtime/parameter_gui_system.py:59-69`,
`src/grafix/core/parameters/codec.py:18-22`, `src/grafix/core/parameters/codec.py:37-127`,
`src/grafix/core/parameters/persistence.py:37-128`,
`src/grafix/core/runtime_config.py:195-203`, `src/grafix/core/runtime_config.py:316-324`,
`src/grafix/core/runtime_config.py:450-463`, `src/grafix/core/output_paths.py:301-307`

**問題**

「表示は戻ったが、どこを直すか」「本当に保存されたか」「何を recovery したか」が分からない。
部分的に壊れた store や config typo は黙って値を失う、または既定へ戻る可能性がある。

**推奨**

- `DiagnosticEvent(category, severity, summary, details, source, action)` を共通化する。
- Inspector に Saved / Saving / Save failed / Recovered session を常設する。
- error drawer に file:line、full traceback、Copy、Open in editor、同一 error 回数を出す。
- ParamStore に schema version と migration を導入し、lossy repair 前に backup と確認を行う。
- config を strict schema で検証し、unknown key の近似候補と `grafix config validate/show` を提供する。
- 相対 path の基準を config または project root に統一し、`config show` には source と resolved path を出す。

### APP-009 [P1] render/export が入口ごとに別製品になっている

**確認したこと**

- `Export` は root `grafix` から公開されず、constructor 実行時に保存する command-like API である。
- interactive は versioned no-clobber、manifest、bounded async job を持つが、CLI は PNG 中心で固定名を使う。
- headless export は ParamStore を暗黙に読み、使用しない選択、明示 store path、`config_path` がない。
- `fmt` と path extension が別々に指定でき、不一致を一つの入口で検証しない。
- `run` は線幅を world unit と説明するが、実装は canvas 短辺に対する比率として換算する。さらに
  `run` の既定は `0.001`、`Export` は `0.01` である。
- Python の Layer color は RGB 0..1、GUI/ParamStore は RGB 0..255 で、内部変換はあるが、
  ユーザー向けの単一 `Color` 契約はない。
- capture manifest は時刻、canvas、形式、artifact path が中心で、code/config/parameter/seed の実効状態を持たない。
- recording 中に scene error が出ても last-good frame を書き、clock を進める。manifest は重複/error を記録しない。

根拠: `src/grafix/__init__.py:7-33`, `src/grafix/api/export.py:25-110`,
`src/grafix/api/runner.py:387-425`, `src/grafix/core/parameters/style.py:21-30`,
`src/grafix/core/parameters/layer_style.py:15-18`,
`src/grafix/devtools/export_frame.py:21-168`,
`src/grafix/core/capture_manifest.py:17-60`,
`src/grafix/interactive/runtime/draw_window_system.py:933-946`,
`src/grafix/interactive/runtime/draw_window_system.py:1023-1063`,
`src/grafix/interactive/runtime/recording_system.py:94-109`

**問題**

GUI では安全な保存が CLI では上書きになり、同じコードでも hidden ParamStore により結果が変わる。
動画は一部が last-good の静止画でも成功に見える。sidecar だけから作品を再現できない。

**推奨**

- GUI/API/CLI が共有する長寿命 `RenderSession` と `CaptureService` を作る。
- preview/export が共有する `RenderOptions` を作り、stroke width を physical unit または明示的な
  canvas-relative ratio として定義する。
- `Color` の一つの入口で hex、named color、RGB8、RGB01 を正規化する。
- `render(...) -> Frame` と `export(frame, path, ...) -> ExportResult` を第一級 API にする。
- format は拡張子から決め、明示 format と不一致なら拒否する。
- `parameter_source="code" | "saved" | "recovery" | Path` を必須または明示既定にする。
- manifest v2 に code/git/Grafix version、effective parameters/config/seed、実出力寸法、frame count、
  dropped/duplicated/error count を記録する。
- recording error policy を pause/abort のいずれかとして明示し、黙った重複 frame を成功扱いしない。

### APP-010 [P1] 一部の品質低下が伝わらず、limit も全経路を一律には守らない

**確認したこと**

- 明示的な `ResourceLimitError` は last-good frame と一行の frame error summary で通知される。
- ただし `ResourceBudget` は一 operation 向けの協調的な仕組みで、evaluator output を一律に検査しない。
- custom primitive/effect は user function 内で巨大配列を確保してから `RealizedGeometry` へ変換できる。
- scene 全体の aggregate limit と、CPU/GPU/cache/export queue を束ねる公開 limit がない。
- `subdivide` は divisions や出力数を内部上限へ黙って下げる。
- grid 系 effect は範囲超過時に `None`、空 geometry、元 geometry へ degrade する経路がある。
- monitor は総量を表示するが、どの layer/effect が遅いかは示さない。

根拠: `src/grafix/interactive/runtime/draw_window_system.py:864-906`,
`src/grafix/interactive/parameter_gui/monitor_bar.py:113-121`,
`src/grafix/core/resource_budget.py:22-133`, `src/grafix/core/realize.py:290-317`,
`src/grafix/core/primitive_registry.py:72-105`, `src/grafix/core/effect_registry.py:85-139`,
`src/grafix/core/effects/subdivide.py:12-86`, `src/grafix/core/effects/util.py:86-177`,
`src/grafix/core/effects/reaction_diffusion.py:245-277`,
`src/grafix/core/effects/metaball.py:361-407`,
`src/grafix/interactive/runtime/perf.py:46-130`

**問題**

明示的な budget error は分かるが、silent clamp / reject / no-op によって結果が空、粗い、短い場合は
「表現の結果」と誤認する。custom op や scene 総量では、限界を探る創作行為が freeze や OOM と
隣り合わせになる。global FPS だけでは、何を簡略化すべきか分からない。

**推奨**

- `OperationDiagnostic` で clamped / coarsened / skipped と元値・実効値を表示する。
- `RuntimeLimits` に per-op、scene aggregate、CPU/GPU cache、capture queue をまとめる。
- custom op に estimate と postflight guard を用意し、協調的予算であることを明文化する。
- preview は draft/final quality と adaptive LOD を持ち、export だけ高予算にする。
- profiler overlay に slowest operations/layers、cache hit/eviction、worker lag を出す。

### APP-011 [P2] 造形語彙と discovery がコードの中に埋もれている

**確認したこと**

- 組み込み primitive は 11 種あるが、circle、ellipse、rect、arc、bezier、from-points など、
  初学者が最初に探す名前が第一級 API にない。
- 独自の線を作るには `(coords, offsets)` の NumPy 契約まで降りる。
- CLI `list` は名前だけで、category、説明、入力数、例、preview がない。
- CLI に `new/init`, `run`, `doctor`, `describe`, `examples` がない。
- stub generator は installed package の `grafix/api/__init__.pyi` を書き換え、user primitive/effect を
  built-in module と同様には扱わない。
- `L.layer()` は単数名でも常に `list[Layer]` を返す。G/E の未知 kwargs は DAG 構築時に検証されず、
  一部の形状選択は意味名ではなく `type_index` である。
- custom op の Geometry/cache identity は op、inputs、args、registry revision が中心で、`OpSpec` に
  cache policy がない。custom op 内で暗黙の乱数、時刻、global state を使うと、結果が cache に固定され得る。

根拠: `src/grafix/core/builtins.py:11-64`, `src/grafix/core/realized_geometry.py:12-21`,
`src/grafix/devtools/list_builtins.py:17-68`, `src/grafix/__main__.py:21-89`,
`src/grafix/devtools/generate_stub.py:317-336`,
`src/grafix/devtools/generate_stub.py:658-796`,
`src/grafix/api/layers.py:35-117`, `src/grafix/api/_param_resolution.py:44-75`,
`src/grafix/core/primitives/polyhedron.py:18-50`,
`src/grafix/core/geometry.py:184-230`, `src/grafix/core/realize.py:170-174`,
`src/grafix/core/realize.py:213-264`, `src/grafix/core/op_registry.py:18-28`

**推奨**

- `G.catalog()` / `E.describe()` と GUI の検索・preview・code insert を同じ catalog から作る。
- `circle`, `ellipse`, `rect`, `arc`, `polyline`, `bezier`, `from_polylines` を基本語彙にする。
- 高水準 `PolylineSet.from_lines(...)` と低水準 NumPy API を分ける。
- `grafix init`, `grafix run --watch`, `grafix doctor`, `grafix describe` を用意する。
- user op の source/provenance を registry に持ち、project-local typings を生成する。
- parameter metadata は signature/`Annotated` など一つの定義元から導出し、重複記述を減らす。
- `L.layer() -> Layer` とし、未知 kwargs、型、choice は DAG 構築時に候補付きで検証する。
  choice は意味名と `Literal[...]` で補完できるようにする。
- custom op は pure/deterministic を既定契約にし、乱数は explicit seed を要求する。必要な場合だけ
  `cache_policy="content" | "frame" | "none"` のような小さな opt-out を提供する。

### APP-012 [P2] A/B を「戻れる機能」から「発見する機能」へ伸ばせる

**確認したこと**

- Undo/Redo と A/B snapshot は良いが、A/B は process 内の一つの辞書にある最大 2 slot に留まる。
- slot の名前、保存時刻、thumbnail、差分数、note、永続化、空状態の明示がない。

根拠: `src/grafix/core/parameters/history.py:21-23`,
`src/grafix/core/parameters/history.py:222-264`,
`src/grafix/interactive/parameter_gui/gui.py:490-521`

**推奨**

- 永続的な named variation を、名前、note、timestamp、seed、thumbnail と共に保存する。
- current との差分 parameter を一覧し、個別/一括で適用できるようにする。
- 選択 parameter の recommended range 内 randomize、lock、favorite を追加する。
- A↔B morph、variation の複製、contact sheet/batch export を用意する。

この領域は Grafix の「創造性を高める」という目的に最も直接効く。ただし、先に APP-001〜010 の
信頼性と反復速度を整えた方が、偶然の良い結果を安心して使える。

### APP-013 [P2] workspace と accessibility をアプリの機能として扱う余地がある

**確認したこと**

- 二窓の初期配置、DPI、font fallback、contrast は配慮されている。
- 一方、どちらの window を閉じても終了し、Inspector だけを隠す状態がない。
- shortcut は二つの window に hard-code され、一覧、remap、command 検索がない。
- 小さい source action、hover tooltip 依存、可視 label と widget ID の分離がある。
- timeline は play/pause/seek/step/speed までで、loop in/out や bookmark はない。

根拠: `src/grafix/interactive/runtime/window_loop.py:55-70`,
`src/grafix/interactive/parameter_gui/table.py:26-47`,
`src/grafix/interactive/parameter_gui/widgets.py:98-200`,
`src/grafix/interactive/parameter_gui/theme.py:68-156`,
`src/grafix/interactive/runtime/frame_clock.py:88-200`

**推奨**

- Inspector の show/hide、window 位置・size、選択 tab を workspace state として保存する。
- command registry から Help、menu、shortcut、remap を生成する。
- Tab focus、Enter/Esc、focus 時 tooltip、Large UI mode を設け、E2E keyboard test を持つ。
- animation 制作には loop in/out、time bookmark、variation と時刻の関連付けを追加する。

## 7. 推奨ロードマップ

### Phase 0: 成果物と実機を守る

1. APP-002 の PNG sibling SVG 上書きを private temp 化し、regression test を追加する。
2. G-code action を valid `CanvasSpec + MachineProfile` が揃うまで無効化する。
3. G-code の機種依存 header/footer、個別 origin、bridge default を安全側へ変更する。
4. recording の scene error policy を pause/abort として明示する。

### Phase 1: 制作ループを切らない

1. canvas-aware な最小例と `Fit to content` を整える。
2. background latest-wins evaluator、cancel、slow-frame 診断を既定にする。
3. transactional source reload と `grafix run --watch` を追加する。
4. command registry、canvas toolbar、notifications/error drawer を作る。
5. MIDI live/frozen、bool source、save/recovery status を正しく表示する。
6. GUI/API/CLI の `RenderSession / CaptureService / ExportResult` を共通化する。

### Phase 2: 探索を増幅する

1. parameter search、filter、semantic metadata、favorite を追加する。
2. named variation、thumbnail、diff、randomize/lock、A/B morph を追加する。
3. operation catalog、基本 primitive、high-level polyline API を整える。
4. draft/final quality と actionable profiler を追加する。

### Phase 3: 長く使える workspace にする

1. window/workspace persistence、Inspector 単独 hide、command remap を追加する。
2. Large UI、keyboard navigation、focus help を検証する。
3. project-local typings、custom op provenance、strict config migration を整える。

## 8. 追加する概念は少数に留める

既存 architecture は十分整理されているため、大きな plugin framework や汎用 state manager は不要である。
次の小さな概念に責務を集約するのがよい。

| 概念 | 一つだけ持たせる責務 |
|---|---|
| `CanvasSpec` | logical / physical / preview pixel の座標契約 |
| `MachineProfile` | G-code dialect、origin、bounds、feed、pen movement |
| `RenderSession` | callable、ParamStore、config、cache、frame evaluation の寿命 |
| `CaptureService` | format、no-clobber、job、manifest、結果通知 |
| `CommandRegistry` | action、shortcut、enabled state、help text |
| `DiagnosticEvent` | scene/export/save/config の user-facing feedback |
| `Variation` | 名前付き parameter snapshot、seed、note、thumbnail |

これは互換 wrapper を増やす提案ではなく、現在 GUI/API/CLI に重複している判断を一箇所へ寄せる提案である。

## 9. 完了条件として使えるシナリオ

1. 新規ユーザーが公式最小例を起動すると、追加調整なしで中央に十分大きな形が見える。
2. 1 frame が数秒かかっても Inspector、Cancel、Quit は応答し続ける。
3. source に syntax error を入れても last-good frame を維持し、file/line を示し、修正後に再起動なしで戻る。
4. 起動時に MIDI へ接続できない場合は `LIVE` を出さず、保存済み snapshot 使用中であることが分かる。
5. `art.png` を出力しても既存 `art.svg` は一 byte も変わらない。
6. machine profile がない状態では G-code を作れず、profile 設定後は bounds/travel/bridge を事前確認できる。
7. recording 中の scene error は pause/abort され、成功動画として黙って重複 frame を残さない。
8. variation を保存して再起動し、同じ code/config/seed と parameter 値で再現できる。
9. 100 個を超える parameter があっても、名前・operation・source・MIDI で目的の値へ数秒で辿り着ける。

## 10. 最終評価

Grafix は、内部基盤の堅牢さに比べて、ユーザーがそれを**見つけ、理解し、信頼するための表面**が薄い。
これは全面再設計が必要という意味ではない。むしろ既にある last-good frame、ParamStore、capture job、
monitor、registry を、少数の application-level contract でつなげればよい。

最も価値の高い順序は、**安全な出力 → 止まらない反復 → 状態の可視化 → variation による探索**である。
この順に整えると Grafix は「コードで線を作れる toolkit」から、
**安心して偶然を探し、良い結果を育てて残せる制作環境**へ進める。
