# effect: pixelate の Numba 高速化 検討メモ/実装計画（2026-01-22）

目的: `src/grafix/core/effects/pixelate.py` の `pixelate` を Numba で高速化し、リアルタイムプレビュー時のフレーム落ちを減らす。

## 実装後の構成（要点）

対象: `src/grafix/core/effects/pixelate.py`

- 入力 `coords` を `step=(sx,sy,sz)` で割り、half away from zero で丸めて **整数格子** `(ix,iy,iz)` にスナップする（ここは NumPy ベクトル演算）。
- 1st pass: 各ポリライン（offsets 区間）ごとに `_pixelate_line_length(...)`（Numba）で出力頂点数を数え、`MAX_TOTAL_VERTICES` を超えない範囲だけ採用する。
- 2nd pass: `coords_out` / `offsets_out` を合計長で一発確保し、各ポリラインは `_pixelate_line_into(...)`（Numba）で `coords_out` の view に直接書き込む。

## Numba 高速化の余地（効果が見込める点）

ボトルネック候補:

1. `_pixelate_segment` の中身（Bresenham + 対角 2 手化 + 各ステップ書き込み）が **Python の for ループ**。
   - 出力点数は `ax+ay` に比例し、pixelate ではここが支配的になりやすい（テキスト/輪郭などで顕著）。
2. 各セグメントごとに Python から `_pixelate_segment` を呼ぶ呼び出し回数も増える（小さな `dx,dy` が大量にあるケースで効く）。
3. `np.concatenate` による **全頂点の追加コピー**（出力が大きいときにメモリ/時間を食う）。

結論: 少なくとも「1 ポリラインの階段化本体」を Numba 化すれば、かなりの改善が見込める（既存でも Numba 依存があるため導入障壁も低い）。

## 実装方針（案）

### 案 A（推奨）: 1ポリライン単位の Numba コアを追加

- `@njit(cache=True)` の `_pixelate_line_core(ix,iy,iz,sx,sy,sz,corner_mode) -> np.ndarray(float32)` を追加
  - 先に必要頂点数をループで数えて `out = np.empty((1+steps,3), float32)` を確保
  - その後、同じループ構造で `out` を埋める（中で `_pixelate_segment_core` を呼んでもよい）
- `pixelate(...)` 側は
  - いまの「量子化（grid 化）」は維持
  - 各ポリラインについて `_pixelate_line_core(...)` を呼んで `out_lines` に積む（挙動は現状維持）

メリット:

- セグメント走査 + ステップ生成が Numba に入り、Python の呼び出し回数が大きく減る
- 既存のテスト（`tests/core/effects/test_pixelate.py`）で挙動一致を担保しやすい

### 案 B（最小変更）: `_pixelate_segment` だけ `@njit` 化

- 差分は小さいが、セグメント数が多いケースでは Python 呼び出し回数が残るため、案 A より伸びにくい可能性がある。

### （必要なら）追加最適化: `np.concatenate` をやめて 2-pass で一発確保

`extrude` のように

1. 各ポリラインの出力頂点数を集計 → `coords_out` を合計長で確保
2. 各ポリラインの出力を `coords_out` の view に直接書き込む

にすると、巨大出力時のコピーとピークメモリを抑えられる。

## 0) 事前に決める（あなたの確認が必要）

- [x] 実装は **案 A（1ポリライン Numba コア）**で進めてよい？；はい
- [x] `np.concatenate` のコピー削減（2-pass 化）も同時にやる？（やるなら少し実装量↑、巨大ケースの効果↑）；はい
- [x] Numba デコレータは `@njit(cache=True)` のみでよい？（`fastmath=True` は今回は使わない想定）；はい

## 1) 受け入れ条件（完了の定義）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py` が通る（出力互換）
- [x] `corner="auto|xy|yx"` の差分が維持される（テスト固定）
- [ ] ざっくりベンチで改善が確認できる（例: 代表ケースで 2x 以上、理想は 5–20x）
  - ※初回は Numba JIT のコンパイル時間が入るので、計測は warm-up 後に実施

## 2) 変更箇所（ファイル単位）

- [x] `src/grafix/core/effects/pixelate.py`
  - [x] Numba コア関数追加（案A）
  - [x] `pixelate(...)` から Numba コアを利用
- [ ] （任意）ベンチ用の小さなスクリプト追加
  - 置き場所は `tools/` か `docs/` のどちらが良いか要相談

## 3) 実行コマンド（ローカル確認）

- [x] `PYTHONPATH=src pytest -q tests/core/effects/test_pixelate.py`
- [x] `ruff check src/grafix/core/effects/pixelate.py`
- [ ] （任意）ベンチ: warm-up → 計測（`time.perf_counter` / `timeit`）
