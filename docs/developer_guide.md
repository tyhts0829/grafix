<!--
どこで: `docs/developer_guide.md`。
何を: Grafix 開発者（人間/コーディングエージェント）向けの “読む順/入口” ガイド。
なぜ: `src/grafix/` の変更（実装改善・新機能追加）に入るまでの探索コストを下げるため。
-->

# Developer Guide（読む順と入口）

このドキュメントは「Grafix を改修したいとき、どこから読めばよいか」を最短で示す。

## まず読む（コンセプト）

1. `README.md`（使い方・API の雰囲気）
2. `architecture.md`（責務境界・依存方向・実行フロー）
3. `docs/glossary.md`（用語の対応表）

## 入口（コード）

### 公開 API（スケッチ作者が触る層）

- `src/grafix/__init__.py`（再エクスポート: `G/E/L/P/run/cc`）
- `src/grafix/api/__init__.py`（公開 API パッケージ）
- `src/grafix/api/primitives.py`（`G.*`）
- `src/grafix/api/effects.py`（`E.*`）
- `src/grafix/api/layers.py`（`L.*`）
- `src/grafix/api/presets.py` / `src/grafix/api/preset.py`（`P.*` / `@preset`）
- `src/grafix/api/runner.py`（`run(draw)` の interactive 実装）
- `src/grafix/api/export.py`（`Export(draw, t, fmt, path, ...)` の headless 導線）

### コア（変更の中心になる層）

- `src/grafix/core/geometry.py`（Geometry: レシピ DAG / 署名）
- `src/grafix/core/realize.py`（`realize(Geometry) -> RealizedGeometry` / cache / inflight）
- `src/grafix/core/realized_geometry.py`（配列表現と不変条件）
- `src/grafix/core/scene.py`（Scene 正規化）
- `src/grafix/core/pipeline.py`（interactive/export 共通の realize パイプライン）
- `src/grafix/core/primitive_registry.py` / `src/grafix/core/effect_registry.py`（登録・meta/defaults）
- `src/grafix/core/builtins.py`（組み込み op 登録の単一入口）
- `src/grafix/core/parameters/`（GUI/CC での param 解決と永続化。流れは `src/grafix/core/parameters/README.md`）

## 変更パターン別 “触る場所”

### primitive を追加/修正したい

- 実装: `src/grafix/core/primitives/*.py`
- 登録: `@primitive(...)`（`src/grafix/core/primitive_registry.py`）
- 組み込みとして常時有効化: `src/grafix/core/builtins.py` の `_BUILTIN_PRIMITIVE_MODULES` に追加

### effect を追加/修正したい

- 実装: `src/grafix/core/effects/*.py`
- 登録: `@effect(...)`（`src/grafix/core/effect_registry.py`）
- 組み込みとして常時有効化: `src/grafix/core/builtins.py` の `_BUILTIN_EFFECT_MODULES` に追加

### preset を追加/修正したい

- 実装と登録: `@preset(...)`（`src/grafix/api/preset.py`）
- 呼び出し: `P.<name>(...)`（`src/grafix/api/presets.py`）
- IDE 補完（スタブ）更新: `python -m grafix stub`

### Parameter GUI（param 解決/表示/永続）を触りたい

- コア（値解決・永続の核）: `src/grafix/core/parameters/`
- GUI 実装: `src/grafix/interactive/parameter_gui/`
- GUI 起動と連携: `src/grafix/interactive/runtime/parameter_gui_system.py` / `src/grafix/api/runner.py`

### Export（headless 出力）を触りたい

- 入口 API: `src/grafix/api/export.py`
- フォーマット別: `src/grafix/export/svg.py` / `src/grafix/export/image.py` / `src/grafix/export/gcode.py`
- 共通パイプライン: `src/grafix/core/pipeline.py`

## 関連ツール（CLI）

- `python -m grafix list`（組み込み effect/primitive の一覧）
- `python -m grafix stub`（`grafix.api` のスタブ再生成）
- `python -m grafix export --callable module:attr --t ...`（headless export。詳細は `python -m grafix export -- --help`）
- `python -m grafix benchmark -- --help`（ベンチ/レポート生成）

