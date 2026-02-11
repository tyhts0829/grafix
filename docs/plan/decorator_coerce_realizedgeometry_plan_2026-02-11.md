# `@primitive` / `@effect` 戻り値の自動 RealizedGeometry 化（A案）実装計画（2026-02-11）

作成日: 2026-02-11  
ステータス: 提案（未実装）

## 背景 / 問題

- 現状の `@primitive` / `@effect` は、ユーザー関数の戻り値として `RealizedGeometry(coords, offsets)` を要求している。
  - その結果、スケッチ作者が `grafix.core.realized_geometry` を import して低レベル型に触れやすい。
- “スケッチ作者は RealizedGeometry を意識しない” という設計意図に対して、拡張ポイント（デコレータ）が内部型を露出している。

## 目的

- `@primitive` / `@effect` で登録するユーザー関数が **RealizedGeometry を直接返さなくても**よいようにする。
- ただし core の評価パイプラインは維持し、最終的に registry へ登録される関数は **必ず `RealizedGeometry` を返す**（既存の描画/export を壊さない）。

## 非目的

- effect の入力（`inputs`）を RealizedGeometry 以外に変える（= B案）はやらない。
- 既存 built-in primitive/effect の実装を総入れ替えする。
- 過度に一般化した “なんでも受ける” 変換（複雑な推論・静かに丸める等）を導入しない。

## 方針（A案）

### 1) 追加する仕様（戻り値の受理型）

デコレータでラップされる **ユーザー関数**の戻り値として、少なくとも次を受理する。

1. `RealizedGeometry`（そのまま採用）
2. `np.ndarray`（coords とみなす）
   - shape `(N,2)` または `(N,3)` を想定
   - offsets は `[0, N]`（単一 polyline）として補完
3. `(coords, offsets)` の 2 要素タプル（そのまま `RealizedGeometry(coords, offsets)` へ）
4. `Sequence[np.ndarray]`（polyline 列）
   - 各要素は shape `(Ni,2)` または `(Ni,3)` の coords
   - 連結して offsets を作る

エラー時は「受理型」と「実際の型/shape」を含む例外を投げ、静かに握りつぶさない。

### 2) 実装の中心

- `src/grafix/core/realized_geometry.py` に “戻り値を RealizedGeometry に正規化する” 小さな helper を追加する。
  - 例: `coerce_realized_geometry(value) -> RealizedGeometry`
  - ここで offsets の生成（polyline 列 → prefix-sum）を行う。
- `src/grafix/core/primitive_registry.py` の `@primitive` wrapper で `f(**params)` の戻り値に helper を適用する。
- `src/grafix/core/effect_registry.py` の `@effect` wrapper で `f(inputs, **params)` の戻り値に helper を適用する。

この変更により、registry が保持する実体関数の契約（`RealizedGeometry` を返す）は維持される。

## 実装タスク（チェックリスト）

### 0) 現状把握

- [ ] `realize()` が期待する型の流れを再確認する（`src/grafix/core/realize.py`）。
- [ ] export / GL で `coords/offsets` をどう使っているかを把握する（最低限 offsets の意味）。

### 1) helper 実装（戻り値の正規化）

- [ ] `src/grafix/core/realized_geometry.py` に `coerce_realized_geometry()` を追加する。
- [ ] 受理型（上記 1〜4）を `isinstance` で明確に分岐する。
- [ ] polyline 列の offsets 生成を最小実装で入れる（concat + cumsum）。
- [ ] 失敗時の例外メッセージを短く分かりやすくする（型/shape を含める）。

### 2) デコレータ側へ組み込み

- [ ] `src/grafix/core/primitive_registry.py` の wrapper で戻り値を `coerce_realized_geometry(...)` に通す。
- [ ] `src/grafix/core/effect_registry.py` の wrapper で戻り値を `coerce_realized_geometry(...)` に通す。
- [ ] `activate=False` の既存挙動は変更しない（primitive は empty、effect は passthrough/concat）。

### 3) テスト追加（最小）

- [ ] `tests/` に “戻り値 coercion” のテストを追加する。
  - primitive が `np.ndarray` を返しても `realize()` できる
  - primitive が `list[np.ndarray]` を返しても `realize()` できる
  - effect が `np.ndarray` / `list[np.ndarray]` / `(coords, offsets)` を返しても `realize()` できる
- [ ] 代表的な shape `(N,2)` / `(N,3)` を 1 ケースずつ入れる。

### 4) ドキュメント更新

- [ ] `README.md` の Extending に “返せる戻り値の形” を 1 つだけ具体例として追記する（RealizedGeometry import 不要を明記）。
- [ ] `architecture.md` の “registry 契約” の記述を「ユーザー関数の戻り値は RealizedGeometry-like を許容、登録後は RealizedGeometry」に更新する。

### 5) 検証

- [ ] `PYTHONPATH=src pytest -q` の関連テストが通る。
- [ ] 既存 built-in effect/primitive の realize が壊れていない（最小スモークで良い）。

## 受け入れ条件（DoD）

- [ ] スケッチ作者が `RealizedGeometry` を import せずに `@primitive` / `@effect` を定義できる（戻り値が ndarray 等でも動く）。
- [ ] core の `realize()` / export / interactive の契約は維持される（registry 内部は `RealizedGeometry` に統一される）。
- [ ] エラー時は型/shape が分かる例外になる（黙って壊れない）。

