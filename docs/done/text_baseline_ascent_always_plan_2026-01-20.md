# どこで: `src/grafix/core/primitives/text.py`
#
# 何を: `use_bounding_box` の ON/OFF で文字の Y 座標が変わらないように、ベースラインの ascent 補正を常時適用する。
#
# なぜ: トグル操作で文字位置がジャンプするのが気持ち悪く、GUI 操作の予測可能性（UX）を落とすため。

作成日: 2026-01-20

## 方針

- 1 行目のベースラインの初期値を **常に** `ascent_em` にする（= `y=0` が “文字ボックス上辺” 相当になる）。
- `use_bounding_box` は「折り返し」と「枠描画」の有効化トグルのまま維持する（= レイアウト機能のスイッチ）。

## 影響（破壊的変更）

- `G.text(...)` の出力が全体的に **下方向へずれる**（フォントの ascent 分、`scale` 倍）。
  - 既存スケッチの配置が変わる可能性がある。
  - 代わりに `use_bounding_box` の ON/OFF で文字座標は変わらなくなる。

## 実装チェックリスト

- [x] `y_em` の初期値を `use_bounding_box` 非依存にする（常に ascent 補正）
- [x] docstring の Notes を更新（「常に ascent 補正」へ）
- [x] テスト更新
  - [x] `use_bounding_box` の ON/OFF で、折り返しが発生しない条件では座標が一致すること
  - [x] 既存の `min_y` 前提テストを修正/置換

## 変更対象（想定）

- `src/grafix/core/primitives/text.py`
- `tests/core/test_text_primitive.py`
