# どこで: `src/grafix/core/primitives/text.py`
#
# 何を: text のバウンディングボックス機能を「box_width>0 で自動有効」ではなく、明示トグルで有効化する。
#       さらに Parameter GUI では有効時のみ関連引数（box_* / show_*）を表示する（`ui_visible`）。
#
# なぜ: レイアウト調整時に、無関係な引数で GUI が煩雑にならないようにしつつ、意図せず折り返しが走るのを避けたい。

作成日: 2026-01-19

## ゴール

- `G.text(...)` に「バウンディングボックス機能の有効化トグル」を追加し、**トグルが True のときだけ**折り返し/枠描画が効く。
- Parameter GUI では `docs/memo/ui_visible.md` の仕組みを使い、トグルが True のときだけ
  - `box_width`
  - `box_height`
  - `show_bounding_box`
  を表示する（トグル自体は常に表示）。

## 非ゴール（今回やらない）

- 既存の文字生成/座標系の仕様変更（`y=0` 上辺のまま）。
- 高さ (`box_height`) による折り返し停止/クリップ。

## 実装チェックリスト

- [x] `text_meta` に有効化トグル（例: `use_bounding_box: bool`）を追加
- [x] `text()` の折り返し条件を「トグル True かつ box_width>0」に変更
- [x] `show_bounding_box` の枠描画条件を「トグル True かつ show_bounding_box True」に変更
- [x] `@primitive(..., ui_visible=...)` を追加し、関連引数をトグル連動で表示/非表示
- [x] テストをトグル前提に更新

## 変更対象（想定）

- `src/grafix/core/primitives/text.py`
- `tests/core/test_text_primitive.py`
