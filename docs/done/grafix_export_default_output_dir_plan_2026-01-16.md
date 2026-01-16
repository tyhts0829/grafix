# どこで: `src/grafix/devtools/export_frame.py`（CLI export） / `src/grafix/export/image.py`（既定 PNG パス生成） / `src/grafix/core/output_paths.py`（ミラー規則） / `src/grafix/resource/default_config.yaml`（paths）。
#
# 何を: `python -m grafix export` の **デフォルト出力先**を「普通のスケッチ」と同じルール（`paths.sketch_dir` をミラーして `paths.output_dir/png/` 配下へ出す）に統一する。
#
# なぜ: 生成スケッチ（例: `sketch/generated/*.py`）の出力が散らばらず、比較→選別→改良のループで管理しやすくするため。

## ゴール

- `--out` / `--out-dir` 未指定時、出力先は常に config の `paths` に従う。
  - 例: `paths.sketch_dir = "sketch"`, `paths.output_dir = "data/output"` のとき
    - 入力スケッチ: `sketch/generated/muller_brockmann.py`
    - 出力ディレクトリ: `data/output/png/generated/`
- 既定のファイル名規則は現状維持（pixel size suffix / run-id suffix / `_f001` 連番）。
- `--out` / `--out-dir` 指定時の挙動は変えない（明示指定が最優先）。

## 非ゴール

- export のファイル名を大きく変える（ルール刷新、テンプレ導入など）。
- `paths.output_dir` / `paths.sketch_dir` 自体の仕様変更（相対/絶対の解釈変更など）。
- SVG を出さないようにする（現状 PNG は中間生成物として SVG を同名生成する）。

## 現状（確認ポイント）

- ミラー規則の実体は `src/grafix/core/output_paths.py` の `output_path_for_draw()`。
  - draw 定義元ファイルが `paths.sketch_dir` 配下にある場合、`output_dir/{kind}/<sketch 相対 dir>/...` へミラーする。
- PNG の既定パス生成は `src/grafix/export/image.py` の `default_png_output_path()`。
  - 内部で `output_path_for_draw(kind="png", ...)` を使い、pixel size suffix（`export.png.scale` 反映）を付ける。
- `python -m grafix export` は `src/grafix/devtools/export_frame.py`。
  - ここで `default_png_output_path()` を使っていれば、基本的にゴールを満たすはず。
  - 満たしていない場合、`default_png_output_path()` を使っていない/使い方がズレている、または config 読み込み順が崩れている可能性がある。

## 仕様（確定したい動作）

### デフォルト出力先

- `draw` の定義元が `<sketch_dir>/<rel_parent>/<stem>.py` のとき:
  - `data/output/png/<rel_parent>/<stem>_<pxW>x<pxH>[_<run_id>].png`
  - 複数 `--t` のときはさらに `_f001` の連番を付ける（ディレクトリは同じ）。

### 例

- `paths.sketch_dir = "sketch"`
- `paths.output_dir = "data/output"`
- スケッチ: `sketch/generated/muller_brockmann.py`

→ 出力例:

- `data/output/png/generated/muller_brockmann_6400x6400.png`
- `data/output/png/generated/muller_brockmann_6400x6400_v2_f003.png`

## 実装方針（最小で美しく）

1) `src/grafix/devtools/export_frame.py` のデフォルトパス生成を **`default_png_output_path()` に一本化**する  
（現状が別実装なら置き換える）

2) `--out` / `--out-dir` の優先順位を明文化して、コードでもそれを反映する

- `--out` 指定: そのパスに 1 枚だけ保存（`--t` は 1 つのみ許可）
- `--out-dir` 指定: そのディレクトリ配下に保存（ファイル名は既定のまま）
- どちらも未指定: `default_png_output_path()` が返すパスに保存（=ミラー規則 + 既定出力）

3) 実装の根拠を `export_frame.py --help` と Skill ドキュメントに 1 行で書く  
（「未指定なら data/output/png/... に出る」）

## 実装チェックリスト

- [x] `src/grafix/devtools/export_frame.py` の既定パス生成が `default_png_output_path()` を使っているか確認（OK）
- [x] `default_png_output_path()` → `output_path_for_draw()` が cwd 依存で崩れないように改善（`src/grafix/core/output_paths.py`）
- [x] 手動テスト: `sketch/generated/muller_brockmann.py` を `--out/--out-dir` 無しで export
  - [x] 出力が `data/output/png/generated/` 配下になることを確認
- [x] 追加の手動テスト: `--out` / `--out-dir` 指定時はその指定先が優先されることを確認
- [x] Skill（`grafix-draw-export`）の例を「デフォルト出力（data/output）を基本」に寄せる
  - [x] `/tmp` は「明示的に変えたいときだけ」の例にする

## 要確認（あなたに質問）

- 決定: 複数 `--t` のデフォルト保存先は、現状どおり「同一ディレクトリ + `_f001` 連番」
