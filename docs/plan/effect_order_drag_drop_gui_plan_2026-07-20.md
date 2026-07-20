# Effect順序ドラッグ＆ドロップGUI実装計画

- 作成日: 2026-07-20
- 状態: 完了
- 対象:
  - `src/grafix/api/effects.py`
  - `src/grafix/core/parameters/`
  - `src/grafix/interactive/parameter_gui/`
  - `src/grafix/interactive/runtime/`
  - 関連テスト

## 1. 目的

Parameter GUI 上で、同一 `EffectBuilder` チェーン内のeffectをドラッグして並べ替え、
表示順だけでなく実際のGeometry DAGの適用順も変更できるようにする。

次を一つの機能として成立させる。

- effect見出しのドラッグによる直感的な並べ替え
- ドロップ前の挿入位置表示
- 実際の描画結果への反映
- コード記述順へのリセット
- Undo/Redo、A/Bスナップショット、named variationへの統合
- 通常保存、recovery、再起動後の復元
- 同期描画とmultiprocessing worker描画の同値性
- Parameter GUIの表示順、連番、Copy Codeとの整合

## 2. 調査済みの現状

- [x] 作業開始時の`git status --porcelain`が空であることを確認した。
- [x] 実際のeffect適用順は
  `src/grafix/api/effects.py::EffectBuilder.__call__()`の
  `enumerate(self.steps)`だけで決まることを確認した。
- [x] 現在の`EffectChainIndex`は、コードから観測した
  `(op, site_id) -> (chain_id, step_index)`とchain ordinalだけを保持する。
- [x] 現在のeffect topology観測は`FrameParamRecord.chain_id/step_index`経由であり、
  GUI metadataを持たないeffectは観測できない。
- [x] GUIのeffect小見出しは
  `table.py::_render_effect_step_heading()`で描画されている。
- [x] GUI表示、step連番、Copy Codeは現在の`step_index`を基準に並べている。
- [x] `ParamSnapshot`と`parameter_context_from_snapshot()`にはparameter値しか含まれず、
  workerは`ParamStore`を参照できない。
- [x] `ParamStoreMemento`はeffect chainをcode-owned構造として明示的に除外している。
- [x] multi-input effectは現行契約でもチェーン先頭でのみ使用できる。
- [x] pyimgui 2.0.0のdrag-and-drop APIとitem矩形、mouse位置、draw listを利用できる。
- [x] ユーザーから実装計画の承認を得た。

GUI行や`EffectChainIndex.step_index`だけを並べ替えても描画結果は変わらない。
正しい適用点は、`EffectBuilder.__call__()`がparameterやselectorを解決し、
`Geometry.create()`でDAGを構築する前である。

## 3. ユーザー操作仕様

### 3.1 ドラッグ操作

- 各effect小見出しの左端にドラッグハンドルを表示する。
- 同じeffect chain内の見出しだけをdrop targetにする。
- target見出しの上半分では「前へ」、下半分では「後ろへ」挿入する。
- drag preview中は、実際に挿入される位置へaccent色の水平線を表示する。
- mouse releaseでdropが確定したときだけstoreを更新する。
- 元と同じ位置へのdropはno-opとし、revisionやUndo履歴を増やさない。
- chain header自体はドラッグ対象にしない。

### 3.2 補助操作

- effect小見出しのcontext menuに`Move Up` / `Move Down`を用意する。
- GUI順が有効なchainには`UI order`を示し、chain単位の
  `Reset to Code Order`を用意する。
- `Reset to Code Order`は順序overrideを削除し、その時点のコード記述順へ戻す。
- drag、Move Up/Down、Resetはいずれも一操作をUndo/Redoの一履歴単位にする。

### 3.3 操作を許可しない状態

- 別chainへのdropは受理しない。
- DAGの別branch、別々にネストした`EffectBuilder`間の移動は許可しない。
- 先頭がmulti-input effectの場合、そのstepは固定し、その前へのdropも許可しない。
- 検索、favorite、active/error等のfilterでchainの一部だけが表示されている間は、
  見えているstepだけから不完全な順序を作らないよう並べ替えを無効にする。
- 同一chain内でstep identityが重複している場合は並べ替えを無効にし、
  tooltipで`key`または`instance_key`による一意化を案内する。
- GUI metadataを持たずParameter GUIに表示されないstepがchain内にある場合は、
  現行の「no-meta custom effectをGUIへ出さない」契約を維持し、
  chain全体の並べ替えを無効にする。

無効状態ではハンドルをdisabled表示し、理由をtooltipで明示する。

## 4. 順序データモデル

### 4.1 code-owned topologyとGUI-owned overrideの分離

effect chainには、性質の異なる二つの状態を持たせる。

1. **code-owned topology**
   - `chain_id`
   - コード記述順のstep列
   - 各stepの`site_id`、operation/selector identity、`n_inputs`
   - コードから毎回観測され、Undo/Redoでは巻き戻さない
2. **GUI-owned order override**
   - `chain_id -> tuple[EffectStepKey, ...]`
   - ユーザーが並べ替えたchainだけに存在する
   - Undo/Redo、A/B、variation、永続化の対象

既存のcode-owned `step_index`を書き換えてoverrideとして流用しない。
「コード順」と「GUIが選んだ順」を別々に保持し、effective orderを純粋関数で解決する。

### 4.2 step identity

- stable identityを`EffectStepKey = (parameter_op, site_id)`として定義する。
- 通常effectでは登録operation名、selectorではtarget名ではなくarity別の
  stable selector operation名を`parameter_op`に使う。
- selectorのtarget名はidentityに含めず、GUIからtargetを変更しても位置を維持する。
- overrideは現在のcode `EffectStepKey`集合に対する完全なpermutationでなければならない。
- 同一chain内の`EffectStepKey`重複は曖昧なので、推測して並べ替えず無効状態にする。
- コード移動後も順序を維持したい利用者にはsemantic `key`の利用を案内する。

### 4.3 effective orderの解決

- overrideが無い場合はコード記述順をそのまま使う。
- overrideが現在の`EffectStepKey`集合と完全一致する場合だけ適用する。
- stepの追加、削除、identity変更、arity変更があった場合は、そのoverrideを無効化して
  コード記述順へ戻す。
- step identityとarityが同じままコード記述順だけが変わった場合は、
  明示的なGUI overrideを維持する。
- GUI操作の結果がコード記述順と一致した場合は、冗長なoverrideを保存せず削除する。
- Reset時はoverrideを削除するため、以後は新しいコード記述順へ追従する。
- effective orderの先頭に`n_inputs > 1`のstepが残ることをcore側でも検証する。

無効な保存データや古いworker snapshotを無理に部分適用しない。
描画時は安全にコード順へfallbackし、main processで次に成功した観測merge時に
stale overrideを削除する。

## 5. 完全なeffect topologyの観測

parameter行からeffect構造を逆算せず、`EffectBuilder`自身がchain全体を観測する。

- `FrameEffectStepRecord`相当のimmutable recordを追加する。
- `FrameEffectChainRecord`相当のrecordに、chain IDと全stepをコード順でまとめる。
- `FrameParamsBuffer`へeffect chain観測用bufferを追加する。
- `EffectBuilder.__call__()`はparameter metadataの有無に関係なく、通常effectとselectorを
  同じ形式で記録する。
- draw失敗時はparameter recordと同様にtopology観測もcommitしない。
- stable frameで同じtopologyを再観測してもstore revisionを増やさない。
- parameterを持たないstepはGUIへ新たに表示しないが、chainの完全性と
  drag可否の判定には含める。

`merge_frame_params()`からeffect topology更新の責務を分離し、
専用merge処理を`parameter_context()`の正常終了時に適用する。

## 6. 実際のEffect適用順への反映

`EffectBuilder.__call__()`では次の順序で処理する。

1. `self.steps`からcode topologyと`EffectStepKey`列を作る。
2. frame開始時に固定されたorder snapshotから当該chainのoverrideを取得する。
3. 共通のpure helperでoverrideを検証し、effective step列を得る。
4. effective step列を`enumerate()`する。
5. effective `step_index`を使って通常parameterまたはselector parameterを解決する。
6. effective順で`Geometry.create()`を積み、Geometry DAGを構築する。
7. code topologyとeffective観測結果をframe bufferへ記録する。

これにより、GUI上の順序、parameter blockの順序、実際のGeometry nestingが一致する。
順序変更後はGeometryの内容IDも自然に変化するため、realize cacheを特別に破棄しない。

`EffectBuilder`から`current_param_store()`を直接参照しない。
frame途中のGUI変更やmain/worker差を避けるため、必ずimmutable snapshotを読む。

## 7. ParamStore操作とrevision

effect順序の変更経路を専用opsへ集約する。

- chainの現在topologyを取得するread API
- code order / effective order / override有無を取得するread API
- source `EffectStepKey`と挿入先から新しいpermutationを作るpure move helper
- 完全なpermutationを検証してoverrideを設定するoperation
- chainのoverrideを削除するReset operation
- stale chainとstale overrideをpruneするoperation

operation側で次を保証する。

- chain ID、およびstep key内のoperation/site IDを文字列へ正規化する。
- source/targetの`EffectStepKey`が同じchainに属することを確認する。
- exact permutation、重複、multi-input先頭制約を検証する。
- no-opでは`False`を返し、store revisionを進めない。
- 実変更ではtable modelとframe snapshotを無効化する。
- 順序変更はparameter値変更ではなくGUI構造変更として扱う。

## 8. frame snapshotとmultiprocessing

### 8.1 同期・headless context

- `ParamSnapshot`自体をGUI固有情報で汚さず、effect order用の
  immutable snapshotを別途定義する。
- `parameter_context()`開始時にparameter snapshotとorder snapshotを同じ
  `store.revision`から固定する。
- effect order用`ContextVar`とread APIを追加する。
- `parameter_context_from_snapshot()`にもorder snapshotを明示的に渡す。
- snapshot未指定時は空mapping、すなわちコード順として扱う。

### 8.2 worker transport

- `MpDraw._DrawTask`と`_SnapshotUpdate`のrevision付きpayloadへorder snapshotを含める。
- parameter snapshotとorder snapshotを同一revisionの一単位としてworkerへ送る。
- worker ACK、task-carried snapshot、control broadcastの既存因果関係を維持する。
- order変更でstore revisionが進んだ場合だけ新しいpayloadを構築・配信する。
- worker側は`parameter_context_from_snapshot()`へ両snapshotを渡す。
- worker resultへeffect topology観測を追加する。
- `SceneRunner._run_mp()`は最新成功frameのrecords/labelsと同じタイミングで
  topology観測もmain側bufferへmergeする。
- worker失敗またはmain側realize失敗時は、topology観測を成功済みとして消費しない。

同期描画、`n_worker=1`、複数workerで同じeffective orderとGeometry DAGになることを
integration testで固定する。

## 9. 永続化、履歴、variation

### 9.1 ParamStore codec

- `PARAM_STORE_SCHEMA_VERSION`を2へ更新する。
- v1およびversion無しpayloadからv2への明示migrationを追加する。
- GUI-owned order overrideを`ui.effect_order_overrides`へ保存する。
- code-owned topologyは既存のeffect step観測形式を整理して保存し、
  GUI-owned overrideとは混在させない。
- decode時は型、重複、空IDを検証し、壊れたentryだけを診断付きで破棄する。
- current topologyが未観測のload直後はoverrideを保持し、最初のコード観測で
  exact permutationを検証する。
- recovery保存でも通常保存でもorder overrideを保持する。
- future schema拒否と原本保護の既存契約を維持する。

### 9.2 Undo/RedoとA/B

- `ParamStoreMemento`へGUI-owned effect order状態を追加する。
- mementoには既知chainごとに、overrideまたは「コード順」を表す状態を記録する。
- capture/matches/restoreでcode-owned topologyを変更せず、互換な現在chainへだけmergeする。
- table描画中はstoreを直接変更せず、drop確定時にreorder commandを一件queueする。
- 現在のparameter用`patch=True` transactionを抜けた後、
  `history.transaction(source=("effect_reorder", chain_id), patch=False)`で
  core operationを一度だけ適用する。
- effect reorderの前後でhistory coalescingを切り、drag/dropの一回のcommitを
  必ず一つのUndo entryにする。
- 順序変更は低頻度操作なのでfull mementoを使用し、parameter hot path向けの
  `ParamStorePatchCapture`やstore observerは拡張しない。
- Undo、Redo、A/B restoreでGeometry適用順も戻ることを検証する。

### 9.3 named variation

- variation mementoへeffect order状態を含める。
- variation codecのencode/decodeへ順序を追加する。
- variation restoreは、現在topologyと互換なchainだけへ順序を適用する。
- variation適用時はeffect順を離散状態として一括復元する。
- 既存`diff_variation()`は`ParameterKey`差分、`morph_variations()`は補間可能な
  parameter値だけを扱う契約のままとし、effect orderのdiff表示や中間補間は行わない。

## 10. Parameter GUI

### 10.1 table model

- `ParameterTableModel`へchain topology、effective step順、drag可否と無効理由を持たせる。
- topologyはfiltered row列ではなく、storeの完全なchain観測から構築する。
- rowはeffective orderで並べ、各step内のparameter順はregistryの`param_order`を維持する。
- order変更で`table_revision`が進み、静的model cacheが一度だけ再構築されるようにする。
- value-only変更の既存incremental refreshは維持する。

### 10.2 drag source / drop target

`table.py::_render_effect_step_heading()`を、単なるtext描画から次を返す小さなUI単位へ変更する。

- drag handleとstep labelの描画
- drag source payloadの生成
- 同一chain targetだけの受理
- mouse位置によるbefore/after判定
- preview中の挿入線描画
- drop確定時のreorder command生成
- disabled理由のtooltip
- Move Up/Down context menu

drag payloadにはchain ID、source operation、source site IDだけを入れ、
並べ替え処理やstore mutationはwidget内で行わない。

### 10.3 store bridge

- `render_parameter_table()`からstore非依存のreorder commandを返せるようにする。
- `render_store_parameter_table()`はcommandを上位へ返し、描画中にはstoreへ適用しない。
- `ParameterGUI`が現在のparameter patch transaction終了後に、専用のfull history
  transactionでcommandをcore order operationへ渡す。
- filtered viewかどうか、全stepが表示されているかをmodel情報から判定する。
- drop確定後にだけstoreへ書き込み、preview中のframeではrevisionを進めない。
- chain headerにoverride状態と`Reset to Code Order`を表示する。

## 11. 表示順、ラベル、Copy Code

effective orderを次の全経路の共通source of truthにする。

- `store_bridge._order_rows_for_display()`
- `labeling.effect_step_ordinals_by_site()`
- effect chain groupingと小見出しの連番
- `snippet.snippet_for_block()`
- chain headerのparameter件数とstep表示

Copy CodeはGUIで選んだeffective orderのメソッドチェーンを生成する。
各stepのparameter、selector target、explicit key処理は既存契約を維持し、
順序だけをeffective orderへ合わせる。

同じoperationが複数回あるchainでは、表示上の`Scale 1`、`Scale 2`等の連番も
effective orderに追従する。

## 12. コード変更とprune

- drawで同じchain topologyを観測した場合は何もしない。
- step集合が変化したchainでは不完全なoverrideを削除し、コード順へ戻す。
- parameter groupのpruneでchain自体が消えた場合はorder overrideも削除する。
- code reload後に古いchain IDだけが残らないよう、既存loaded/observed lifecycleと同期する。
- selector target変更はstep identity変更とみなさず順序を維持する。
- site IDの自動生成位置が変わった場合は別stepとみなし、曖昧な推測移行はしない。
- stableな順序復元が必要な場合は既存の`key` / `instance_key`を使う。

## 13. 主な変更対象

### API / core

- `src/grafix/api/effects.py`
- `src/grafix/core/parameters/effects.py`
- `src/grafix/core/parameters/frame_params.py`
- `src/grafix/core/parameters/merge_ops.py`
- `src/grafix/core/parameters/store.py`
- `src/grafix/core/parameters/snapshot_ops.py`
- `src/grafix/core/parameters/context.py`
- `src/grafix/core/parameters/codec.py`
- `src/grafix/core/parameters/persistence.py`
- `src/grafix/core/parameters/memento.py`
- `src/grafix/core/parameters/variations.py`
- `src/grafix/core/parameters/prune_ops.py`
- `src/grafix/core/parameters/invariants.py`
- 必要に応じて新設するeffect order専用ops/module

### runtime

- `src/grafix/interactive/runtime/mp_draw.py`
- `src/grafix/interactive/runtime/scene_runner.py`

### Parameter GUI

- `src/grafix/interactive/parameter_gui/table.py`
- `src/grafix/interactive/parameter_gui/store_bridge.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/interactive/parameter_gui/table_model.py`
- `src/grafix/interactive/parameter_gui/grouping.py`
- `src/grafix/interactive/parameter_gui/group_blocks.py`
- `src/grafix/interactive/parameter_gui/labeling.py`
- `src/grafix/interactive/parameter_gui/snippet.py`

### tests

- `tests/api/`のEffectBuilder / selector関連テスト
- `tests/core/parameters/test_context.py`
- `tests/core/parameters/test_frame_params.py`
- `tests/core/parameters/test_revision.py`
- `tests/core/parameters/test_persistence.py`
- `tests/core/parameters/test_memento.py`
- `tests/core/parameters/test_history.py`
- `tests/core/parameters/test_variations.py`
- `tests/interactive/runtime/test_mp_draw.py`
- `tests/interactive/parameter_gui/test_parameter_gui_display_order_code_order.py`
- `tests/interactive/parameter_gui/test_parameter_gui_table_rules.py`
- `tests/interactive/parameter_gui/test_parameter_gui_snippet.py`
- effect drag/drop専用の新規GUIテスト

実装中の責務分割により対象ファイルを減らせる場合は、不要なファイルへ変更を広げない。

## 14. テスト計画

### 14.1 core / EffectBuilder

- [x] override無しでは従来と同じGeometry DAG、ID、parameter解決順になる。
- [x] unary effect 3件を並べ替えるとDAGのnestingが指定順になる。
- [x] 同じoperationを複数回含むchainでも`EffectStepKey`単位で正しく動く。
- [x] selector stepを並べ替えてもtargetとparameterが同じstep identityへ残る。
- [x] selector targetを変更してもorder overrideが維持される。
- [x] stale、不完全、重複したoverrideはコード順へfallbackする。
- [x] multi-input先頭stepを動かすorderをcore operationが拒否する。
- [x] 同位置dropと同一order設定はno-opでrevisionを増やさない。
- [x] stable topologyの毎frame観測でrevisionが増えない。

### 14.2 codec / lifecycle

- [x] schema v2のencode/decode round tripでorder overrideを保持する。
- [x] v1とversion無しpayloadは空overrideでv2へmigrationできる。
- [x] malformed order entryだけを捨て、decode issueへ記録する。
- [x] 通常保存、recovery保存、autosaveでorderを保持する。
- [x] step追加、削除、operation/site ID変更、arity変更でstale overrideをリセットする。
- [x] chain pruneでoverrideとcollapse stateの孤児を残さない。

### 14.3 history / snapshot / variation

- [x] drag 1回がUndo 1回、Redo 1回で往復する。
- [x] Reset to Code Orderも一つの履歴単位になる。
- [x] A/B snapshotがparameter値とeffect順序を一緒に復元する。
- [x] named variationの保存、復元、複製、codecへ順序が含まれる。
- [x] variationのparameter diff/morph契約は変えず、orderを補間対象にしない。
- [x] topology変更後のmemento restoreは現在構造を壊さず、互換なchainだけを復元する。

### 14.4 multiprocessing

- [x] order snapshotがtask-carried pathとcontrol broadcast pathの両方でworkerへ届く。
- [x] 同じrevisionのparameter値とorderが分離せず一緒に適用される。
- [x] worker観測のtopologyが最新成功frameだけmain storeへmergeされる。
- [x] error frameまたはrealize失敗frameのtopologyをcommitしない。
- [x] sync、1 worker、複数workerでGeometry DAGと実現結果が一致する。
- [x] stable revisionではorder snapshot payloadを毎frame再構築しない。

### 14.5 GUI / Copy Code

- [x] drag source、同一chain target、before/after判定、drop commitを検証する。
- [x] preview中の挿入線とdrop後の見出し順を検証する。
- [x] cross-chain dropを無視する。
- [x] multi-input先頭stepのhandleと不正dropをdisabledにする。
- [x] filter中、不完全topology、重複`EffectStepKey`でdragをdisabledにする。
- [x] Move Up/DownとResetを検証する。
- [x] effect行、小見出し、同名step連番がeffective orderへ追従する。
- [x] Copy Codeがeffective orderのchainを生成する。
- [x] drag中のparameter値、override、MIDI割当が元stepに残る。
- [x] Retina/通常DPIでhandle、label、挿入線がclipしない。

### 14.6 静的検査と全体回帰

- [x] 対象focused pytestを実行する。
- [x] `ruff check src/grafix tests`を実行する。
- [x] `mypy src/grafix`を実行する。
- [x] `PYTHONPATH=src pytest -q`を実行する。
- [x] `git diff --check`を実行する。

## 15. 実機確認

確認用chainは、順序差が目視できる非可換なeffectを3件以上含むものとする。

- [x] 見出しを上方向・下方向へdragし、挿入線とdrop位置が一致する。
- [x] drop直後のpreviewが新しいeffect順へ変化する。
- [x] parameter値を保持したままstep全体が移動する。
- [x] Undo/Redoで表示順と描画結果が同時に戻る。
- [x] Reset to Code Orderでコード記述順へ戻る。
- [x] 保存、GUI終了、再起動後もGUI順が復元される。
- [x] filter中やmulti-input chainでは誤操作できず、理由をtooltipで理解できる。
- [x] 通常DPIとRetinaでhandle、drop target、挿入線の視認性を確認する。

## 16. 実装チェックリスト

- [x] 完全なeffect chain topology観測recordとmergeを追加する。
- [x] code-owned topologyとGUI-owned order overrideを分離して保持する。
- [x] `EffectStepKey` permutationとmulti-input制約を検証するcore order opsを追加する。
- [x] immutable order snapshotとContextVarを追加する。
- [x] `EffectBuilder.__call__()`のDAG構築前にeffective orderを適用する。
- [x] worker snapshotとresultへorder/topologyを伝播する。
- [x] codec v2 migration、通常保存、recovery、pruneへ統合する。
- [x] memento、full history transaction、A/B、named variationへ統合する。
- [x] Parameter GUIへhandle、drop target、挿入線、補助menu、Resetを追加する。
- [x] filter、cross-chain、multi-input、不完全topology時のdisabled契約を実装する。
- [x] 表示順、step連番、Copy Codeをeffective orderへ統一する。
- [x] live source reloadの成功generation境界でstale chainを自動pruneする。
- [x] core、codec、history、worker、GUIのfocused testを追加する。
- [x] Ruff、mypy、full pytest、`git diff --check`を完了する。
- [x] 実機GUIでdrag、Undo/Redo、保存復元、DPIを確認する。
- [x] 本計画のcheckbox、検証結果、未完了項目を更新する。

## 17. 完了条件

- 同一`EffectBuilder`チェーン内のGUI-visible effectをドラッグで任意順へ変更できる。
- GUI表示順と実際のGeometry DAG適用順が一致する。
- 別chain、hidden stepを含むchain、重複identity、multi-input先頭では
  不正な順序を作れない。
- 順序変更がparameter値、selector target、MIDI割当、site identityを入れ替えない。
- Undo/Redo、A/B、named variation、通常保存、recovery、再起動後復元が機能する。
- 同期描画とmultiprocessing描画が同じ順序を使う。
- コード変更でstale overrideが安全にコード順へ戻る。
- 表示連番とCopy Codeがeffective orderに一致する。
- focused test、Ruff、mypy、full pytest、実機確認が成功する。
- 計画書に完了項目、検証結果、未完了項目が記録される。

## 18. 対象外

- 別々の`EffectBuilder`チェーン間のstep移動
- Geometry DAGのbranchをまたぐ並べ替え
- graph editorやnode editorの新設
- primitiveとeffectの相互移動
- effect引数行だけの個別ドラッグ
- GUI metadataを持たないcustom effectをParameter GUIへ公開する変更
- source codeファイル自体の自動書き換え
- 互換wrapper、shim、新規外部依存の追加

## 19. 実施結果

### 完了した実装

- `EffectBuilder`がparameter metadataに依存せず完全なcode topologyを観測し、
  frame開始時に固定したGUI order snapshotをDAG構築前へ適用するようにした。
- code-owned topologyとGUI-owned overrideを`EffectChainIndex`で分離し、
  exact permutation、重複identity、multi-input先頭制約、stale topologyを検証する
  専用operationを追加した。
- parameter snapshotと同じrevisionでorder snapshotをworkerへ送り、
  最新の成功frameで得たtopologyだけをmain storeへmergeするようにした。
- schema v2 codec、通常/recovery保存、memento、Undo/Redo、A/B、
  named variation、明示的なstale-group pruneへorder状態を統合した。
- arity変更後に古いmemento/variationから順序が復活しないよう、
  code順に依存しないtopology signatureで復元互換性を確認するようにした。
- Parameter GUIへdrag handle、handle laneを含むdrop target、before/after挿入線、
  Move Up/Down、`UI order`表示、Resetを追加した。
- table第1列のclipで挿入線が短く切れないよう、縦clipを維持したまま
  挿入線の横clipだけをwindow content全幅へ拡張するようにした。
- filter中、hidden step、重複identity、cross-chain、multi-input制約では
  不完全または不正な順序を作らないよう操作を無効化した。
- effect行、小見出し連番、Copy Codeを同じeffective orderへ統一した。
- live source reload成功時に一度限りの観測generationを開始し、最初の成功evaluationの
  完全な`FrameEffectChainRecord`集合に存在しない旧chainについて、topology、ordinal、
  order override、collapse状態を同時にpruneするようにした。失敗frameとMP result待ちは
  generationを確定しない。

### 検証結果

- full pytest: `2234 passed, 1 skipped`
- Parameter GUI全体およびeffect-order focused tests: 成功
- 実pyimgui 2.0回帰test:
  DPI scale 1.0 / 2.0の双方で上方向・下方向へ
  `press -> drag開始 -> target hold -> release`を再現し、hold中は未commit、
  挿入線はtable全幅かつclip内、release時だけcommandが1件発生
- 実Grafix Inspector:
  handle/label/`UI order`/Resetの表示、effective順へ並んだ見出し、
  parameter値の保持、通常DPIでのclipなしを目視確認
- 通常保存データへorder overrideを保存し、GUI終了・再起動後の
  Inspectorで同じ順序とparameter値が復元されることを確認
- filter中とmulti-input先頭stepについて、renderer-levelでhandle/payloadの無効化と
  理由tooltipを確認
- multiprocessing:
  1 worker / 2 worker、task-carried / broadcast、error / realize rollbackを確認
- live reload generation focused tests: `107 passed`
  （同期失敗rollback、MP result待ち、chain 0件のfresh成功、collapse pruneを含む）
- `ruff check src/grafix tests`: 成功
- `mypy src/grafix`: 成功（229 source files）
- `git diff --check`: 成功
- 実Grafix GUIの起動と再起動後復元: 成功

### 未完了項目

- なし

### live reload generation契約

- 動的な条件分岐の全topologyを一つのframeから自動判別することはできないため、
  source reload後の最初の成功evaluationを当該generationのcanonical topologyとする。
- その成功frameに現れない条件branch内のchainもprune対象になり、後で再出現した場合は
  新規chainとして扱う。この場合、以前のGUI order overrideは復元しない。
- この契約はsource reload直後の一度だけ適用する。通常frameでは条件分岐により一時的に
  観測されないchainをpruneせず、既存のsession累積観測semanticsを維持する。
