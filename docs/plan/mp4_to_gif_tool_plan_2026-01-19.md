# どこで: `tools/mp4_to_gif.py`（新規ユーティリティ）。
# 何を: mp4（等の動画）を GIF に変換するスクリプトを追加する。スクリプト実行でファイル選択 UI が開き、入力動画を選べる（CLI 引数は使わない）。
# なぜ: 作品制作の検討・共有のために、短いループ動画を軽量な GIF に素早く落としたい（CLI だけだと入力パス指定が面倒な場面があるため）。

作成日: 2026-01-19

## ゴール

- `python tools/mp4_to_gif.py` を実行すると、ファイル選択ウィンドウが開いて入力動画を選べる。
- アスペクト比を維持しつつ、出力サイズを縮小できる（縮小率はスクリプト冒頭の定数で調整）。
- 変換は `ffmpeg` を使って行い、品質/容量のバランスが良い（palettegen/paletteuse）。

## 非ゴール（今回やらない）

- 変換エンジンの内製化（ffmpeg 以外の実装）。
- GUI アプリ化（Finder 拡張、ドラッグ&ドロップ等）。
- 依存関係の追加（pip で新規ライブラリ導入）。

## 仕様（案）

### 入出力（GUI）

- 入力: tkinter のファイルダイアログで選択（拡張子フィルタ: mp4/mov/m4v/webm/all）
- 出力: 保存先ダイアログで `<stem>.gif` を初期値として提案し、ユーザーが保存先を決める
  - これにより上書き/採番の悩みを GUI 側へ寄せる（キャンセルで中断できる）

### リサイズ（アスペクト比維持）

- スクリプト冒頭に定数 `SCALE` を置く（例: `SCALE = 0.5`）。
- `scale=iw*SCALE:ih*SCALE` の形で ffmpeg の `scale` filter に渡す。

### 追加パラメータ（定数）

- `FPS`（例: 15）
- `START_SEC` / `DURATION_SEC`（任意。秒でトリム。未指定なら全体）
- `LOOP`（例: 0。0=無限ループ）

※ ここは必要最小限。増やしたくなったら定数を追加する方針（CLI 引数は作らない）。

## 実装方針

### ffmpeg コマンド（palette を使う）

1 回の ffmpeg 実行で完結するフィルタ構成を使う（中間 palette ファイルを作らない）。

- 例（概念）:
  - `-vf "fps=FPS,scale=...,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer"`

### 依存

- Python 標準: `pathlib`, `subprocess`, `shutil`, `tkinter`
- 外部: `ffmpeg`（存在しない場合はエラーメッセージで案内）

## 決定事項

- 失敗時の見せ方: 標準エラーへ print して終了（シンプル）

## 実装チェックリスト

- [x] `tools/mp4_to_gif.py` を追加
  - [x] スクリプト冒頭に `SCALE/FPS/START_SEC/DURATION_SEC/LOOP` を定義
  - [x] tkinter でファイル選択ダイアログを開く
  - [x] tkinter で保存先ダイアログを開く（初期ファイル名: `<stem>.gif`）
  - [x] `ffmpeg` の存在チェック（`shutil.which("ffmpeg")`）
  - [x] palettegen/paletteuse で GIF を生成
  - [x] 失敗時のエラーメッセージ方針（print）を反映
- [ ] 手動確認
  - [ ] mp4 を選択して gif が生成される
  - [ ] `SCALE = 0.5` で縦横比を保って縮小される
  - [ ] `FPS` を変えるとフレームレートが変わる

## 変更対象（想定）

- `tools/mp4_to_gif.py`（新規）
