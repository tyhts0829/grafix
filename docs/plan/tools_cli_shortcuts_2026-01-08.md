# どこで: Grafix リポジトリ（開発用ツール `tools/`）。
# 何を: `tools/benchmarks/effect_benchmark.py` / `tools/benchmarks/generate_report.py` / `tools/gen_g_stubs.py` を短い CLI で実行できる導線を追加する計画。
# なぜ: 開発中に「長い python -m パス」を覚えずに済み、打ち間違いと手戻りを減らすため。

# tools 実行用 CLI 追加: 実装計画（2026-01-08）

## ゴール

- ベンチ計測を短いコマンドで実行できる:
  - `python -m tools bench run ...` → `tools/benchmarks/effect_benchmark.py`
  - `python -m tools bench report ...` → `tools/benchmarks/generate_report.py`
- スタブ生成を短いコマンドで実行できる:
  - `python -m tools stubs gen` → `tools/gen_g_stubs.py`
- `--help` が機能し、サブコマンドの入口が分かりやすい。

## 非ゴール（今回やらない）

- `grafix` 本体のユーザー向け CLI（スケッチ実行、export、設定生成など）を作り込む。
- 外部依存（click/typer 等）追加。
- ツール群の移動・パッケージング方針変更（`tools/` を `src/grafix/` に移す等）。

## 仕様を先に決めたい点（要確認）

- コマンド体系: `bench run/report` / `stubs gen` で良い？（より短い別名: `bench`=`b`, `stubs`=`s` を入れるか）
- `generate_report` 側の引数:
  - いまは固定パス生成（`data/output/benchmarks/...`）だが、CLI から `--out` や `--runs-dir` を指定できるようにする？
  - 最小は「引数なしで実行できる」だけで良い？
- `gen_g_stubs` のモード:
  - 最小は「生成して上書き」だけで良い？
  - （任意）`--check` を入れて “差分があるなら exit 1” を提供する？（CI/手元確認向け）

## 実装方針（最小）

- `tools/__main__.py` を新規追加し、`python -m tools ...` のエントリポイントにする。
- 実装は標準ライブラリ `argparse` のサブコマンドで分岐し、実処理は既存スクリプトの `main()` を呼ぶだけに寄せる。
  - `tools.benchmarks.effect_benchmark.main(argv)`（既に `argv` 対応済み）
  - `tools.benchmarks.generate_report.main()`（必要なら `main(argv)` に拡張）
  - `tools.gen_g_stubs.main()`（必要なら `main(argv)` に拡張）

## CLI 案（叩き台）

### ベンチ

- 実行:
  - `python -m tools bench run [effect_benchmark の既存引数...]`
    - 例: `python -m tools bench run --only mirror --cases ring_big --repeats 10 --warmup 2 --disable-gc`
- レポート生成:
  - `python -m tools bench report`（最小）
  - （拡張する場合）`python -m tools bench report --out data/output/benchmarks`

### スタブ

- 生成:
  - `python -m tools stubs gen`
  - （任意）`python -m tools stubs gen --check`

## 実装チェックリスト

- [ ] 入口 CLI を追加
  - [ ] `tools/__main__.py`（新規）を追加し、`python -m tools --help` が動く
  - [ ] サブコマンド `bench` と `stubs` を定義する
- [ ] ベンチ: effect_benchmark を接続
  - [ ] `python -m tools bench run ...` が `tools.benchmarks.effect_benchmark.main(argv)` に転送される
  - [ ] `bench run --help` で `effect_benchmark` 側の `--help` を見せる方針を決める
    - 案A: `bench run` は未解釈引数を素通しし、`effect_benchmark` の `argparse` に任せる（実装最小）
    - 案B: 入口側で `--help` を専用に出す（導線は良いが二重管理になりやすい）
- [ ] ベンチ: report 生成を接続
  - [ ] `python -m tools bench report` が `tools.benchmarks.generate_report.main()` を実行する
  - [ ] （引数対応する場合）`tools/benchmarks/generate_report.py` に `--out/--runs-dir/--output` を追加する
- [ ] スタブ生成を接続
  - [ ] `python -m tools stubs gen` が `tools.gen_g_stubs.main()` を実行する
  - [ ] （`--check` を入れる場合）`tools/gen_g_stubs.py` に “生成結果と現ファイルの一致” 判定を追加する
- [ ] ドキュメント（最小）
  - [ ] `docs/memo/generate_stub.md` に新コマンドを追記する（既存の `python -m tools.gen_g_stubs` は残す/置換するか要決定）
  - [ ] （必要なら）`tools/benchmarks/` の使い方を `docs/memo/` へ 5 行程度で追加
- [ ] 検証（手元コマンド）
  - [ ] `python -m tools bench run --only scale --cases ring_big --repeats 3 --warmup 1`
  - [ ] `python -m tools bench report` で `data/output/benchmarks/report.html` が更新される
  - [ ] `python -m tools stubs gen` で `src/grafix/api/__init__.pyi` が更新される
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
  - [ ] lint（変更ファイル限定）: `ruff check tools/__main__.py tools/benchmarks/generate_report.py tools/gen_g_stubs.py`

## Done（受け入れ条件）

- [ ] `python -m tools bench run` / `python -m tools bench report` / `python -m tools stubs gen` が迷わず実行できる
- [ ] 既存の実行方法（`python -m tools.benchmarks.effect_benchmark` / `python -m tools.gen_g_stubs` など）は壊さない

