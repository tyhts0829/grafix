# README 改善プラン（2026-02-10）

目的: `README.md` を「初見の成功率が高い導線」に再構成し、現行実装と矛盾する記述を解消する。必要に応じて `architecture.md` へ情報を寄せ、README の焦点を保つ。

対象ファイル:

- `README.md`
- `architecture.md`（必要なら）

前提/注意:

- 依頼範囲外の差分には触れない（現状 `pyproject.toml` が変更扱いだが、今回の対象外）。

## 作業項目（チェックリスト）

### 1) README の “仕様乖離” を修正（必須）

- [x] `config.yaml` の探索/優先順を実装に合わせて修正（「先勝ちで 1 つだけ採用」+ 明示 config）
- [x] `Export` の導線を明確化（`python -m grafix export` を主導線にする / import パスを明記）
- [x] Dependencies 記述を整理（Python 依存の長い列挙をやめ、`pyproject.toml` を真実として参照させる）

### 2) README の導線を改善（必須）

- [x] Requirements を追加（Python >= 3.11 / macOS-first を明記）
- [x] External tools を追加（`resvg`/`ffmpeg` が必要な機能と導入例 `brew install ...`）
- [x] 出力先（既定 `data/output`）と、ショートカット（`P/S/V/G` + `Shift+G`）を整理
- [x] 2D の最小例（ペンプロッタ視点で “線→変形→出力” が最短で分かる例）を追加
- [x] よくある失敗（resvg/ffmpeg 不在等）の Troubleshooting を短く追加

### 3) 冗長/焦点散漫を解消（必須）

- [x] 冒頭の `Press G ...` とショートカット節の重複を解消
- [x] README の “内部設計（Geometry/RealizedGeometry）詳細” を縮約し、`architecture.md` へリンクで逃がす
- [x] “Not implemented yet” を README から除去 or 別ドキュメントへ移動（README の目的に合わせる）

### 4) （必要なら）architecture.md を補強（任意）

- [x] README から削った内容が “設計メモ” として必要なら `architecture.md` 側へ追記/整形（実装状況の誤記: export/MIDI 周りを更新）

## 完了の定義

- README だけ読めば「インストール → 動かす → 出力（PNG/SVG/MP4/G-code）→ つまずき回避」まで辿れる
- README の `config.yaml` 説明が `src/grafix/core/runtime_config.py` の挙動と矛盾しない
- README から内部設計詳細が過剰に突出せず、必要なら `architecture.md` に誘導される
