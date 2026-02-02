# polyhedron: type_index クランプテスト修正プラン（2026-02-02）

## 背景

`polyhedron` の種別（`_TYPE_ORDER`）を増やした結果、`type_index=4` が「最大インデックス」ではなくなった。
そのため、`type_index=999` のクランプ先が `icosahedron`（4）ではなく「末尾の種別」になり、既存テストが落ちている。

## ゴール

`type_index` の範囲外指定が **0..N-1 にクランプされる**ことを、N（種別数）の増減に影響されない形でテストする。

## 作業項目

- [x] 失敗再現: `PYTHONPATH=src pytest -q tests/core/primitives/test_polyhedron.py::test_polyhedron_type_index_is_clamped`
- [x] テスト修正: 最大インデックスをコードから取得して比較する（例: `polyhedron_meta["type_index"].ui_max` もしくは `len(_TYPE_ORDER)-1`）
- [x] テスト実行: `PYTHONPATH=src pytest -q tests/core/primitives/test_polyhedron.py`
- [x] 影響確認: 依頼範囲外の差分には触れない
