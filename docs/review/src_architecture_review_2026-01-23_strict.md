<!--
どこで: `docs/review/src_architecture_review_2026-01-23_strict.md`。
何を: `src/grafix/` 配下の全体設計（アーキテクチャ/保守性/エレガントさ）に対する厳しめコードレビュー結果。
なぜ: 構造的なボトルネックと将来の負債ポイントを早期に潰すため。
-->

# src 配下 アーキテクチャ/保守性コードレビュー（厳しめ, 2026-01-23）

対象: `src/grafix/`（`api/`, `core/`, `export/`, `interactive/`, `devtools/`, `resource/`）  
対象外: 個々の primitive/effect のアルゴリズム詳細・品質評価（個別実装レビューはしない）

---

## 結論（短く）

- レイヤ分離（`core`/`export`/`interactive`）はテストで守られており良いが、**「初期化（built-in 登録）」「グローバル状態」「外部依存（CLI/バイナリ）」**が要所で雑に残っていて、長期保守の足を引っ張る。
- “作品制作の体験” は強いが、パッケージとしては **「最小コアを軽く使う」ユースケースに最適化されていない**（依存/副作用/初期化責務が太い）。

---

## 重要度: 高（先に直したい）

### 1) built-in op 登録の初期化責務が分散（import 副作用 + 手動列挙）

- 影響
  - 追加/削除時に列挙漏れが起きやすい（「登録されてないから動かない」がランタイムで初めて露見）。
  - マルチプロセス/テスト/CLI で “念のため import” が増殖して、初期化順序がブラックボックス化する。
  - `api` が「初期化責務」を背負っており、層の純度が落ちる（`interactive` が `api` に依存する穴が開く）。
- 根拠（該当箇所）
  - `src/grafix/api/effects.py`（core/effects の手動 import 列挙）
  - `src/grafix/api/primitives.py`（core/primitives の手動 import 列挙）
  - `src/grafix/interactive/runtime/mp_draw.py`（worker で `grafix.api.*` を import して登録）
  - `src/grafix/devtools/list_builtins.py`（registry 初期化のために `grafix.api.*` を import）
  - `src/grafix/devtools/generate_stub.py`（スタブ生成のために registry 初期化 + import）
- 提案
  - **初期化の入口を 1 箇所へ集約**し、`api/interactive/devtools` はそこだけを呼ぶ形にする（import 副作用の拡散を止める）。
  - 列挙を維持するなら「単一リスト（単一モジュール）を参照する」形へ寄せ、重複列挙を禁止する。

### 2) `realize_cache` が無制限・グローバル（長時間実行でリークし得る）

- 影響
  - 時間依存/乱数/外部入力で GeometryId が毎フレーム変わると、キャッシュが効かないまま増え続ける。
  - interactive 利用が長いほどメモリが単調増加し得る（再現しづらい “徐々に重い” バグの温床）。
- 根拠
  - `src/grafix/core/realize.py`（容量上限・クリア戦略なしのグローバル cache + inflight）
- 提案
  - LRU/世代/上限制御のいずれかを入れ、**「効かないケースの安全弁」**を設計に組み込む。
  - 可能なら `SceneRunner` 等のライフサイクルに紐づけて、スコープを明確にする（グローバル固定をやめる）。

### 3) `site_id` が絶対パス + `f_lasti` に依存（永続化と共有に弱い）

- 影響
  - プロジェクト移動/別マシン/別ユーザーで ParamStore を持ち回るとキーが壊れる（GUI 永続が実質使えない）。
  - 小さな編集で `f_lasti` がズレて、キーが雪崩れる（古いキーの増殖、UI の “効かない” 感）。
- 根拠
  - `src/grafix/core/parameters/key.py`（`"{abs_filename}:{co_firstlineno}:{f_lasti}"`）
- 提案
  - `sketch_dir` 基準の相対パス化など、**環境差で揺れにくい表現**へ変更する。
  - さらに「ユーザーが安定キーを明示できる導線」を用意して、編集耐性の逃げ道を作る（特に作品制作では重要）。

### 4) 外部コマンド依存（`resvg`/`ffmpeg` 等）が “製品仕様” として未整理

- 影響
  - Python 依存は満たしているのに機能が動かない（環境差で壊れる）＝トラブルシュート負荷が高い。
  - CI/配布/README の整合が崩れやすい（実用段階で地味に効く）。
- 根拠
  - `src/grafix/export/image.py`（`resvg` を subprocess 実行）
  - `src/grafix/interactive/runtime/video_recorder.py`（`ffmpeg` を subprocess 実行）
- 提案
  - 「必須/任意」を明記し、起動時 or 機能呼び出し前に **“わかりやすい診断”**を出す（`grafix doctor` 的な導線でも良い）。
  - 依存を外部バイナリに寄せるなら、その設計を前提としてドキュメント/エラーメッセージ/設定を統一する。

### 5) 依存関係が all-in-one で、最小コア利用の障壁が高い

- 影響
  - “ヘッドレスだけ使いたい/コアだけ使いたい” ユースケースでも GUI/GL/MIDI 系が必須になり、導入が重くなる。
  - プラットフォーム差でのインストール失敗が増える（結果として利用可能者が減る）。
- 根拠
  - `pyproject.toml` の `project.dependencies`（`pyglet`, `moderngl`, `imgui`, `python-rtmidi` 等が base）
- 提案
  - 依存を **`core` と `interactive`/`midi`/`devtools` で extras 分割**し、必要な人だけ重い依存を入れる設計にする。

---

## 重要度: 中（やると効く）

### 1) `import grafix` の副作用/コストが太い（初期化責務と絡む）

- 影響
  - “軽い import” ができず、スクリプト/ツール側の起動コストが積み上がる。
  - 初期化順の暗黙依存がさらに増える（副作用が追いづらい）。
- 根拠
  - `src/grafix/__init__.py` → `src/grafix/api/__init__.py` → `src/grafix/api/effects.py` / `src/grafix/api/primitives.py`
- 提案
  - ルートパッケージは **可能な限り薄く**し、重いものは遅延 import（または明示初期化）へ寄せる。

### 2) 公開 API の形が “例外的” な箇所がある（`__init__` が実行副作用など）

- 影響
  - 利用側の直感とズレる API は、使い始めで事故りやすい＆ドキュメントが太る。
- 根拠
  - `src/grafix/api/export.py`（`Export.__init__` が書き込みまで実行）
- 提案
  - 実行はメソッドに寄せる/関数 API に寄せるなど、Python 的な期待に揃える。

### 3) “握りつぶし” 例外処理が散見され、壊れているのに静かに動く可能性

- 影響
  - ライブ系（GUI/MIDI/マルチプロセス）で、誤設定・不整合・バグの切り分けが難しくなる。
- 根拠（例）
  - `src/grafix/cc.py`
  - `src/grafix/api/runner.py`（ウィンドウ activate の例外黙殺 など）
- 提案
  - 期待する例外だけ捕捉し、それ以外は落とす/ログに残す（“静かに壊す” を減らす）。

### 4) `core/parameters` が過分割気味で、認知負荷が高い

- 影響
  - 改修時に “どこに何があるか” の探索コストが高く、作業が遅くなる。
  - 小さな仕様変更でも触るファイルが増えてレビュー/テストが重くなる。
- 根拠
  - `src/grafix/core/parameters/`（`*_ops.py` が多数）
- 提案
  - 「読み物としての分割」になっている部分は統合し、**変更単位に沿ったモジュール境界**へ再配置する。

### 5) 型安全の投資が “最後の一歩” で止まっている

- 影響
  - `py.typed` / stub 生成までやっているのに、mypy 設定側で効果が薄くなる。
- 根拠
  - `pyproject.toml`（`[tool.mypy] ignore_missing_imports = true`）
- 提案
  - “全面 ignore” ではなく、影響範囲が大きい所だけ段階的に締める（最低限、内部コアの型は守る）。

---

## 重要度: 低（気持ち悪さの整理）

- API の “namespace + pending label” パターン（`G/E/L/P`）に類似コードが多く、改善余地はある（ただし抽象化しすぎると読みにくくなるので注意）。
  - 根拠: `src/grafix/api/effects.py`, `src/grafix/api/primitives.py`, `src/grafix/api/layers.py`, `src/grafix/api/presets.py`
- `runtime_config` がモジュールグローバルキャッシュで、テスト/マルチスレッドで扱いづらい（現状でも運用は可能だが設計の不透明さが残る）。
  - 根拠: `src/grafix/core/runtime_config.py`
- “拡張ポイント” の公開範囲（registry/decorator の公開）が将来の破壊的変更を難しくし得る（どこまで public とするかの線引きが必要）。
  - 根拠: `src/grafix/api/__init__.py`

---

## 良い点（残すべき）

- 依存境界がテストで守られている（少なくとも `core` → `interactive/export` の逆流が防げている）。
  - 根拠: `tests/architecture/test_dependency_boundaries.py`
- `core/parameters` は「永続ストア本体」と「ops」を分けようとしており、方向性は良い（God-object 化を抑えている）。
  - 根拠: `src/grafix/core/parameters/store.py` 周辺
- 動的 API（`G/E/P`）に対して stub 生成と同期テストを持っているのは堅い（IDE 体験と破壊検知が両立）。
  - 根拠: `src/grafix/devtools/generate_stub.py`, `src/grafix/api/__init__.pyi`, `tests/stubs/test_api_stub_sync.py`

