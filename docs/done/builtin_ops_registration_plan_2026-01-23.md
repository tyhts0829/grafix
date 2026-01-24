# built-in op 登録初期化の集約プラン（2026-01-23）

目的: built-in の primitive/effect の登録（registry 初期化）を **単一の入口**に集約し、import 副作用と手動列挙の分散を解消する。

背景（現状の痛み）:

- `api/effects.py` / `api/primitives.py` が built-in 実装モジュールを手動列挙 import して登録している。
- その結果、`interactive/runtime/mp_draw.py` や `devtools/list_builtins.py` などが「念のため `grafix.api.*` を import」する構造になっている。
- 追加/削除時に列挙漏れしやすく、初期化順序が追いづらい。

非目的:

- 個々の primitive/effect の中身の改善
- 公開 API の形（`G/E/L/P`）の再設計（必要なら別チケット）

---

## 0) 事前に決める（あなたの確認が必要）

- [x] 方式: **A**
  - [x] A: 「明示リストを 1 箇所に集約」する（最小変更・挙動が読みやすい）
  - [ ] B: `pkgutil` / `importlib` で `grafix.core.effects` / `primitives` を自動探索して import（列挙不要だが、意図しない import/起動コスト増のリスク）
- [x] 初期化タイミング: **A**
  - [x] A: `grafix.api.effects` / `grafix.api.primitives` import 時に確実に登録（現状互換）
  - [ ] B: `G.<name>` / `E.<name>` の初回アクセスで遅延登録（`import grafix` を軽くできるが、テスト/CLI の前提が変わる）
  - [ ] C: 利用側が明示的に `ensure_*()` を呼ぶ（最も純粋だが利用負担が増える）

---

## 1) 受け入れ条件（完了の定義）

- [x] built-in 登録の入口が **1 箇所**（単一関数）に集約されている
- [x] built-in の列挙（採用方式Aの場合）が **1 箇所**だけに存在し、重複リストが無い
- [x] `interactive/runtime/mp_draw.py` が built-in 登録のために `grafix.api.*` を import しない
- [x] `python -m grafix list` / `python -m grafix stub` が「registry 初期化のための `grafix.api.*` import」に依存しない（依存するなら、依存先が単一入口に置き換わっている）
- [ ] `PYTHONPATH=src pytest -q` が通る（この環境では `tests/tools/test_cache_visualize.py` が `tools` import で collection error）

---

## 2) 設計案（推奨: 方式A + タイミングA）

### 2.1 新規モジュール（単一入口）

- [x] `src/grafix/core/builtins.py`（新規）を追加
  - `ensure_builtin_primitives_registered()`
  - `ensure_builtin_effects_registered()`
  - `ensure_builtin_ops_registered()`（↑2つを呼ぶ）
  - 実装は `importlib.import_module()` + “一度だけ実行” のフラグで idempotent にする
  - built-in の列挙はこのファイル（または同ディレクトリの 1 ファイル）にのみ置く

### 2.2 呼び出し箇所の置換（分散初期化の撤去）

- [x] `src/grafix/api/primitives.py`
  - built-in 手動 import 列挙を削除
  - `ensure_builtin_primitives_registered()` を呼ぶ（タイミングは 0) の選択に従う）
- [x] `src/grafix/api/effects.py`
  - built-in 手動 import 列挙を削除
  - `ensure_builtin_effects_registered()` を呼ぶ（タイミングは 0) の選択に従う）
- [x] `src/grafix/interactive/runtime/mp_draw.py`
  - worker 起動時の `import grafix.api.effects/primitives` を削除
  - 代わりに `ensure_builtin_ops_registered()` を呼ぶ（層の穴を塞ぐ）
- [x] `src/grafix/devtools/list_builtins.py`
  - `importlib.import_module("grafix.api.*")` を削除
  - 代わりに `ensure_builtin_ops_registered()` を呼ぶ
- [x] `src/grafix/devtools/generate_stub.py`
  - registry 集計の前に `ensure_builtin_ops_registered()` を呼ぶ（遅延初期化に寄せる場合でも安定化）

---

## 3) 影響範囲の整理（壊れ方と対策）

- 想定される壊れ方
  - [ ] “import しただけで built-in が登録されている” 前提の箇所があると、遅延初期化（0-B）で壊れる
  - [ ] 初期化関数が循環 import を踏むと、起動時に落ちる
- 対策
  - [ ] まずは 0-A（import 時）で実装して挙動を維持し、次に 0-B（遅延）を検討する（二段階）
  - [ ] `core/builtins.py` は `core` 内だけを import し、`api/export/interactive` は絶対に参照しない（依存境界を崩さない）

---

## 4) 実装タスクリスト（着手順）

### Phase 1（集約して分散を潰す / 互換維持）

- [x] `src/grafix/core/builtins.py` を追加（単一入口 + 単一リスト）
- [x] `api/effects.py` / `api/primitives.py` の built-in 列挙 import を撤去し、単一入口を呼ぶ
- [x] `interactive/runtime/mp_draw.py` を単一入口呼び出しへ置換
- [x] `devtools/list_builtins.py` を単一入口呼び出しへ置換
- [x] `devtools/generate_stub.py` を単一入口呼び出しへ置換

### Phase 2（任意: import を軽くする / 遅延初期化へ）

- [ ] `G/E` の `__getattr__` で必要時に `ensure_*()` を呼ぶようにし、トップレベル import 時の登録を削る
- [ ] それに伴うテスト前提の見直し（必要なら `tests/core/test_effect_bypass.py` 等を調整）

---

## 5) 確認コマンド（ローカル）

- [x] `PYTHONPATH=src pytest -q tests/architecture/test_dependency_boundaries.py`
- [x] `PYTHONPATH=src pytest -q tests/core/test_effect_bypass.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
- [x] `PYTHONPATH=src python -m grafix list all`
- [ ] `PYTHONPATH=src python -m grafix stub`

---

## 6) メモ（実装時の方針）

- 互換ラッパー/シムは作らず、必要なら破壊的に整理する（ただし Phase 1 は挙動維持が目的）。
- built-in の “正” は `core/builtins.py` に置き、他の場所に列挙を増やさない。
