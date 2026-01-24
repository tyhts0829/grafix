# 外部コマンド依存（resvg/ffmpeg 等）整理 実装改善チェックリスト（2026-01-24）

目的: Grafix の外部コマンド依存（`resvg`/`ffmpeg` 等）を「製品仕様」として整理し、機能呼び出し前に分かりやすい診断・導線を提供する。

背景:

- Python 依存は満たしているのに、外部コマンド不足で機能が動かないケースが起きる（環境差で壊れる）。
- CI/配布/README の整合が崩れやすく、トラブルシュート負荷が高い。
- 根拠（現状の呼び出し箇所）
  - `src/grafix/export/image.py`（`resvg` を subprocess 実行）
  - `src/grafix/interactive/runtime/video_recorder.py`（`ffmpeg` を subprocess 実行）

方針（案）:

- 外部コマンドは「必要な機能の直前」で検出し、**統一されたエラーメッセージ**で案内する（import 時には要求しない）。
- “見つからない/失敗した” の診断を 1 箇所に集約し、ドキュメントと文言を揃える。
- `python -m grafix doctor` のような入口を用意して、ユーザーが自力で状況を把握できるようにする。

非目的:

- `resvg`/`ffmpeg` の同梱・自動インストール
- 外部コマンドを内製化して置き換える
- 過度に一般化した依存解決（OS ごとの複雑な分岐を増やす）

## 0) 事前に決める（あなたの確認が必要）

- [ ] 対象範囲（最低: `resvg`, `ffmpeg`）；これで
  - [ ] “等” に含めるものも棚卸しする（例: `pbcopy`/`pbpaste`, `git` など）→ doctor 対象に入れる/入れないを決める
- [ ] 「必須/任意」の定義；どちらも必須
  - [ ] 例: core は常に動く / PNG 出力は `resvg` 必須 / 動画録画は `ffmpeg` 必須（機能単位で必須判定）
- [ ] 外部コマンドの解決方法（どれで行くか）
  - [ ] 案A: PATH のみ（`shutil.which` で検出、見つからなければ案内）
  - [ ] 案B: `config.yaml` にパス/コマンド名を追加（例: `tools.resvg`, `tools.ffmpeg`）
  - [ ] 案C: 環境変数オーバーライド（例: `GRAFIX_RESVG`, `GRAFIX_FFMPEG`）
- [ ] `doctor` の仕様；これはなし
  - [ ] コマンド名: `python -m grafix doctor` でよい？
  - [ ] 終了コード: 既定は 0（表示のみ）/ `--strict` で不足があれば non-zero、など
  - [ ] 出力形式: 人間向けテキストのみ / 将来のために `--json` も要るか
- [ ] インストール案内の範囲（macOS-first）
  - [ ] macOS は `brew install ...` を正として書く；これで。READMEに説明加えて
  - [ ] Linux/Windows の案内は README では最小にする（必要なら doctor の出力だけで補う）

## 1) 受け入れ条件（完了の定義）

- [ ] `resvg` が無い環境で PNG 出力を呼ぶと、次を満たす例外になる
  - [ ] 「何が足りないか（resvg）」「何の機能に必要か（PNG 出力）」「次に何をすべきか（install/doctor）」が 1 メッセージで分かる
- [ ] `ffmpeg` が無い環境で録画開始すると、同様に分かりやすい例外になる（録画キー/録画開始の直前で落ちる）
- [ ] `python -m grafix doctor` が、外部コマンドの検出結果（found/missing）とインストール案内を表示できる
- [ ] テストは外部コマンド非依存で通る（`resvg`/`ffmpeg` が無くても CI で落ちない）

## 2) 実装設計（案）

### 2.1 外部コマンド診断の集約

- 新規: `src/grafix/core/external_tools.py`（名前は要相談）
  - 役割: “外部コマンドの検出/診断/例外文言” を 1 箇所に集約する
  - 提供する最小 API（案）
    - `find_tool(name: str) -> str | None`（PATH or 設定から解決）
    - `require_tool(name: str, *, for_feature: str) -> str`（見つからなければ RuntimeError を投げる）
    - `doctor_report() -> list[ToolStatus]`（`doctor` 用の診断情報を返す）
  - エラーメッセージに含める要素（案）
    - tool 名 / 必要な機能名 / 代表的なインストール手段（macOS: brew）/ `python -m grafix doctor` の案内

### 2.2 呼び出し側の統一（resvg/ffmpeg）

- `src/grafix/export/image.py`
  - `resvg` 実行前に `require_tool("resvg", for_feature="PNG export")` を呼ぶ
  - `subprocess.run([...])` の先頭要素をどうするか（要決定）
    - 案A: 解決した実パスを使う（doctor と整合、テスト更新が必要）
    - 案B: `"resvg"` のまま（最小変更、事前診断だけ統一）
- `src/grafix/interactive/runtime/video_recorder.py`
  - `ffmpeg` 起動前に `require_tool("ffmpeg", for_feature="video recording")` を呼ぶ
  - 同様に cmd[0] を実パスにするかどうかを決める

### 2.3 `python -m grafix doctor` の追加

- `src/grafix/__main__.py`
  - `doctor` サブコマンドを追加し、`grafix.devtools.doctor`（新規）を呼ぶ
- 新規: `src/grafix/devtools/doctor.py`
  - `external_tools.doctor_report()` を表示用に整形して出力
  - `--strict`（不足があれば終了コード 1）などの最小フラグを持たせる（要確認）

## 3) 変更箇所（ファイル単位）

（※実装フェーズに入ってから着手）

- [ ] `src/grafix/core/external_tools.py`（新規）
- [ ] `src/grafix/export/image.py`（resvg 診断導線の統一）
- [ ] `src/grafix/interactive/runtime/video_recorder.py`（ffmpeg 診断導線の統一）
- [ ] `src/grafix/__main__.py`（`doctor` サブコマンド追加）
- [ ] `src/grafix/devtools/doctor.py`（新規）
- [ ] `README.md`（Dependencies の External を「必須/任意 + どの機能に必要か」に分解して明記）
- [ ] （必要なら）`src/grafix/resource/default_config.yaml` + `src/grafix/core/runtime_config.py`（tools 設定を追加する場合）

## 4) テスト方針（案）

- [ ] `tests/export/test_image.py`
  - [ ] `resvg` 解決ロジックの変更に合わせて更新（cmd[0] が `"resvg"` 固定でなくなる可能性）
  - [ ] `resvg` 不在時の RuntimeError 文言が “診断として分かる” ことを検証
- [ ] `tests/interactive/runtime/test_video_recorder.py`
  - [ ] `ffmpeg` 解決ロジックの変更に合わせて更新
- [ ] 新規: `tests/core/test_external_tools.py`（または同等）
  - [ ] `find_tool/require_tool` の振る舞い（which の monkeypatch で完結）

## 5) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src python -m grafix doctor`
- [ ] `PYTHONPATH=src pytest -q tests/export/test_image.py`
- [ ] `PYTHONPATH=src pytest -q tests/interactive/runtime/test_video_recorder.py`
- [ ] `PYTHONPATH=src pytest -q`
