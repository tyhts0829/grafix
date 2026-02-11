# 組み込み primitive `G.lissajous(...)` 実装計画（2026-02-10）

## 背景 / 目的

- リサージュ曲線を直接生成できる組み込み primitive を追加し、`G` だけで周期曲線の作図を完結できるようにする。
- 既存方針（シンプル・可読・過剰防御なし）に合わせ、最小構成で実装する。

## 0) 実装前に決めること（あなたの確認が必要）

- [x] パラメータ集合を確定する
  - 採用: `a`, `b`, `phase`, `samples`, `turns`, `center`, `scale`
- [x] `a`/`b` の型を確定する
  - 案A: `float`（自由度優先）
  - 採用: 案B `int`（閉曲線の予測しやすさ優先）
- [x] 出力ポリラインを「常に閉じるか」を確定する
  - 案A: 常に先頭点を末尾へ複製して閉じる
  - 採用: 案B 閉じない（数式どおりの終点を維持）

## 1) 仕様案

- [x] 生成式を固定する
  - `x(t) = 0.5 * sin(a * t + phase_rad)`
  - `y(t) = 0.5 * sin(b * t)`
  - `t ∈ [0, 2π * turns]` を `samples` 点でサンプリング
- [x] `center`/`scale` を他 primitive と同様に最後段で適用する
- [x] 戻り値は `RealizedGeometry(coords=float32, offsets=int32)` を返す
- [x] 引数バリデーション方針を最小で定義する
  - 例: `samples < 2` は `ValueError`

## 2) 変更対象ファイル

- [x] `src/grafix/core/primitives/lissajous.py`（新規）
- [x] `src/grafix/core/builtins.py`（`_BUILTIN_PRIMITIVE_MODULES` へ追加）
- [x] `tests/core/test_lissajous_primitive.py`（新規）
- [x] `src/grafix/api/__init__.pyi`（stub 再生成で更新）

## 3) 実装タスク（チェックリスト）

### 3.1 primitive 実装

- [x] `lissajous_meta` を定義（`ParamMeta`）
- [x] `@primitive(meta=lissajous_meta)` で `lissajous(...)` を実装
- [x] NumPy で座標列を生成し、`coords`/`offsets` を構築
- [x] dtype を `float32`/`int32` に統一

### 3.2 組み込み登録

- [x] `src/grafix/core/builtins.py` の `_BUILTIN_PRIMITIVE_MODULES` に `grafix.core.primitives.lissajous` を追加

### 3.3 テスト

- [x] `G.lissajous()` が実体化でき、`coords/offsets` の shape・dtype が妥当であることを確認
- [x] 同一パラメータで座標が再現可能であることを確認
- [x] `center`/`scale` が座標へ反映されることを確認
- [x] 異常系（例: `samples < 2`）で期待どおり失敗することを確認

### 3.4 スタブ同期

- [x] `PYTHONPATH=src python -m grafix stub` を実行して `src/grafix/api/__init__.pyi` を同期
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py` で同期状態を確認

## 4) 検証コマンド（実装後）

- [x] `PYTHONPATH=src pytest -q tests/core/test_lissajous_primitive.py`
- [x] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`

## 5) 完了の定義

- [x] `G.lissajous(...)` が組み込み primitive として利用できる
- [x] パラメータ変更でリサージュ形状が意図どおり変化する
- [x] 追加テストが安定して通り、stub 同期テストも通る
