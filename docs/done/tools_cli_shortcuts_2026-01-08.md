# どこで: Grafix パッケージ（`src/grafix/`）+ 開発用機能（devtools）。

# 何を: ベンチ計測+レポート生成/スタブ生成を「配布パッケージに含めた上で」 `python -m grafix benchmark` / `python -m grafix stub` で実行できる導線を追加する計画。

# なぜ: 開発中に「長い python -m パス」や `tools/` 直叩きを覚えずに済み、打ち間違いと手戻りを減らすため。

# grafix devtools CLI 追加: 実装計画（2026-01-09）

## ゴール

- ベンチ計測を短いコマンドで実行できる:
  - `python -m grafix benchmark ...` → effect ベンチ計測（旧: `tools/benchmarks/effect_benchmark.py` 相当）→ レポート生成（旧: `tools/benchmarks/generate_report.py` 相当）まで一括実行
- スタブ生成を短いコマンドで実行できる:
  - `python -m grafix stub` → `grafix.api.__init__.pyi` 再生成（旧: `tools/gen_g_stubs.py` 相当）
- 上記が「配布パッケージに同梱」され、`pip install grafix` 後でも import できる配置にする。
- `--help` が機能し、入口が分かりやすい。

## 非ゴール（今回やらない）

- `grafix` 本体のユーザー向け CLI（スケッチ実行、export、設定生成など）を作り込む。
- 外部依存（click/typer 等）追加。
- 「開発用コマンド」を増やしすぎる（最小の 2 系統: benchmark / stub に絞る）。

## 決定事項（ユーザー回答）

- `python -m grafix benchmark ...` は「計測 → レポート生成」を連続実行する（`benchmark report` は作らない）。
- `generate_report` は CLI 引数を追加しない（既定出力は `data/output/benchmarks`。CWD 基準）。
- スタブ生成コマンドは `python -m grafix stub` にする。
  - 出力先は「インストールされた grafix のパス配下」をデフォルトにする（editable install 前提）。
  - `--out` / `--check` は追加しない。

## 実装方針（最小）

- `src/grafix/__main__.py` を新規追加し、`python -m grafix ...` のエントリポイントにする。
- ベンチ/スタブ生成コードを `tools/` から `src/grafix/` 配下へ移設し、配布パッケージに同梱する。
  - `src/grafix/devtools/benchmarks/*`（旧: `tools/benchmarks/*`）
  - `src/grafix/devtools/generate_stub.py`（旧: `tools/gen_g_stubs.py`）
- CLI 実装は標準ライブラリのみ（`argparse`）で分岐し、実処理は移設先モジュールの `main()` を呼ぶだけに寄せる。
  - `grafix.devtools.benchmarks.effect_benchmark.main(argv)`（`argv` 対応済み）
  - `grafix.devtools.benchmarks.generate_report.main()`（CLI 引数なし）
  - `grafix.devtools.generate_stub.main()`（CLI 引数なし）

## CLI 案（叩き台）

### ベンチ

- 実行:
  - `python -m grafix benchmark [effect_benchmark の既存引数...]`（計測 → report 生成）
    - 例: `python -m grafix benchmark --only mirror --cases ring_big --repeats 10 --warmup 2 --disable-gc`

### スタブ

- 生成:
  - `python -m grafix stub`

## 実装チェックリスト

- [ ] パッケージ内へ移設（同梱前提）
  - [ ] `tools/benchmarks/*` を `src/grafix/devtools/benchmarks/*` へ移設する
    - [ ] `effect_benchmark.py` の `sys.path` ブートストラップを撤去し、パッケージ import 前提にする
    - [ ] `generate_report.py` の「プロジェクトルート決め打ち」を撤去し、既定は `Path.cwd()` 基準にする
  - [ ] `tools/gen_g_stubs.py` を `src/grafix/devtools/generate_stub.py` へ移設する
    - [ ] 出力先の既定を「インストールされた `grafix` 配下の `api/__init__.pyi`」にする
- [ ] 入口 CLI を追加
  - [ ] `src/grafix/__main__.py`（新規）を追加し、`python -m grafix --help` が動く
  - [ ] サブコマンド `benchmark` と `stub` を定義する
- [ ] ベンチ: CLI を接続
  - [ ] `python -m grafix benchmark ...` が `effect_benchmark.main(argv)` → `generate_report.main()` を順に実行する
- [ ] スタブ: CLI を接続
  - [ ] `python -m grafix stub` が `grafix.devtools.generate_stub.main()` を実行する
- [ ] テスト/参照の移行
  - [ ] `tests/stubs/test_api_stub_sync.py` の import 元を `tools.gen_g_stubs` → `grafix.devtools.generate_stub` に更新する
- [ ] ドキュメント（最小）
  - [ ] `README.md` か `docs/memo/` に「devtools の実行例」を短く追記する
  - [ ] `docs/memo/generate_stub.md` を `python -m grafix stub` に更新する
- [ ] 検証（手元コマンド）
  - [ ] `python -m grafix benchmark --only scale --cases ring_big --repeats 3 --warmup 1`
  - [ ] `python -m grafix benchmark` 実行後に `data/output/benchmarks/report.html` が更新される
  - [ ] `python -m grafix stub` で `grafix/api/__init__.pyi` が更新される（editable install 前提）
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`
  - [ ] lint（変更ファイル限定）: `ruff check src/grafix/__main__.py src/grafix/devtools src/grafix/devtools/benchmarks tests/stubs/test_api_stub_sync.py`

## Done（受け入れ条件）

- [ ] `python -m grafix benchmark` / `python -m grafix stub` が迷わず実行できる
- [ ] `pip install grafix` 後でも devtools の import ができる配置になっている（`grafix` パッケージ内に同梱）
