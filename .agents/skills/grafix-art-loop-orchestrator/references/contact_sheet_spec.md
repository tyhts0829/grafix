# Contact Sheet 仕様（grafix-art-loop-orchestrator）

## 目的

- 画像合成を機械処理として固定し、run ごとの比較を安定化する。
- ideaman/artist/critic の創作判断と分離し、再現可能な成果物を必ず残す。

## 生成モード

### 1) `round` モード

- 入力: `round_XX/v*/loop_*/out.png`
- 収集対象:
  - `round_dir.glob("v*")` 配下を variant 単位で走査する
  - `vNN` ディレクトリのみ採用
  - 各 `vNN` では `loop_NN/out.png` のうち最大 loop 番号だけを採用する
  - `round_dir/contact_sheet.png` は収集対象外
- 並び順: `v01`, `v02`, ... を数値昇順で固定
- 出力既定: `round_XX/contact_sheet.png`

### 2) `final` モード

- 入力: `run_dir/round_*/contact_sheet.png`
- 収集対象:
  - `run_dir.glob("round_*/contact_sheet.png")`
  - `round_NN` ディレクトリのみ採用
  - `run_summary/*.png` は収集対象外
- 並び順: `round_01`, `round_02`, ... を数値昇順で固定
- 出力既定: `run_summary/final_contact_sheet_8k.png`

## レイアウト規約

- 背景: RGB `(246, 244, 239)`
- 余白: outer padding `40px`
- セル間隔: `24px`
- ラベル領域高さ: `44px`
- ラベル色: RGB `(32, 32, 32)`
- ラベル内容:
  - `round` モード: `vNN`（例: `v03`）
  - `final` モード: `round_NN`（例: `round_02`）
- セルサイズ:
  - 収集した画像の `max(width)` / `max(height)` をセルサイズとする
  - 各画像はセル内にアスペクト比維持でフィット
- グリッド:
  - 入力件数から列数を探索し、`16:9` に近く空きセルが少ない配置を選ぶ

## 最終画像の長辺要件

- `final` モードのみ適用:
  - 出力画像の長辺が `7690` 未満なら拡大
  - 拡大後の長辺を `7690` に合わせる（縦横比維持）
  - 長辺が `7690` 以上なら拡大しない

## エラー方針

- 収集結果が 0 件のときは失敗する（stderr に理由を出力）。
- 必須引数不足（例: `--mode round` で `--round-dir` 無し）は失敗する。
