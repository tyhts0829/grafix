<!--
どこで: `docs/review/agent_understandability_review_2026-02-02.md`。
何を: コーディングエージェント視点での「理解しやすさ」評価と改善案。
なぜ: `src/grafix/` の実装改善・新機能追加を素早く進めるためのボトルネックを明確化するため。
-->

# コーディングエージェント視点: 設計/ドキュメント理解しやすさレビュー（2026-02-02）

対象: 本リポジトリ全体（重点: `src/grafix/`）  
目的: コーディングエージェントが「実装改善・新機能追加」を行う際の理解コストを評価し、改善案を提案する。

## スコア（100点満点）

**83 / 100**

### 採点観点（内訳）

- 入口の明確さ（どこから読めばよいか）: 16/20
- コア概念の説明（Geometry/RealizedGeometry/Layer/ParamStore 等）: 18/20
- 依存境界・責務分離の読みやすさ: 17/20
- 変更時の安全網（テスト/型/ツール）: 16/20
- 探索性（builtins一覧、レジストリ、ディレクトリの見通し）: 16/20

## 良い点（すでに強い）

- `architecture.md` が「責務境界・依存方向・実行フロー」まで具体的で、初期理解が速い。
- `src/grafix/` の多くのファイルに「どこで/何を/なぜ」ヘッダがあり、探索が速い。
  - 簡易計測: `src/grafix` の `.py` 152 ファイル中、`どこで:` を含むファイルが 113（約 74%）。
- コアデータモデル（Geometry/RealizedGeometry/Layer）がコード上でも docstring/型で一貫しており、変更の影響範囲を追いやすい。
- 依存境界がテストで守られている（`tests/architecture/test_dependency_boundaries.py`）ため、リファクタ時の「やってはいけない依存」が明確。
- 動的 API（`G/E/P`）に対してスタブ生成/同期テストがあり、破壊的変更の検知ができる。
  - 例: `python -m grafix stub` / `tests/stubs/*`

## つまずきやすい点（エージェントが迷う箇所）

- ドキュメントの“正”が分散している。
  - `README.md` / `architecture.md` / `docs/review/*` / `docs/agent_docs/*` に情報があり、「最新の一次情報」がどれか判断コストが発生する。
- `core/parameters/` が細分化されており、初見での「どのファイルを読むべきか」コストが高い。
  - 例: `resolver.py` / `context.py` / `store.py` / `*_ops.py` の関係を掴むまでに回遊が必要。
- built-in op 登録は `grafix.core.builtins` に集約されているが、依然として「import で登録される」前提知識が必要。
  - `grafix.api.effects` / `grafix.api.primitives` を直接 import しないケースでは、registry が空に見える可能性がある。
- “公開 API として安定させたい範囲”が明文化されていない。
  - どこまでが破壊変更 OK か（外部スケッチ/外部ユーザーが触ってよいか）の判断が、その都度必要になる。

## 改善案（効果が高い順）

### A. すぐ効く（ドキュメント/探索性の改善、コード変更なし）

- [] `docs/` に「開発者向け入口」1 枚を追加し、読む順番を固定する。
  - 例: `docs/developer_guide.md`（または `docs/readme/developer.md`）
  - 内容案:
    - まず読む: `README.md` / `architecture.md`
    - 入口（コード）: `src/grafix/api/*` → `src/grafix/core/pipeline.py` → `src/grafix/core/realize.py`
    - 変更パターン別: primitive/effect/preset/Parameter GUI/Export
    - 関連ツール: `python -m grafix list|stub|export`

- [] `core/parameters` に “1 ファイルだけ読むならこれ” を明記したミニ README を置く。
  - 例: `src/grafix/core/parameters/README.md`
  - 内容案: `store.snapshot -> parameter_context -> resolve_params -> frame_params -> merge` の流れと主要ファイルへのリンク。
- [] 用語集（Glossary）を追加する。
  - `site_id`, `chain_id`, `ParamSnapshot`, `FrameParamsBuffer`, `explicit_args` 等を 1〜2 行で定義し、参照先（ファイル/関数）を併記する。
- [] `python -m grafix` のサブコマンド一覧を `README.md` に追記する。
  - 探索/生成の導線（list/stub/export）が初見でも見つかるようにする。

### B. 中期（設計の明確化。必要なら破壊的変更もあり）

- [] “公開 API 境界” を宣言する。
  - 例: `src/grafix/api/*` は public、`src/grafix/core/*` は internal（破壊変更の許容範囲も含める）。
- [] built-in 登録の入口をさらに統一する。
  - `ensure_builtin_ops_registered()` を「常にここから呼ぶ」方針に寄せ、interactive/devtools も含めた初期化の迷いを減らす。
- [] `core/parameters` の分割を「変更単位」ベースに再編する。
  - “読み物としての分割” になっている箇所を統合し、関連変更が 1〜2 ファイルで完結する構造へ寄せる。

## エージェント向け “読む順” 推奨（最短導線）

1. `README.md`（使い方と概念）
2. `architecture.md`（依存境界・実行フロー）
3. `src/grafix/api/*.py`（G/E/L/P/run の書き味層）
4. `src/grafix/core/geometry.py` / `src/grafix/core/realize.py` / `src/grafix/core/pipeline.py`
5. `src/grafix/core/parameters/context.py` / `src/grafix/core/parameters/resolver.py` / `src/grafix/core/parameters/store.py`
6. `tests/architecture/test_dependency_boundaries.py`（破ってはいけない依存の確認）

---

## まとめ

現状でも「コア概念 + 依存境界 + 実行フロー」が文章化されており、エージェントにとって理解しやすい部類。  
一方で、情報の分散と `core/parameters` の探索コストがスコアを押し下げている。  
上記 A の “入口 1 枚 + parameters ミニ README + 用語集” を足すだけで、理解の立ち上がりはさらに速くなる。
