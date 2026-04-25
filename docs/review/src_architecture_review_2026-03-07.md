# src/grafix アーキテクチャレビュー（2026-03-07）

対象:
- `src/grafix/` 全体

対象外:
- 個々の primitive / effect のアルゴリズムや画としての品質

実施した確認:
- 主要設計メモ確認: `README.md`, `architecture.md`
- 主要コード確認: `api/`, `core/`, `export/`, `interactive/`, `devtools/`
- 依存境界テスト実行: `PYTHONPATH=src pytest -q tests/architecture/test_dependency_boundaries.py`（4 passed）

## 総評

全体としては、`Geometry` の DAG、`realize` による遅延評価、`pipeline` による interactive/export 共通化、`core` と `interactive` の依存境界テストなど、骨格はかなり良いです。特に「レシピを組み立てる層」と「実体化する層」を分けている判断は、このリポジトリの強みです。

一方で、長期保守で効いてきそうな弱点ははっきりしていて、主に次の 6 点です。

## Findings

### 1. High: `site_id` が不安定で、永続化と GUI 識別が「reconcile 前提」になっている

根拠:
- `src/grafix/core/parameters/key.py:22-41`
- `src/grafix/core/parameters/reconcile_ops.py:16-55`
- `src/grafix/core/parameters/persistence.py:54-69`

`ParameterKey` の核である `site_id` が `absolute path + co_firstlineno + f_lasti` で生成されています。これはコード移動、軽微なラップ、Python 実装差分で揺れやすく、安定識別子として弱いです。その結果、`reconcile` が例外対応ではなく通常運用の補修機構になっています。

影響:
- GUI 調整値の持ち越しがコード編集に弱い
- マシン移動やパス変更で永続化が壊れやすい
- parameter 系の設計が「安定キー」ではなく「事後修復」に寄る

改善方向:
- `site_id` を bytecode offset と絶対パスから切り離す
- 少なくとも相対パス化する
- 理想は callsite に対する明示 stable key を持てるようにする

### 2. High: `realize_cache` がグローバルかつ無制限で、実行ライフサイクルに紐づいていない

根拠:
- `src/grafix/core/realize.py:30-57`
- `src/grafix/core/realize.py:100-145`

`realize_cache` はプロセスグローバルで、容量上限も世代管理もクリア戦略もありません。`GeometryId` が毎フレーム変わるスケッチでは、interactive 利用時間に比例してメモリが増え続ける構造です。

影響:
- 長時間セッションでのメモリ増加
- 「徐々に重くなる」系の不具合が起きやすい
- `run()` 単位、window 単位、scene 単位の寿命が設計に現れていない

改善方向:
- LRU か世代キャッシュにする
- 少なくとも run/session 単位でスコープを切る
- cache 戦略を `core` の明示的な責務として定義する

### 3. Medium: parameter system が snapshot ベースと live-read ベースに分裂している

根拠:
- `src/grafix/core/parameters/context.py:71-88`
- `src/grafix/core/parameters/style_resolver.py:55-83`
- `src/grafix/core/parameters/layer_style.py:141-179`
- `src/grafix/interactive/runtime/draw_window_system.py:425-451`

通常の primitive/effect 引数は `parameter_context()` で固定した snapshot から解決されますが、global style と layer style は `store.get_state()` をその場で読む live-read です。同じ parameter system の中に 2 つの時間モデルが共存しています。

影響:
- 「1 フレームの値は固定」という原則が style 系では崩れる
- mp-draw を含む非同期経路で、geometry と style の時間整合性が読みづらい
- parameter 周りの設計理解が難しくなる

改善方向:
- frame 開始時の immutable な parameter view を 1 つ作る
- style / layer style もその view から解決する

### 4. Medium: built-in と preset の初期化が暗黙 import とグローバル状態に依存している

根拠:
- `src/grafix/core/builtins.py:11-90`
- `src/grafix/api/primitives.py:10-16`
- `src/grafix/api/effects.py:11-16`
- `src/grafix/interactive/runtime/mp_draw.py:93-99`
- `src/grafix/api/presets.py:21-49`
- `src/grafix/api/runner.py:100-108`
- `src/grafix/devtools/generate_stub.py:668-683`

built-in op は import 副作用で登録され、preset は属性アクセスや runner 起動や stub 生成の途中で自動 import されます。動く経路は複数ありますが、初期化フェーズとしては明示化されていません。

影響:
- import 順と実行経路が正しさに入り込む
- devtools の結果がローカル設定や process state に依存しやすい
- 失敗時に「どこで何がロードされたか」を追いにくい

改善方向:
- built-in registration は明示 bootstrap に寄せる
- preset discovery も `load_presets(...)` のような明示フェーズに寄せる
- tooling は runtime import ではなく manifest 的な読み方へ寄せたい

### 5. Medium: `ParamStore` の不変条件が多数のモジュールへ漏れており、実質的に内部表現が public 化している

根拠:
- `src/grafix/core/parameters/store.py:18-26`
- `src/grafix/core/parameters/store.py:79-127`
- `src/grafix/core/parameters/codec.py:49-116`
- `src/grafix/core/parameters/codec.py:205-290`
- `src/grafix/core/parameters/merge_ops.py:24-106`
- `src/grafix/core/parameters/prune_ops.py:161-203`
- `src/grafix/core/parameters/reconcile_ops.py:67-121`
- `src/grafix/interactive/parameter_gui/store_bridge.py:391-449`

ドキュメント上は「Store はデータ」「書き込みは ops 経由」ですが、実際には codec / reconcile / prune / snapshot / GUI bridge が private ref や内部辞書へ直接触れています。設計意図は理解できますが、変更コストは既に高めです。

影響:
- `ParamStore` の内部表現変更が多点修正になる
- 不変条件の知識が散ってレビューしづらい
- parameter 系がモジュール数の多さ以上に密結合

改善方向:
- query / command の最小 API を用意して mutation surface を狭める
- 「内部表現に直接触ってよい層」をさらに限定する

### 6. Medium: `DrawWindowSystem` が runtime の副作用を抱え込みすぎている

根拠:
- `src/grafix/interactive/runtime/draw_window_system.py:128-214`
- `src/grafix/interactive/runtime/draw_window_system.py:215-357`
- `src/grafix/interactive/runtime/draw_window_system.py:388-552`

このクラス 1 つが window/GL、scene 実行、MIDI、録画、PNG 保存、G-code subprocess、キーハンドリング、perf、close 時の後始末まで持っています。`runner.py` は薄くなっていますが、責務は `DrawWindowSystem` に集中しただけです。

影響:
- runtime を部分的に差し替えるのが難しい
- テストしづらい
- 初期化失敗や teardown 不具合の切り分け点が粗い

改善方向:
- render host
- export / recording controller
- input / shortcut controller

このあたりを分離し、必要なものだけ遅延生成する形に寄せると伸びやすいです。

## 良い点

- `core` と `export` / `interactive` の依存境界をテストで守っている  
  根拠: `tests/architecture/test_dependency_boundaries.py`

- `Geometry` を DAG として表現し、`realize` と `pipeline` で評価を分離している  
  根拠: `src/grafix/core/geometry.py`, `src/grafix/core/realize.py`, `src/grafix/core/pipeline.py`

- 動的 API に対して stub 生成と同期テストを持っている  
  根拠: `src/grafix/devtools/generate_stub.py`, `src/grafix/api/__init__.pyi`, `tests/stubs/test_api_stub_sync.py`

## 優先順位の提案

まず着手するなら次の順がよいです。

1. `site_id` の安定化
2. `realize_cache` の寿命と容量戦略
3. parameter snapshot の一貫化
4. 初期化フェーズの明示化
5. `ParamStore` と interactive runtime の責務整理
