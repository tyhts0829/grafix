# どこで: `src/grafix/core/primitives/text.py`
#
# 何を: `show_bounding_box` の枠が「文字を囲まず、文字が上にはみ出て見える」問題を直す。
#
# なぜ: 現状は “1行目のベースラインが y=0” で、glyph がベースラインより上（負の y）にも伸びるため、
#      枠の上辺（y=0）が文字の下側に見えてしまい、ボックス外に文字があるように見える。

作成日: 2026-01-19

## 現状整理

- text は `y_em=0` をベースラインとして生成している（glyph の上方向は y<0）。
- `show_bounding_box` は `y=0..box_height` に枠を描く。
- 結果として「枠の上辺が文字の下側」になりやすい（特に大文字など descender が無い場合）。

## 方針（提案）

`use_bounding_box=True` のときだけ、1 行目のベースラインを **フォントの ascent 分だけ下げる**。

- `y=0` を “行ボックスの上辺” とみなせるようにする
- 枠は現状どおり `y=0..box_height` のままで、文字が枠内に入る見た目にする

※ `use_bounding_box=False` の既存挙動は変えない（座標がズレない）

## 実装チェックリスト

- [x] フォントの ascent（units）を取得する小関数を追加（優先: `hhea.ascent`、fallback: `OS/2.sTypoAscender`、fallback: `head.yMax`）
- [x] `use_bounding_box=True` のとき、描画開始の `y_em` を `ascent_em` から始める
- [x] `show_bounding_box` の枠描画は `y=0..box_height` のまま（変更しない）
- [x] テスト追加: `use_bounding_box=True` で、文字の `min_y` が概ね 0 以上になること（枠線は不要）

## 変更対象（想定）

- `src/grafix/core/primitives/text.py`
- `tests/core/test_text_primitive.py`
