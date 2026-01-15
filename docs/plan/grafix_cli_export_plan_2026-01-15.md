# どこで: `src/grafix/__main__.py` と `src/grafix/devtools/`。
#
# 何を: `python -m grafix export ...` を追加し、`draw(t)` を headless で 1 フレーム書き出せる CLI を提供する（方針B）。
#
# なぜ: Codex Skill が生成した `draw(t)` を、対話ウィンドウ無しで **確実に PNG/SVG に export** できる導線を Grafix 側へ集約するため。

## ゴール

- `python -m grafix export ...` で **PNG / SVG** を保存できる。
- 入力は `draw` の参照（例: `sketch.foo:draw`）を受け取る。
- `--out` 省略時は Grafix の既存ルール（`data/output/...` ミラー）で保存先を決める。
- `--config` を渡せば `config.yaml`（特に `export.png.scale`）を反映できる。

## 非ゴール（今回やらない）

- 連番フレーム / アニメ（mp4）export（既存の録画系とは別設計になるため）。
- ParamStore（GUI の override 値）を headless export に適用する仕組み。
- `grafix` ルートパッケージ（`from grafix import Export`）の公開 API 変更。

## CLI 仕様案

### コマンド

```bash
PYTHONPATH=src python -m grafix export --callable sketch.foo:draw --fmt png --canvas 800 800
PYTHONPATH=src python -m grafix export --callable sketch.foo:draw --fmt svg --canvas 800 800
```

### 引数

- `--callable`（必須）: `module:attr` 形式（例: `sketch.main:draw`）
- `--fmt`（必須）: `png|svg`（将来 `gcode` を足す余地は残すが、今回は PNG/SVG に絞る）
- `--t`（任意, 既定 0.0）: `draw(t)` に渡す時刻
- `--canvas`（任意, 既定 `800 800`）: `canvas_size=(w,h)`（現状 export は canvas_size 必須のため）
- `--out`（任意）: 出力パス（省略時は既定パス）
  - `--fmt png` の場合: `default_png_output_path(draw, canvas_size=...)` を使う（pixel size suffix 付き）
  - `--fmt svg` の場合: `output_path_for_draw(kind="svg", ext="svg", canvas_size=...)` を使う
- `--run-id`（任意）: 出力ファイル名の suffix（既定パス生成時に使用）
- `--config`（任意）: `config.yaml` を明示指定（`set_config_path` を呼んで反映）
- （必要なら）`--bg` / `--line-color` / `--line-thickness` は後から追加（今回は固定で開始して良い）

### 出力

- 成功時: 保存したパスを stdout に 1 行で出す（例: `Saved PNG: ...`）。
- 失敗時: 例外内容を stderr に出し、終了コード `!=0`。

## 実装方針（最小で美しく）

- `src/grafix/__main__.py` に `export` サブコマンドを追加し、処理本体は `src/grafix/devtools/export_frame.py`（新規）に寄せる。
  - 既存の `benchmark/list/stub` と同じ構造に揃える（`main(argv)` を持つ小さいモジュール）。
- `--callable` の解決は `importlib.import_module(module)` + `getattr(module, attr)` のみで行い、余計な推測はしない。
  - 失敗したら素直にエラー（過度に防御的にしない）。
- export 実体は既存の `grafix.api.Export` を呼ぶだけにする（パイプラインの再実装はしない）。

## 実装チェックリスト

### 1) CLI の配線

- [ ] `src/grafix/__main__.py` に `export` サブコマンドを追加
- [ ] `python -m grafix export --help` のヘルプ文言を整える

### 2) export コマンド本体（新規ファイル）

- [ ] `src/grafix/devtools/export_frame.py` を追加
  - [ ] `--callable/--fmt/--t/--canvas/--out/--run-id/--config` を argparse で受ける
  - [ ] `set_config_path(--config)` を適用
  - [ ] draw を import して `grafix.api.Export(...)` を実行
  - [ ] `--out` 省略時の既定パス生成（PNG は `default_png_output_path` を使用）
  - [ ] 成功/失敗時の exit code と表示を確定

### 3) 最小動作確認（手元）

- [ ] `PYTHONPATH=src python -m grafix export --callable sketch.main:draw --fmt svg --canvas 800 800`
- [ ] `PYTHONPATH=src python -m grafix export --callable sketch.main:draw --fmt png --canvas 800 800`

### 4) テスト（入れるなら最小）

- [ ] `tests/` に **SVG export だけ**の最小テストを追加（resvg 非依存にするため）
  - 例: `tmp_path` に `--out` 指定して `.svg` が生成されることだけ確認
- [ ] `PYTHONPATH=src pytest -q`（もしくは対象テストだけ）

### 5) ドキュメント（最小）

- [ ] `README.md` に `python -m grafix export ...` の例を 1 つ追記（任意）

## 決めたい点（実装前にあなたの確認が欲しい）

1. `--callable` の形式は `module:attr` だけで開始して良い？（`--file` 対応は後回しで良い？）
2. `--canvas` の既定は `(800, 800)` で良い？（Skill 側で明示指定する運用でもOK）
3. `--fmt` はまず `png|svg` の 2 種だけで開始して良い？（gcode も同時に欲しい？）

