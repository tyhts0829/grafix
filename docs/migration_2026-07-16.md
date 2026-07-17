# Application foundations migration notes (2026-07-16)

この変更は互換shimを置かない破壊的整理を含む。既存sketch/toolを更新するときは、
以下を上から確認する。

## 公開render/export API

- `Export(...)` のconstructor副作用は廃止した。
- 単発処理は `frame = render(draw, t, ...)`、続けて
  `result = export(frame, path, overwrite=False)` を使う。
- 複数frameは `with RenderSession(draw, ...) as session:` でcache/config/storeを共有する。
- headless parameter sourceの既定は明示的な`code`。保存値を使う場合だけ
  `saved` / `recovery` / JSON pathを指定する。
- line thicknessはcanvas短辺比で、共通既定は`0.001`。

## Interactive evaluation / reload

- `run(..., n_worker=1)` はbackground評価になった。同期実行が必要なら`n_worker=0`。
- background drawはmodule top-levelに置き、起動処理を
  `if __name__ == "__main__":` でguardする。
- source watchはsketch内の`run()`ではなく
  `python -m grafix run sketch.py --watch`を使える。

## Parameter source / identity

- source名は`code | ui | midi_live | midi_frozen`。旧`base/gui/cc`を前提にした表示・
  trace consumerは更新する。
- boolも他kindと同じく明示`override`へ従う。codeを優先するにはCODE、編集値を使うには
  UIを選ぶ。
- 移動に耐える重要groupは`key=...`、loop個体は`instance_key=...`、意図的な共有は
  `shared=True`を指定する。`instance_key`と`shared=True`は同時指定できない。
- 自動reconcileが曖昧な値は捨てずRELINK一覧へ残る。候補を確認して1:1 migrateする。

## Operation / Layer API

- `L.layer(...)` は`list[Layer]`ではなく単一`Layer`を返す。既存の`[0]`や不要な展開を
  削除する。
- `G.polyhedron(type_index=...)`は`G.polyhedron(kind="tetrahedron" | ...)`へ変更する。
- `G.sphere(type_index=..., mode=...)`は意味名`style=...`, `line_mode=...`へ変更する。
- unknown keyword/choiceはDAG作成前に拒否される。`G.describe()` / `E.describe()`または
  `python -m grafix describe ...`で有効引数を確認する。

## Config / path

- user config内の相対pathはprocess CWDではなく、そのconfig fileの親から解決する。
- unknown key、非有限値、逆range、不正choiceはstrict errorになる。
- `python -m grafix config validate/show`で事前確認する。interactiveだけはinvalid configを
  診断した上でpackaged defaultへ退避する。

## Typing / persisted schema

- `python -m grafix stub`はinstalled packageを直接変更せず、project-local stubを生成する。
- ParamStore、capture manifest、WorkspaceStateはversioned schemaになった。future schemaは
  黙って空値へ変換せず拒否する。破損ParamStoreは原本をquarantineして診断する。
- named variation、favorite/lock、workspace配置もParamStore/workspace schemaへ保存される。

## 意図的に変更していない領域

- G-code profile/header/footer/単位/origin/bridge/bounds既定
- canvas/primitive既定とFit to content
- previewのpan/zoom、canvas toolbar、capture command surface、focus共有

これらはAPP-001/003/005として今回の採用範囲から明示的に除外した。
