# README: Quick start の次に Examples を追加（grn タイル自動生成）

作成日: 2026-01-25

## ゴール

- `README.md` の `## Quick start` の次の章として `## Examples` を追加する
- `data/output/png/readme/grn` の PNG を「6 枚/行」でタイル表示する（6 列 × 複数行）
- 並べる枚数は「6 で割り切れる最大枚数」に丸める（例: 13 枚なら 12 枚）
  - 余った分は **末尾（新しい側）** を落とす
- 元画像は `docs/readme/grn` に README 用サイズへ変換して保存する
  - ファイル名は **番号のみ**（例: `docs/readme/grn/13.png`）
- 変換 + README 反映までを 1 回で行うスクリプトを `src/grafix/devtools` に追加する

## 対象（変更するもの）

- `README.md`
- `src/grafix/devtools/`（新規スクリプト追加）
- `docs/readme/grn/`（変換済み PNG を追加/更新）

## 仕様（確定）

### 対象画像の選び方

- 入力: `data/output/png/readme/grn/*.png`
- ファイル名先頭の連番（例: `13_1184x1680.png` の `13`）を番号として扱う
- 番号で昇順ソートし、先頭から `N = (len // 6) * 6` 枚を採用する
  - 余りは末尾（新しい側）を落とす（例: 13 枚なら 12 枚）

### 変換後の出力先と名前

- 出力先: `docs/readme/grn/`
- 出力名: `<番号>.png`（例: `docs/readme/grn/13.png`）

### 変換サイズ

macOS-first の方針に合わせ、依存追加無しで `sips` を使って縮小する。

- 変換後の長辺: 600px（例: `sips -Z 600 ...`）
- README での表示幅: 180〜200px（6 枚が 1 行に収まりやすい値）

### README 更新方式

- `README.md` の `## Examples` 章に「自動生成ブロック（BEGIN/END）」を置く
- スクリプトがそのブロック内だけを書き換える（手編集と衝突しにくい）

## 実装手順（チェックリスト）

- [x] 仕様確定（余りは末尾を落とす / 出力名は番号のみ）
- [ ] 自動生成スクリプト追加: `src/grafix/devtools/prepare_readme_examples_grn.py`
  - [ ] 入力: `data/output/png/readme/grn`
  - [ ] 出力: `docs/readme/grn/<番号>.png`
  - [ ] `sips` の存在チェック + 実行（subprocess）
  - [ ] 6 枚で割り切れる枚数に丸めて採用（例: 13→12）
  - [ ] 既存出力は上書き（増分追加の運用を優先）
  - [ ] `README.md` の BEGIN/END ブロック内を生成して差し替え
- [ ] スクリプトを実行して `docs/readme/grn/*.png` を生成/更新
- [ ] `README.md` に `## Examples` を追加（`## Quick start` の次）
  - [ ] 6 列 × 複数行のタイル（HTML table など）
  - [ ] 参照先は `docs/readme/grn/<番号>.png`
- [ ] 表示確認（GitHub README 想定の Markdown/HTML で崩れないこと）
