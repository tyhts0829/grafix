# どこで: Grafix リポジトリ（設計メモ / 実装チェックリスト）。

# 何を: `python -m grafix generate_stub` で、ユーザー定義 preset を `P.<name>` の明示メソッドとして列挙し、IDE 補完（引数名/型）を効かせる。

# なぜ: `P.__getattr__` による動的解決だけだと静的解析が引数を推論できず、UX が落ちるため。

# P（PresetNamespace）のユーザー preset 補完: 実装計画

## ゴール

- `paths.preset_module_dirs` で自動 import されるユーザー preset が、`grafix/api/__init__.pyi` の `P` で補完できる。
  - 例: `P.logo(` と打つと `logo` が候補に出て、引数名も出る。
- ユーザーは「preset を追加/変更したら `python -m grafix generate_stub`」だけでよい（手動 import 不要）。
- 生成結果は決定的（毎回同じ順序/同じ出力）。

## 非ゴール（今回やらない）

- ユーザー独自型（プロジェクト内クラス等）まで含めた “完全な” 型解決。
  - スタブは `grafix.api` 内に閉じるため、未知の型は `Any` に落とす。
- ファイル監視やホットリロード。

## 方針（最小）

- `generate_stub` 実行時に preset autoload を走らせ、レジストリに登録された callable から `_P` を生成する。
- `class _P(Protocol)` の `__getattr__` は残しつつ、補完目的で `def <preset_name>(...)` を列挙する。

## 仕様を先に決めたい点（要確認）

- [x] 型注釈の採用方針
  - A 案: ユーザー関数の注釈は使わず、`@preset(meta=...)` の `kind` から型を決める（安全・単純）。
  - B 案: 注釈が “スタブ内で解決可能” な場合だけ採用し、無理なら `kind` / `Any` に落とす（補完が良くなる）。
- [x] `_P` メソッドの引数スタイル
  - A 案: 既存の `G/E` と揃えてすべて kw-only（`def logo(self, *, ...)`）にする。
  - B 案: 元関数の signature をできるだけ再現する（positional-only 等も反映）。

## 実装チェックリスト

- [x] `src/grafix/devtools/generate_stub.py` で preset を autoload する
  - [x] `import grafix.api.presets` を追加し、`grafix.api.presets._autoload_preset_modules()` を呼ぶ
  - [x] `preset_func_registry` / `preset_registry` を参照し、preset 名一覧を取得する（名前でソート）
- [x] `_render_p_protocol()` を拡張して preset を列挙生成する
  - [x] Python 識別子として不正な preset 名はスキップする（`_is_valid_identifier` を流用）
  - [x] `inspect.signature()` で引数/戻り値の注釈を取得する
  - [x] 引数の型は「注釈がスタブ内で解決可能なら注釈、無理なら `meta.kind`」で決める
  - [x] 戻り値型は注釈が取れれば採用し、無理なら `Any`
  - [x] docstring は 1 行 summary + NumPy Parameters を拾える範囲で拾い、無ければ `meta` ヒントに落とす
- [x] 生成後の `src/grafix/api/__init__.pyi` を更新する
  - [x] `python -m grafix generate_stub` を実行して同期する
- [x] テストを追加する（回帰防止）
  - [x] `tests/devtools/test_generate_stub_p_presets.py`（新規）:
    - [x] tmpdir に preset モジュールを生成し、明示 config（`set_config_path`）で `preset_module_dirs` に追加する
    - [x] `generate_stubs_str()` の出力に `class _P` の `def <name>(...)` が含まれることを検証する
  - [x] 既存のスタブ同期テスト（`tests/stubs/test_api_stub_sync.py`）が通る状態にする
- [x] README を最小更新する
  - [x] 「ユーザー preset の補完は `preset_module_dirs` + `python -m grafix generate_stub`」を 2〜3 行で追記する

## 追加で気づいた点（提案）

- `generate_stub` は “import 副作用” を許容するコマンドなので、preset autoload をここで走らせるのが一番素直。
- autoload 由来の import エラー/二重登録（同名 preset）は、スタブ生成を失敗させて早期に気づける方が安全。
- `generate_stub` 側で preset 一覧を列挙するため、`PresetFuncRegistry.items()`（read-only）を追加した。
