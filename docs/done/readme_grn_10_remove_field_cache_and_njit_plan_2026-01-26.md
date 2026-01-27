# sketch/readme/grn/10.py: field cache 無効化 + Numba(njit) 最適化

作成日: 2026-01-26

## 目的

- `sketch/readme/grn/10.py` の Gray-Scott 反応拡散 primitive から **field キャッシュ（V 場のメモ化）を一旦無効化**し、挙動/運用をシンプルにする（コードはコメントアウトで残す）
- キャッシュ削除で重くなる部分を補うため、**Numba の `@njit` でボトルネックを最適化**してインタラクティブ性を確保する

## 対象（変更するもの）

- `sketch/readme/grn/10.py`
  - `_FIELD_CACHE` と `_gray_scott_field_cached()` をコメントアウト（復旧しやすい形で残す）
  - Gray-Scott の時間発展ループを `@njit` 化（スケッチは `__main__`/動的 import になりやすく、`cache=True` は壊れやすいため使わない）
  - （必要なら）Marching Squares のセル走査部分も `@njit` 化（ただし計測して必要性を判断）

## 前提 / 背景メモ

- Grafix 本体には `Geometry.id -> RealizedGeometry` のキャッシュ（`grafix.core.realize.realize_cache`）があるため、**同じ引数の primitive は通常再計算されない**。
- ただし GUI で `level` や `min_points` 等を触ると `Geometry.id` が変わり、primitive が再実行されるため、field キャッシュを消すと反応拡散計算まで毎回走る。
- そこで **Gray-Scott 本体を Numba で高速化**して、キャッシュ無しでも耐える状態を狙う。

## Numba 適用候補（当たりを付ける）

### 1) Gray-Scott（最優先）

- 現状: `np.roll` を 1 ステップで多数呼ぶため、一時配列生成が多い
- 変更案: 周期境界の 9 点ラプラシアンを、`for j/i` の stencil ループで計算し、`u/v` を 2 バッファで更新（swap）
- 期待: メモリ確保が減り、ステップ数が多いと効きやすい

### 2) Marching Squares（次点）

- 現状: Python の二重ループでセル走査（`(nx-1)*(ny-1)`）
- 変更案: セル走査部分だけ `@njit` にして「線分 endpoints」を配列に詰めて返し、stitch（辞書/グラフ）は Python 側のまま
- 期待: contour モードの速度改善

### 3) thinning / skeleton trace（見送り寄り）

- Zhang-Suen は NumPy のブーリアン演算中心で、`np.pad` を多用（Numba 化のメリットが薄い/コードが複雑化しやすい）
- skeleton のトレースは set/dict を使うため Numba で扱いにくい

## 実装手順（チェックリスト）

- [x] `sketch/readme/grn/10.py` の field cache をコメントアウトし、`gray_scott_lines` は常に `_gray_scott_field(...)` を呼ぶ
- [x] Gray-Scott を「初期化（Python）」「時間発展（`@njit`）」に分割し、`@njit` の関数を追加
  - [x] 周期境界 + 9 点ラプラシアン + clamp(0..1)
  - [x] dtype は float32 を維持（速度/メモリ重視）
- [ ] （任意）Marching Squares のセル走査を `@njit` 化し、線分 endpoints を配列で返す（計測の結果、現状不要なので見送り）
- [x] `python -m py_compile sketch/readme/grn/10.py` で構文チェック
- [x] `PYTHONPATH=src python -c "import importlib.util; ...; draw(0.0)"` の軽いスモーク

## 注意点

- Numba は初回呼び出し時にコンパイルが走るため、**最初の 1 回だけ待ち時間**が出る（2 回目以降は速い）
- field キャッシュを消すので、GUI で `level` をガリガリ動かすと「毎回反応拡散」が走り、まだ重い可能性がある（その場合は defaults 調整や Marching Squares の `njit` 化を検討）
