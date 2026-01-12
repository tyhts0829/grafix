# どこで: Grafix リポジトリ（interactive 描画 + export）。
# 何を: 背景は毎フレームクリアしつつ、フレームごとのジオメトリを蓄積して「残像（trail）」を表示/出力する。
# なぜ: 画面だけでなく SVG/G-code でも同じ “残像” を再現できるようにするため。

# ジオメトリ蓄積型 Trail（残像）: 実装計画（2026-01-12）

## ゴール

- 背景クリアは現状どおり毎フレーム行う。
- それでも過去フレームの軌跡が残るように、ジオメトリ（RealizedLayer）を履歴として保持し、毎フレーム「履歴 + 現在フレーム」を描画する。
- `S`（SVG）/`G`（G-code）/`P`（PNG）エクスポートでも、画面に見えている残像をそのまま出せる。

## 非ゴール（今回やらない）

- OpenGL の accumulation buffer / `auto_clear` のような “クリアしない” 経路追加。
- G-code 上でのアルファ合成・減衰（薄くなる/消える）。必要なら後で「間引き」等として別仕様で扱う。
- メモリ/キャッシュ最適化の作り込み（まず仕様を固定する）。

## 仕様（案）

### 追加する公開 API（案）

- `grafix.api.run(..., trail_frames: int = 0, trail_stride: int = 1)`
  - `trail_frames=0`: 無効（現状と同じ）。
  - `trail_frames>0`: 過去フレームの履歴を最大 `trail_frames` 分保持して描画/出力に含める。
  - `trail_stride>=1`: 何フレームに 1 回履歴へ追加するか（負荷調整）。

### Trail に「何を溜めるか」（重要）

背景を毎フレームクリアする前提では、単純に「毎フレームの全レイヤ」を履歴へ積むと、
G-code で同じ線を何度もなぞる（濃くなる）問題が起きやすい。

そのため、履歴には “前フレームの状態” のうち **変化が起きたレイヤだけ** を追加する方式を基本にする。

- フレーム i の描画は `clear → (trail履歴) → (current)`。
- 履歴へ追加するのは「フレーム i-1 のレイヤ」のうち、フレーム i の同一 `Layer.site_id` と比べて `GeometryId` が変わったもの。
  - レイヤが消えた場合（i で存在しない）は「変化した」とみなして i-1 を履歴へ入れる。
  - 新規に現れたレイヤは “過去” がないので履歴には入れない（現在フレーム側にのみ出る）。

これにより:
- 画面: 動いた分だけ残像が増える（静止レイヤは残像が増えない）。
- G-code: 同じ線の重複出力を避けやすい（意図した「軌跡」だけが増える）。

### 色/線幅の扱い

- 履歴に積む `RealizedLayer` は「そのフレームで解決された color/thickness」を保持する。
  - GUI 操作等で色/太さが変わった場合、以後のフレームだけ反映される（過去の残像は変わらない）。

### 操作（任意）

- `C` キーで trail 履歴をクリア（表示/エクスポート上の残像をリセット）。

## 実装方針（最小）

### データ構造

- `TrailBuffer`（新規）を用意し、以下を保持する:
  - `history: deque[list[RealizedLayer]]`（過去フレームの差分レイヤ列。古い順）
  - `prev: list[RealizedLayer] | None`（直前フレームのレイヤ列）
  - `frame_index`（stride 判定用）
- `TrailBuffer.step(current_layers) -> list[RealizedLayer]`
  - 内部で必要なら `prev` から差分を抽出して `history` に追加
  - 返り値は「描画/エクスポート対象のフラットなレイヤ列」（`history` を結合したもの + `current_layers`）

### 組み込み箇所

- `src/grafix/interactive/runtime/draw_window_system.py`:
  - `self._trail = TrailBuffer(...)` を保持
  - `draw_frame()` で `realized_layers` を得た後、`layers_to_draw = self._trail.step(realized_layers)` に置き換える
  - 以降は `layers_to_draw` を描画し、`self._last_realized_layers` もそれで更新する（= エクスポートも残像込み）
  - `C` キーで `self._trail.clear()` を呼ぶ
- `src/grafix/api/runner.py` / `src/grafix/interactive/render_settings.py`:
  - `trail_frames` / `trail_stride` を `run()` の引数として追加し、settings 経由で `DrawWindowSystem` に渡す

## 実装チェックリスト（承認後に実装）

- [ ] 仕様確定（事前確認）
  - [ ] `trail_frames`/`trail_stride` の名前で良いか
  - [ ] 「変化したレイヤだけ i-1 を履歴へ積む」方式で良いか（G-code 重複回避）
  - [ ] 履歴の色/線幅は “当時の値を固定” で良いか
  - [ ] `C` キーでのリセットを入れるか
- [ ] `src/grafix/interactive/runtime/trail_buffer.py`（新規）を追加
  - [ ] `TrailBuffer` を実装（history/prev/stride/maxlen/clear）
  - [ ] `site_id -> geometry_id` 対応で差分抽出
- [ ] `src/grafix/interactive/runtime/draw_window_system.py` を更新
  - [ ] `trail_*` 設定を受け取り、`TrailBuffer` を作る
  - [ ] `draw_frame()` の描画対象を `trail + current` に差し替える
  - [ ] `save_svg` / `save_gcode` / `save_gcode_per_layer` が “画面に見えているレイヤ列” を出すことを確認
  - [ ] `C` キーで履歴クリア（入れる場合）
- [ ] `src/grafix/interactive/render_settings.py` を更新（trail 設定を追加）
- [ ] `src/grafix/api/runner.py` を更新（`run(..., trail_frames, trail_stride)` を追加）
- [ ] スタブ同期
  - [ ] `src/grafix/devtools/generate_stub.py` を更新
  - [ ] `src/grafix/api/__init__.pyi` を再生成
  - [ ] `pytest -q tests/stubs/test_api_stub_sync.py`
- [ ] テスト追加（最小）
  - [ ] `tests/interactive/test_trail_buffer.py`（新規）で `TrailBuffer` の maxlen/stride/差分抽出/clear を検証
- [ ] 最小動作確認
  - [ ] `PYTHONPATH=src pytest -q tests/interactive/test_trail_buffer.py`
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`

## 追加で気づいた点（要相談）

- 現状 `realize_cache` は無制限なので、アニメーション（毎フレーム別 GeometryId）を長時間回すとメモリが増え続ける。
  - 今回は “trail の仕様確定” を優先し、必要になったら別タスクで LRU 化や手動 clear を検討したい。

