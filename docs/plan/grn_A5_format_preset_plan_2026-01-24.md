# grn/A5_format.py の preset 化（実装計画）

## 目的

`sketch/presets/grn/A5_format.py` を「再利用できる preset」として切り出し、他のスケッチから `P.<name>(...)` で呼び出せるようにする。

## 完了条件

- `P.grn_a5_format(...)`（または合意した名前）を呼ぶと、現状の A5 フォーマット（layout + template）が同等に生成される。
- preset の公開引数は `# THIS GONNA BE VARIABLE` が付いた 5 パラメータのみ。

## 変数化するパラメータ（現状 → preset 引数）

- `P.layout_grid_system(activate=True)` → `layout_activate: bool`
- `L.layer(..., color=(0.75, 0.75, 0.75))` → `layout_color: (r, g, b)`
- `G.text(text="1")` → `number_text: str`
- `G.text(text="G.polygon()\\nE.repeat().displace()")` → `explanation_text: str`
- `L.layer(..., color=(0.0, 0.0, 0.0))` → `template_color: (r, g, b)`

## 新しい preset API（案）

```py
from grafix import preset

meta = {
    "layout_activate": {"kind": "bool"},
    "layout_color": {"kind": "vec3", "ui_min": 0.0, "ui_max": 1.0},
    "number_text": {"kind": "str"},
    "explanation_text": {"kind": "str"},
    "template_color": {"kind": "vec3", "ui_min": 0.0, "ui_max": 1.0},
}

@preset(meta=meta)
def grn_a5_format(
    *,
    layout_activate: bool = True,
    layout_color: tuple[float, float, float] = (0.75, 0.75, 0.75),
    number_text: str = "1",
    explanation_text: str = "G.polygon()\\nE.repeat().displace()",
    template_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    ...
```

返り値は `layout` と `template` の 2 Layer（`list[Layer]`）を返す（`layout + template`）。

## 注意点（先に合意したい点）

- `sketch/presets/grn/A5_format.py` は内部で `P.layout_grid_system(...)` を呼んでいる。
  - このファイル自体を `@preset` 化すると、**直接実行**（`python sketch/presets/grn/A5_format.py`）時に `P` の autoload が走って同一 preset を二重登録し、例外になる可能性がある。
  - 対応方針はどちらか:
    1. **直接実行サポートを捨てる**（このファイルは preset モジュール専用にし、`__main__`/`run()` を削除 or 使わない）；こちらで
    2. **`P` 依存を外す**（grid_system を別の呼び方に変え、直接実行でも二重登録が起きない構造にする）

## 実装手順（チェックリスト）

- [ ] 1. `sketch/presets/grn/A5_format.py` に `meta` と `@preset` 付き関数（名前は合意したもの）を追加する
- [ ] 2. `# THIS GONNA BE VARIABLE` の 5 箇所を、preset 引数を使う形に置き換える
- [ ] 3. `layout_activate` を `P.layout_grid_system(activate=layout_activate, ...)` に反映する
- [ ] 4. `layout_color` / `template_color` を `L.layer(..., color=...)` に反映する
- [ ] 5. `number_text` / `explanation_text` を `G.text(text=...)` に反映する
- [ ] 6. （方針に応じて）`__main__` ブロックの扱いを整理する
- [ ] 7. 動作確認（最小）
  - [ ] `python -m grafix stub`（補完が必要なら）
  - [ ] `PYTHONPATH=src pytest -q`（可能なら）
