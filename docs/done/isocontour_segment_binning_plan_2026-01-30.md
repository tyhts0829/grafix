# isocontour effect 方針B（線分ビニング）実装計画

作成日: 2026-01-30

対象: `src/grafix/core/effects/isocontour.py`（`E.isocontour`）

目的: SDF 評価のボトルネック（`O(Ngrid * Nsegments)`）を、空間ビニング（タイル）で平均計算量を下げる。

前提/制約
---------

- 依存追加なし（SciPy など入れない）
- 既存パラメータの意味を維持（新規パラメータ追加なし）
- 出力は現状どおり「閉ループのみ」

実装方針
--------

- 距離（unsigned）は「近傍タイルだけ線分距離」を見て最短を取る
- 符号（inside/outside）は「行ごとの scanline even-odd」で計算する（点ごとの全線分走査をやめる）
- タイル→線分の可変長リストは CSR（count → prefix sum → fill）で構築する（Numba で扱える形）

チェックリスト
--------------

- [x] リング群から線分配列（端点 + AABB）を生成する
- [x] タイルグリッド（tile_size / tile_nx / tile_ny）を決める
- [x] CSR 形式で tile→segments を構築する（Numba: 2-pass）
- [x] scanline even-odd で inside parity を行単位に計算する（Numba）
- [x] タイル探索で最短距離を求めて SDF グリッドを作る（Numba / parallel）
- [x] `isocontour()` から新 SDF evaluator を呼ぶ
- [x] `tests/core/effects/test_isocontour.py` を通す
- [x] `docs/plan/isocontour_further_performance_plan_2026-01-30.md` に反映する
