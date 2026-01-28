# parameter_gui と `G.text(text="...")` の日本語対応（フォント）計画

作成日: 2026-01-26
更新日: 2026-01-28

## 背景 / 問題

### parameter_gui

Parameter GUI（`src/grafix/interactive/parameter_gui/`）は ImGui のフォント atlas を 1 つだけロードしており、
glyph range が既定（`get_glyph_ranges_default()` 相当）になりやすい。

- `name=` に日本語を含める
- 文字列パラメータ（例: `G.text(text=...)`）を日本語にする

といったケースで、GUI 上では豆腐（□）や空表示になりやすい。

### `G.text(text="...")`

`src/grafix/core/primitives/text.py` は「指定フォント 1 つ」からアウトラインを生成する。

- 指定フォントに無い文字（例: 日本語）を含む場合、該当文字は描画されない。
- 現状の実装だと “描画されない” だけでなく、advance が 0 扱いになりやすく、文字間が詰まってレイアウトが崩れて見えることがある。

## ゴール

- parameter_gui 上で、日本語を含むラベル/値が読める（豆腐にならない）
  - 英数字の見た目は極力変えない（既定フォントを維持し、日本語だけ補完する）
  - フォールバックフォントが見つからなくてもクラッシュしない
- `G.text` の実装をシンプルに保つ（単一フォント・自動フォールバック無し）
  - 指定フォントに無い文字は「空白」として扱い、**描画しないが advance は確保**してレイアウトを破綻させにくくする
  - 日本語を描きたい場合は、ユーザーが日本語グリフを含むフォントを明示指定できる

## 非ゴール（今回やらない）

- OS 依存の自動フォールバック（CoreText など）
- HarfBuzz 等による shaping / 正確な字詰め
- `G.text` の自動フォールバック（不足グリフを別フォントで補う）

## 方針（採用）

### parameter_gui: 既定 + 日本語フォールバックを merge

- ベースフォントは現状の既定フォントを維持する（英数字の見た目を変えない）
- 日本語フォントは追加でロードし、`merge_mode=True` で atlas に統合する（日本語だけ補完）

### `G.text`: 単一フォント + 欠字は空白

`G.text` は「指定フォントにあるグリフだけ描く」。無いものは空白。

- どの環境でも挙動が決定的（OS の暗黙フォールバックを使わない）
- 作品側で `font=` を明示すれば日本語も描ける（例: `Hiragino Sans GB.ttc` / `NotoSansJP-VariableFont_wght.ttf`）

## 仕様

### 1) parameter_gui（日本語 glyph range + フォールバック merge）

#### フォント atlas 生成

1. ベースフォント
   - 現状の GUI 用既定フォント（例: `default_font_path()`）をロード
   - glyph range: `io.fonts.get_glyph_ranges_default()`
2. 日本語フォールバックフォント（見つかる場合のみ）
   - `merge_mode=True` で追加ロード
   - glyph range: `io.fonts.get_glyph_ranges_japanese()`

期待効果:
- 英数字は従来の見た目を保ち、日本語だけが補完される。

#### フォールバックフォントの選択

- config で指定できるようにする（最小 1 キー）
  - `ui.parameter_gui.fallback_font_japanese: "Hiragino Sans GB.ttc"` のような文字列
- 未指定/解決不能の場合は自動選択（優先順）
  1) `Hiragino Sans GB.ttc`
  2) `NotoSansJP-VariableFont_wght.ttf`
- 見つからない場合はベースのみ（=現状維持、ただし豆腐は許容）

#### 再ビルド条件

- atlas 再作成は “必要なときだけ” 行う
  - backing scale（DPI）が変わったとき
  - （将来的に）フォールバックフォント設定が変わったとき

### 2) `G.text`（欠字＝空白）

#### 欠字判定

- `tt_font.getBestCmap()` に `ord(char)` が無い（または glyph 解決できない）場合、その文字は欠字とみなす

#### 欠字の描画

- アウトラインは生成しない（ポリラインを追加しない）

#### 欠字の advance

欠字でもレイアウトが崩れにくいように、advance は “スペース幅” として扱う。

- `advance_em(missing_char) == advance_em(" ")`（スペースメトリクスが無い場合は既存フォールバック `0.25em`）
- これにより、例えば `A日A`（日が欠字）と `A A` のレイアウトが一致する

## 実装方針（最小変更）

### parameter_gui

- `ParameterGUI._sync_font_for_window()` に “日本語フォールバック merge” を追加する
- 追加設定キー: `ui.parameter_gui.fallback_font_japanese`（string 1つ、未指定は自動選択）

### `G.text`

- `_get_char_advance_em(...)` の “glyph が無い” 分岐を、0 ではなくスペース幅に寄せる
  - 折り返し（`box_width`）と行揃え（`text_align`）の両方が自然に改善される

## 変更箇所（予定）

- `src/grafix/interactive/parameter_gui/gui.py`
- `src/grafix/resource/default_config.yaml`（`ui.parameter_gui.fallback_font_japanese` を追加する場合）
- `src/grafix/core/runtime_config.py`（設定キーの読み取りを追加する場合）
- `src/grafix/core/primitives/text.py`
- `tests/core/test_text_primitive.py`（欠字の advance が空白と同等になる回帰テストを追加）

## 実装手順（チェックリスト）

### parameter_gui

- [ ] 1. `fallback_font_japanese` の仕様確定（string 1つ / 未指定は自動選択）
- [ ] 2. GUI フォント atlas を “ベース + 日本語フォールバック merge” に変更
- [ ] 3. 既存テストが通ることを確認（parameter_gui）
  - [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui`
- [ ] 4. 目視確認（任意）
  - [ ] `name="日本語ラベル"` 等が GUI 上で豆腐にならない

### `G.text`

- [ ] 1. 欠字を含むときの現状挙動を確認（advance が詰まる再現）
- [ ] 2. `_get_char_advance_em(...)` の欠字分岐を “スペース幅” に変更
- [ ] 3. テスト追加（欠字 advance が空白と等価になること）
  - [ ] `G.text(text="A A")` と `G.text(text="A日A")`（日が欠字）で `coords/offsets` が一致する
- [ ] 4. 対象テスト実行
  - [ ] `PYTHONPATH=src pytest -q tests/core -k text`
