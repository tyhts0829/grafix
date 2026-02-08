# Grafix Usage Playbook

このファイルは、art loop 実行で繰り返し必要になる Grafix 操作の最小手順。
コマンド探索や試行錯誤を減らすために使う。

## 前提

- Python 実行は `/opt/anaconda3/envs/gl5/bin/python` を使う。
- `grafix` のコマンド実行時は `PYTHONPATH=src` を付ける。

## 主要コマンド

### primitive / effect 一覧

```bash
PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list primitives
PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix list effects
```

使いどころ:
- `primitive_key` / `effect_chain_key` の実在確認
- references スナップショットとの差分確認

### 画像書き出し

```bash
PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export \
  --callable sketch.main:draw \
  --t 0 \
  --canvas 1024 1024 \
  --out sketch/agent_loop/runs/<run_id>/iter_01/v01/out.png
```

使いどころ:
- variant 単体レンダリング
- `Artifact.image_ref` の生成

## 典型エラーと最短対処

### `No module named grafix`

- 原因: `PYTHONPATH=src` が付いていない。
- 対処: コマンド先頭に `PYTHONPATH=src` を付ける。

### `unknown primitive/effect` 相当の不一致

- 原因: recipe のキーがレジストリ外。
- 対処:
  1. `grafix list primitives/effects` を再取得
  2. `artist_context.json` の `primitive_key` / `effect_chain_key` を再割当

### 画像が出ない / 真っ白

- 原因候補: clipping し過ぎ、描画対象の欠落、呼び出し先ミス。
- 対処:
  1. `callable_ref` を確認
  2. `stdout_ref` / `stderr_ref` を確認
  3. `artist_summary` の guardrail 記述を確認

## 出力境界チェック

- 出力は `sketch/agent_loop/runs/<run_id>/` 配下のみ。
- `/tmp` やリポジトリ直下への出力は禁止。
- 一時作業が必要なら `sketch/agent_loop/runs/<run_id>/.tmp/` を使う。

## 運用メモ

- 追加で調べた手順は run 末尾に
  `skill_improvement_report.json.discovery_cost` として残す。
- 再利用価値が高いものはこの playbook へ追記して、次回の探索を減らす。
