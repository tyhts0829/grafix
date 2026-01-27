# geometry の highpass（高周波強調）effect 計画（2026-01-27）

目的: 与えられた geometry（`RealizedGeometry` のポリライン列）から「高周波成分」を抽出/強調し、細かい揺れ・ディテールを目立たせる effect を追加する。

非目的:

- 角を残す/エッジ保持（bilateral 等）
- 形状縮みの抑制（Taubin smoothing 等）
- 周波数領域（FFT）での厳密フィルタ（再サンプル必須のため、まずは空間ドメインで実装）
- ネットワーク（分岐/接合）を考慮した全体最適化（`relax` の領域）

## 0) 確認（あなたの返答が必要）

- [x] effect 名は `highpass` でよい？
- [x] highpass の定義は「unsharp mask（高周波強調）」でよい？
  - 定義: `detail = x - lowpass(x)`、出力 `y = x + gain * detail`
  - `gain=0` は no-op（入力をそのまま返す）
- [x] パラメータは `step`（再サンプル間隔）, `sigma`（平滑半径）, `gain`（強調係数）, `closed`（`auto|open|closed`）でよい？
- [x] `closed=auto` は近接判定にする（しきい値はモジュール先頭の定数 `CLOSED_DISTANCE_EPS`）
- [x] closed 扱いの出力は「始点==終点を維持（最後に始点を複製して閉じる）」でよい？

## 1) 実装方針（アルゴリズム）

`lowpass` と同じ「弧長で等間隔に再サンプル → ガウス畳み込み（空間ドメイン）」をベースにする。

1. **弧長で等間隔に再サンプル**（`step` 間隔）し、信号 `x` を得る
2. `x` に **ガウス畳み込み**（`sigma`）をかけて `low = lowpass(x)` を得る
3. `detail = x - low`
4. 出力 `y = x + gain * detail`

境界条件:

- open: 反射（reflect）でパディングして畳み込み
- closed: 周期（wrap）で畳み込み

closed 判定:

- `closed="closed"`: 常に closed
- `closed="open"`: 常に open
- `closed="auto"`: 端点距離が `CLOSED_DISTANCE_EPS` 以下なら closed

実装上の制約/注意:

- `src/grafix/core/effects/` 配下は **モジュール間依存禁止**（`util.py` の利用のみ可）。
  - `lowpass` の内部関数を import しないため、必要な kernel は `highpass.py` 内に持つ（または util へ共通化する案も検討）。
- 出力は入力と同じ offsets 数（ポリライン本数）を維持するが、各ポリラインの頂点数は `step` により変動する。
- `gain` を上げると自己交差/暴れが起き得るが、それは仕様（creative coding 的に許容）。

## 2) 変更点（触るファイル候補）

- `src/grafix/core/effects/highpass.py`（新規）: effect 本体 + Numba kernel
- `src/grafix/core/builtins.py`: 組み込み effect モジュール一覧に追加
- `tests/core/effects/test_highpass.py`（新規）: 最低限の挙動テスト

## 3) 手順

- [x] 仕様確定（この計画の「確認」項目にあなたが回答）
- [x] `src/grafix/core/effects/highpass.py` を新規作成
  - [x] `highpass_meta` 定義（`step`, `sigma`, `gain`, `closed`）
  - [x] polyline ごとに (1) 等間隔 resample → (2) gaussian smoothing（low）→ (3) detail → (4) boost を実施
  - [x] open/closed の境界条件を実装（reflect / wrap）
  - [x] closed の場合、出力の末尾に始点を複製して閉じを維持
  - [x] `RealizedGeometry(coords, offsets)` を組み立てて返す
- [x] `src/grafix/core/builtins.py` の `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.highpass` を追加
- [x] `tests/core/effects/test_highpass.py` を追加
  - [x] `gain=0` が厳密 no-op（coords/offsets が一致）である
  - [x] ジグザグ（高周波）入力で、出力の「粗さ」が増える（例: y の標準偏差/2階差分 L2 が増える）
  - [x] `closed=auto` で near-closed 入力が closed 扱いになり、出力が閉じている（始点==終点）
- [ ] 最小の検証コマンド（任意）
  - [x] `PYTHONPATH=src pytest -q tests/core/effects/test_highpass.py`

## 4) 受け入れ条件（完了の定義）

- [x] `E.highpass(step=..., sigma=..., gain=..., closed=...)` が使える（未登録エラーにならない）
- [x] `gain>0` で高周波のディテールが明確に強調される
- [x] open/closed の両方で破綻しない（例外/NaN なし）
- [x] `tests/core/effects/test_highpass.py` が通る
