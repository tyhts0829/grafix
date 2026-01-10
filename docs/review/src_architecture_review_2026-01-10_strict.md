<!--
どこで: `docs/review/src_architecture_review_2026-01-10_strict.md`。
何を: `src/grafix/` 配下モジュール群の俯瞰アーキテクチャに対する厳しめコードレビュー結果を整理する。
なぜ: 構造的な負債/境界の弱さを早期に特定し、次の改善テーマを選びやすくするため。
-->

# src 配下モジュール 俯瞰アーキテクチャ・コードレビュー（厳しめ, 2026-01-10）

対象: `src/grafix/`（`api/`, `core/`, `export/`, `interactive/`, `devtools/`, `resource/`）  
対象外: 個々の effect / primitive のアルゴリズム詳細（実装内容の良し悪し）、個別パラメータ設計の妥当性

---

## TL;DR（結論）

良い芯:

- **レイヤ分離（`core` / `api` / `interactive` / `export`）は概ね成立**している。`core` が `interactive` を参照しない依存方向は健全。
- **Geometry=レシピ（DAG）→ realize（配列）**という中核設計は強い（`core/geometry.py`, `core/realize.py`）。
- **parameters サブシステムは設計が文章化され、レイヤ（data/pure/ops/control）が明確**（`core/parameters/architecture.md`）。

厳しめ指摘（優先度順）:

- **[高] 「組み込み op 登録」が import 副作用 + 手動列挙に依存**しており、構造として脆い（`api/effects.py`, `api/primitives.py`, `interactive/runtime/mp_draw.py`, `devtools/list_builtins.py`）。
- **[高] `realize_cache` が無制限・グローバル**で、時間依存の生成（アニメ/ノイズ等）でメモリが単調増加し得る（`core/realize.py`）。
- **[高] `site_id` が “絶対パス + f_lasti” で、永続化/共有に弱い**（移動/編集/環境差でキーが大きく揺れる）（`core/parameters/key.py`）。
- **[中] 公開 API の import コスト/副作用が重い**（`import grafix` が `api` を通じて built-in 群を引き込む）（`grafix/__init__.py`, `api/__init__.py`）。
- **[中] `Export` がコンストラクタで書き込み副作用を持つ**のは API として不自然（`api/export.py`）。
- **[中] “過剰に握りつぶす” 例外処理が散見**され、壊れているのに静かに動く系のバグを招きやすい（例: `grafix/cc.py`）。

---

## 1) パッケージ構造/依存方向のレビュー

依存方向（概観）は良い:

- `core` はドメイン核（Geometry/realize/registry/parameters）で、`interactive` や `export` を参照しない。
- `export` は `core` に依存し、`interactive` には依存しない（ヘッドレス境界が守られている）。
- `interactive` は `core` と `export` に依存し、UI/GL/MIDI/プロセス制御を担当。

ただし境界の “穴” がある:

- `interactive/runtime/mp_draw.py` が **built-in op 登録のために `grafix.api.*` を import**している。
  - これは “動く” が、**「API 層が初期化責務を背負っている」**ことの表れで、レイヤの純度を落としている。

---

## 2) 初期化（built-in 登録）: import 副作用依存が構造的に脆い（高）

現状:

- `api/effects.py` が `core/effects/*` を **手で列挙 import**して `effect_registry` を初期化する。
- `api/primitives.py` が同様に `core/primitives/*` を列挙 import して `primitive_registry` を初期化する。
- その結果、`mp_draw` や `devtools/list_builtins.py` は「念のため public API 起点で import」している。

問題:

- **初期化の真の入口が分散**し、「どこを import すると何が登録されるか」が追いにくい。
- 追加/削除時に **列挙漏れが起きる構造**（静的解析・テストで検知しづらい）。
- マルチプロセス/テストで「登録されている前提」が崩れやすく、結果として “念のため import” が増える。

提案（設計変更案）:

- built-in 登録の責務を `core` 側へ集約し、**明示関数**にする（例: `grafix.core.builtins.register_all()`）。
  - `api/*`, `interactive/*`, `devtools/*` はその関数を呼ぶだけにして、import 副作用を減らす。
- さらに進めるなら、built-in 群は “列挙” ではなく、規約に基づく **自動探索**（`pkgutil` / `importlib`）で register する。
  - ただし探索は起動コスト/デバッグ容易性とのトレードオフなので、用途（開発時のみ、など）を決めて導入したい。

---

## 3) `realize_cache` の無制限グローバルは危険（高）

現状:

- `core/realize.py` の `realize_cache` は容量上限無し・クリア戦略無し。
- `GeometryId` は内容署名なので、`t`（時間）や乱数、外部入力により **毎フレーム異なる DAG**を作ると、キャッシュは “効かないのに増え続ける”。

問題:

- interactive で長時間動かすと、**メモリ使用量が単調増加**し得る（特にアニメ系）。
- 「キャッシュが効く」前提の設計は強いが、効かないケースを想定した**安全弁が無い**。

提案（設計変更案）:

- `RealizeCache` を LRU/サイズ上限/世代（フレーム境界での sweep）などで制御する。
- もしくは「時間依存ノードはキャッシュしない」仕組み（op/引数で no-cache を宣言）を用意する。

---

## 4) `site_id` が永続化/共有に弱い（高）

現状:

- `core/parameters/key.py` の `site_id` は `"{abs_filename}:{co_firstlineno}:{f_lasti}"`。

問題:

- **絶対パス**が混ざるため、プロジェクト移動・別マシン・別ユーザーで **ParamStore を共有しにくい**。
- `f_lasti` は実装依存で揺れやすく、ちょっとした編集で **キーが大きく変わり得る**。
  - 「GUI 永続が突然効かなくなる」「古いキーが増殖する」といった UX を招きやすい。

提案（設計変更案）:

- 少なくとも **`sketch_dir` からの相対パス**を使う（`runtime_config.sketch_dir` を基準にする）。
- さらに安定性を上げるなら「ユーザーが key を明示できる」導線（`G(key="...")` / `E(..., key="...")` 的な）を用意する。
  - 既に preset には `key` があるので、primitive/effect 側にも同系統の逃げ道が欲しい。

---

## 5) 公開 API の形状: import と副作用の設計が粗い（中）

良い点:

- `api/__init__.py:run()` が遅延 import で GUI 依存を後回しにしているのは良い。
- `G/E/L/P` で “書き味” を整えたファサード設計自体は読みやすい。
- `__init__.pyi` を持ち、動的属性（`__getattr__`）に対して型情報を補完しようとしているのは筋が良い。

厳しめ指摘:

- `grafix/__init__.py` が `from grafix.api import ...` を行うため、`import grafix` が “軽い import” になっていない。
  - ここで `api/effects.py` / `api/primitives.py` が import されると、built-in 群の import が走る（起動コスト/副作用の面で重い）。
- `effect` / `primitive` デコレータが `core` からそのまま公開されており、op 名が関数名に直結する。
  - 衝突（同名 effect/primitive）や overwrite の挙動が、将来的に “地雷” になりやすい。

---

## 6) `Export` の API: コンストラクタ副作用は避けたい（中）

現状:

- `api/export.py:Export.__init__()` が export 実行（ファイル書き込み）まで行う。

問題:

- Python の一般的な期待（`__init__` は初期化で、副作用実行はメソッド呼び出し）とズレる。
- 将来的に引数が増える/失敗モードが増えるほど、例外処理と利用側の見通しが悪くなる。

提案（設計変更案）:

- `export_svg(draw, ...)` のような関数 API に寄せるか、`Export(...).save()` のように実行を分ける。

---

## 7) 例外処理の握りつぶしが多い箇所がある（中）

例:

- `grafix/cc.py:CcView` は広い `except Exception` が多く、入力ミスと実装バグを区別しにくい。

問題:

- “壊れているのに静かに動く” 系のバグは、特にライブ系（MIDI/GUI）でデバッグを困難にする。

提案（設計変更案）:

- 期待する異常（型/範囲）だけ捕捉し、それ以外は例外で落とすかログに残す。

---

## 8) ドキュメント整合性（小〜中）

良い点:

- `architecture.md` と `core/parameters/architecture.md` があり、設計意図が追えるのは強い。

気になる点:

- `api/export.py` の docstring に「当面はスタブ」等の表現が残っており、現状実装とズレて見える。
  - こういう “小さなズレ” が積み重なると、設計の信頼性が落ちる。

---

## 付録: 参照した主なファイル

- レイヤ/初期化: `src/grafix/__init__.py`, `src/grafix/api/__init__.py`, `src/grafix/api/effects.py`, `src/grafix/api/primitives.py`
- registry/realize: `src/grafix/core/effect_registry.py`, `src/grafix/core/primitive_registry.py`, `src/grafix/core/realize.py`
- pipeline/scene: `src/grafix/core/pipeline.py`, `src/grafix/core/scene.py`, `src/grafix/core/layer.py`
- parameters: `src/grafix/core/parameters/architecture.md`, `src/grafix/core/parameters/context.py`, `src/grafix/core/parameters/key.py`
- interactive: `src/grafix/interactive/runtime/window_loop.py`, `src/grafix/interactive/runtime/mp_draw.py`
- export: `src/grafix/api/export.py`, `src/grafix/export/svg.py`, `src/grafix/export/image.py`
