<!--
どこで: `src/grafix/core/parameters/README.md`。
何を: `core/parameters` の “1 ファイルだけ読むならこれ” ミニガイド。
なぜ: param 解決（base/GUI/CC）と永続化の流れを最短で把握できるようにするため。
-->

# `grafix.core.parameters` ミニガイド（読む順とデータフロー）

このディレクトリは、`draw(t)` 実行中に「引数の最終値（effective）を決める」ための仕組みと、
その結果を GUI/永続化へ繋ぐためのストアを提供する。

## まず押さえる 5 つ（最短）

1. ストア本体: `src/grafix/core/parameters/store.py`（`ParamStore`）
2. フレーム境界: `src/grafix/core/parameters/context.py`（`parameter_context`）
3. 値解決: `src/grafix/core/parameters/resolver.py`（`resolve_params`）
4. 観測バッファ: `src/grafix/core/parameters/frame_params.py`（`FrameParamsBuffer`）
5. マージ（永続化）: `src/grafix/core/parameters/merge_ops.py`（`merge_frame_params`）

## データフロー（1 フレーム）

流れは次の 1 本だけを覚えればよい:

`store_snapshot -> parameter_context -> resolve_params -> frame_params -> merge`

対応する実体は以下。

### 1) `store_snapshot(store)`（スナップショット固定）

- 実装: `src/grafix/core/parameters/snapshot_ops.py`
- 役割: `ParamStore` から「読み取り専用のスナップショット」を生成する。

### 2) `parameter_context(store, cc_snapshot)`（フレーム境界の固定）

- 実装: `src/grafix/core/parameters/context.py`
- 役割:
  - `store_snapshot(store)` を contextvar に固定（draw 中の参照が決定的になる）
  - `FrameParamsBuffer()` を作って「このフレームで観測した引数」を蓄積する
  - MIDI CC スナップショット（任意）を固定する

### 3) `resolve_params(...)`（base/GUI/CC から effective を決める）

- 実装: `src/grafix/core/parameters/resolver.py`
- 役割:
  - `ParameterKey(op, site_id, arg)` で GUI 行を識別する（`src/grafix/core/parameters/key.py`）
  - スナップショットに state があれば GUI/CC を反映し、なければ base を採用する
  - 量子化（署名安定化）はここで一元化する（`_quantize`）
  - 観測結果を `FrameParamsBuffer.record(...)` に積む（次の merge の入力）

`resolve_params` は通常、API 層から呼ばれる:

- `src/grafix/api/_param_resolution.py`（`resolve_api_params`）

### 4) `FrameParamsBuffer`（観測の一時置き場）

- 実装: `src/grafix/core/parameters/frame_params.py`
- 役割:
  - (key, base, meta, effective, source, explicit, chain_id, step_index) を蓄積する
  - label の観測もここへ集める（`FrameParamsBuffer.set_label`）

### 5) `merge_frame_params(store, records)`（フレーム終了時に永続化）

- 実装: `src/grafix/core/parameters/merge_ops.py`
- 呼び出し元: `src/grafix/core/parameters/context.py`（`parameter_context` の `finally`）
- 役割:
  - 観測されたキーを `ParamStore` に登録し、UI 値/override などの初期ポリシーを適用する
  - label は `src/grafix/core/parameters/labels_ops.py` の `merge_frame_labels` で保存する

## 重要な補足

- worker（multiprocessing）では `parameter_context_from_snapshot(...)` を使う:
  - 実装: `src/grafix/core/parameters/context.py`
  - 役割: `ParamStore` を持たずに、スナップショット + 観測だけを行う（集約はメイン側で行う）
- `site_id` は「呼び出し箇所 ID」で、GUI 行の安定性に直結する:
  - 生成: `grafix.core.parameters.caller_site_id`（入口は `src/grafix/core/parameters/__init__.py` 側）

