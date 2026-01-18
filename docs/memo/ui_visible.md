# どこで: `src/grafix/interactive/parameter_gui/visibility.py` と各 registry（`preset_registry` / `primitive_registry` / `effect_registry`）。
# 何を: Parameter GUI で「いまの状態で効いている引数だけを表示する」ための `ui_visible` の実装/追加方法メモ（開発者向け）。
# なぜ: 分岐の多い preset/effect で GUI が “引数の海” になり、理解/操作が遅くなるのを避けるため。

## 概要

`ui_visible` は **GUI 表示だけ** を制御する仕組み。  
「他のパラメータ状態によって、今は効かない引数行」を非表示にして、操作すべき行だけを見せる。

- 影響範囲: **Parameter GUI の表示のみ**
- 非活性行の値・override・MIDI 割当を **勝手に変更しない**
- `Show inactive params` を ON にすれば **いつでも全行表示** に戻せる

## 仕組み（内部の動き）

実体は「arg -> predicate（表示するなら True）」の辞書。

- ルールは registry に登録される（永続化しない）
  - preset: `preset_registry.get_ui_visible(op)`
  - primitive: `primitive_registry.get_ui_visible(op)`
  - effect: `effect_registry.get_ui_visible(op)`
- GUI 側は行の group を `(op, site_id)` とみなし、group 内の “現在値辞書” を作って predicate に渡す
  - 現在値は基本 `last_effective_by_key`（解決後の実効値）
  - 無ければ `row.ui_value` にフォールバック
- predicate が例外を投げたら **fail-open（その行は表示）** に倒す（GUI を壊さない）

実装箇所:
- 可視マスク計算: `src/grafix/interactive/parameter_gui/visibility.py`
- 表示行だけ `render_parameter_table()` に渡しつつ、`rows_before/after` の 1:1 は維持: `src/grafix/interactive/parameter_gui/store_bridge.py`

## ルールの書き方（API）

### preset の場合

`@preset(..., ui_visible=...)` を渡す。

```python
from collections.abc import Mapping
from typing import Any

def _base_is(name: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return str(v.get("base", "")) == name
    return _pred

UI_VISIBLE = {
    "cell_size": _base_is("square"),
    "ratio": _base_is("ratio_lines"),
}

@preset(meta=meta, ui_visible=UI_VISIBLE)
def layout(...):
    ...
```

ポイント:
- predicate の引数 `v` は **その preset 呼び出し 1 回（= op+site_id の 1 group）** の現在値辞書
- `@preset` は `activate` を自動で公開する（必要なら `v.get("activate")` も参照できる）
- ルール未指定の引数は常に表示される（後方互換）

### primitive / effect の場合

それぞれデコレータに `ui_visible=` を渡す（同じ形）。

```python
from collections.abc import Mapping
from typing import Any

UI_VISIBLE = {
    # 例: auto_center が false のときだけ pivot を見せる
    "pivot": lambda v: not bool(v.get("auto_center")),
}

@effect(meta=meta, ui_visible=UI_VISIBLE)
def rotate(...):
    ...
```

## 値辞書 `v` の中身

`v` は「同一 group（op+site_id）」に存在する行の (arg -> value) 辞書。

例:

```python
{
  "base": "square",
  "cell_size": 10.0,
  "show_baseline": False,
  "baseline_step": 4.0,
  ...
}
```

型は UI/解決結果に依存するので、判定はなるべく `str(...)` / `bool(...)` で正規化すると安全。

## 実装ガイド（おすすめ）

- predicate は **純粋関数** にする（外部状態や乱数に依存しない）
- “スイッチ役” の引数（例: `base`, `show_*`）は原則 **常に表示**（ルールを書かない）にする
  - 誤って隠しても `Show inactive params` で復帰できるが、基本は迷子を作らない設計を優先
- 依存関係が複雑なら、ヘルパを用意して読みやすくする（`_base_is`, `_any_true` など）

## 既知の制約

- group は `(op, site_id)` 単位なので、**別 group の値には依存できない**（意図的に単純化している）
- `ui_visible` は **表示だけ**。非表示でも値は残り、後で再表示になったときに効く（これが基本挙動）

## テスト

- 可視マスクと fail-open の挙動: `tests/interactive/parameter_gui/test_parameter_gui_visibility.py`
