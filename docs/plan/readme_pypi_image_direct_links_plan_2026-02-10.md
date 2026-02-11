# README PyPI 画像直リンク化プラン（2026-02-10）

目的: `README.md` の画像参照を相対パスから絶対 URL（`raw.githubusercontent.com`）へ統一し、GitHub/PyPI の両方で同一表示できるようにする。

対象ファイル:

- `README.md`

前提/注意:

- 依頼範囲外の差分には触れない。
- ブランチは `main` を使用する（`https://raw.githubusercontent.com/tyhts0829/grafix/main/...`）。

## 作業項目（チェックリスト）

### 1) 画像参照の洗い出し

- [ ] `README.md` 内の `<img src="...">` を全件確認する
- [ ] 相対パス参照のみを今回の変換対象に限定する

### 2) 直リンク化

- [ ] `docs/readme/...` の相対参照を `https://raw.githubusercontent.com/tyhts0829/grafix/main/docs/readme/...` へ置換する
- [ ] 既存の `width` / `alt` など属性は維持する

### 3) 反映確認

- [ ] `README.md` を再走査し、相対画像参照が残っていないことを確認する
- [ ] 変更差分が依頼範囲（README の画像 URL）のみに収まっていることを確認する

## 完了の定義

- `README.md` の画像参照が絶対 URL に統一されている
- 変更内容が PyPI 表示不具合対策に限定されている
