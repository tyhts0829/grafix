# src_code_review_2026-1-14 妥当性確認と改善計画

対象レビュー: `docs/review/src_code_review_2026-1-14.md`  
確認日: 2026-01-14  

方針:
- 「指摘が事実としてコードに存在するか」と「改善する価値があるか」を分けて判断する。
- 妥当な指摘のみ、実装改善のチェックリスト（後でチェックを付けて進める）として残す。

## 妥当性確認（指摘ごと）

### 1) パラメータ処理の分散 / 関心事混在

判定: 妥当（事実として混在あり）

根拠（コード）:
- `src/grafix/core/pipeline.py:63` 以降で `current_param_store()` を参照し、Layer style の観測（records 追加）と GUI override 適用（`store.get_state(...).override`）まで実行している。
- 同様の label/param 解決が API 層にも分散している（例: `src/grafix/api/_param_resolution.py:1`, `src/grafix/api/layers.py:1`）。

コメント:
- parameter_gui と描画パイプラインを 1 本化する意図は明確だが、`realize_scene()` の見通しは落ちやすい構造になっている。

### 2) グローバル状態の多用（realize_cache / cc / runtime_config）

判定: 妥当（事実としてグローバル依存・無制限キャッシュあり）

根拠（コード）:
- `src/grafix/core/realize.py:30` で `RealizeCache` を定義し、`realize_cache = RealizeCache()` がグローバル。容量上限なしはコメントでも明記されている（`src/grafix/core/realize.py:35`）。
- `src/grafix/cc.py:25` で `cc[...]` は `current_cc_snapshot()` が無い場合 0.0 を返す（コンテキスト外でも静かに動く）。
- `src/grafix/core/runtime_config.py:29` で `_CONFIG_CACHE` がモジュールグローバル。

コメント:
- テスト容易性/複数インスタンス/長時間実行の予測可能性という観点では改善余地がある。

### 3) mp-draw の重複計算 + 複雑さ

判定: 一部妥当

根拠（コード）:
- `src/grafix/interactive/runtime/scene_runner.py:57` で worker の結果（layers）を受け取り、メイン側で `realize_scene()` を呼んでいる（`src/grafix/interactive/runtime/scene_runner.py:81`）。
- ただし worker は `normalize_scene()` までで、`realize()` は呼んでいない（`src/grafix/interactive/runtime/mp_draw.py:55`）。よって「Geometry 評価が worker と main で二重に走る」という懸念は現状は当たらない。

コメント:
- 「mp-draw は draw のオフロード」であり「realize の並列化」ではない。誤解しやすいので明文化したい。

### 4) API デザインの懸念（G/E/L の短名、EffectBuilder の registry 参照）

判定: 一部妥当（主に可読性/微小性能の観点）

根拠（コード）:
- `src/grafix/api/__init__.py:10` で `G/E/L` を公開している。
- `src/grafix/api/effects.py:80` で各ステップごとに `effect_registry.get_meta/get_defaults/get_n_inputs` を呼んでいる。

コメント:
- 名前は方針の問題（簡潔さと衝突/可読性のトレードオフ）。
- 性能は致命的ではないが、ステップ数が増えると不要な辞書コピー/参照が増える。

## 実装改善計画（チェックリスト）

### A. Layer style/Param 観測の集約（関心事分離）

- [ ] `src/grafix/core/parameters/layer_style.py` に「観測 + override 適用」を担う関数を追加する（例: `apply_layer_style_overrides(...)`）。
- [ ] `src/grafix/core/pipeline.py` から label 設定・records 生成・override 適用の直書きを削り、上記関数に委譲する。
- [ ] mp-draw（worker に store が無い）でも label/records が失われない責務分担を明記する（どこで label を確定させるか）。
- [ ] 最小の回帰テストを追加（Layer name と override が期待通り反映されること）。

### B. realize_cache の制御（長時間実行のメモリ肥大対策）

- [ ] `RealizeCache` に `clear()` を追加する。
- [ ] `RealizeCache` に上限（件数ベース）を追加する（`LRU` か `FIFO` を決める）。
- [ ] どこから操作するかを決める（例: `grafix.core.realize.clear_realize_cache()` を公開 / `runtime_config` で上限指定）。
- [ ] 上限動作のテストを追加（少数アイテムで eviction を確認）。

### C. runtime_config のグローバル依存を弱める（テスト/複数インスタンス）

- [ ] `runtime_config` の「キャッシュをどの粒度で持ちたいか」を決める（プロセス全体 / コンテキスト単位）。
- [ ] 最小案: `contextvars` で上書きできるコンテキスト API を追加し、テストや一時上書きを可能にする。
- [ ] 影響範囲（export/interactive/runner）を洗い出し、必要箇所だけ差し替える。

### D. mp-draw の理解しやすさ（複雑さの管理）

- [ ] `mp_draw` のドキュメントを追記（「worker は draw/normalize まで。realize は main」）。
- [ ] `SceneRunner.run()` の mp 経路にコメント or 小さなヘルパ関数を導入し、処理の 2 段（draw と realize）を分けて読めるようにする。
- [ ] （任意）デバッグ用の最小ログ/フックを追加（ワーカー例外、キュー詰まり等）。

### E. API（短名と EffectBuilder 最適化）

- [ ] `G/E/L` の扱い方針を決める（維持して README に推奨 import 形を明記 / 破壊的に改名）。
- [ ] `EffectBuilder.steps` に meta/defaults/n_inputs を保持する形へ変更し、`__call__` の registry 参照回数を減らす。
- [ ] （任意）`EffectNamespace/PrimitiveNamespace` の `__getattr__` 生成をキャッシュする（初回アクセスで `setattr`）。

## 事前確認が必要な決定（あなたに確認したい）

- [ ] realize_cache の上限ポリシー: `LRU` / `FIFO` / 上限なしで `clear()` のみ
- [ ] 上限値（件数）のデフォルト: 例 `0（無制限）` / `1000` / `10000`
- [ ] `runtime_config` の上書き方法: `contextvars` ベース（既存 API は維持）で良いか
- [ ] `G/E/L` を破壊的に変えるか（変えるなら新しい名前/導線）

