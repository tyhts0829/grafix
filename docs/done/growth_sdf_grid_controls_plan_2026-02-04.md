# `E.growth` の SDF グリッド制御（pitch 露出 + auto/manual）

作成日: 2026-02-04

対象:

- `src/grafix/core/effects/growth.py`
- `src/grafix/api/__init__.pyi`（stub）
- `tests/core/effects/test_growth.py`

## 目的

- SDF グリッドの「粗さ（ピッチ）」をパラメータとして露出し、意図的に精度を落として“グリッチ”を作れるようにする。
- 既定は従来通りの **自動**。必要なときだけ **手動**へ切り替える。

## 仕様案（API）

新規引数:

- `sdf_auto: bool = True`
  - True: ピッチは内部で自動決定（従来の挙動を維持）
  - False: `sdf_pitch` を採用
- `sdf_pitch: float = 2.0`
  - SDF 用のグリッドピッチ [mm]（大きいほど粗い/速い/グリッチ強い）

メモ:

- 「自動調整（大きすぎるグリッドを避けるための内部クランプ）」は安全のため維持する。
- `sdf_pitch` は **SDF 用**にのみ影響し、生成ロジック（反発など）のパラメータは増やさない。

## 実装方針

- `growth_meta` に `sdf_auto` / `sdf_pitch` を追加
- `ui_visible` を追加し、`sdf_auto=True` のとき `sdf_pitch` を隠す
- 既存の `step_sdf = max(target_spacing, 0.5)` を
  - auto: `step_sdf = max(target_spacing, 0.5)`
  - manual: `step_sdf = sdf_pitch`（不正値は auto にフォールバック）
  として扱い、
  - リング簡略化（SDF 用）
  - SDF グリッド構築（pitch_hint）
  の両方へ使う

## テスト

- 既存テストはデフォルトのまま通ること
- 追加:
  - `sdf_auto=False` + `sdf_pitch` 指定でもクラッシュせず non-empty
  - `sdf_auto=False` でも同一 seed で決定的

## 手順（チェックリスト）

- [ ] `growth_meta` に引数追加 + docstring 更新 + `ui_visible` 追加
- [ ] SDF ピッチ決定ロジックを `auto/manual` で分岐
- [ ] `PYTHONPATH=src python -m grafix stub`
- [ ] `tests/core/effects/test_growth.py` を更新
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_growth.py`

