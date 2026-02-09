# Contact Sheet 仕様（grafix-art-loop-orchestrator）

## 目的

- 画像合成を機械処理として固定し、run ごとの比較を安定化する。
- ideaman/artist/critic の創作判断と分離し、再現可能な成果物を必ず残す。

## 生成モード

### 1) `iter` モード

- 入力: `iter_XX/v*/out.png`
- 収集対象:
  - `iter_dir.glob("v*/out.png")`
  - `vNN` ディレクトリのみ採用
  - `iter_dir/contact_sheet.png` は収集対象外
- 並び順: `v01`, `v02`, ... を数値昇順で固定
- 出力既定: `iter_XX/contact_sheet.png`

### 2) `final` モード

- 入力: `run_dir/iter_*/contact_sheet.png`
- 収集対象:
  - `run_dir.glob("iter_*/contact_sheet.png")`
  - `iter_NN` ディレクトリのみ採用
  - `run_summary/*.png` は収集対象外
- 並び順: `iter_01`, `iter_02`, ... を数値昇順で固定
- 出力既定: `run_summary/final_contact_sheet_8k.png`

## レイアウト規約

- 背景: RGB `(246, 244, 239)`
- 余白: outer padding `40px`
- セル間隔: `24px`
- ラベル領域高さ: `44px`
- ラベル色: RGB `(32, 32, 32)`
- ラベル内容:
  - `iter` モード: `vNN`（例: `v03`）
  - `final` モード: `iter_NN`（例: `iter_02`）
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
- 必須引数不足（例: `--mode iter` で `--iter-dir` 無し）は失敗する。
