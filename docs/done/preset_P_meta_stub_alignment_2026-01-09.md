# どこで: Grafix リポジトリ（設計メモ / 実装チェックリスト）。
# 何を: preset の `P.<name>(...)` について「meta（GUI公開引数）＝IDE補完に出る引数」を徹底する。
# なぜ: GUI/永続化/スニペット/補完のズレを無くし、`@preset(meta=...)` を唯一の “公開契約” にするため。

# P（preset）の meta=補完 統一: 実装改善計画（2026-01-09）

## ゴール

- `P.<name>(...)` の補完に出る引数は `@preset(meta=...)` のキーと一致する。
- `meta` に入っていない引数は「公開 API ではない」として扱い、補完にも出さない。
- `layout_guides` の `canvas_size` は `canvas_w` / `canvas_h` の 2 つの float に分割し、meta に含める。

## 非ゴール（今回やらない）

- `vec2` kind の追加（GUI widget / CC / normalize / range 編集まで増えるため）。
- `meta` に無い “隠し引数” を補完だけ出す（設計思想に反する）。

## 決定事項

- [x] `P` の補完引数は `meta` 由来のみ（= `PresetRegistry` の `meta` / `param_order` のみ）で生成する。
- [x] `layout_guides.canvas_size` は廃止し、`canvas_w` / `canvas_h` を meta に追加する。

## 実装チェックリスト

### 1) P のスタブ生成を meta-only に寄せる

- [x] `src/grafix/devtools/generate_stub.py` の `_render_p_protocol(...)` を「meta に無い引数を出さない」方針に統一する
  - [x] 予約引数 `name` / `key` を `_P` の明示メソッドから外す（meta と一致させる）
  - [x] 引数型: “解決可能な注釈があれば注釈、無理なら `meta.kind`/`Any`” を維持する
  - [x] docstring: 既存の “summary + Parameters（拾える範囲） + meta ヒント” を維持する
- [x] 回帰テスト更新
  - [x] `tests/devtools/test_generate_stub_p_presets.py` の期待値を meta-only へ更新する
  - [x] `tests/stubs/test_api_stub_sync.py` が通るように `python -m grafix generate_stub` を再実行する

### 2) “meta と signature のズレ” を潰す（最低限: 既存プリセット）

- [x] `sketch/presets/layout_guides.py` を更新する（canvas_size → canvas_w/canvas_h）
  - [x] `meta` に `canvas_w` / `canvas_h`（kind=float）を追加する（ui_min/ui_max も設定する）
  - [x] `layout_guides(...)` の引数を `canvas_w: float` / `canvas_h: float` に変更し、内部では `(canvas_w, canvas_h)` を組み立てて既存ロジックに渡す
  - [x] docstring の Parameters を更新する（`canvas_size` の説明を置換）
  - [x] `draw()` や `__main__` の呼び出し側も新引数に合わせる（必要なら）
- [x] （任意だが推奨）`paths.preset_module_dirs` 配下の preset を点検し、meta に無い必須引数が残っていないことを確認する
  - [x] 例: `sketch/presets/flow.py` に `meta` 非公開の引数が残っていないか確認する（あれば公開するか除去する）

### 3) テスト（最小）

- [x] `PYTHONPATH=src pytest -q tests/devtools/test_generate_stub_p_presets.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `PYTHONPATH=src pytest -q tests/api/test_preset_namespace.py`

## 追加で気づいた点（要相談）

- `@preset` の予約引数 `name/key` は “GUI非公開の利便機能” だが、meta=補完の厳密一致を優先するなら補完から外すのが一番単純。
  - 予約引数の補完が必要になったら、その時点で API を整理（例: `P(label).logo(...)` 的な明示 API）する方が筋が良い。
