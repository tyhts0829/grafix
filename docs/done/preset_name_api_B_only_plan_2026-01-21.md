# Preset のラベル付けを B 案（`P(name=...).foo(...)`）で実装する: 計画（2026-01-21）

## 背景 / 問題

- primitive/effect は `G(name=...)` / `E(name=...)` で “グループラベル” を付けられる。
- preset も同じ体験にしたい（= `P(name=...).foo(...)`）。
- 現状は:
  - `P(name="...")` が存在しない（`PresetNamespace` に `__call__` が無い）
  - `@preset` wrapper が `sig.bind(*args, **kwargs)` を行うため、preset 関数が `name/key` をシグネチャに持たないと `name/key` を渡せない
    - 例: `layout_grid_system` は `name/key` を持たない

これにより、実装変更で `site_id` が揺れるときの復帰性（reconcile のヒント）を preset 側で活かしにくい。

## ゴール

- `P(name="Grid").layout_grid_system(...)` の形で、どの preset でもラベル付けできる。
- preset 関数本体に `name`/`key` を書かなくてよい（必要なら書いてもよい）。
- Parameter GUI の snippet も preset については B 案形式（`P(name=...).foo(...)`）を出力する。

## Non-goals（今回やらない）

- A 案（`P.foo(..., name=...)`）を “推奨 API” として整備しない。
  - 実装都合で内部的に通ってもよいが、ドキュメント/スニペット/テストの主眼にしない。
- snippet で `key=` を復元する（site_id から逆算する等）。

## 方針（設計）

### 1) `P(name=...)` を追加（pending ラベル方式）

- `src/grafix/api/presets.py` の `PresetNamespace` に `__call__` を追加する。
- `P(name="Grid")` は「pending name/key を持つ別インスタンス」を返す（`G`/`E` と同型）。
- `P(name="Grid").foo(...)` は内部的に `P.foo(..., name="Grid")` を呼ぶ薄い糖衣とする。
  - 呼び出し側が明示で `name=`/`key=` を渡した場合はそちらを優先（pending は上書きされる）。

### 2) `@preset` wrapper を “予約引数は常に受け付ける” ようにする

`P(name=...).foo(...)` が成立するには、wrapper 側が `name/key` をシグネチャ非依存で受け付ける必要がある。

- `src/grafix/api/preset.py` の wrapper で `kwargs` から先に `name/key` を pop する
  - `sig.bind` は残りの kwargs で行う（これでシグネチャに無い `name/key` が bind を壊さない）
- pop した `name/key` は:
  - label: GUI の group header（`name`）
  - site_id: 同一行複数呼びの分岐（`key`）
  に使う
- 元の関数が `name/key` をシグネチャに含む場合のみ、実関数呼び出しへ渡す（既存の挙動維持）

### 3) snippet は B 案形式に寄せる

- `src/grafix/interactive/parameter_gui/snippet.py` の preset 出力を
  - `P(name='...').foo(...)`（raw label が “既定名と異なる” 場合のみ）
  へ変更する。
- raw label が無い / 既定名と同じ場合は従来どおり `P.foo(...)` を出す（ノイズを増やさない）。

## 変更範囲（想定ファイル）

- `src/grafix/api/presets.py`
- `src/grafix/api/preset.py`
- `src/grafix/interactive/parameter_gui/snippet.py`
- `tests/api/test_preset_namespace.py`（or 新規テスト）
- `tests/interactive/parameter_gui/test_parameter_gui_snippet.py`

## 実装タスク（チェックリスト）

- [x] `PresetNamespace.__call__` を追加（pending name/key）
  - [x] `P(name=...).foo(...)` が動く
  - [x] pending を `__getattr__` の factory 呼び出しへ注入（明示 kwargs があればそちら優先）
- [x] `@preset` wrapper を修正し、`name/key` をシグネチャ非依存で受理
  - [x] `sig.bind` 前に `name/key` を `kwargs.pop` する
  - [x] label 設定/`site_id` 生成に `name/key` を使う
  - [x] 元関数が `name/key` を受ける場合のみ実引数として渡す
- [x] snippet の preset 出力を B 案へ変更
  - [x] raw label が既定名と違う時だけ `P(name=...).foo(...)`
- [x] テスト追加/更新
  - [x] `name/key` をシグネチャに持たない preset で `P(name=...).foo(...)` が落ちない
  - [x] ParamStore に label が保存される（snapshot の label で確認）
  - [x] snippet の preset が `P(name=...).foo(...)` 形式になる
- [x] `PYTHONPATH=src pytest -q` で関連テストを実行

## 受け入れ条件（Definition of Done）

- `P(name="...").foo(...)` が、preset の関数シグネチャに依存せず動く。
- snippet が preset のラベルを B 案形式で復元できる。
- 既存の preset/parameter_gui のテストが通る。
