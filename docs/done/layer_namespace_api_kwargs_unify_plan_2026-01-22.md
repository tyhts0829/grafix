# Layer API の kwargs 位置を統一する（`L(name=...).layer(..., color/thickness)`）: 計画（2026-01-22）

## どこで

- 実装: `src/grafix/api/layers.py`
- スタブ: `src/grafix/devtools/generate_stub.py` → `python -m grafix stub`（`src/grafix/api/__init__.pyi` 再生成）
- テスト: `tests/api/test_layer_helper.py`
- 利用側（repo 内）: `sketch/*`（`rg "\\bL\\("` で検出）

## 何を

Layer API の “kwargs をどこに置くか” を 1 通りに統一する。

- ✅ OK: `L(name="foo").layer(geom, color=(...), thickness=...)`
- ✅ OK: `L.layer(geom, color=(...), thickness=...)`（無名 Layer）
- ❌ NG: `L(name="foo", color=(...), thickness=...).layer(...)`（pending style を廃止）
- ❌ NG: `L(color=(...), thickness=...)`（builder 側で style 指定を廃止）
- ❌ NG: `L(...).layer(..., name="foo")`（name は builder 側に限定）

## なぜ

- `G/E/P` と並べたときの直感（「ラベルは builder 側」「実体の生成はメソッド側」）を揃えたい。
- `L` は effect のように連鎖させないため、pending style を持つと “どこで何が決まっているか” がブレやすい。
- 既存の `Layer.name`（Parameter GUI の label / layer style）という役割は維持しつつ、書き方だけを 1 パターンに絞りたい。

## ゴール（完了条件）

- `L(name=...).layer(..., color/thickness)` の形式だけで repo 内が統一されている。
- `Layer.name` の意味（label / GUI / layer_style）が壊れていない。
- `PYTHONPATH=src pytest -q tests/api/test_layer_helper.py` が通る。

## Non-goals（今回やらない）

- 互換ラッパー/シムの追加（古い呼び方を残すなど）
- `Layer` モデルや layer_style（観測/適用/GUI）の仕様変更

## 変更方針（破壊的）

### 1) `L(...)`（builder）は name のみ受け取る

- `LayerNamespace.__call__(name: str | None = None) -> LayerNamespace` にする。
- `color/thickness` の pending は廃止する。

### 2) `.layer(...)` は geometry + style（color/thickness）だけ受け取る

- `LayerNamespace.layer(geometry_or_list, *, color=None, thickness=None) -> list[Layer]`
- `.layer(..., name=...)` は廃止し、`Layer.name` は builder の `name` からのみ決める。
- `set_label(..., label=name)` は今まで通り、確定した builder `name` がある場合のみ行う。

## 実装タスク（チェックリスト）

- [x] `src/grafix/api/layers.py`
  - [x] `LayerNamespace.__call__` から `color/thickness` を削除（pending style を削除）
  - [x] `LayerNamespace.layer` から `name` 引数を削除（name は builder に限定）
  - [x] `Layer(name=...)` に入れる `name/color/thickness` の決定ロジックを整理
- [x] repo 内の利用箇所を移行（`rg "\\bL\\("`）
  - [x] `L(name=..., color=..., thickness=...).layer(...)` → `L(name=...).layer(..., color=..., thickness=...)`
  - [x] `L(thickness=..., color=...).layer(...)` → `L.layer(..., color=..., thickness=...)`（無名）
  - [x] `L(...).layer(..., name=...)` → `L(name=...).layer(...)`
- [x] `tests/api/test_layer_helper.py` を新 API に追従
  - [x] 既存テストの書き換え
  - [x] （任意）`L(color=...)` が `TypeError` になることをテストで固定
- [x] `src/grafix/devtools/generate_stub.py` の `_render_l_protocol()` を更新
- [x] `PYTHONPATH=src python -m grafix stub` で `src/grafix/api/__init__.pyi` を再生成
- [x] `PYTHONPATH=src pytest -q tests/api/test_layer_helper.py`

## メモ（既存計画との関係）

- `docs/plan/layer_namespace_api_plan_2026-01-21.md` で導入した `L(name=...).layer(...)` をさらに “kwargs の置き場” まで一意にする追加整理。
