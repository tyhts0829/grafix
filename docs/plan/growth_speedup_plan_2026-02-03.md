# 既存 effect: `E.growth(mask)` の高速化計画

作成日: 2026-02-03

対象:

- `src/grafix/core/effects/growth.py`

## 背景 / 現状

- `E.growth` は各 iteration ごとに、全頂点へ「マスク境界の SDF（距離＋外向き法線）」を評価して境界拘束を行っている。
- この SDF 評価は概ね **O(Npoints × Nedges(mask))** で、マスクの分割数が大きいほど支配的になる。

簡易計測（ローカル環境での目安）:

- mask 8192 辺、points 4000:
  - SDF 1 回: ~107ms
  - 反発＋スプリング（近傍グリッド）: ~3ms
- `seed_count=48, iters=300, target_spacing=1.2` で ~2.5s 程度（例）

## ゴール

- 体感で遅いケース（複雑マスク + iters 多め）を **まず 2x**、可能なら **2〜5x** 程度高速化する。
- `seed` による決定性（同一入力 + 同一 seed → 同一出力）を維持する。
- 依存追加なし（外部ライブラリ導入なし）。

## 非ゴール

- 出力の厳密一致（最適化で浮動小数誤差が変わるのは許容）。
- 高度に一般化された SDF ライブラリ化（この effect 内に閉じた最小実装を維持）。
- GUI 露出パラメータの増殖（必要なら最小限だけ）。

## 方針（段階的に、重いところから潰す）

### Phase 0: ベースライン計測を固定する

- 代表ケースを 2〜3 個固定して、変更ごとに時間と点数を記録する。
  - A: mask=polygon(512) / seed_count=24 / iters=300 / target_spacing=1.2
  - B: mask=polygon(8192) / seed_count=24 / iters=300 / target_spacing=1.2
  - C: mask=複数リング（穴あり）/ seed_count=24 / iters=300 / target_spacing=1.2
- 可能なら `tools/bench_growth.py` のような短いベンチスクリプトを追加して、毎回同じ条件で測る。

### Phase 1: SDF を並列化（最優先・効果大・実装小）

対象:

- `growth.py::_evaluate_sdf_points_numba`

やること:

- `@njit(parallel=True, fastmath=True, cache=True)` 化
- `for i in prange(n)` へ置換（点ごとに独立なので並列化適性が高い）
- ループ内の `float(...)` 変換や分岐を軽量化（可読性を崩さない範囲）

期待:

- マルチコア環境で素直に短縮（2〜数倍の上振れが見込める）

リスク/注意:

- `fastmath`/並列化で微小な差分が出る可能性 → テスト許容誤差で吸収（または fastmath を外して差分を小さくする）

### Phase 2: SDF 用のマスクを軽量化（辺数を直接削る）

狙い:

- SDF の O(Npoints × Nedges) の **Nedges** を落とす。

案:

- `mask` リングを弧長でリサンプルして、SDF 用にだけ軽量版を使う。
  - 例: `mask_step = max(target_spacing, 0.5)`（自動、API 追加なし）
  - 元の頂点数が多いときだけ有効化（例: `> 2048` のとき）
- 生成用途の effect なので、「マスクの微細ディテールが拘束に反映されない」ことは許容（ただし穴/内外判定は壊さない）。

検証:

- 同じ seed で “破綻しない” こと（外へ飛び出さない、崩れすぎない）
- ベンチで高速化が効くこと（特に複雑マスク）

### Phase 3: SDF 自体のアルゴリズムを短絡（必要なら）

Phase 1+2 で不足なら、SDF 計算コストの形を変える。

オプション A（精度より実装優先）:

- 距離場を 2D グリッドへ一度だけ評価し、各点は bilinear で参照（距離＋勾配）。
- 1 iter のコストを O(Npoints) へ寄せられる。
- 欠点: グリッドピッチ設計が必要（精度/速度のトレードオフが露骨）。

オプション B（精度維持寄り）:

- セグメントを空間ハッシュ（2D グリッド）でバケット化して、最近距離計算を「近傍セルの辺」だけに限定する。
- “距離” の計算は短絡できるが、inside parity の ray crossing も短絡が必要（ここが難所）。

採用条件:

- Phase 1+2 の後、`mask` が非常に複雑なケース（数万辺など）でまだ体感が悪い場合のみ。

### Phase 4: ループ内の割り当て削減（仕上げ）

狙い:

- `iters` が大きいとき、Python 側の flatten/scatter の確保が効いてくる可能性がある。

候補:

- `points/roff/forces/disp/d/g/out` の再利用（点数が変動するので “上限確保 + スライス運用” を検討）
- `_build_prev_next` の numba 化（Python ループを削る）
- 点追加（subdivide）頻度の調整（`subdivide_every` を固定値として内部に入れる、または自動化）

## テスト / 検証

- 既存: `tests/core/effects/test_growth.py` を維持（必要なら許容誤差を微調整）。
- 追加（任意）:
  - 速度ベンチの結果を `docs/plan/growth_speedup_plan_2026-02-03.md` にメモ（手動記録で OK）。
  - “複雑マスク” の代表入力を 1 つ `sketch/` に置いて、目視比較しやすくする（やりすぎない）。

## 実装手順（チェックリスト）

- [ ] Phase 0: ベンチ条件を固定（スクリプト or 手動手順を決める）
- [ ] Phase 1: `_evaluate_sdf_points_numba` を並列化し、ベンチで短縮を確認
- [ ] Phase 2: SDF 用マスクの軽量化を入れ、複雑マスクで短縮を確認
- [ ] Phase 3: まだ必要なら、SDF 短絡案（A/B）を比較して 1 つに決めて実装
- [ ] Phase 4: 割り当て削減（必要な場合のみ）
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_growth.py`

## 追加で確認したい（実装開始前に決める）

- Phase 2 の軽量化は **API を増やさず自動**にするか、`mask_step` のような **パラメータ追加**にするか
- “見た目の同等性” の許容幅（軽量化で境界追従が甘くなるのはどこまで OK か）
