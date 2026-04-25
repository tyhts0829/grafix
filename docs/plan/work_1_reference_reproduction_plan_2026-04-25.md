# sketch/work/1.py 参照画像再現計画

## 目的

`sketch/work/1.py` に、添付画像の構成を Grafix スケッチとして再現するコードを書く。

## 対象

- `sketch/work/1.py`

## アクション

- [x] 既存スケッチ API とサンプルの書き方に合わせ、A5 縦 canvas の `draw(t)` を実装する。
- [x] 大きな黒い台形、半透明グレーの有機的な重なり、赤い円、下部キャプションを個別のジオメトリとして構成する。
- [x] 参照画像の印象に合わせ、余白、配置、サイズ、重なり順を調整する。
- [ ] `PYTHONPATH=src python -m grafix export --callable sketch.work.1:draw --t 0 --canvas 148 210 --out ...` でレンダリングできることを確認する。

## 検証メモ

- `python3 -m py_compile sketch/work/1.py` は成功。
- export はローカル Python に `numpy` が無いため未完了。

## 非対象

- 依存追加
- 既存 API の変更
- `sketch/work/1.py` 以外のスケッチ変更
