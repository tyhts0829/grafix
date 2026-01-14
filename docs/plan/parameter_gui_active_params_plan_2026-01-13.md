# どこで: `src/grafix/interactive/parameter_gui/`（表示/描画）、`src/grafix/api/preset.py` と各 registry（UI ルール登録）、`sketch/presets/layout.py`（layout の依存関係を記述）。
#
# 何を: Parameter GUI に「現在の状態で効いている（active な）パラメータだけを表示する」仕組みを追加する。
#
# なぜ: `use_safe_area` や `base` などの分岐で “効かない引数” が多数発生する preset では、GUI に全パラメータが並ぶと理解/操作が遅くなり混乱するため。

## ゴール

- “効く状態” のパラメータだけを Parameter GUI に表示できる。
- いつでも全パラメータ表示へ戻せる（探索/事前設定のため）。
- hidden 行があっても ParamStore 反映（`rows_before/after` の 1:1）を壊さない。

## 非ゴール（今回やらない）

- 依存関係の自動推論（コード解析で「使われた引数だけ」を出す等）。
- 値の自動リセット（非活性になった引数を勝手に既定値へ戻す等）。
- MIDI/CC の自動解除（非活性引数の cc_key を勝手に消す等）。

## 現状整理（なぜ難しいか）

- GUI は `render_parameter_table()` が **入力 rows と同じ長さ** の `rows_after` を返す前提。
  - `store_bridge` が `zip(rows_before, rows_after, strict=True)` で差分適用するため。
- そのため「行を物理的に削除」すると store 反映が崩れる。
  - 解決策: “表示は減らす” が “配列は減らさない”（非表示行は更新せずに素通し）にする。

## 方針（採用: 案B）

- meta（ParamMeta）は今のまま: 型/レンジ/choices のみを保持（永続化の意味が明確）。
- visibility は **永続化しない** “純粋に GUI の都合” として別マップで保持する。
- preset/primitive/effect の decorator で `ui_visible=...` を受け取り、各 registry に登録する。

## 仕様（案Bの具体）

### 1) UI ルールの形

- `ui_visible: dict[str, Callable[[Mapping[str, object]], bool]]`
  - key: 引数名（arg）
  - value: “その group（op+site_id）の現在値” を受け取り、その引数行を表示するか返す predicate
- ルール未指定の引数は常に表示（後方互換）。

理由:
- DSL（式言語）を作らず、Python の関数で完結させてシンプルにする。
- 永続化不要なので関数で問題ない。

#### `ui_visible` の具体例（`layout` preset）

前提: `@preset` が `ui_visible=` を受け取れるようになった後の想定例。

```python
from collections.abc import Mapping
from typing import Any

def _base_is(name: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return str(v.get("base", "")) == name
    return _pred

def _any_true(*keys: str):
    def _pred(v: Mapping[str, Any]) -> bool:
        return any(bool(v.get(k)) for k in keys)
    return _pred

LAYOUT_UI_VISIBLE = {
    # base 選択で “効く” 引数だけ出す
    "cell_size": _base_is("square"),
    "ratio": _base_is("ratio_lines"),
    "levels": lambda v: str(v.get("base")) in {"ratio_lines", "metallic_rectangles"},
    "min_spacing": _base_is("ratio_lines"),
    "max_lines": _base_is("ratio_lines"),
    "metallic_n": _base_is("metallic_rectangles"),
    "corner": _base_is("metallic_rectangles"),
    "clockwise": _base_is("metallic_rectangles"),

    "cols": lambda v: str(v.get("base")) in {"columns", "modular"},
    "gutter_x": lambda v: str(v.get("base")) in {"columns", "modular"},
    "show_column_centers": lambda v: str(v.get("base")) in {"columns", "modular"},
    "rows": _base_is("modular"),
    "gutter_y": _base_is("modular"),

    # “表示トグルが false の間は設定不要” なものは隠す
    "baseline_step": _any_true("show_baseline"),
    "baseline_offset": _any_true("show_baseline"),
    "trim": _any_true("show_trim"),
    "mark_size": _any_true("show_intersections"),

    # safe area が無関係なら margin 自体を見せない（事前設定したい場合は Show inactive を ON）
    "margin_l": _any_true("use_safe_area", "show_margin"),
    "margin_r": _any_true("use_safe_area", "show_margin"),
    "margin_t": _any_true("use_safe_area", "show_margin"),
    "margin_b": _any_true("use_safe_area", "show_margin"),
}

@preset(meta=meta, ui_visible=LAYOUT_UI_VISIBLE)
def layout(...):
    ...
```

ポイント:
- predicate の入力 `v` は **その preset 呼び出し 1 回（= 1 group）** の “現在値辞書”。
- `Show inactive params` を ON にすれば、非活性の引数も一時的に表示できる（事前設定の逃げ道）。

### 2) “現在値” の解決

- 基本は `last_effective_by_key`（解決後の実効値）を使う。
- 無ければ `row.ui_value` にフォールバック。

### 3) GUI のトグル

- Parameter GUI 上部にチェックボックスを追加:
  - `Show inactive params`（ON=全部表示、OFF=active だけ）
- 既定値は OFF（active のみ）を推奨。

## 実装チェックリスト

### 1) ルール登録の器を用意

- [x] `src/grafix/core/preset_registry.py` に `ui_visible` を保持できるよう `PresetSpec` を拡張
- [x] `src/grafix/core/primitive_registry.py` / `src/grafix/core/effect_registry.py` にも同様の仕組みを追加（将来対応）
- [x] `src/grafix/api/preset.py` / `src/grafix/core/primitive_registry.py` / `src/grafix/core/effect_registry.py` の decorator に `ui_visible=` を追加（任意）

### 2) 可視性判定（純粋関数）を追加

- [x] `src/grafix/interactive/parameter_gui/visibility.py`（新規）を追加
  - [x] `active_mask_for_rows(rows, *, show_inactive, last_effective_by_key)` を実装
  - [x] registry から (op,arg) の `ui_visible` を引いて評価する
  - [x] 例外時は “表示する” に倒し、ログに 1 行だけ warning（GUI 全体のクラッシュ回避）

### 3) table 描画へ組み込み

- [x] `src/grafix/interactive/parameter_gui/store_bridge.py` で “表示だけ減らす” を実現する
  - [x] `visible_mask` を計算し、`render_parameter_table(view_rows, ...)` に渡す rows を絞る
  - [x] `rows_after` は入力と同長を維持（非表示行は未変更でそのまま格納）

### 4) GUI トグルを追加

- [x] `src/grafix/interactive/parameter_gui/gui.py` に `Show inactive params` の checkbox を追加
- [x] その値を `render_store_parameter_table(..., show_inactive_params=...)` へ渡す
- [x] toggle は永続化しない（GUI ローカル状態のみ）

### 5) layout preset にルールを付与（最初の適用対象）

- [x] `sketch/presets/layout.py` に `ui_visible` マップを追加して `@preset(..., ui_visible=...)` へ渡す
  - [x] `cell_size` は `base=="square"` のときだけ表示
  - [x] `ratio/levels/min_spacing/max_lines` は `base=="ratio_lines"` のときだけ表示
  - [x] `metallic_n/levels/corner/clockwise` は `base=="metallic_rectangles"` のときだけ表示
  - [x] `cols/gutter_x/show_column_centers` は `base in {"columns","modular"}` のときだけ表示
  - [x] `rows/gutter_y` は `base=="modular"` のときだけ表示
  - [x] `margin_*` は `use_safe_area or show_margin` のときだけ表示
  - [x] `trim` は `show_trim` のときだけ表示
  - [x] `baseline_step/baseline_offset` は `show_baseline` のときだけ表示
  - [x] `mark_size` は `show_intersections` のときだけ表示

### 6) テスト

- [x] `tests/interactive/parameter_gui/test_parameter_gui_visibility.py`（新規）
  - [x] “mask 計算” が期待通りになる（base/flags の組み合わせ）
  - [x] 非表示行があっても `rows_after` の長さが入力と一致する（store_bridge 前提を満たす）

## 要確認

- UI トグルの既定値は active-only（OFF）で確定（必要なら ON で “全部表示” に戻せる）。
- “表示” ではなく “無効化（グレーアウト）” は今回やらない（まずは表示を減らして混乱を減らす）。
