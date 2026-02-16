# text primitive の既定フォントを Noto Sans JP に変更（実装計画 / 2026-02-14）

作成日: 2026-02-14  
ステータス: 完了（実装済み）

## 背景 / 問題

- `src/grafix/core/primitives/text.py` の `DEFAULT_FONT` が `"Helvetica.ttc"` になっている。
- ユーザー環境によっては Helvetica が存在せず、`resolve_font_path()` が `FileNotFoundError` となって `G.text()` が落ちる。

## 目的

- `G.text()` のデフォルトフォントを grafix 同梱の `NotoSansJP-Regular.ttf` にし、OS 依存のフォント存在に依存しないようにする。

## 方針

- `DEFAULT_FONT` に OS / インストール場所依存になりやすい絶対パスや `src/...` 相対パスは入れない。
  - GUI の表示や設定保存で「環境固有パス」が混ざるのを避けるため。
- フォントの実体パス解決は `resolve_font_path()` に寄せ、デフォルト値は **ファイル名**（例: `NotoSansJP-Regular.ttf`）にする。
- 同梱フォント探索に `resource/font/Noto_Sans_JP/static` も含める（既存の Google Sans は維持）。

## 実装タスク（チェックリスト）

- [x] 現状確認: `text.DEFAULT_FONT` の参照箇所と `resolve_font_path()` の探索順を確認
- [x] `src/grafix/core/font_resolver.py` の同梱探索に Noto Sans JP を追加（Google Sans を壊さない）
- [x] `src/grafix/core/primitives/text.py` の `DEFAULT_FONT` を `NotoSansJP-Regular.ttf` に変更
- [x] `pyproject.toml` の `tool.setuptools.package-data` に Noto Sans JP の配布対象を追加
  - `resource/font/Noto_Sans_JP/static/*.ttf`
  - `resource/font/Noto_Sans_JP/OFL.txt`
  - `resource/font/Noto_Sans_JP/README.txt`
- [x] スモーク: `PYTHONPATH=src pytest -q tests/core/test_font_resolver.py` を実行して通ることを確認

## 受け入れ条件（DoD）

- [x] Helvetica が無い環境でも `G.text()` がデフォルト設定で例外にならない（デフォルト指定が同梱フォントに変更済み）
- [x] `resolve_font_path("NotoSansJP-Regular.ttf")` が同梱フォントから解決できる
- [x] パッケージ配布に Noto Sans JP の必要ファイルが含まれる設定になっている（`pyproject.toml` を更新済み）

## 注意

- 現状の作業ツリーでは `src/grafix/resource/font/Noto_Sans_JP/` が未追跡（`git status` 上 `??`）なので、配布を成立させるには別途このディレクトリをリポジトリに含める必要がある。
