# Grafix: 作品を書かせるための Skill 改善計画（advice.md 反映 / 2026-01-16）

どこで:

- `skills/`（Codex skills をリポジトリ側で管理）
- 既存: `skills/grafix-draw-export/`（export と改良ループ）
- 参考: `advice.md`（skills 分割・運用の指針）

何を:

- 「コーディングエージェントに作品（`draw(t)`）を書かせる」ことを安定させるため、skills を役割分割し、テンプレ/カタログ/手順を整備する。

なぜ:

- primitive/effect が増えるほど、1 つの skill に全部を詰めると選択が雑になりやすい。
- Codex skills は **skill 内から別 skill を確実に呼び出す機構がない**ため、運用は「複数 skills を同一プロンプトで明示 invoke」前提に寄せた方が再現性が高い（`advice.md`）。
- 重い情報（API 一覧、作例、テンプレ）は `references/` / `assets/` に退避し、`SKILL.md` は工程管理に寄せて薄く保ちたい（`advice.md`）。

---

## 0) 事前に決める（あなたの確認が必要）

1. 分割方針: 以下の 3 skill（+ 任意 1）に分けてよい？；OK
   - `grafix-api-catalog`（参照特化）
   - `grafix-compose`（コンセプト → 構成決定）
   - `grafix-draw-export`（実装・export・改良ループ。既存を整理）
   - （任意）`grafix-artwork`（薄いオーケストレータ。毎回の呼び出し例・会話手順を集約）
2. カタログ生成: `grafix-api-catalog` の `references/api.md` は **自動生成（script）** を正とする方針でよい？；OK
3. 「候補を複数出す」の単位:；A で
   - A) まずは `t` 複数で候補出し（1 ファイルの中で完結）
   - B) 作品自体を複数案（`*_a.py`, `*_b.py`）として出す
   - どちらをデフォルト運用にする？（おすすめは A → 気に入ったら B）

---

## 1) 受け入れ条件（完了の定義）

- ユーザーがモチーフを 1 行で渡すだけで、エージェントが `sketch/generated/<slug>.py` を作り、`python -m grafix export` で PNG を複数枚出力し、出力パス一覧を返せる。
- 以降は「人間が選別 → エージェントが改良 → 再 export」を `run-id` 更新で回せる。
- built-in の確認は、必要時だけ `grafix-api-catalog` を有効化（または `python -m grafix list ...`）して解決できる。
- skill 本体（`SKILL.md`）は工程と制約中心で、API 一覧は `references/` / `assets/` に分離されている。

---

## 2) 設計（skill 構成）

### A) `grafix-api-catalog`（参照特化）

目的:

- 「今このコンセプトに合う primitive/effect をどう選ぶか」を支援する索引を提供する。

同梱物（案）:

- `SKILL.md`: どう検索し、どう選ぶか（短い）
- `references/api.md`: primitive/effect の “薄いカード”一覧（自動生成）
  - 各項目: 名前 / 1 行説明 / 主要引数 / 相性タグ（任意）/ 2〜6 行の短い例
- `scripts/build_catalog.py`: `src/grafix` を import して `inspect.signature` と docstring 先頭行などから一覧を生成

### B) `grafix-compose`（コンセプト → 構成決定）

目的:

- モチーフを「構図」「レイヤ」「primitive/effect の最小セット」「`t` の使い方」に落として、実装がブレないようにする。

SKILL.md に固定したい制約（案）:

- まず **静的構図**を完成させる → 次に `t` で変化を付ける。
- 1 作品あたり primitive は最大 3 種、effect は最大 2 種（まずは少なめ）。
- 乱数を使う場合は seed を固定し、`t` に依存する揺らぎは意図して設計する。
- 実装は `sketch/generated/<slug>.py`、`draw` はトップレベル関数。

同梱物（案）:

- `assets/sketch_template.py`: 最小スケルトン（imports / draw(t) / 任意の preview）
- `assets/pattern_recipes.md`: 使い回せる構成レシピ（grid/radial/moiré/typographic 等の短い型）

### C) `grafix-draw-export`（実装・export・改良ループ）

方針:

- 既存 `grafix-draw-export` は「工程管理（実装 →export→ 選別 → 改良）」に寄せる。
- 参照・カタログ類は `grafix-api-catalog` へ移し、`grafix-draw-export` はリンク（= 併記 invoke 推奨）で済ませる。

追加したい明文化（案）:

- 既定出力は `data/output/png/...`（config の `paths.output_dir`）で、スケッチ相対パスをミラーする。
- 「誰が残す画像を決めるか」: **人間が決める**（ファイル名 or t/index 指定）をデフォルト運用として固定。

### （任意）D) `grafix-artwork`（薄いオーケストレータ）

目的:

- 毎回のプロンプトを短くしつつ、必要な skills を “セットで明示 invoke” する運用を固定する。

内容（案）:

- 「この順で進める」だけを書いた短い手順
- 推奨 invocation 例（ユーザーが貼るテンプレ）:
  - `$grafix-api-catalog $grafix-compose $grafix-draw-export`

---

## 3) 実装手順（順序）

1. skill 分割の土台を作る

- [ ] `skills/grafix-api-catalog/` を追加（`SKILL.md` / `references/` / `scripts/`）
- [ ] `skills/grafix-compose/` を追加（`SKILL.md` / `assets/`）
- [ ] （必要なら）`skills/grafix-artwork/` を追加（薄い `SKILL.md` のみ）

2. API カタログ生成を実装する

- [ ] `scripts/build_catalog.py` を実装（import + introspection → `references/api.md` を生成）
- [ ] 生成結果の品質を最低限整える（見出し、並び、短い例の体裁）

3. テンプレ/レシピを整備する

- [ ] `assets/sketch_template.py` を追加（最小で美しく）
- [ ] `assets/pattern_recipes.md` を追加（短い型だけ）

4. `grafix-draw-export` を整理する（必要最小）

- [ ] `SKILL.md` を「デフォルト出力（data/output）前提」「人間が選別」中心に寄せる
- [ ] カタログ/詳細説明は `grafix-api-catalog` に寄せ、重複を減らす
- [ ] 推奨 invocation（複数 skills 併記）を追記する

5. `.skill` を再生成して導線を揃える

- [ ] `package_skill.py` で `dist/*.skill` を更新
- [ ] インストール/同期方法を各 `SKILL.md` に 1 行で明記（コピーパス）

---

## 4) 手動スモークテスト（最小）

- [ ] 1 作品を新規生成（`sketch/generated/<slug>.py`）
- [ ] `python -m grafix export --callable sketch.generated.<slug>:draw --t 0 0.25 0.5 0.75 1.0 --run-id v1` が通る
- [ ] 出力が `data/output/png/...` に揃う
- [ ] ユーザーが 1 枚選ぶ → `run-id v2` で改良して再 export できる

---

## 5) 補足（運用メモ）

- skills は「skill の中から別 skill を呼ぶ」より、プロンプトで **複数 skills を同時に明示 invoke** する前提に寄せる（`advice.md`）。
- 依存追加（例: `resvg` のインストール案内）は Ask-first。skill はまず export を試し、失敗時にだけ案内する。
