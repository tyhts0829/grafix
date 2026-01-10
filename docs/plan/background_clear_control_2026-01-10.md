# 背景クリア制御（auto_clear）実装計画（2026-01-10）

## 目的

- 毎フレームの背景クリア有無を、ユーザーが選べるようにする。
- 「クリアしない＝前フレームが確実に残る」を、バックエンド差に依存せず安定して提供する（B: preserve）。
- 既定挙動（毎フレーム背景色でクリアしてから描画）は維持する。

## 非目的

- 低レベル OpenGL 状態をユーザーへ露出する。
- 互換ラッパー/シムの追加（既存 API を温存するための二重経路など）。
- パフォーマンス最適化（まず仕様を固定し、必要になったら後で）。

## 仕様

### ユーザー向け API

- `grafix.api.run(..., auto_clear: bool = True)`

### auto_clear の意味

- `auto_clear=True`（現状）
  - 毎フレーム、解決済み背景色で `screen` をクリアしてから、そのフレームのシーンを描画する。
- `auto_clear=False`（preserve）
  - 内部に RGBA の蓄積用オフスクリーン（accumulation buffer）を持つ。
  - 蓄積バッファは「透明で初期化」し、以後は **毎フレームクリアしない**。
  - 毎フレームの最後に `screen` を「その時点の背景色」でクリアし、蓄積バッファを `screen` へ合成して表示する。
  - 背景色が GUI などで変わっても「背景だけ変わって線は残る」を成立させる。

### 期待される挙動

- `auto_clear=False` では「新しく描いた線は残り続ける」。
- ウィンドウリサイズは想定しない（現状 `resizable=False`）。
  - 万一 framebuffer サイズが変化した場合は、蓄積バッファを作り直し「残像はリセット」する。

## 実装チェックリスト（案）

- [ ] `grafix.api.run` に `auto_clear` 引数を追加し、docstring を更新する（NumPy スタイル）。
- [ ] `RenderSettings` に `auto_clear` を追加してランナーから渡せるようにする。
- [ ] `DrawWindowSystem` が毎フレーム呼ぶ「背景クリア」手順を `auto_clear` で分岐する。
- [ ] `DrawRenderer` に `auto_clear=False` 用の蓄積バッファ（texture + framebuffer）を追加する。
- [ ] `auto_clear=False` 用の present（screen 合成）パスを実装する（フルスクリーンクアッド + 最小シェーダ）。
- [ ] framebuffer サイズ変化を検知し、蓄積バッファを再作成できるようにする（再作成時は透明で初期化）。
- [ ] 録画（`VideoRecordingSystem`）が最終出力（present 後の screen）を拾うことを確認する。
- [ ] 公開 API 変更に伴い `grafix/devtools/generate_stub.py` を更新し、`src/grafix/api/__init__.pyi` を再生成する。
- [ ] `pytest -q tests/stubs/test_api_stub_sync.py` が通ることを確認する。
- [ ] `ruff check .` / `mypy src/grafix` / `pytest -q` の範囲で確認する。
- [ ] 使い方メモを `README.md` か `docs/` に 1 例だけ追記する（「軌跡を残す」例）。

## 決定事項

1. 引数名: `auto_clear: bool`（既定 `True`）。
2. `auto_clear=False`（preserve）時の背景色: 変更を即反映する。
3. `auto_clear=False`（preserve）時の手動クリア: 今回は用意しない（必要になったら追加）。
4. リサイズ: 想定しない（現状 `resizable=False`）。万一 framebuffer が変化したら蓄積はリセットする。

## メモ（A と B の扱い）

- A（単に clear を呼ばない）は「前フレームが残る保証がない」ため不定になり得る。
- 本計画は B（preserve）を正式挙動として提供する前提。
