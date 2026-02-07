---
name: grafix-art-loop-orchestrator
description: Grafixアート反復（N回・M並列）を、skill発動時はエージェント直書きで自動実行する。成果物はsketch/agent_loop配下へ保存する。CLIモードは明示時のみ。
---

# Grafix Art Loop Orchestrator

## 目的

- アイデア生成 → M並列の実装/レンダリング → 批評/選抜 を N 反復で回す。
- 生成物とログを `sketch/agent_loop` 配下に保存し、追跡可能にする。

## デフォルトモード（skill発動時）

- 出力は常に `sketch/agent_loop/runs/<run_id>/...` に保存する。
- デフォルトは `run_loop.py` を使わず、エージェント自身が反復ループを回す。
- このモードでは計画 md の新規作成は不要とする。
- `artist` は variant ごとの作業ディレクトリ（`.../iter_XX/vY/`）に `sketch.py` を生成する。
- レンダリングは `PYTHONPATH=src python -m grafix export` を使い、各 variant の `out.png` を生成する。
- 各反復で contact sheet を作成し、`critique.json` と `winner_feedback.json` を保存する。

## 自動ループ手順（agent-native）

1. `run_id` を作成し、`sketch/agent_loop/runs/<run_id>/` を作る。
2. 反復ごとに `iter_XX/vY/` を作成し、各 variant の `draw(t)` を実装する。
3. 各 `sketch.py` を `python -m grafix export` でレンダリングする。
4. 候補を比較し、`critique.json` と winner を保存する。
5. winner 情報を次反復へ引き継ぐ。

## CLIモード（明示時のみ）

- ユーザーが明示的に `run_loop.py` / `run_one_iter.py` 実行を指定した場合のみ使う。
- `ideaman` / `artist` / `critic` は外部コマンドとして実行し、JSON ファイルで受け渡しする。
- 標準レンダリングは orchestrator 側の `GrafixAdapter` が `python -m grafix export` で実行する。

## 使い方

1. `scripts/run_loop.py` を実行する。
2. `--ideaman-cmd` / `--artist-cmd` / `--critic-cmd` を指定する。
3. 受け渡し JSON の形式は `references/schemas.md` に従う。

```bash
python .codex/skills/grafix-art-loop-orchestrator/scripts/run_loop.py \
  --n 8 \
  --m 6 \
  --ideaman-cmd "python ideaman.py --out {brief}" \
  --artist-cmd "python artist.py --context {context} --out {artifact}" \
  --critic-cmd "python critic.py --candidates {candidates} --grid {grid} --out {critique}"
```

## コマンドテンプレートの主なプレースホルダ

- `ideaman`: `{brief}` `{context}` `{run_id}` `{iteration}` `{repo_root}` `{loop_root}`
- `artist`: `{artifact}` `{context}` `{brief}` `{baseline}` `{feedback}` `{variant_dir}` `{seed}` `{attempt}` `{artist_id}` `{variant_id}` `{profile}` `{repo_root}`
- `critic`: `{candidates}` `{grid}` `{critique}` `{context}` `{run_id}` `{iteration}` `{repo_root}` `{loop_root}`

### `artist` の最小出力

- `status: "success"`
- `code_ref`: `variant_dir` 配下の `*.py`（`draw(t)` を実装）
- `callable_ref`（任意）: 例 `sketch:draw`

`image_ref` が無くても、`code_ref` があれば orchestrator が `python -m grafix export` で `out.png` を生成する。

## 実装ファイル

- `scripts/run_one_iter.py`: 1反復を実行
- `scripts/run_loop.py`: N反復を実行
- `scripts/make_contact_sheet.py`: Pillow でコンタクトシートを作成
