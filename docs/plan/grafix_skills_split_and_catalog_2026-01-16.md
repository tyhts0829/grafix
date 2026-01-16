# Grafix: skills 分割 + API カタログ自動生成（実装計画 / 2026-01-16）

どこで:

- skills（新規）:
  - `skills/grafix-api-catalog/`（参照特化 + 生成スクリプト）
  - `skills/grafix-compose/`（コンセプト→構成決定）
  - `skills/grafix-draw-export/`（実装・export・改良ループ）
  - `skills/grafix-artwork/`（任意: 薄いオーケストレータ）

何を:

- primitive/effect が増えても「作品（`draw(t)`）を書かせる」運用がブレないように、skills を役割分割する。
- `grafix-api-catalog` の `references/api.md` は **スクリプト自動生成**を正とし、参照を薄いカード形式で提供する。

なぜ:

- Codex skills は skill 内から別 skill を確実に呼び出せないため、プロンプトで複数 skills を明示 invoke する運用が堅い（`advice.md`）。
- 重い情報（API 一覧・テンプレ）を `references/` / `assets/` に逃がし、`SKILL.md` は工程中心に薄く保ちたい（`advice.md`）。

---

## 0) 事前決定（ユーザー確認済み）

- [x] 役割分割は 3 skill + 任意 1（`grafix-artwork`）で進める
- [x] `references/api.md` は自動生成（script）を正とする
- [x] 候補出しの単位は A（`t` 複数で 1 ファイル完結）

---

## 1) 受け入れ条件（完了の定義）

- [x] `skills/` 配下に 3〜4 skill が揃い、Codex から参照できる（repo 管理）。
- [x] `grafix-api-catalog/scripts/build_catalog.py` で `references/api.md` が生成できる（決定的・差分がきれい）。
- [x] `grafix-compose` にテンプレ（`assets/`）があり、`draw(t)` 実装のブレが減る。
- [x] `grafix-draw-export` が「export→選別→改良」の運用に寄っており、API 一覧は `grafix-api-catalog` に委譲できている。

---

## 2) 実装チェックリスト

### A) `grafix-api-catalog`

- [x] `skills/grafix-api-catalog/SKILL.md` を追加（目的・使い方・再生成方法）
- [x] `skills/grafix-api-catalog/scripts/build_catalog.py` を追加
- [x] `skills/grafix-api-catalog/references/api.md` を生成し、生成物である旨を明記

### B) `grafix-compose`

- [x] `skills/grafix-compose/SKILL.md` を追加（コンセプト→構成決定の制約）
- [x] `skills/grafix-compose/assets/sketch_template.py` を追加
- [x] `skills/grafix-compose/assets/pattern_recipes.md` を追加（短い型）

### C) `grafix-draw-export`

- [x] `skills/grafix-draw-export/SKILL.md` を repo 管理で追加（既存版を整理して移植）
- [x] API 一覧の重複記述を減らし、`grafix-api-catalog` の参照導線を追加

### D) （任意）`grafix-artwork`

- [x] `skills/grafix-artwork/SKILL.md` を追加（推奨 invocation 例・会話手順）

### E) パッケージング（任意）

- [x] `package_skill.py` で `.skill` を再生成（`dist/`）
