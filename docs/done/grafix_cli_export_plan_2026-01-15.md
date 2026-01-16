# どこで: `src/grafix/__main__.py` と `src/grafix/devtools/`。

#

# 何を: `python -m grafix export ...` を追加し、`draw(t)` を headless で 1 フレーム書き出せる CLI を提供する（方針 B）。

#

# なぜ: Codex Skill が生成した `draw(t)` を、対話ウィンドウ無しで **確実に PNG に export** できる導線を Grafix 側へ集約するため。

## ゴール

- `python -m grafix export ...` で **PNG** を保存できる。
- 入力は `draw` の参照（例: `sketch.foo:draw`）を受け取る。
- `--t` を複数指定して **複数枚を一括 export** できる（比較 → 選別 → 改良のループ用）。
- `--out` 省略時は Grafix の既存ルール（`data/output/...` ミラー）で保存先を決める。
- `--config` を渡せば `config.yaml`（特に `export.png.scale`）を反映できる。

## 非ゴール（今回やらない）

- 連番フレーム / アニメ（mp4）export（既存の録画系とは別設計になるため）。
- ParamStore（GUI の override 値）を headless export に適用する仕組み。
- `grafix` ルートパッケージ（`from grafix import Export`）の公開 API 変更。
- SVG 出力（今回不要）。

## CLI 仕様案

### コマンド

```bash
PYTHONPATH=src python -m grafix export --callable sketch.foo:draw --t 0 --canvas 800 800
PYTHONPATH=src python -m grafix export --callable sketch.foo:draw --t 0 0.5 1.0 --canvas 800 800
```

### 引数

- `--callable`（必須）: `module:attr` 形式（例: `sketch.main:draw`）
- `--t`（任意, 既定 `0.0`）: `draw(t)` に渡す時刻（複数指定可）
- `--canvas`（任意, 既定 `800 800`）: `canvas_size=(w,h)`（現状 export は canvas_size 必須のため）
- `--out`（任意）: 出力パス（省略時は既定パス）
  - PNG の既定: `default_png_output_path(draw, canvas_size=...)` を使う（pixel size suffix 付き）
- `--out-dir`（任意）: 複数枚 export の保存先ディレクトリ（省略時は既定の PNG 出力ディレクトリへ連番保存）
- `--run-id`（任意）: 出力ファイル名の suffix（既定パス生成時に使用）
- `--config`（任意）: `config.yaml` を明示指定（`set_config_path` を呼んで反映）
- （必要なら）`--bg` / `--line-color` / `--line-thickness` は後から追加（今回は固定で開始して良い）

### 出力

- 成功時: 保存したパスを stdout に出す（複数枚なら 1 行/枚で列挙）。
- 失敗時: 例外内容を stderr に出し、終了コード `!=0`。
- 注: PNG 出力時も同名の `.svg` が生成される（PNG は SVG を `resvg` でラスタライズして作る）。

## 想定ワークフロー（「複数出して選ぶ」→「改良」ループ）

1. まず粗い候補をまとめて出す

```bash
PYTHONPATH=src python -m grafix export --callable sketch.generated:draw --t 0 0.25 0.5 0.75 1.0 --canvas 800 800 --run-id v1
```

2. 良かった `t`（または出力 index）をメモする
3. `draw` を改良する（線密度/構図/パラメータなど）
4. 選んだ `t` だけ再出力して比較する

```bash
PYTHONPATH=src python -m grafix export --callable sketch.generated:draw --t 0.5 --canvas 800 800 --run-id v2
```

## 実装方針（最小で美しく）

- `src/grafix/__main__.py` に `export` サブコマンドを追加し、処理本体は `src/grafix/devtools/export_frame.py`（新規）に寄せる。
  - 既存の `benchmark/list/stub` と同じ構造に揃える（`main(argv)` を持つ小さいモジュール）。
- `--callable` の解決は `importlib.import_module(module)` + `getattr(module, attr)` のみで行い、余計な推測はしない。
  - 失敗したら素直にエラー（過度に防御的にしない）。
- export 実体は既存の `grafix.api.Export` を呼ぶだけにする（パイプラインの再実装はしない）。

## 実装チェックリスト

### 1) CLI の配線

- [x] `src/grafix/__main__.py` に `export` サブコマンドを追加
- [x] `python -m grafix export --help` のヘルプ文言を整える

### 2) export コマンド本体（新規ファイル）

- [x] `src/grafix/devtools/export_frame.py` を追加
  - [x] `--callable/--t/--canvas/--out/--out-dir/--run-id/--config` を argparse で受ける
  - [x] `set_config_path(--config)` を適用
  - [x] draw を import して `grafix.api.Export(..., fmt="png", ...)` を実行
  - [x] `--out` 省略時の既定パス生成（`default_png_output_path` を使用）
  - [x] `--t` 複数指定時のファイル名ポリシー: `_f001.png` 連番
  - [x] 成功/失敗時の exit code と表示を確定

### 3) 最小動作確認（手元）

- [x] `PYTHONPATH=src python -m grafix export --callable sketch.main:draw --t 0 --canvas 300 300 --out /tmp/grafix_export_test.png`
- [x] `PYTHONPATH=src python -m grafix export --callable sketch.main:draw --t 0 0.5 1.0 --canvas 300 300 --out-dir /tmp/grafix_export_batch`

### 4) テスト（入れるなら最小）

- [x] `tests/` は **今回は無し**（PNG 出力は `resvg` 依存のため、環境差が出やすい）

### 5) ドキュメント（最小）

- [ ] `README.md` に `python -m grafix export ...` の例を 1 つ追記（任意）

## 決めたい点（実装前にあなたの確認が欲しい）

1. 決定: `--callable` は `module:attr` のみ（`--file` は後回し）
2. 決定: `--canvas` の既定は `(800, 800)`（Skill 側は明示指定推奨）
3. 決定: `--t` 複数時は「既定ディレクトリ + 連番」保存（`--out-dir` は任意）
