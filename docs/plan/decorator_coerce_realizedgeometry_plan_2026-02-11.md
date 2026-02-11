# `@primitive` / `@effect` の tuple I/O 化（coords, offsets）実装計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 提案（未実装）

## 背景 / 問題

- 現状の `@primitive` / `@effect` は、ユーザーが書く関数の I/O に `RealizedGeometry(coords, offsets)`（core 内部型）を要求している。
  - その結果、スケッチ作者が `grafix.core.realized_geometry` を import して低レベル型に触れやすい。
- “スケッチ作者は RealizedGeometry を意識しない” という想定に対して、拡張ポイント（デコレータ）が内部型を露出している。

## 目的

- `@primitive` / `@effect` で登録するユーザー関数の I/O を、内部型ではなく **`(coords, offsets)` タプル**に統一する。
  - primitive: 戻り値が `(coords, offsets)`（coords は shape `(N,3)` のみ）
  - effect: 入力も出力も `(coords, offsets)`（入力は `n_inputs` に応じた positional 引数）
- core の評価パイプラインは維持し、registry に登録される wrapper は **必ず `RealizedGeometry` を返す**（既存の描画/export を壊さない）。

## 非目的

- 2D coords（shape `(N,2)`）を受理する（z=0 補完）はしない（この計画では `(N,3)` のみに限定）。
- polyline 列（`Sequence[np.ndarray]`）など “なんでも受ける” 変換は導入しない（仕様を小さく保つ）。
- 互換ラッパー/シムで旧シグネチャを温存しない（破壊的変更として整理する）。

## 方針（tuple I/O 契約）

### 1) ユーザー関数の契約（primitive/effect）

#### primitive

`@primitive` でデコレートされる関数は **`(coords, offsets)`** を返す。

- `coords`: `np.ndarray`（shape `(N,3)` のみ）
- `offsets`: `np.ndarray`（shape `(M+1,)`）

#### effect

`@effect(..., n_inputs=k)` でデコレートされる関数は、入力を **positional 引数**として受け取る。

- `n_inputs=1`: `f(g, *, ...) -> (coords, offsets)`
- `n_inputs=2`: `f(g1, g2, *, ...) -> (coords, offsets)`
- 一般に `n_inputs=k`: `f(g1, ..., gk, *, ...) -> (coords, offsets)`

ここで `g` / `g1..gk` はすべて `(coords, offsets)` タプル。

#### 共通（エラー/検証）

- デコレータ wrapper は、ユーザー関数の戻り値が `(coords, offsets)` であることを検証し、満たさない場合は例外にする。
- `coords` の shape は `(N,3)` のみを許可する（`(N,2)` はエラー）。
- offsets の整合（先頭 0 / 末尾 N / 単調非減少）は `RealizedGeometry` の検証に委譲しつつ、型/shape の入口チェックは wrapper 側でも最低限行う。

### 2) 実装の中心（どこで包むか）

- `src/grafix/core/primitive_registry.py` の `@primitive` wrapper で、`f(**params)` の戻り値 `(coords, offsets)` を `RealizedGeometry(coords, offsets)` で包む。
- `src/grafix/core/effect_registry.py` の `@effect` wrapper で、
  - `inputs: Sequence[RealizedGeometry]` を `[(coords, offsets), ...]` に変換し、`f(*inputs_as_tuples, **params)` を呼ぶ
  - 戻り値 `(coords, offsets)` を `RealizedGeometry(coords, offsets)` で包む

この変更により、**ユーザー I/O は tuple**、**core 内部は `RealizedGeometry`** に統一される。

## 実装タスク（チェックリスト）

### 0) 現状把握

- [ ] `realize()` が期待する型の流れを再確認する（`src/grafix/core/realize.py`）。
- [ ] export / GL で `coords/offsets` をどう使っているかを把握する（最低限 offsets の意味）。

### 1) 変換/検証 helper（最小）

- [ ] `src/grafix/core/realized_geometry.py` か registry 内に、`(coords, offsets)` を検証して `RealizedGeometry` 化する小さな関数を追加する。
  - `coords` shape `(N,3)` 以外はエラー
  - `offsets` は 1D を要求（細部の整合は `RealizedGeometry` に委譲）
- [ ] 失敗時の例外メッセージに「op 名」「関数名」「戻り値の型/shape」を含める。

### 2) デコレータ（registry）を tuple I/O 契約へ変更

- [ ] `src/grafix/core/primitive_registry.py` の wrapper を「戻り値 tuple -> `RealizedGeometry`」に変更する。
- [ ] `src/grafix/core/effect_registry.py` の wrapper を「`RealizedGeometry` inputs -> tuple inputs（positional）-> 戻り値 tuple -> `RealizedGeometry`」に変更する。
- [ ] `activate=False` の既存挙動は変更しない（primitive は empty、effect は passthrough/concat）。

### 3) built-in 実装の移行（破壊的変更）

- [ ] `src/grafix/core/primitives/*.py` を「戻り値 tuple」に置き換える（`RealizedGeometry` の直 import を除去）。
- [ ] `src/grafix/core/effects/*.py` を「入力/出力 tuple」に置き換える（`inputs: Sequence[RealizedGeometry]` を廃止）。
  - multi-input effect（例: `n_inputs=2`）は `f(g1, g2, *, ...)` へ変更する。

### 4) テスト更新（最小）

- [ ] `tests/core/effects/*` のテスト用 `@primitive` を tuple 戻り値へ更新する。
- [ ] effect のテストが新シグネチャで動くように更新する（入力/出力 tuple）。
- [ ] 代表ケースとして `(N,3)` coords のみを扱うテストを用意する（`(N,2)` は扱わない）。

### 5) ドキュメント更新

- [ ] `README.md` の Extending を tuple I/O の例に更新する（RealizedGeometry import 不要を明記）。
- [ ] `architecture.md` の “registry 契約” を tuple I/O 契約に更新する（core 内部は `RealizedGeometry` を維持）。
- [ ] `docs/glossary.md` の `@primitive/@effect` 説明を更新する。

### 6) 検証

- [ ] `PYTHONPATH=src pytest -q` の関連テストが通る。
- [ ] 既存 built-in effect/primitive の realize が壊れていない（最小スモークで良い）。

## 受け入れ条件（DoD）

- [ ] スケッチ作者が `RealizedGeometry` を import せずに `@primitive` / `@effect` を定義できる（I/O は `(coords, offsets)` タプルのみ）。
- [ ] `coords` は shape `(N,3)` のみを想定し、逸脱は明示的エラーになる。
- [ ] core の `realize()` / export / interactive の契約は維持される（内部は `RealizedGeometry` に統一）。
- [ ] エラー時は型/shape が分かる例外になる（黙って壊れない）。
