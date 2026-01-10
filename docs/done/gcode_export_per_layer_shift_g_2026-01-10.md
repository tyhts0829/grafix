# どこで: `src/grafix/interactive/runtime/draw_window_system.py`（入力） / `src/grafix/export/gcode.py`（出力）。

# 何を: `Shift+G` で「レイヤーごと」に G-code を分割保存する機能を追加する（既存の `G` は全レイヤ一括のまま）。

# なぜ: レイヤ単位で試し書き/段階的な加工をしたい時、全レイヤ一括の G-code だと取り回しが悪いため。

# Shift+G: レイヤーごと G-code 出力（実装計画 2026-01-10）

## 0. 前提

- 対象: interactive ランタイムのショートカット追加（描画中の「最後に realize したレイヤ列」を保存する）。
- 既存挙動:
  - `G` で `self._last_realized_layers` を 1 ファイルへ保存（非同期 export worker）。
  - 保存先は `output_path_for_draw(kind="gcode", ...)` で決まる。
- やらないこと:
  - `export_gcode()` の仕様変更（G-code の内容最適化とは別件）
  - 依存追加

## 1. ゴール（受け入れ条件）

- `Shift+G` を押すと、**レイヤ数ぶんの `.gcode` が生成**される。
- 出力順は **`self._last_realized_layers` の順**（= 画面の描画順）で固定される。
- `G`（通常）による **全レイヤ一括出力は壊れない**。
- UI を固めない（既存と同様に **別プロセスで export** する）。
- 保存ログが分かりやすい（開始と完了が追える）。

## 2. 実装方針（案）

### 2.1 キー判定

- `DrawWindowSystem._on_key_press(symbol, modifiers)` で `key.G` を判定する。
- `modifiers & key.MOD_SHIFT` が立っていれば「レイヤーごと」、立っていなければ「従来どおり全レイヤ一括」。
- pending フラグは 2 種類に分ける（例: `_pending_gcode_save_all` と `_pending_gcode_save_layers`）か、mode を保持する（例: `_pending_gcode_save_mode: Literal["all","layers"]|None`）。

### 2.2 出力先（パス設計）

- ベースは既存の `self._gcode_output_path`（`output_path_for_draw(...)` の結果）を使う。
- レイヤごとの保存先は **ベースから派生**させる（衝突しない・グルーピングできる）。
- 命名は「人が見て分かる」ことを優先し、最低限以下を入れる:
  - layer index（固定桁推奨）
  - layer の識別子（`layer.name` があればそれ、なければ `site_id`）

（※具体案は「7. ユーザー確認が必要な決定事項」で確定）

### 2.3 export worker

- 既存の `_gcode_export_worker_main(...)` に加え、分割用 worker を追加する（例: `_gcode_export_layers_worker_main(...)`）。
- worker 内で `for i, layer in enumerate(layers): export_gcode([layer], path_i, canvas_size=canvas_size)` のように逐次書き出す。
- 結果通知は既存の `result_q` を流用し、**1 ファイルにつき 1 メッセージ**投げる（UI 側はすでに複数件の `get_nowait()` に対応）。

### 2.4 表示（ログ）

- 開始時に「どこへ出すか」を 1 行で出す（例: “Exporting G-code per layer: <dir>”）。
- 完了時は既存の `Saved G-code: <path>` がレイヤ分だけ出る。

## 3. 実装チェックリスト

- [x] 1. パス設計を確定し、レイヤごとの出力パス生成を実装する
  - [x] layer 名のサニタイズ規則: `[^A-Za-z0-9._-] -> _`（末尾/先頭 `_` は除去）
  - [x] 同名レイヤの衝突回避: layer index を必ず含める
- [x] 2. 分割 export worker を追加する
  - [x] worker から `result_q` へ結果を push（成功/失敗）
- [x] 3. `Shift+G` のショートカットを追加する
  - [x] `DrawWindowSystem._on_key_press` で modifiers を使って分岐
  - [x] `_start_gcode_export(mode=...)` から適切な worker を起動する
- [ ] 4. 手動確認（interactive）
  - [ ] `G` で従来どおり 1 ファイル出る
  - [ ] `Shift+G` でレイヤ数ぶんのファイルが出る
  - [ ] export 実行中に再度押した場合の挙動が分かりやすい（“already running” 等）
- [x] 5. 自動テスト（追加する場合）
  - [x] 出力パス生成のユニットテスト（`tests/core/test_output_paths.py`）
- [x] 6. 検証
  - [x] `mypy src/grafix/core/output_paths.py src/grafix/interactive/runtime/draw_window_system.py`
  - [x] `PYTHONPATH=src pytest -q tests/core/test_output_paths.py`

## 7. ユーザー確認が必要な決定事項

- [x] 1. 出力形式: B（同階層サフィックス方式）
  - A) ディレクトリ方式: `<base_stem>_layers/ layer000_<name>.gcode`
  - B) 同階層サフィックス方式: `<base_stem>_layer001[_<name>].gcode`
- [x] 2. layer index の基準: `layer001`（1 始まり）
- [x] 3. layer 識別子: `layer.name` があれば付与（無ければ省略、index のみ）
- [x] 4. ファイル名の長さ: `layer name` は 32 文字で切る
- [x] 5. `Shift+G` 時のログ: “保存先ディレクトリ” を表示してよい
