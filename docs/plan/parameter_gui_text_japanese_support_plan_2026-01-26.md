# parameter_gui と `G.text(text="...")` の日本語対応（フォント）計画

作成日: 2026-01-26

## 背景 / 問題

### parameter_gui

- 現状の Parameter GUI は `src/grafix/interactive/parameter_gui/gui.py` で ImGui のフォントを 1 つだけロードしている。
- その際の glyph range が既定（`get_glyph_ranges_default()` 相当）になっており、日本語（ひらがな/カタカナ/漢字）をフォント atlas に含めない。
- その結果、`name=` に日本語を含める、あるいは文字列パラメータ（例: `G.text(text=...)`）を日本語にすると、GUI 上では豆腐（□）や空表示になりやすい。

### `G.text(text="...")`

- `src/grafix/core/primitives/text.py` は「指定フォント 1 つ」からアウトラインを生成する。
- 既定フォント（現状は `Helvetica.ttc`）に日本語グリフが無い場合、見つからない文字は警告を出してスキップされ、ジオメトリが欠ける/空になる。
- OS が持つフォントフォールバック（描画時の自動置換）を、アウトライン生成側では行っていない。

## ゴール

- Parameter GUI 上で、日本語を含むラベル/値（`name=`、`text=` 等）が文字化けせず表示される。
- `G.text(text="日本語...")` が「フォント指定なし」でも破綻しにくい（少なくとも macOS では標準フォントで描ける）。
- 実装はシンプルに保ち、互換ラッパー/シムは作らない（破壊的変更は許容）。

## 方針（提案）

1. フォント探索を “config の font_dirs + macOS 標準フォントディレクトリ + 同梱フォント” に拡張する。
2. Parameter GUI は ImGui のフォント atlas を「ベース + 日本語フォールバック」の 2 段にして merge する。
3. `G.text` は “見つからない文字だけ” フォールバックフォントで描く（軽いキャッシュ付き）。

## 仕様案（最小）

### 1) フォント探索（font_resolver）

- 変更: `src/grafix/core/font_resolver.py:_search_dirs()`
- macOS のみ、以下を探索ディレクトリに追加する（順序は後述）。
  - `/System/Library/Fonts`
  - `/System/Library/Fonts/Supplemental`
  - `/Library/Fonts`
  - `~/Library/Fonts`
- 探索順（後勝ちではなく「先に見つかったものを採用」なので順序が重要）:
  - `config.yaml:font_dirs`（ユーザーが最優先で上書きできる）
  - macOS 標準フォントディレクトリ
  - grafix 同梱フォント（Google Sans）

期待効果:
- `resolve_font_path("Hiragino Sans GB.ttc")` のような “OS 既定フォント名” が config 無しでも通りやすくなる。
- Parameter GUI のフォント picker（`list_font_choices()`）でも OS フォントを列挙できる。

### 2) Parameter GUI（日本語 glyph range + フォールバック merge）

- 変更: `src/grafix/interactive/parameter_gui/gui.py:ParameterGUI._sync_font_for_window()`
- フォント atlas 生成を以下に変更する:
  1. ベースフォント: 既存どおり `default_font_path()`（同梱 Google Sans）をロード
     - glyph range: `io.fonts.get_glyph_ranges_default()`
  2. フォールバックフォント: 可能なら以下の優先順で 1 つ解決してロード（merge_mode=True）
     - `Hiragino Sans GB.ttc`（macOS 標準フォント、少なくとも日本語基本 + 漢字を含む）
     - `NotoSansJP-VariableFont_wght.ttf`（repo の `data/input/font` に置ける/置いてある想定）
  3. フォールバック側 glyph range: `io.fonts.get_glyph_ranges_japanese()`

注意:
- 既定フォントを “置換” ではなく “merge” にすることで、従来の見た目（英数字）を大きく変えずに日本語だけ補完できる。
- フォールバックが見つからない場合はベースのみ（=現状維持）で動作させる。

### 3) `G.text`（グリフ単位フォールバック）

- 変更: `src/grafix/core/primitives/text.py`
- 文字ごとに cmap を引き、以下を行う:
  - まず primary font で `ord(char)` が cmap にあるか確認
  - 無ければフォールバックフォントを順に試し、最初に見つかったフォントでグリフを描く
- フォールバック候補（最小）:
  - macOS: `Hiragino Sans GB.ttc`（font_index=0 固定）
  - 追加候補（存在する場合のみ）: `NotoSansJP-VariableFont_wght.ttf`
- キャッシュ:
  - `(primary_font_path, primary_index, char)` → “採用フォント（path/index）” を LRU で持ち、毎回の探索コストを下げる。

## 変更箇所（予定）

- `src/grafix/core/font_resolver.py`
- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/core/primitives/text.py`
- `tests/core/test_text_primitive.py`（日本語フォールバックの回帰テストを追加）

## 実装手順（チェックリスト）

- [ ] 1. `font_resolver` に macOS 標準フォントディレクトリを追加し、`resolve_font_path` / `list_font_choices` で拾えることを確認
- [ ] 2. Parameter GUI のフォント atlas を “ベース + 日本語フォールバック merge” に変更
- [ ] 3. `G.text` にグリフ単位フォールバックを追加（missing glyph を補完）
- [ ] 4. テスト追加（対象限定）
  - [ ] `G.text(text="日本語", font="GoogleSans-Regular.ttf")` が “空にならない” こと（フォールバックが効いている）
- [ ] 5. 最小動作確認（手元目視）
  - [ ] `name="日本語ラベル"` や `text="こんにちは"` を含むスケッチを `parameter_gui=True` で起動し、GUI 上で表示できる
- [ ] 6. 対象テスト実行
  - [ ] `PYTHONPATH=src pytest -q tests/core -k text`
  - [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui`（フォント変更が影響しないことの確認）

## 要確認（あなたに決めてほしい点）

1. Parameter GUI の方針は “置換（日本語フォント単独）” ではなく “merge（既定 + 日本語）” で OK？
2. `G.text` のフォールバックは「常に有効（`font=` を明示しても不足グリフだけ補う）」で OK？
   - それとも「既定フォント利用時のみ」など、発動条件を絞る？
3. フォールバック優先順は `Hiragino Sans GB.ttc` を 1st で OK？（macOS 標準で揃う想定）

