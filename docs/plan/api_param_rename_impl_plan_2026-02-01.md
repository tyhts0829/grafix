# 何を: 優先ランキング（P0/P1）に沿って、実コードの引数名をリネームし、全呼び出し箇所とスタブ/テストを更新する。

# なぜ: 引数の命名/順序ルールを “口約束” ではなく実体として統一し、迷いを減らすため。

## スコープ（今回やる）

### P0: transform / ノイズ語彙

- `E.repeat`
  - `offset` -> `delta`
  - `rotation_step` -> `rotation`
- `E.displace`
  - `spatial_freq` -> `frequency`
  - `t` -> `phase`

### P1: 衝突/中心語彙

- `E.drop`
  - `keep_mode` -> `mode`
- `E.mirror`
  - `cx` -> `center_x`
  - `cy` -> `center_y`

## スコープ外（今回やらない）

- 互換ラッパー/シムの追加（破壊的変更でよい）
- P2（表示順ルールの全面適用、seed の末尾寄せなど）は後回し

## 影響範囲（更新が必要なもの）

- 対象 effect 実装ファイル（meta / 関数シグネチャ / 内部参照）
- 呼び出し箇所（主に `sketch/`、テスト、ドキュメント）
- `python -m grafix stub` による `src/grafix/api/__init__.pyi` 再生成

## 実装チェックリスト

- [ ] 1) 影響範囲を `rg` で列挙（各旧名の使用箇所）
- [ ] 2) `E.repeat` の rename を実装 + 呼び出し更新
- [ ] 3) `E.displace` の rename を実装 + 呼び出し更新
- [ ] 4) `E.drop` の rename を実装 + 呼び出し更新
- [ ] 5) `E.mirror` の rename を実装 + 呼び出し更新
- [ ] 6) `python -m grafix stub` を実行してスタブを更新
- [ ] 7) `PYTHONPATH=src pytest -q` を実行して確認
- [ ] 8) `docs/review/api_param_order_2026-01-30.md` の `old -> new` を「実施済み」に合わせて微調整（必要なら）
