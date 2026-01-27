# reaction_diffusion: contour を「閉ループのみ」出力にする

作成日: 2026-01-27

## 背景 / 課題

- `E.reaction_diffusion(..., mode="contour")` の出力は現状「開いたパス」も混ざるため、`E.fill` で塗れる閉領域（リング列）として扱いにくい。
- 目的は **常に閉曲線（先頭点=終端点）だけを返す** こと。
- マスクがソフト/ハードかは本改善の主目的ではなく、まず出力トポロジ（閉ループ化）を安定させる。

## ゴール

- `E.reaction_diffusion(...)` の出力ポリライン列が **常に閉ループのみ**（open path を出さない）
  - 1 本ごとに `coords[s] == coords[e-1]` を満たす（polygon primitive と同じ「終端に先頭を複製」形式）
  - 必要点数未満・閉じられない線は破棄して良い（結果が empty になるのは許容）
- API は **contour 専用**に絞ってシンプル化する（破壊的変更 OK）

## 変更方針（設計）

### 1) API を contour 専用へ整理

- `mode="skeleton"` と細線化系パラメータを削除する
  - `reaction_diffusion_meta` から `mode/thinning_iters` を落とす
  - 実装から Zhang-Suen / skeleton trace を削除（肥大化を避ける）
- 名前は据え置き（`reaction_diffusion`）で、返すのは常に等値線ループ。

### 2) Marching Squares の「セグメント→ループ」接続を loops-only に変更

- 現状の `_stitch_segments_to_paths()` は endpoints から open path を作るため、これを使わない。
- `metaball` の `_stitch_segments_to_loops()` と同系のロジックを `reaction_diffusion.py` 内へ実装し、
  - `path[-1] == start` で閉じたものだけ `loops` として採用
  - open は捨てる
- 追加で、座標列として `coords[0] == coords[-1]` を必ず満たすように整形（不足時は先頭点を末尾に追加）。

### 3) （必要なら）境界起因の open を減らす

- open が多すぎてループが出にくい場合は、次のいずれかを検討（※まずは 2) のみで着手）
  - 計算領域の padding（margin）増加
  - マスク付き marching の「4隅が全部 inside」の条件を緩める / 代替（ただしマスク境界に線が出る）
  - 周期境界（wrap）導入（大改造なので後回し）

## 変更対象ファイル

- `src/grafix/core/effects/reaction_diffusion.py`
  - skeleton 系の削除
  - loops-only stitching の追加・適用
- `tests/core/effects/test_reaction_diffusion.py`
  - skeleton smoke の削除
  - 「全ポリラインが閉じている」ことのテスト追加
- `src/grafix/api/__init__.pyi`
  - `python -m grafix stub` で自動更新

## 実装手順（チェックリスト）

- [ ] `reaction_diffusion` を contour 専用に整理（meta/引数/実装から skeleton を削除）
- [ ] `_stitch_segments_to_loops()`（loops-only）を追加し、等値線抽出でそれを使う
- [ ] 出力の各ポリラインで `first == last` を保証（必要なら末尾に 1 点追加）
- [ ] スタブ更新: `PYTHONPATH=src python -m grafix stub`
- [ ] テスト更新:
  - [ ] `test_reaction_diffusion_skeleton_smoke` を削除
  - [ ] `contour` 出力が「全ループ閉」なことを検証（各 offsets 区間で `coords[s] == coords[e-1]`）
- [ ] `PYTHONPATH=src pytest -q tests/core/effects/test_reaction_diffusion.py`
- [ ] `ruff check src/grafix/core/effects/reaction_diffusion.py tests/core/effects/test_reaction_diffusion.py`

## 受け入れ基準

- `E.reaction_diffusion(...)(mask)` の realized 出力に open path が含まれない
- `E.fill(...)` が（入力として）破綻しない形のリング列になる

