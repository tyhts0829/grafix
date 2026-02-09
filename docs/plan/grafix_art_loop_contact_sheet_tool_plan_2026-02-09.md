# Grafix Art Loop contact_sheet ツール実装計画（2026-02-09）

## 背景

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md` では、各 iteration の `contact_sheet.png` と最終 `run_summary/final_contact_sheet_8k.png` の生成が必須。
- 画像合成は創作判断ではなく機械処理なので、LLM 手作業ではなく専用ツールで固定化する。
- 参考 run として `sketch/agent_loop/runs/run_20260209_214538_n4m8_a5` の構造を基準にする。

## 参考ディレクトリ構成（今回の観測）

- variant 画像: `sketch/agent_loop/runs/run_20260209_214538_n4m8_a5/iter_XX/vYY/out.png`
- iteration シート: `sketch/agent_loop/runs/run_20260209_214538_n4m8_a5/iter_XX/contact_sheet.png`
- 最終シート: `sketch/agent_loop/runs/run_20260209_214538_n4m8_a5/run_summary/final_contact_sheet_8k.png`

## 実装対象ファイル（予定）

- `.agents/skills/grafix-art-loop-orchestrator/scripts/make_contact_sheet.py`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/references/contact_sheet_spec.md`（新規）
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`（呼び出し手順の追記）

## 実装タスク

### 1) 仕様固定（spec）

- [x] `contact_sheet_spec.md` を作成し、以下を固定する。
- [x] 入力モード: `iter`（variant 画像を並べる）/ `final`（iteration contact sheet を並べる）
- [x] 出力先: `iter_XX/contact_sheet.png` と `run_summary/final_contact_sheet_8k.png`
- [x] レイアウト要件: 余白、背景色、ラベル描画、セルサイズの決定式
- [x] 最終画像要件: 長辺 `>= 7690` を満たす拡大ルール

### 2) PNG 収集ロジック実装

- [x] `iter` モード収集を実装する。
- [x] 対象は `iter_dir/v*/out.png` のみ（`iter_dir/contact_sheet.png` は対象外）。
- [x] `v01..v08` のような番号順で安定ソートする。
- [x] `final` モード収集を実装する。
- [x] 対象は `run_dir/iter_*/contact_sheet.png` のみ（`run_summary/*.png` は対象外）。
- [x] `iter_01..iter_N` の番号順で安定ソートする。
- [x] 収集結果が 0 件なら即失敗（理由を stderr に明示）にする。

### 3) 画像合成ロジック実装

- [x] 収集件数から行列数を決めるグリッド配置を実装する。
- [x] セル内フィット（アスペクト維持）と余白埋めを実装する。
- [x] ラベル（`vYY` または `iter_XX`）を各セルに描画する。
- [x] `iter` モードで `contact_sheet.png` を書き出す。
- [x] `final` モードで `final_contact_sheet_8k.png` を書き出す。

### 4) CLI I/F 実装

- [x] 単一スクリプトで `--mode iter|final` を切り替え可能にする。
- [x] `iter` では `--iter-dir` 必須、`final` では `--run-dir` 必須にする。
- [x] `--out` 省略時は規定パス（`iter_XX/contact_sheet.png` / `run_summary/final_contact_sheet_8k.png`）に保存する。
- [x] 実行ログは短い要約（収集件数・出力パス・画像サイズ）だけ標準出力へ出す。

### 5) スキル文書への接続

- [x] `SKILL.md` に contact sheet 生成の標準コマンドを追記する。
- [x] `references/project_quick_map.md` から `contact_sheet_spec.md` へ到達できるようにする。
- [x] 創作 role（ideaman/artist/critic）ではなく機械処理ツールであることを明記する。

### 6) 検証

- [x] `run_20260209_214538_n4m8_a5` を入力に `iter` モードを dry-run し、`v01..v08` が順序どおり収集されることを確認する。
- [x] 同 run を入力に `final` モードを dry-run し、`iter_01..iter_04` の順で収集されることを確認する。
- [x] 生成物が `sketch/agent_loop/runs/<run_id>/` 配下のみになることを確認する。

## 受け入れ条件（DoD）

- [x] `iter_XX/vYY/out.png` から `iter_XX/contact_sheet.png` を再現可能。
- [x] `iter_XX/contact_sheet.png` 群から `run_summary/final_contact_sheet_8k.png` を再現可能。
- [x] 欠損入力時はサイレント成功せず、失敗理由が即分かる。
- [x] 収集順序がファイルシステム依存で揺れず、常に番号順で固定される。

## 実装開始前確認

- [x] この計画で実装に進めてよいか、ユーザー承認を得る。
