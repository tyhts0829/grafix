# site_id 安定化（relpath + PEP 657 + 安定キー導線）計画（2026-01-24）

目的:

- ParamStore のキー（`ParameterKey.site_id`）を **プロジェクト移動/別マシン/別ユーザー**に耐える表現へ寄せ、GUI 永続化を実運用できる状態にする。
- 小さな編集で `f_lasti` がズレてキーが雪崩れる問題を解消し、UI の「効かない/増殖する」体験を減らす。
- さらに、作品制作向けに「ユーザーが安定キーを明示できる導線」を用意し、編集耐性の逃げ道を作る。

背景 / 現状:

- 現状の site_id は `src/grafix/core/parameters/key.py` の `make_site_id()` が生成し、形式が `"{abs_filename}:{co_firstlineno}:{f_lasti}"`。
- 影響:
  - 絶対パス依存で、プロジェクト移動/別マシンで ParamStore を持ち回るとキーが壊れる（永続が実質使えない）。
  - `f_lasti` 依存で、軽微な編集でもキーが大量に変わり得る（古いキーが増殖、UI が “効かない” 感）。

関連メモ:

- `docs/review/src_code_review_2025-12-30_strict.md` に「PEP 657 の位置情報（行・列）で `"{relpath}:{lineno}:{col}"` へ」の指摘あり。
- 既存の reconcile/prune は「揺れた site_id を再リンクして増殖を抑える」方向で実装されているが、根本として `site_id` 自体を環境差に強くしたい。

---

## 0) 事前に決める（あなたの確認が必要）

- [ ] `site_id` の新フォーマットは `"{path}:{lineno}:{col}"` にする（`path` は原則 sketch_dir 基準の相対、`lineno/col` は PEP 657 由来）
- [ ] `lineno/col` は **0-based col** で保存する（PEP 657 の `col_offset` に合わせる）／それとも 1-based に寄せる
- [ ] `path` の決め方（優先順）:
  - A. `sketch_dir` 配下なら sketch_root 相対（例: `generated/foo.py`）
  - B. それ以外は `__name__`（module 名）優先
  - C. 最後に basename（`foo.py`）へフォールバック
- [ ] 明示キーの導線: API から `key=` を受け付ける（`G.*` / `E.*` / `L.layer` / `P.*`）
- [ ] `key` 指定時の site_id 仕様:
  - 案1: `"{path}|{key}"`（**lineno/col を捨てる**。編集耐性を優先）
  - 案2: `"{path}:{lineno}:{col}|{key}"`（衝突回避は強いが、編集耐性は弱い）
- [ ] 互換/移行は作らず、既存 JSON が直接一致しなくなるのは許容する（必要なら reconcile に期待する）
  - ※この方針はリポガイド（互換ラッパー/シムを作らない）に合わせる
- [ ] preset の `key=` の意味も上記に合わせて **編集耐性目的の key** に寄せる（現状は `base_site_id|key`）

---

## 1) 変更後の仕様（挙動の約束）

### 1.1 自動生成 site_id（デフォルト）

- 目的: **環境差に揺れにくい**・**同一行の複数呼び出しを区別できる**。
- `path`:
  - `runtime_config().sketch_dir` が設定され、呼び出し元ファイルがその配下にある場合は **sketch_root 相対パス**を採用する。
  - それ以外は module 名や basename にフォールバック（0) で確定した優先順に従う）。
- `lineno/col`:
  - `inspect.getframeinfo(frame).positions`（PEP 657）から start position を取得し、`lineno/col` として使う。
  - 取得不能なら `frame.f_lineno` と `col=0` にフォールバックする。
- 文字列化:
  - `site_id = f\"{path}:{lineno}:{col}\"`。

### 1.2 ユーザーが指定する安定キー（escape hatch）

- 目的: 「空行追加」「引数追加」「整形」「関数分割」などで `lineno/col` が変わっても、**意図的に同じ GUI 行として扱える**ようにする。
- API から `key=`（`str|int`）を受け取り、site_id を構成する。
  - `key` の型や空文字などの扱いは簡潔に（過度に防御しない）。
  - 文字列化して使う（例: `str(key)`）。
- `key` 指定時の site_id は 0) で確定した案に従う（lineno/col を捨てるかどうかが重要）。

### 1.3 既存 ParamStore との関係

- site_id 形式変更により、既存 JSON のキーは直接一致しない可能性がある。
- ただし現状の reconcile/prune があるため、**同一 op で label/meta が一致する**ケースは自動再リンクされ得る（期待値として明記）。
- 期待が外れる場合は「初期化される」のを正とし、誤マッチは避ける。

---

## 2) 方針（実装案）

### 2.1 `src/grafix/core/parameters/key.py`

- `make_site_id(frame, *, key=None)` を中心に整理する。
- file id（path）生成:
  - `runtime_config().sketch_dir` と、`src/grafix/core/output_paths.py` 相当の「sketch_root 推定」ロジックを再利用するか、必要最小限を `key.py` に持つ。
  - 絶対パスは出さない（出すなら最終フォールバックとしてだけ、が基本だが今回は避けたい）。
- 位置情報:
  - `inspect.getframeinfo(frame, context=0)` で `positions` を使う（Python>=3.11 前提）。
- 生成関数の公開 API:
  - `caller_site_id(skip=1, *, key=None)` を追加して、呼び出し側（api 層）が `key` を渡せるようにする。

### 2.2 API 層で `key=` を受ける

- `src/grafix/api/primitives.py`:
  - `factory(**params)` で予約引数 `key` を `params.pop("key", None)` し、`caller_site_id(skip=1, key=key)` を使う。
  - `key` は resolver に渡さない（meta にも出さない）。
- `src/grafix/api/effects.py`:
  - `EffectNamespace.factory(**params)` と `EffectBuilder.factory(**params)` で同様に `key` を pop。
  - chain_id の扱いは「最初のステップの site_id」基準を維持（key 指定時も自然に安定化される）。
- `src/grafix/api/layers.py`:
  - `LayerNamespace.layer(..., *, key=None, color=None, thickness=None)` のように kw-only 追加し、`caller_site_id(skip=1, key=key)`。
- `src/grafix/api/preset.py`:
  - `_preset_site_id()` を 0) で確定した仕様へ寄せる（`base_site_id|key` から脱却するかどうか）。

### 2.3 ドキュメント更新

- 旧形式を明記している箇所を更新:
  - `architecture.md`（`site_id` 形式の説明）
  - `src/grafix/core/parameters/architecture.md`
- `key=` の使い方（作品制作向けの推奨）をどこか 1 箇所に短く追記する（README か docs）。

### 2.4 テスト方針

- `tests/core/parameters/test_site_id.py`（新規）を追加し、以下を最小で担保する:
  - `caller_site_id()` が **絶対パスを含まない**（少なくとも `Path.cwd()` 等が露出しない）こと
  - 同一行に 2 回呼んだときに site_id が衝突しにくい（`col` が効く）こと
  - `key=` 指定時に、行番号変更に影響されない形式になっている（lineno/col を捨てる案なら特に重要）
- 既存テストで `preset` の site_id 末尾（`|1`）を仮定しているものがあれば更新する。

---

## 3) 変更箇所（ファイル単位）

- [ ] `src/grafix/core/parameters/key.py`
- [ ] `src/grafix/api/primitives.py`
- [ ] `src/grafix/api/effects.py`
- [ ] `src/grafix/api/layers.py`
- [ ] `src/grafix/api/preset.py`（仕様確定次第）
- [ ] `architecture.md`
- [ ] `src/grafix/core/parameters/architecture.md`
- [ ] `tests/core/parameters/test_site_id.py`（新規）

---

## 4) 手順（実装順）

- [ ] 事前確認: `git status --porcelain` を見て、依頼範囲外の差分は触らない
- [ ] `key.py`: 新 site_id 生成（relpath + lineno/col + key オプション）を実装
- [ ] API: `key=` の予約引数を受けて `caller_site_id(..., key=...)` を使う
- [ ] docs: site_id 形式と `key=` の説明を更新
- [ ] tests: site_id の最小回帰テストを追加/既存調整
- [ ] 最小確認: 関連 pytest のみ実行
- [ ] 任意: `ruff` / `mypy`（対象ディレクトリのみ）

---

## 5) 実行コマンド（ローカル確認）

- [ ] `PYTHONPATH=src pytest -q tests/core/parameters/test_site_id.py`
- [ ] `PYTHONPATH=src pytest -q`（任意）
- [ ] `ruff check src/grafix/core/parameters src/grafix/api tests/core/parameters`（任意）
- [ ] `mypy src/grafix/core/parameters src/grafix/api`（任意）

---

## 6) 手動確認（実機）

- [ ] 既存スケッチを起動し、GUI でいくつか override して保存 → 再起動で復元される
- [ ] スケッチを別ディレクトリへ移動（または別マシンへコピー）して起動 → **同じ行が同じ GUI 行として復元**される（期待）
- [ ] 重要な呼び出しに `key=` を付け、空行追加/引数追加などの軽微な編集後でも同じ GUI 行として残る

