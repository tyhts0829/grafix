# Parameter GUI の Style snippet を「コピペして機能する形」に直す: 計画（2026-01-22）

## 背景 / 課題

Parameter GUI の `Style` ヘッダの `Code`（snippet）出力が、現状は「Pythonとして貼れる場所がない」形式になっている。

例（`sketch/readme/examples/1.py` の Style snippet）:

```py
    dict(
        background_color=(0.0, 0.0, 0.0),
        line_thickness=0.001,
        line_color=(1.0, 1.0, 1.0),
    )

    dict(
        name='layout1',
        color=(1.0, 1.0, 1.0),
        thickness=0.001,
    )

    dict(
        color=(1.0, 1.0, 1.0),
        thickness=0.001,
    )
    ...
```

- `dict(...)` が **ただの式**として並んでいるため、貼っても “何にもならない”。
- さらに layer 側は `name` が無い dict が大量に出て、どの Layer に対応するかコードへ戻せない。
- 目的（GUIで調整した Style をコードに戻す）に対して、出力形式が合っていない。

## ゴール

- Style snippet が、そのまま **貼る場所が明確**で、最低限 “動く/使える” 形式になる。
  - global style は `run(..., background_color=..., line_thickness=..., line_color=...)` に貼れる。
  - layer style は `L(name="...").layer(..., color=..., thickness=...)` に貼れる（※ `L` API は現行仕様に追従）。
- “名前が無い layer style” のノイズを減らし、ユーザーが次に取るべき行動（= `L(name=...)` を付ける）まで誘導できる。

## Non-goals（今回やらない）

- Style/LAYER_STYLE の内部表現（ParamStore / layer_style 観測・適用）の変更
- GUI 側の大規模なレイアウト変更（Style を複数ヘッダに分割する等）
- 自動で「この style はこの変数の Layer だ」と推測して draw コードを生成する（誤マッチの温床）

## 方針（出力形式の統一）

Style snippet を **2 セクション**に分け、どちらも “貼る場所が決まっている” 形で出す。

### A) global style（`run(...)` 用）

- `dict(...)` ではなく、**kwargs 断片**として出す（行末に `,` を付ける）。
- 例:

```py
    # --- run(...) ---
    background_color=(0.0, 0.0, 0.0),
    line_thickness=0.001,
    line_color=(1.0, 1.0, 1.0),
```

### B) layer style（`L(name=...).layer(...)` 用）

- `raw label`（= `L(name=...)` 由来の永続ラベル）がある layer のみを “コードに戻せる対象” とみなし、出力する。
  - `raw label` が無い layer（= implicit layer / 無名）は **出力しない**（または 1 行の注意コメントにまとめる）。
- 形式は、**`.layer(..., color/thickness)` に貼れる kwargs 断片**として出す。
- 例:

```py
    # --- L(name=...).layer(..., color/thickness) ---
    # layout1: paste into `L(name='layout1').layer(...)`
    color=(1.0, 1.0, 1.0),
    thickness=0.001,
```

※ 無名 layer をどうしても出したい場合は `site_id` をコメントで示す程度に留める（コードへ書き戻す対象にはしない）。

## 実装範囲（想定）

- `src/grafix/interactive/parameter_gui/snippet.py`
  - `group_type == "style"` の分岐のみを修正
- `tests/interactive/parameter_gui/test_parameter_gui_snippet.py`
  - Style snippet の期待仕様を更新（`dict(` が並ばない / セクション見出しが入る / raw label が無い layer を出さない 等）

## 実装タスク（チェックリスト）

- [ ] `snippet.py`: Style snippet を “kwargs断片 + セクション見出し” へ変更
  - [ ] global style: `dict(` wrapper をやめ、`background_color=...,` 等をそのまま出す
  - [ ] layer style: raw label がある site のみ出す（無名はまとめて注意コメント）
  - [ ] layer style の `name=` key は出さない（`L(name=...)` 側で指定するため）
- [ ] `test_parameter_gui_snippet.py`: Style snippet のテスト更新/追加
  - [ ] global: `dict(` が含まれないこと
  - [ ] layer: raw label がある場合のみ出ること（無名 layer は出ない）
  - [ ] 断片として貼りやすいよう、各 kwargs 行が `,` で終わること
- [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_snippet.py`

## 受け入れ条件（Definition of Done）

- `sketch/readme/examples/1.py` の Style snippet が、上記フォーマットのように
  - `run(...)` に貼れる global kwargs 断片
  - `L(name=...).layer(...)` に貼れる（名前付きのみの）layer kwargs 断片
  を含み、無名 layer の `dict(color=..., thickness=...)` が連発しない。

