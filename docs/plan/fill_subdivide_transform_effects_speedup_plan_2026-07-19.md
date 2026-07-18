# fill / subdivide / scale / rotate / translate 高速化計画・実績

- 作成日: 2026-07-19
- 基準 commit: `9ffdf60`
- 状態: 完了
- 対象:
  - `src/grafix/core/effects/fill.py`
  - `src/grafix/core/effects/subdivide.py`
  - `src/grafix/core/effects/scale.py`
  - `src/grafix/core/effects/rotate.py`
  - `src/grafix/core/effects/translate.py`

## 1. 目的と維持する契約

対象 5 effect の実作業を高速化する。ただし速度より既存挙動の維持を優先し、
次の契約を変更しない。

- canonical geometry の `coords=float32`、`offsets=int32`
- 入力配列を変更しない
- 座標だけを変える effect は入力 `offsets` object を共有する
- empty / identity / invalid mode 等の no-op は既存の object identity を維持する
- 頂点順、polyline 順、offsets、診断内容、例外種別、浮動小数点通知、評価順を維持する
- 公開 signature、default、ParamMeta、UI visibility、cache policy を変更しない
- 互換 wrapper / shim と新規依存を追加しない

## 2. 変更前調査

### 2.1 テスト

変更前の対象 effect テストは `41 passed`。

### 2.2 ボトルネック

- `fill`: scanline ごとに全 edge の mask、交点配列、sort を作っていた。
- `subdivide`: polyline ごとの Python/Numba 呼び出し、count と生成の重複走査、
  level ごとの再確保があった。
- `scale`: `all` の複数中間配列と、`by_line` / `by_face` の polyline 単位
  Python loop が支配していた。
- `rotate`: float64 変換・中心計算・座標中間配列が重複していた。
- `translate`: 3 要素 broadcast 加算の一時配列と固定費が大きかった。

### 2.3 正しさと性能の採用条件

- 変更前参照実装との `coords` / `offsets` の bitwise 一致を基本条件とする。
- input 不変、offsets identity、no-op identity、diagnostic、例外と評価順を維持する。
- 非 canonical 入力、非有限値、浮動小数点通知が変わり得る入力は従来経路へ戻す。
- actual-work の median / p95 と exact checksum を同一 benchmark contract で比較する。
- warm 性能だけでなく process-cold、compile-cold、peak RSS も確認する。

## 3. 実装実績

### Phase 0: benchmark と参照挙動

- [x] 50k 頂点、5k 短線、512 ring、dense fill の actual-work fixture を追加した。
- [x] scale の `all` / `by_line` / `by_face`、subdivide の actual-work / guard、
      translate の small / long / many-lines、rotate の auto / fixed-pivot を分離した。
- [x] seed、規模、parameter、case source を固定した。
- [x] effect 実装変更前の `warm / long / disable-gc` baseline を保存した。
- [x] 変更前実装と同じ演算順の test-only reference を追加した。
- [x] 基準 commit の effect module を一時 source treeへ戻し、cold baseline も測定した。

### Phase 1: translate

- [x] small/non-canonical/IEEE 通知が危険な入力では従来 broadcast を維持した。
- [x] 通常の large canonical 入力は 1 回だけ copy し、3 軸を scalar 加算した。
- [x] 0 軸も加算し、従来の `-0.0` 正規化と sNaN quieting を bitwise に維持した。
- [x] NaN、Inf、overflow、subnormal、F-order、strided、readonly、subclass を確認した。
- [ ] 「非ゼロ軸だけ加算」は不採用。0 軸を省くと signed zero が変わるため。

### Phase 2: rotate / scale

#### rotate

- [x] degree、`Rz @ Ry @ Rx`、X→Y→Z、従来の BLAS 積方向を維持した。
- [x] auto-center は従来の C-order float64 mean をそのまま維持した。
- [x] 1,024 頂点以上の安全な通常範囲では、従来の積方向を変えずに
      F-order float64 working buffer を使った。
- [x] 安全な通常範囲だけ add と float32 cast を 1 pass にした。
- [x] subclass、非 canonical、非有限値、underflow 通知が必要な入力は従来経路へ戻した。
- [x] pivot / rotation の左から右への評価順、malformed parameter の評価省略を維持した。
- [ ] `(rot @ shifted.T).T` は不採用。妥当な float32 入力で 1 ULP 差が出たため。

#### scale

- [x] `mode="all"` の float64 working buffer を再利用した。
- [x] `by_line` / `by_face` の閉判定、中心、変換を canonical 入力で bulk 化した。
- [x] XYZ、`rtol=0`、`atol=1e-6`、`equal_nan=False`、face 中心の末尾除外を維持した。
- [x] line metadata と vertex gather を 8,192 本単位へ chunk 化した。
- [x] small/non-canonical/subclass/IEEE 通知が危険な入力は従来 loop へ戻した。
- [x] 8,191 / 8,192 / 8,193 / 16,385 本の chunk 境界を bitwise 比較した。

### Phase 3: subdivide

- [x] 全 polyline の解析 count / effective level を 1 回の Numba 呼び出しへまとめた。
- [x] vertex cap 内の共通 `selected_divisions` を従来どおり決定した。
- [x] capacity を 1 回だけ確保し、単一 batch kernel で後ろ向きに midpoint 展開した。
- [x] actual count による前方 compaction と diagnostic level mask を実装した。
- [x] `MAX_TOTAL_VERTICES` monkeypatch、停止境界、cap 境界、複数 line を維持した。
- [x] 非 canonical、非有限値、overflow / underflow 通知が必要な入力は従来経路へ戻した。

### Phase 4: fill

- [x] `PlanarFrame`、even-odd grouping、fallback、boundary packing 順を変更しなかった。
- [x] `fastmath=False` の Numba 2-pass scanline kernel で exact allocation した。
- [x] 半開交差、水平 edge 除外、pair 順、退化 segment 除外を維持した。
- [x] signed zero の sort 順を NumPy と一致させた。
- [x] NaN pair 幅でも pass 1/2 の採用条件を同一にし、配列外書込みを防いだ。
- [x] overflow / underflow / 非有限値があり得る場合は従来 NumPy loop へ戻した。
- [ ] active-edge algorithm は不採用。2-pass だけで warm 目標を満たしたため。

### Phase 5: 回帰テスト

- [x] input 不変、dtype / shape / layout、offsets identity、no-op identity を確認した。
- [x] C/F contiguous、strided、readonly、ndarray subclass を確認した。
- [x] 固定 seed `20260719` の differential test と境界値 test を追加した。
- [x] signed zero、sNaN、NaN/Inf、subnormal、overflow/underflow 通知を確認した。
- [x] diagnostic、closure tolerance、chunk/cap/停止境界を exact 比較した。

### Phase 6: 検証と採否

- [x] Phase 6 対象一式: `111 passed`
- [x] full pytest: `1686 passed`
- [x] Ruff: 成功
- [x] Mypy: 成功
- [x] `git diff --check`: 成功
- [x] 同一 case set の before / after を取得した。
- [x] `benchmark compare` の environment compatibility、checksum、contract を確認した。
- [x] same-process の interleaved A/B と固定回数測定で order drift を確認した。
- [ ] runner による厳密な A→B→A→B の 4 run は未実施。同一 process の交互測定と
      30-sample formal run、p95、MAD の併用で代替した。

## 4. 最終 warm benchmark

環境互換性あり、warning なし。全 14 case で exact checksum、
hard/soft contract、status が一致した。

| case | before median | after median | speedup |
| --- | ---: | ---: | ---: |
| `fill.dense.rings_2` | 67.808 ms | 33.606 ms | 2.02x |
| `fill.many_rings` | 31.773 ms | 27.157 ms | 1.17x |
| `fill.rings_2` | 1.714 ms | 1.337 ms | 1.28x |
| `subdivide.actual.many_lines` | 26.268 ms | 0.267 ms | 98.38x |
| `subdivide.actual.polyline_spaced_long` | 3.152 ms | 1.098 ms | 2.87x |
| `subdivide.polyline_long` | 0.190 ms | 0.095 ms | 2.01x |
| `scale.by_line.many_lines` | 76.365 ms | 0.599 ms | 127.43x |
| `scale.by_face.many_rings` | 7.945 ms | 0.135 ms | 58.90x |
| `scale.polyline_long` | 1.372 ms | 0.767 ms | 1.79x |
| `translate.polyline_long` | 0.313 ms | 0.104 ms | 3.00x |
| `translate.many_lines` | 0.076 ms | 0.037 ms | 2.05x |
| `translate.line_small` | 0.009 ms | 0.009 ms | 1.03x |
| `rotate.polyline_long`（default auto-center） | 1.370 ms | 1.038 ms | 1.32x |
| `rotate.pivot.polyline_long` | 1.028 ms | 0.652 ms | 1.58x |

全 actual-work primary case が 10% 以上改善し、p95 でも同じ改善傾向を確認した。
small translate は実質同等だった。

成果物:

- baseline: `/tmp/grafix-five-effects-formal/runs/five-effects-actual-before-20260719.json`
- after: `/tmp/grafix-five-effects-formal/runs/five-effects-actual-after-final3-20260719.json`
- compare: `/tmp/grafix-five-effects-formal/final3-compare.json`

## 5. Cold performance とメモリ

| mode / case | before | after | ratio |
| --- | ---: | ---: | ---: |
| compile-cold / subdivide many-lines | 2080.534 ms | 826.601 ms | 2.52x faster |
| process-cold / subdivide many-lines | 320.587 ms | 307.310 ms | 1.04x faster |
| compile-cold / fill dense | 1002.437 ms | 2192.586 ms | 2.19x slower |
| process-cold / fill dense | 358.539 ms | 348.650 ms | 1.03x faster |

- fill の空 cache JIT compile は約 1.19 秒増えた。cache 利用後の別 process 初回実行と
  warm actual-work は悪化していないため、2-pass kernel の明示的 tradeoff として採用した。
- translate の 5,000,000 頂点 spot-check は旧実装と peak RSS が実質同等だった。
- scale の 200,000 line spot-check は旧 loop 比で約 4.8 MB の定数的上乗せがある。
  8,192 本 chunk により line 数比例の増加はなく、未 chunk 版からは大幅に削減した。

## 6. Differential / fuzz 検証

- subdivide: canonical 5,000 case、非 canonical 1,000 case
- fill: public call 1,000 case、scanline 50,000 case
- scale: signed-zero を含む 20,000 case と chunk 境界
- rotate: BLAS 丸め境界、subclass、pivot 評価順、C/F working buffer の
  raw 10,000 case、最終 float32 10,000 case、警告・例外 900 条件
- translate: signed-zero、layout、subclass、浮動小数点通知

レビューで見つかった fill の配列外書込み、subdivide の Inf 停止差、
transform の signed-zero / layout / subclass / 評価順差はすべて修正済み。
重大・中程度の未解決所見はない。

## 7. 変更ファイル

- 実装:
  - `src/grafix/core/effects/fill.py`
  - `src/grafix/core/effects/subdivide.py`
  - `src/grafix/core/effects/scale.py`
  - `src/grafix/core/effects/rotate.py`
  - `src/grafix/core/effects/translate.py`
- benchmark:
  - `src/grafix/devtools/benchmarks/cases.py`
  - `src/grafix/devtools/benchmarks/runner.py`
  - `tests/devtools/benchmarks/test_effect_benchmark.py`
- correctness:
  - `tests/core/effects/test_fill.py`
  - `tests/core/effects/test_subdivide.py`
  - `tests/core/effects/test_scale.py`
  - `tests/core/effects/test_rotate.py`
  - `tests/core/effects/test_translate.py`

公開 API と型スタブは変更していない。未採用案と既知の cold/memory tradeoff は
上記へ明記済みであり、必要な実装・回帰検証は完了した。
