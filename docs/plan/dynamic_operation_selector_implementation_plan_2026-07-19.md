<!--
どこで: `docs/plan/dynamic_operation_selector_implementation_plan_2026-07-19.md`。
何を: 登録済み primitive / effect を Parameter GUI から切り替える selector API の実装手順を定義する。
なぜ: 実 evaluator を入れ子呼び出しせず、対象 operation 本来の検証・cache・profiling 契約を保ったまま動的選択を提供するため。
-->

# Primitive / effect selector 実装計画

- 作成日: 2026-07-19
- 計画時 HEAD: `2186422`
- 状態: **実装完了**
- 対象:
  - `G.select(...)`
  - `E.select(...)`
  - selector 用 Parameter GUI metadata・永続化・表示制御
  - stub / README / tests

## 1. 目的

登録済み operation をコード変更なしで Parameter GUI から切り替えられる、次の公開 API
を追加する。

```python
geometry = G.select(target="circle")

effect = E.select(target="rotate", n_inputs=1)
geometry = effect(geometry)
```

選択後の DAG は selector operation ではなく、実際に選ばれた operation を持つ。

```python
assert G.select(target="circle").op == "circle"
assert E.select(target="rotate")(G.line()).op == "rotate"
```

これにより、対象 operation が元から持つ次の契約をそのまま利用する。

- `OpSpec` による kwargs / choice / arity 検証
- `cache_policy="content" | "none"`
- registry revision を含む cache key
- operation 単位の profiler・diagnostic・resource budget
- lazy built-in 登録と custom operation

## 2. 今回の公開契約

### 2.1 Primitive

```python
G.select(
    target="circle",
    params_by_target={
        "circle": {"radius": 30.0},
        "rect": {"width": 60.0, "height": 40.0},
    },
    key="main-shape",
)
```

- `target` は Parameter GUI の choice とし、全ての公開済み registered primitive を候補にする。
- built-in と、selector 呼び出し前に登録済みの custom primitive を対象にする。
- `_` で始まる内部 operation と selector 自身は候補から除く。
- 選択先の `meta` を持つ引数は、その primitive 固有の widget として表示する。
- 選択先を切り替えても、primitive ごとの UI 値・override・MIDI 割当を保持する。
- `params_by_target` は code 側の target 別 base kwargs とする。
  未指定 target は対象 operation 本来の default を使う。
- GUI 非公開の引数や required 引数を持つ custom primitive は、
  `params_by_target` から値を渡せるようにする。
- `G(name)(...)`、`key`、`instance_key`、`shared` の既存 identity / label 契約を維持する。

### 2.2 Effect

```python
unary = E.select(
    target="rotate",
    n_inputs=1,
    params_by_target={"rotate": {"rotation": (0.0, 0.0, 30.0)}},
)
out = unary(source)

binary = E.select(
    target="boolean",
    n_inputs=2,
    params_by_target={"boolean": {"mode": "difference"}},
)
out = binary(source, mask)
```

- `n_inputs` は code-owned の固定値とし、Parameter GUI には出さない。
- target choice は同じ `n_inputs` の registered effect だけに絞る。
- 既定は `n_inputs=1` とする。
- binary 以上の selector は既存 EffectBuilder と同様、chain の先頭だけで許可する。
- target 切替後も `n_inputs` は変えない。異なる arity へ切り替える場合は
  別の `E.select(..., n_inputs=...)` 呼び出しにする。
- selector の後ろには通常の effect をチェーンできる。

```python
out = E.select(target="fill").rotate()(source)
```

## 3. Selector の内部モデル

### 3.1 DAG 構築時に実 operation へ lower する

selector evaluator から `primitive_registry[target].evaluator(...)` や
`effect_registry[target].evaluator(...)` を直接呼ばない。

API の parameter 解決段階で target を決め、選択先 spec の引数へ戻してから
`Geometry.create(op=target, ...)` を呼ぶ。

これにより、外側 selector の cache policy だけが適用される問題、profiler に target が
現れない問題、realize cache hit 時に parameter 観測が欠落する問題を作らない。

### 3.2 GUI 用の private selector spec

Parameter GUI の既存 grouping、引数順、`ui_visible`、未知引数 pruning を再利用するため、
selector の GUI 契約だけを表す private `OpSpec` を既存 registry に置く。

- primitive: private selector spec を 1 個
- effect: `n_inputs` ごとに private selector spec を 1 個
- private 名は `_` で始め、`G.catalog()` / `E.catalog()` / generated operation list へ出さない
- evaluator は DAG に現れないことを不変条件とし、誤って realize された場合は明確に失敗する
- public catalog の構成または metadata が変わったときだけ selector spec を再構築する
- 同一 catalog の steady frame では registry revision を進めない

### 3.3 target 別 parameter identity

selector の一つの `(op, site_id)` group 内で、target 固有引数を内部的に namespace 化する。

概念例:

```text
target
circle::<radius>
circle::<segments>
rect::<width>
rect::<height>
```

- 実際の内部 key は operation 名と arg 名の衝突が起きない可逆 encoding にする。
- GUI では namespace を表示せず、元 spec の `display_name` または arg 名だけを表示する。
- `ui_visible` は現在の `target` と一致する引数だけを表示する。
- 選択されていない target の state は削除せず非表示にする。
- target を戻したとき、以前の UI 値・override・MIDI 割当を復元する。
- 選択先 operation 自身の `ui_visible` も合成し、target 内の条件表示を維持する。

## 4. 動的 catalog と metadata 更新

- selector 呼び出し前に built-in catalog を明示的に初期化する。
- custom operation 登録、overwrite、source hot reload 後は候補と target metadata を更新する。
- `ParamMeta(kind="choice")` の候補は selector spec の現在世代を正とする。
- 保存済み target が現在の catalog から消えた場合は、黙って別 operation に変更せず、
  target 名と利用可能候補を含む明確なエラーにする。
- target の choices 追加時は既存 UI state を維持したまま dropdown へ追加候補を反映する。
- target parameter の kind / choices が更新された場合は、既存 Parameter Store の
  code-owned metadata 更新規則に従って安全に反映する。
- source reload の staging registry と live registry を混線させず、commit 後の registry
  世代だけを GUI と DAG の source of truth にする。

## 5. 引数検証

- `target` が未登録、private、arity 不一致なら DAG 作成前に失敗する。
- `params_by_target` の target 名と kwargs を catalog の `OpSpec` で検証する。
- unknown kwarg と不正 choice は既存 `validate_operation_kwargs` と同じ文言・候補提示を使う。
- 選択先の `required_args` が code 値にも GUI/default にも無い場合は、必要引数名を示す。
- `params_by_target` の入力 mapping はコピーし、呼び出し後の外部 mutation に依存しない。
- selector 自身、primitive/effect kind の取り違え、effect arity の取り違えは許可しない。
- 互換 wrapper、別名 shim、target evaluator の再帰 dispatch は追加しない。

## 6. 実装フェーズ

- [x] ユーザーが本計画を承認した。

### Phase 1: selector metadata / lowering 共通部

- [x] private selector 名、target arg key encoding、catalog fingerprint を定義する。
- [x] primitive/effect catalog から selector 用 `meta/defaults/param_order/ui_visible` を生成する。
- [x] target choice と target 固有引数を二段階で解決する共通 helper を実装する。
- [x] target spec へ戻す際の kwargs 検証と required 引数検査を実装する。
- [x] current catalog の choice metadata を既存 state へ反映する最小の merge 規則を実装する。

### Phase 2: `G.select`

- [x] `PrimitiveNamespace.select` を追加する。
- [x] target 固有 parameter を解決し、実 target の primitive `Geometry` を返す。
- [x] label / key / instance_key / shared を既存 primitive と同じ規則で処理する。
- [x] custom primitive、required 引数、`cache_policy="none"` を確認する。

### Phase 3: `E.select`

- [x] selector step を EffectBuilder が保持できる小さな immutable 表現を追加する。
- [x] `n_inputs` ごとの候補抽出と private selector spec を追加する。
- [x] 選択された実 effect node を chain 内へ lower する。
- [x] unary chain、binary 先頭、arity mismatch の既存制約を維持する。
- [x] selector 後続の通常 effect と chain ordinal / step index を維持する。

### Phase 4: Parameter GUI

- [x] selector group を primitive/effect の既存 header・chain groupingへ統合する。
- [x] target dropdown を常に先頭へ表示する。
- [x] 選択中 target の引数だけを表示する。
- [x] 選択先 operation の `ui_visible` を selector target 条件と合成する。
- [x] namespace を row label / Help / search textへ漏らさない。
- [x] catalog revision 更新時に table model cache を正しく再構築する。
- [x] inactive target の値を保持し、target 復帰時に再利用する。

### Phase 5: 公開型・文書

- [x] stub generator の `_G` / `_E` に `select` を追加する。
- [x] packaged `src/grafix/api/__init__.pyi` を再生成する。
- [x] README Core API に unary primitive/effect selector 例を追加する。
- [x] binary effect、`params_by_target`、custom operation 登録順の注意を記載する。
- [x] 公開関数へ日本語 NumPy スタイル docstring と型ヒントを付ける。

### Phase 6: 検証

- [x] focused API / core / Parameter GUI / stub tests を通す。
- [x] `PYTHONPATH=src pytest -q` を通す。
- [ ] `ruff check .` を通す（依頼範囲外の既存 33 件で失敗。変更対象は全件成功）。
- [x] `mypy src/grafix` を通す。
- [x] `git diff --check` を通す。
- [x] 小さな manual sketch で target 切替と parameter 復元を目視確認する。
- [x] 本計画の完了項目と検証結果を更新する。

## 9. 実装・検証結果（2026-07-20）

- `G.select`、`E.select`、`EffectBuilder.select` を追加し、選択後の DAG は実 target
  operation を保持するようにした。
- selector metadata / identity は `core`、API lowering は `api` に分離し、
  `interactive -> api` の依存境界を維持した。
- target は Parameter GUI の combo とし、target 固有 state、`ui_visible`、MIDI、
  save/recovery、worker/main registry 更新へ対応した。
- Copy Code は非表示中の target parameter も復元する。GUI 非公開引数を安全に
  復元できない custom operation では、不完全なコードの代わりに NOTE を出す。
- full test: `2160 passed, 1 skipped`
- mypy: `Success: no issues found in 228 source files`
- 変更対象 Ruff: `All checks passed`
- repository-wide Ruff: 依頼範囲外の既存 33 件
  （`.agents/skills/` と `sketch/`）により未完了
- `git diff --check`: 成功
- 実 GUI で primitive/effect の target combo と target 固有行を目視確認した。
  manual smoke では `circle -> rect -> circle` 後に radius `4.25` が復元された。

## 7. テスト項目

### API / DAG

- primitive target 切替で root `Geometry.op` が実 target になる。
- unary effect target 切替で effect node `op` が実 target になる。
- binary selector が2入力 effectを適用できる。
- selector 後ろの通常 effect chain が正しい順序になる。
- target change、target args changeで `GeometryId` が変わる。
- 同一 target / args は同じ `GeometryId` になる。
- `cache_policy="none"` の custom target が cache されない。
- profiler / diagnostic の operation 名が selector ではなく実 targetになる。

### Parameter GUI / persistence

- target dropdown に built-in と登録済み custom operation が名前順で出る。
- effect dropdown は同じ `n_inputs` の effect だけを含む。
- target A/B の固有引数が相互に混ざらない。
- A → B → A で A の UI 値、override、MIDI 割当が復元される。
- target 内の既存 `ui_visible` が維持される。
- selector group の label、ordinal、effect chain step が安定する。
- save/load 後も target と target 別 state が復元される。
- hot reload / custom registration 後に候補と metadata が更新される。
- 削除された target は明確なエラーになり、別 targetへ暗黙変更されない。

### Validation / isolation

- unknown target、private target、unknown kwarg、不正 choice、required 欠落を拒否する。
- effect arity mismatch と multi-input selector の chain 中段使用を拒否する。
- selector private spec が catalog、generated built-in method、operation help listへ露出しない。
- 外部 `params_by_target` mapping の呼び出し後 mutationが構築済み builderへ影響しない。
- registryを差し替える test が global registry状態を後続testへ漏らさない。

## 8. 完了条件

- `G.select` と `E.select` が実 target operation の DAG を生成する。
- Parameter GUI から target と target 固有引数を編集できる。
- target ごとの state が切替・永続化をまたいで保持される。
- custom operation と registry 更新が dropdown へ反映される。
- effect arity の曖昧さを `n_inputs` で排除する。
- target 本来の validation、cache、profiling、resource budget 契約を壊さない。
- private selector 実装が通常の operation catalog や公開 stub を汚染しない。
- focused / full test、Ruff、mypy、diff check、manual GUI確認が完了する。
