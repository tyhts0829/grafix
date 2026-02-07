# Grafix Art Loop: `tools/ideaman.py` / `tools/artist.py` / `tools/critic.py` 実装計画

作成日: 2026-02-07

目的:
- `run_loop.py` をそのまま実行しても動くように、最低限のエージェント実装を `tools/` に追加する。
- 生成物は既存仕様どおり `sketch/agent_loop` 配下に出ることを確認する。

## 実装対象

- `tools/ideaman.py`
- `tools/artist.py`
- `tools/critic.py`

## 受け入れ条件

- [x] `python tools/ideaman.py --out ... --context ...` が `CreativeBrief` JSON を出力できる
- [x] `python tools/artist.py --artifact ... --variant-dir ...` が `Artifact` JSON（少なくとも `code_ref`）を出力できる
- [x] `python tools/critic.py --candidates ... --grid ... --out ...` が `Critique` JSON を出力できる
- [x] `run_loop.py` を `tools/*.py` 指定で実行し、`valid_count > 0` で完走する

## 実装チェックリスト

### 1) `tools/ideaman.py`

- [x] CLI 引数: `--out`, `--context` を受ける
- [x] `CreativeBrief` 最低必須項目を JSON 出力する
- [x] `context` を読める場合は反復番号などを brief に反映する

### 2) `tools/artist.py`

- [x] CLI 引数: `--context`, `--artifact`, `--variant-dir`, `--variant-id`, `--artist-id`, `--seed`, `--iteration`
- [x] `variant_dir` に `sketch.py`（`draw(t)`）を生成する
- [x] `Artifact` JSON を出力する（`status=success`, `code_ref` を含む）
- [x] `callable_ref` は省略可能（orchestrator 側推定に任せる）

### 3) `tools/critic.py`

- [x] CLI 引数: `--candidates`, `--grid`, `--out`, `--iteration`
- [x] 候補 JSON を読み、`ranking` と `winner` を返す
- [x] 候補ゼロ件でも壊れず `Critique` JSON を返す

### 4) スモーク実行

- [x] 以下コマンドで `run_loop.py` を実行し、`loop_summary.json` を確認する

```bash
python .codex/skills/grafix-art-loop-orchestrator/scripts/run_loop.py \
  --n 2 --m 3 --canvas 512 512 \
  --ideaman-cmd "python {repo_root}/tools/ideaman.py --out {brief} --context {context}" \
  --artist-cmd "python {repo_root}/tools/artist.py --context {context} --artifact {artifact} --variant-dir {variant_dir} --variant-id {variant_id} --artist-id {artist_id} --seed {seed} --iteration {iteration}" \
  --critic-cmd "python {repo_root}/tools/critic.py --candidates {candidates} --grid {grid} --out {critique} --iteration {iteration}"
```

### 5) 最小品質確認

- [x] `python3 -m py_compile tools/ideaman.py tools/artist.py tools/critic.py`
- [x] 生成された `artifact.json` に `code_ref` と `image_ref` が入ることを確認する（`image_ref` は orchestrator が補完）
