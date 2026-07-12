# sketch/work/3.py 画像再現計画

対象: `sketch/work/3.py`

## 目的

添付画像の幾何構成を Grafix スケッチとして再現する。

## 作業項目

- [x] 作業ツリーと `sketch/work/3.py` の現状を確認する。
- [x] 画像を構成要素に分解する。
  - クリーム色の背景
  - 上部の黒いリング
  - 中央の淡色縦ストリップ
  - 右下の黒い丸角ゲート形状
  - 左下の赤い円
  - 左中と右下の黒い小ドット
- [x] `sketch/work/3.py` に、再現用の `draw()` と必要最小限の primitive を実装する。
- [x] 穴や重なりは紙色レイヤで隠さず、形状生成時に線分を除外する。
- [x] `py_compile` / `ruff` / headless export で確認する。
- [x] 完了項目をこの計画に反映する。

## 方針

- 編集対象は `sketch/work/3.py` と本計画ファイルに限定する。
- 依頼範囲外の `sketch/work/1.py`、`sketch/work/2.py`、既存 PNG、`.vscode/` には触れない。
- 紙色レイヤでの上書きは使わない。背景色は `run(..., background_color=...)` のみで扱う。
- 穴や重なりは、可能な限り shape/mask 生成時点で除外し、`E.clip` は必要な場合だけ使う。
