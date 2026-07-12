# sketch/work/2.py クリップ切り抜き修正計画

対象: `sketch/work/2.py`

## 目的

紙色の上書きで穴を表現している箇所を `E.clip` に置き換え、ペンプロッター出力時に重ね描きが発生しない線分構造にする。

## 作業項目

- [x] `E.clip` の API と既存利用例を確認する。
- [x] 上側の円形くり抜きと下側の有機形くり抜きを、マスク Geometry として分離する。
- [x] 黒い本体の塗り線に `E.clip(mode="outside")` を適用し、マスク内の線分を実際に除去する。
- [x] 紙色の上書きレイヤ（`upper paper cut` / `lower paper field`）を削除する。
- [x] 内側の流線は下側有機マスクの内側に `E.clip(mode="inside")` で収める。
- [x] `py_compile` / `ruff` / headless export で実行確認する。
- [x] 完了項目をこの計画に反映する。

## 方針

- 編集対象は `sketch/work/2.py` と本計画ファイルに限定する。
- 依頼範囲外の `sketch/work/1.py`、`.vscode/`、`sketch/work/2.PNG` には触れない。
- 互換ラッパーや別 API は追加せず、既存の `E.clip` をそのまま使う。
