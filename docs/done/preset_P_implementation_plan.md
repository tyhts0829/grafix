# どこで: Grafix リポジトリ（設計メモ / 実装チェックリスト）。

# 何を: preset に `P.<name>` でアクセスできる公開 API（PresetNamespace）を導入する計画。

# なぜ: `@preset` で登録した「再利用単位」を、G/E と同じ感覚で呼び出せるようにするため。

# P（PresetNamespace）導入: 実装計画

## ゴール

- `from grafix import P`（または `from grafix.api import P`）で `P` を使える。
- `@preset` で登録した preset を `P.<name>(...)` で呼び出せる。
- `config.yaml` の `paths.preset_module_dirs` に指定したディレクトリから preset モジュールを自動 import できる（ユーザーの手動 import 不要）。
- Parameter GUI / 永続化の既存挙動（`preset_registry` を参照している箇所）が壊れない。

## 非ゴール（今回やらない）

- 補完/型の完全対応（ユーザー定義 preset を静的に列挙するのは困難）。
- ファイル監視によるホットリロード（再起動で反映で十分）。
- Python パッケージ/entrypoint 等によるプラグイン探索（今回の config 指定方式のみ）。
- 互換ラッパー（破壊的変更が必要なら素直に変更する）。

## 公開 API 案（最小）

- `P.<name>(**kwargs)`:
  - `<name>` は preset の公開名（基本は関数名）。
  - 実体は `@preset` が返す wrapper（= 既存の GUI 連携つき関数）を呼ぶだけ。
- 例:
  - `@preset(...)` で `def logo(...): ...` を定義
  - `P.logo(scale=2.0, ...)` で呼ぶ

## 登録ストーリー（ユーザー定義 preset）

- `@preset` はデコレータ適用時に「name -> callable」をグローバルレジストリへ登録する。
- ユーザー定義 preset は `config.yaml` の `paths.preset_module_dirs` で「格納ディレクトリ」を指定する。
- `P` 初回アクセス時に `preset_module_dirs` を走査して自動 import し、`P.<name>` が生える。
- 例（手動 import 不要）:

```yaml
# ./.grafix/config.yaml（または ~/.config/grafix/config.yaml）
paths:
  preset_module_dirs:
    - "sketch/presets"
```

```python
from grafix import P

P.logo(scale=2.0)
```

## 仕様を先に決めたい点（要確認）

- `@preset(op=...)` を残す？；残さない
  - 残す場合、`P.<name>` はどの op に解決する想定にする？（`preset.<name>` 固定か、op 任意か）
- `P` の名前解決は「関数名のみ」でよい？；はい
  - 例: `@preset(op="preset.my_logo") def logo(...): ...` のとき `P.logo` と `P.my_logo` のどっちを正にするか。
- 同名 preset（`P.<name>` が衝突）した場合はどうする？；raise（ValueError）
  - import 順で “どっちが勝つか” を避け、衝突は早期に検出する。
- `paths.preset_module_dirs` の探索ルールは？
  - 直下の `*.py` のみ / 再帰する？；再帰する。
  - import 順（ファイル名ソートで固定する等）を決める？；ファイルパスでソートして固定する
  - import エラー時に止める？（まずは止めて良い気はする）；止める
- Parameter GUI の snippet 出力:
  - 現状は `logo(...)` のように “素の関数呼び出し” を生成する。
  - `P.logo(...)` を生成する方針に変える？（preset autoload 前提なら整合しやすいが、既存テスト/UX に影響）
  - 実装は「文字列の先頭に `P.` を足す」ではなく、preset 分岐だけ `G.` と同様に prefix を渡す（インデント済み出力を壊さない）。
    - 例: `snippet_for_block(..., group_type="preset")` で `_format_kwargs_call("P.", op=call_name, ...)`

## 実装チェックリスト

- [x] `preset_registry` と別に「呼び出し可能な preset 本体」を保持するレジストリを用意する（例: `preset_func_registry: dict[str, Callable[..., Any]]`）
- [x] `@preset` デコレータで、GUI 用 spec 登録（既存）に加えて callable 登録も行う
  - [x] `src/grafix/api/preset.py` 内の `ParamSpec("P")` が新しい公開変数 `P` と衝突するのでリネームする（例: `_PSpec`）
  - [x] 同名 preset の二重登録は `ValueError` で fail-fast（import 順依存を作らない）
- [x] `paths.preset_module_dirs`（config.yaml）を追加する
  - [x] `src/grafix/resource/default_config.yaml` にキーを追加（既定は空配列）
  - [x] `src/grafix/core/runtime_config.py` に読み取り・型を追加
- [x] preset autoload を追加する
  - [x] `paths.preset_module_dirs` の `*.py` を自動 import する（初回のみ）
  - [x] 呼び出し箇所を決める（候補: `P.__getattr__` の先頭）
  - [x] Parameter GUI 有効時は `run()` 開始時に main プロセスで autoload して registry を埋める（mp-draw worker だけで登録される問題の回避）
  - [x] autoload 中に同名衝突が起きたら raise（上の fail-fast が効く前提）
- [x] `P` 名前空間（PresetNamespace）を追加する
  - [x] `src/grafix/api/presets.py`（新規）に `PresetNamespace` + `P = PresetNamespace()` を置く
  - [x] `__getattr__` で未登録なら `AttributeError`（G/E と同じ）
  - [x] `_` 始まりは拒否（G/E と同じ）
- [x] `grafix.api` / `grafix` ルートから `P` を公開する
  - [x] `src/grafix/api/__init__.py` の `__all__` に追加
  - [x] `src/grafix/__init__.py` の `__all__` に追加
- [x] 型スタブ同期
  - [x] `src/grafix/devtools/generate_stub.py` を更新して `src/grafix/api/__init__.pyi` に `P` を含める
  - [x] `tests/stubs/test_api_stub_sync.py` が通る状態にする
- [x] テスト追加/更新
  - [x] `tests/api/` に `P.logo(...)` で `ParamStore` 連携が動く最小テストを追加
  - [x] `paths.preset_module_dirs` の自動 import で `P.logo(...)` が使える最小テストを追加
  - [x] snippet を `P.<name>` へ変更するなら `tests/interactive/parameter_gui/test_parameter_gui_snippet.py` を更新
  - [x] 同名 preset の二重登録が raise される最小テストを追加
- [x] ドキュメント更新
  - [x] `README.md` の “Optional features” / “Extending” に `P` の説明と例を追加（ユーザー定義 preset は `paths.preset_module_dirs` で登録する前提も明記）

## 追加で気づいた点（提案）

- `preset_registry` が “op -> spec” のみなので、`P.<name>` 実現には「name -> callable」マップが別途必要。
  - ここを `preset_registry` に統合するか、別レジストリにするかで実装の単純さが変わる（統合の方がシンプル）。
