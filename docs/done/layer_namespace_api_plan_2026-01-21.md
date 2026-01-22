# Layer の API を namespace 形式（B 案）に寄せる: 実装計画（2026-01-21）

## 背景 / 課題

- `G` / `E` / `P` は「名前空間 + ラベル（pending）」の体験になっている。
  - 例: `G(name="circle").polygon(...)` / `E(name="fx").repeat()...` / `P(name="Grid").layout_grid_system(...)`
- 一方 `L` は callable ヘルパで、例が `L(name="...", geometry_or_list=...)` のように見た目が浮く。
  - 特に `geometry_or_list=` が目立ち、`G/E/P` と並べたときの直感が弱い。

## ゴール

- `L` も `G/E/P` と同じ “namespace + ラベル” の感覚で使える。
  - 例: `L(name="layout1").layer(layout)`
- Layer style のラベル保存（Parameter GUI の表示名）が今まで通り機能する。
- 既存 repo 内の使用箇所（sketch / tests / docs の例）が新 API に移行済み。

## Non-goals（今回やらない）

- 互換ラッパー/シムの維持（`L(geom, ...)` を残す等）はしない。
- `Layer` の概念（1 Layer = 1 Geometry）や、style 解決/GUI の仕様変更はしない。

## 方針（B 案）

`L` を `G/E/P` と同型の “namespace オブジェクト” にする。

### 新しい使い方（案）

- 基本: `L(name="...").layer(geom_or_list)`
- 追加: `L(name="...").layer(..., color=(...), thickness=...)`

※ メソッド名は `layer` を採用（`L(name=...).layer(...)` で “Layer 化する” 意味に寄せる）。

## 設計（最小・素直）

### 1) `LayerNamespace` を追加し、`L` を差し替える

- `src/grafix/api/layers.py`:
  - `LayerNamespace.__call__(name: str | None = None) -> LayerNamespace`
    - `G/E/P` と同じ “pending 値を持つ別インスタンス” を返す。
  - `LayerNamespace.layer(geometry_or_list, *, color=None, thickness=None) -> list[Layer]`
    - `color/thickness` は `.layer(...)` 側で指定する（pending style は持たない）。
    - `name` は builder（`L(name=...)`）側でのみ指定する。
    - `caller_site_id(skip=1)` を使って `Layer.site_id` を決める（現行 `L` と同じ）。
    - `ParamStore` がある場合、確定した `name` があれば `set_label(LAYER_STYLE_OP, site_id, name)` を保存する（現行と同じ）。
    - `geometry_or_list` の正規化・例外（TypeError/ValueError）は現行 `LayerHelper` と同等にする。
    - 複数 Geometry は `Geometry.create(op="concat", inputs=..., params={})` で 1 つにまとめ、結果は常に `list[Layer]`（長さ 1）にする（現行と同じ）。

### 2) 破壊的変更として旧 API を削除する

- `L(geom)` / `L([g1, g2], ...)` の形式は削除し、repo 内は全面的に新 API に移行する。
- ドキュメント/スケッチの例も `L(...).layer(...)` に揃える。

### 3) 型スタブ生成を追従させる

- `src/grafix/devtools/generate_stub.py` の `_render_l_protocol()` を更新し、
  - `__call__ -> _L`（pending）
  - `layer(...) -> list[Layer]`
    を出力する。
- `src/grafix/api/__init__.pyi` は生成物なので `python -m grafix stub` で再生成する。

## 変更範囲（想定）

- 実装:
  - `src/grafix/api/layers.py`
- スタブ:
  - `src/grafix/devtools/generate_stub.py`
  - `src/grafix/api/__init__.pyi`（自動生成）
- テスト:
  - `tests/api/test_layer_helper.py`（内容更新。必要ならファイル名も更新）
- 例/スケッチ（repo 内の使用箇所を移行）:
  - `sketch/readme/examples/1.py`
  - `sketch/readme/1.py`
  - `sketch/readme/18.py`
  - `sketch/readme.py`
  - その他 `rg "\\bL\\("` で出た箇所

## 実装タスク（チェックリスト）

- [x] 命名確定: メソッド名は `layer` を採用
- [x] `src/grafix/api/layers.py` を `LayerNamespace` 方式に置き換える（`L = LayerNamespace()`）
- [x] `tests/api/test_layer_helper.py` を新 API に合わせて更新する
- [x] スケッチ/README 用の例を `L(...).layer(...)` へ移行する（repo 内の `L(` 使用箇所を更新）
- [x] `src/grafix/devtools/generate_stub.py` の `_render_l_protocol()` を更新する
- [x] `python -m grafix stub` で `src/grafix/api/__init__.pyi` を再生成する
- [x] `PYTHONPATH=src pytest -q tests/api/test_layer_helper.py` を実行して最低限の回帰を確認する

## 受け入れ条件（Definition of Done）

- `sketch/readme/examples/1.py` から `geometry_or_list=` の例が消え、`L(name="...").layer(...)` になっている。
- `L` の label 保存（Parameter GUI の Layer 名）が引き続き機能する（既存の Layer style 実装を壊さない）。
- `PYTHONPATH=src pytest -q tests/api/test_layer_helper.py` が通る。
