# Plan: `sketch/presets/layout/common.py` の mypy エラー修正（2026-01-16）

目的: `sketch/presets/layout/common.py:71` の `Unsupported left operand type for + ("object")` を解消する。

## 作業手順（進捗）

- [x] 現状確認: `common.py` の Geometry 合成（`out + g`）周りの型注釈を確認する
- [x] 方針決定: `object` ではなく `Geometry` で型を表現する（必要なら `cast` を使う）
- [x] 実装: `_concat` の `out + g` を `cast(Geometry, ...)` 経由にして mypy を通す
- [x] 検証: `PYTHONPATH=src mypy sketch/presets/layout/common.py` でエラーが消えることを確認する

## 変更範囲

- 変更: `sketch/presets/layout/common.py`
- 追加: この plan ファイルのみ
