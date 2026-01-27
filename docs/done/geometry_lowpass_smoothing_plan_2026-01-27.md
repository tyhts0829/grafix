# geometry の高周波成分除去（ローパス/スムージング）effect 計画（2026-01-27）

目的: 与えられた geometry（`RealizedGeometry` のポリライン列）から高周波成分（細かいギザギザ/ノイズ）を除去し、コーナーを丸める effect を追加する。

非目的:

- コーナー保持（シャープ化）やエッジ検出
- 形状縮みの抑制（Taubin smoothing 等）
- ネットワーク（分岐/接合）を考慮した全体緩和（既存 `relax` の領域）

## 0) 確認（あなたの返答が必要）

- [x] 入力は open/closed どちらもあり得る。端点固定は不要
- [x] エフェクトとして効果がはっきり出る方を優先する
- [x] コーナーは丸めたい（角は残さない）
- [x] effect 名は `lowpass`（= ガウシアン低域通過の意味）でよい
- [x] パラメータは `step`（再サンプル間隔）, `sigma`（平滑半径）, `closed`（`auto|open|closed`）でよい
- [x] `closed=auto` は近接判定にする（しきい値はモジュール先頭の定数 `CLOSED_DISTANCE_EPS`）
- [x] `closed` 扱いの出力は「始点==終点を維持（最後に始点を複製して閉じる）」でよい

## 1) 実装方針（アルゴリズム）

ポリラインを弧長パラメータ上の 1D 信号とみなし、以下の 2 段でローパス化する。

1. **弧長で等間隔に再サンプル**（`step` 間隔）
2. 再サンプル点列に **ガウス畳み込み**（`sigma`）を適用（x/y/z を独立に平滑）

境界条件:

- open: 反射（reflect）でパディングして畳み込み（端点が「固定」になりにくい）
- closed: 周期（wrap）で畳み込み（連続性を保ったまま丸める）

実装上の制約/注意:

- `src/grafix/core/effects/` 配下は **モジュール間依存禁止**（`util.py` の利用のみ可）。既存 `dash.py` / `trim.py` の関数は import せず、必要な kernel は当該モジュール内に持つ。
- 出力は入力と同じ offsets 数（ポリライン本数）を維持するが、各ポリラインの頂点数は `step` により変動する。

## 2) 変更点（触るファイル候補）

- `src/grafix/core/effects/lowpass.py`（新規）: effect 本体 + Numba kernel
- `src/grafix/core/builtins.py`: 組み込み effect モジュール一覧に追加
- `tests/core/effects/test_lowpass.py`（新規）: 最低限の挙動テスト

## 3) 手順

- [x] 仕様確定（この計画の「確認」項目にあなたが回答）
- [x] `src/grafix/core/effects/lowpass.py` を新規作成
  - [x] `lowpass_meta` 定義（`step`, `sigma`, `closed`）
  - [x] polyline ごとに (1) 等間隔 resample → (2) gaussian smoothing を実施
  - [x] open/closed の境界条件を実装（reflect / wrap）
  - [x] `RealizedGeometry(coords, offsets)` を組み立てて返す
- [x] `src/grafix/core/builtins.py` の `_BUILTIN_EFFECT_MODULES` に `grafix.core.effects.lowpass` を追加
- [x] `tests/core/effects/test_lowpass.py` を追加
  - [x] zigzag ノイズ（高周波）を入力し、出力の「粗さ」が下がることを確認
    - 例: 2 階差分（離散曲率相当）の L2 が減る / 総変動が減る、など単純な指標
  - [x] open と closed（始点==終点）で動作し、closed の場合は閉じが維持されること
  - [x] `sigma=0` または `step<=0` が no-op であること（または定義した仕様どおり）
- [ ] 最小の検証コマンド（任意）
  - [x] `PYTHONPATH=src pytest -q tests/core/effects/test_lowpass.py`

## 4) 受け入れ条件（完了の定義）

- [x] `E.lowpass(step=..., sigma=..., closed=...)` が使える（未登録エラーにならない）
- [ ] 高周波（細かいギザギザ）が目視で明確に減り、コーナーが丸まる
- [x] open/closed の両方で破綻しない（例外/NaN なし）
- [x] `tests/core/effects/test_lowpass.py` が通る
