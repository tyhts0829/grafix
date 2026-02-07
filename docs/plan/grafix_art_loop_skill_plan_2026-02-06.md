# Grafix: Art Loop skills（N 反復 x M 並列）実装計画

作成日: 2026-02-06

この計画は `grafix_art_loop.md` の設計メモを、Codex skills（リポジトリ配下の `./.codex/skills/`）+ Python スクリプトに落とすための実装チェックリストです。

---

## 背景 / 目的

- Grafix を使ったジェネラティブ画像生成を、**アイデア → 実装 → 出力 → 批評 → 改善** の反復で N 回回す。
- 各反復で M 本の候補を（論理的に）分離して生成し、批評家が **全候補を比較して 1 つだけ**次へ持ち越す。
- Grafix の I/F（API/CLI/依存）が変わっても破綻しないよう、レンダリングはアダプタで吸収する。

## ゴール（DoD）

- [x] 1 回の run（`run_id`）で `N` 反復が完走する（途中の失敗混入は許容）。
- [x] 各反復で **M バリアント**が個別ワークスペース（`runs/<run_id>/iter_XX/vY/`）に保存される。
- [x] 批評家が **必ず全候補**を比較できる入力（コンタクトシート or 個別画像一覧）が生成される。
- [x] 批評結果は構造化（JSON）され、次反復に渡る情報が最小 3 点に絞られている:
  - 勝者の `code_ref` / `image_ref`
  - 「維持すべき要素」+「次に直すべき要素」
  - クリエイティブブリーフ（要約版）

## 非ゴール（今回やらない）

- LLM プロバイダ/API をこの repo に直結する（まずは外部コマンド注入で成立させる）。
- 大規模な GUI/ビューワ（最低限、成果物パスとコンタクトシートで運用できれば OK）。
- 互換ラッパーやシムで古い設計を温存する（破壊的でもシンプル優先）。

---

## 全体方針（設計の固定点）

- **役割分離**: orchestrator / ideaman / artist / critic を JSON でつなぐ。
- **Grafix 依存隔離**: 画像出力は `GrafixAdapter` だけが知る（最初に「動く最小」を確定）。
- **並列の前提**: M 本の生成は、同一プロセスのループではなく「実行単位の分離」を担保する。
  - 実装としては `subprocess` で M 回起動（最小・確実）を第一候補にする。
- **失敗混入 OK**: M の一部が失敗しても、成功分で批評→選抜へ進む（全滅だけ別扱い）。
- **コンテキスト肥大化を防ぐ**: 次反復へ渡す情報を最小化し、過去候補の詳細は原則渡さない。

---

## 置き場所（skills の構成案）

まずはリポジトリ配下で完結させる（`./.codex/skills/`）。`~/.codex/skills` は後回し（必要ならパッケージ化で移送）。

- [x] `./.codex/skills/grafix-art-loop-orchestrator/`
  - `SKILL.md`: 実行手順・入出力・制約（薄く）
  - `scripts/run_loop.py`: N 反復の統括
  - `scripts/run_one_iter.py`: 1 反復だけ回す（デバッグ用）
  - `scripts/make_contact_sheet.py`: 画像グリッド合成（任意だが推奨）
  - `references/schemas.md`: JSON 仕様（CreativeBrief/Artifact/Critique）
- [x] `./.codex/skills/grafix-art-loop-ideaman/`
  - `SKILL.md`: CreativeBrief を **JSON で**返す規約（必須フィールド固定）
- [x] `./.codex/skills/grafix-art-loop-artist/`
  - `SKILL.md`: 実装→レンダ→Artifact JSON 返却の規約
  - `references/artist_profiles/`: 作家性プロファイル（M の散らし方を固定）
- [x] `./.codex/skills/grafix-art-loop-critic/`
  - `SKILL.md`: 全候補比較→1 つ選抜→改善指示（優先度付き）を JSON で返す規約

注:

- skills は「skill の中から別 skill を確実に呼ぶ」仕組みが弱いので、運用は `$grafix-art-loop-...` を **並べて明示 invoke** する想定に寄せる。

---

## データモデル（JSON の最小仕様）

実装はまず依存を増やさず（Pydantic 無し）、`dataclasses + json` と最小バリデーションで進める。

- [x] `CreativeBrief`
  - `title: str`
  - `intent: str`
  - `constraints: { canvas: {w:int,h:int} | "unknown", time_budget_sec:int, avoid:list[str] }`
  - `variation_axes: list[str]`
  - `aesthetic_targets: str`
- [x] `Artifact`（artist の返却。成功/失敗を統一）
  - `artist_id: str`, `iteration:int`, `variant_id:str`
  - `status: "success" | "failed"`
  - `code_ref: str | null`, `image_ref: str | null`
  - `seed: int | null`, `params: dict[str, Any]`
  - `stdout_ref: str | null`, `stderr_ref: str | null`
  - `artist_summary: str`
- [x] `Critique`（critic の返却）
  - `iteration:int`
  - `ranking: list[{variant_id:str, score:float, reason:str}]`（reason は短く）
  - `winner: { variant_id, why_best, what_to_preserve, what_to_fix_next, next_iteration_directives:list[{priority:int,directive:str,rationale:str}] }`

---

## GrafixAdapter（最初に確定する点）

Grafix のレンダリングだけは I/F を確定させる必要があるので、最小を先に作る。

- [x] 既存 CLI `PYTHONPATH=src python -m grafix export --callable ... --t ... --canvas ... --out ...` を前提にする
  - 根拠: `src/grafix/__main__.py` に `export` があり、`src/grafix/devtools/export_frame.py` が実装済み。
- [x] `GrafixAdapter.render(callable_ref, *, t, canvas, out_path, config_path=None) -> RenderResult` を固定
  - 中身はまず `subprocess` で CLI を叩く（import 事故を避ける）
  - `RenderResult` に `stdout/stderr` と成功判定（画像ファイル存在/サイズ）を含める

---

## オーケストレーター（N 反復の状態遷移）

### 1 反復の入出力（IterationContext）

- [x] 入力:
  - `creative_brief`（反復 1 は ideaman から生成、2..N は要約を持ち越し）
  - `baseline_artifact`（反復 1 は `null`、2..N は前回 winner）
  - `critic_feedback_prev`（反復 1 は `null`、2..N は前回 winner 部分）
- [x] 出力:
  - `variants: list[Artifact]`（最大 M、失敗混入あり）
  - `critique: Critique`
  - `winner: Artifact`

### 並列化（M 本生成）

- [x] 最初は「M 回 `subprocess` 起動」で成立させる（プロセス分離が明確）
- [x] 各バリアントのワークスペースを完全分離: `runs/<run_id>/iter_XX/vY/`
- [x] 失敗混入の扱い:
  - `status=success` かつ `image_ref` が実在するものだけを critic に渡す
  - 0 件の場合のみリカバリ（同 iteration 1 回だけリトライ or ブリーフ簡略化）

### コンタクトシート

- [x] 入力制約を踏まえ、まず contact sheet を生成して critic に渡す
- [ ] 依存追加なしで難しければ「個別画像の一覧（パス + サムネ情報）」で代替し、Pillow 導入は後で判断

---

## Artist profiles（M を散らす設計）

- [x] `artist_profiles/artist_01..M.txt` を用意し、毎回同じ作家性で改善を続ける
- [ ] exploit/explore の比率を orchestrator が持つ（例: 70% 改善 / 30% 逸脱探索）
- [x] profile に含める項目（文章で固定）:
  - 優先美学（余白、リズム、対称性、ノイズ、構成など）
  - 変更方針（色から/形から/アルゴリズムから/レンジを詰める等）
  - baseline 尊重度（高/中/低）

---

## プロンプト（skills）設計メモ

各 skill の SKILL.md は「創造性」より「出力の構造」を先に固定する。

- [x] ideaman: variation axes を必須にし、抽象ムードだけの返答を禁止
- [x] artist:
  - baseline がある場合は差分方針と「何を変えたか」を必須
  - Grafix の不明点は想像で埋めない（必ずテンプレ/実行で確認）
  - 返却は Artifact JSON（成功/失敗を統一）
- [x] critic:
  - **全候補比較**を明示し、ランキング理由は短く、勝者の理由と次アクションは厚く
  - 次アクションは優先度付き、実装可能な粒度（変更対象/期待効果/副作用）で返す

---

## 実装チェックリスト（順序）

### 0) 事前確認（最小）

- [x] skill 配置場所は `./.codex/skills/` で OK？
- [x] skill 分割は 4 skill（orchestrator/ideaman/artist/critic）で OK？
- [x] contact sheet 生成に Pillow を入れる必要が出たら依存追加して良い？（Ask-first）

### 1) GrafixAdapter の “動く最小” を作る

- [x] `python -m grafix export` を叩いて PNG が出ることを、最小スケッチで確認
- [x] adapter I/F を固定し、stdout/stderr と検証（ファイル存在/サイズ）を返す

### 2) 成果物保存規約（workspace）を確定

- [x] `runs/<run_id>/iter_XX/vY/` を生成するユーティリティ
- [x] `artifact.json` / `critique.json` / `manifest.json` の保存場所と命名を固定

### 3) コンタクトシート（または代替）を用意

- [x] contact sheet: `grid.png` を作る（候補サイズ・余白・並べ方を固定）
- [ ] 代替案: 個別画像の一覧（パス + 画像サイズ）を critic に渡す

### 4) 1 反復 runner（run_one_iter）を実装

- [x] ideaman/artist/critic を「外部コマンド」で差し込める形にする（JSON をファイルに出力させる）
- [x] M 本生成→検証→critic→winner 決定→保存、までを 1 回で成立させる

### 5) N 反復 runner（run_loop）を実装

- [x] baseline と critic_feedback の持ち越しを最小 3 点に絞る
- [ ] 停滞検出（簡易で OK）と exploit/explore 比率調整を入れる（任意）

### 6) skills（SKILL.md）を実装

- [x] 4 skill の YAML frontmatter（`name` / `description`）を確定
- [x] JSON 出力仕様を `references/` に逃がし、SKILL.md を薄く保つ
- [x] 使用例（推奨 invocation）を SKILL.md に書く

### 7) スモークテスト（LLM 無しで回す）

- [x] ダミーの ideaman/artist/critic コマンドで、N=2/M=3 程度を完走できる
- [x] 失敗混入（1 件失敗）でも critic→選抜が進む

### 8) （任意）パッケージ化

- [ ] `package_skill.py` で `.skill` を生成して `dist/` に出力（配布が必要な場合のみ）

---

## 要確認（あなたに決めてもらいたいこと）

- skill 名（候補）:OK
  - `grafix-art-loop-orchestrator`
  - `grafix-art-loop-ideaman`
  - `grafix-art-loop-artist`
  - `grafix-art-loop-critic`
- contact sheet の実装方針:
  - 依存追加なしで作る（代替あり）
  - Pillow を追加して確実に作る（Ask-first）；こちらで。すでにpillowはインストール済み。
- このスキルを実行したときに生じるすべての出力の出力先はsketch/agent_loop配下にして。
