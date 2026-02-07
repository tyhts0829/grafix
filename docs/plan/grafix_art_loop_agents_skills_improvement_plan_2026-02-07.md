# Grafix Art Loop: `.agents/skills`（agent_art）改善計画

作成日: 2026-02-07

この計画は `grafix_art_loop.md` の助言（設計レバーのトークン化 / 批評→差分化 / exploration↔exploitation の分離）を、リポジトリ配下の skills 実装（`./.agents/skills/grafix-art-loop-*`）へ反映するためのチェックリストです。

---

## 背景（`grafix_art_loop.md` からの要点）

- 生成側（コード）の自由度が「デザインのレバー」ではなく「ノイズの自由度」になっていると、批評が“感想”止まりで改善が収束しない。
- 批評は「次の実装差分」に落ちるように、**ロック（保持）**と**可変（変更）**を分け、変更は最大 3 件程度に絞ると効く。
- M 並列は「別案」ではなく、**探索（exploration）**と**収束（exploitation）**の役割を分けて運用すると比較が意味を持つ。

---

## 改善ゴール（DoD）

- `CreativeBrief` に **design tokens**（palette / stroke / spacing / grid_unit / noise_scale など）が明示され、artist がそのトークンをコードに落とし込める。
- critic の `winner.next_iteration_directives` が **トークン単位の差分指示**になり、かつ「保持/変更」が機械的に読み取れる。
- orchestrator が各 variant に `mode: exploration|exploitation` を付与して渡し、序盤は探索寄り・中盤以降は収束寄りに寄せられる。

（任意）:

- critic の判断ブレを下げるため、単一 critic 内で「構図/色/技術品質/独創性」のサブ評価→統合、もしくは複数 critic の統合ができる。
- “破綻”を弾く軽量フィルタ（PIL だけで可能な範囲）を入れ、批評対象から雑さを先に落とせる。

---

## 対象（触るファイル範囲）

- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/run_one_iter.py`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/run_loop.py`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- （必要なら）`.agents/skills/grafix-art-loop-artist/references/artist_profiles/*.txt`

---

## 設計方針（シンプル優先）

- **破壊的変更 OK**（互換ラッパー/シムは作らない）。
- まずは “美しさを測る” ではなく、**制御できるレバー**と **差分指示の規約**を固定する（最優先）。
- バリデーションは最小限にし、運用は「欠けてたら fallback」ではなく「欠けてたらその場で直す」寄りにする（過度に防御しない）。

---

## 具体タスク（実装チェックリスト）

### 0) 事前整理（現状の齟齬を潰す）

- [ ] `run_one_iter.py` / `run_loop.py` の artist profile 既定パスが `.codex/...` になっているので、`.agents/...` に揃える（この repo 実体に合わせる）

### 1) スキーマ拡張：design tokens と差分指示を “構造” にする

- [ ] `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` を拡張し、最低限次を追加する
  - `CreativeBrief.design_tokens`（dict）
  - `CreativeBrief.composition_template`（例: grid / thirds / diagonal / center_focus / asym_balance）
  - `CreativeBrief.layers`（主役→副要素→テクスチャ の 3 階層を想定した配列 or dict）
- [ ] `Artifact.params` に `design_tokens_used`（実際に使ったトークン）を入れる運用を固定する
- [ ] `Critique.winner` に「ロック/可変」を明示できるフィールドを追加する（例）
  - `locked_tokens: ["palette", "composition_template", ...]`
  - `mutable_tokens: ["spacing", "density", ...]`
  - `next_iteration_directives[]` は最大 3 件、各 directive に `token_keys` と `success_criteria` を持たせる

### 2) ideaman skill 改善：抽象テーマ→実装可能レバーへ

- [ ] `.agents/skills/grafix-art-loop-ideaman/SKILL.md` を更新し、`CreativeBrief` の必須項目として
  - 構図テンプレ（composition_template）
  - design tokens（固定/レンジ/候補）
  - layers（主役/副要素/テクスチャの役割）
    を要求する
- [ ] `variation_axes` は「token をどう動かすと画がどう変わるか」に直接対応する文で書かせる（token 名を含める）
- [ ] “完全自由”を避け、パレット/線/間隔/ノイズ粒度は **少数候補**から選ばせる（探索がノイズ化しない）

### 3) artist skill 改善：コード側を「デザインのレバーがある構造」にする

- [ ] `.agents/skills/grafix-art-loop-artist/SKILL.md` を更新し、実装規約として
  - `design_tokens` をコードにそのままマップし、関数引数/定数として集約する
  - “主役→副要素→テクスチャ” の 3 レイヤー構成で組み立てる
  - `Artifact.params.design_tokens_used` を必ず埋める
  - baseline + critic 指示がある場合は **ロックされた token を絶対に変えない**
  - 変更は最大 3 トークンに絞る（critic 指示に追従）
    を明記する
- [ ] `mode: exploration|exploitation` を context で受け取った場合の方針を固定する
  - exploration: 構図テンプレ/語彙の変更を許可（ただし guardrails を置く）
  - exploitation: ロックを増やし、余白/密度/リズムなど微調整中心

### 4) critic skill 改善：批評を「差分指示」に落とす

- [ ] `.agents/skills/grafix-art-loop-critic/SKILL.md` を更新し、
  - 勝者選定理由は “厚め”
  - 変更は最大 3 件
  - `locked_tokens` / `mutable_tokens` を必ず返す
  - directive は token 指定 + 理由 + 成功条件（success_criteria）で書く
    を必須化する
- [ ] （任意）単一 critic 内でサブ評価（構図/色/技術品質/独創性）を出してから統合し、ブレを下げる（実装は JSON を増やさない範囲で）

### 5) orchestrator 改善：探索と収束の “運用” を組み込む

- [ ] `.agents/skills/grafix-art-loop-orchestrator/scripts/run_loop.py` に iteration ごとの `explore_ratio`（例: 序盤 0.7 → 終盤 0.2）を持たせ、各 variant に `mode` を付与して context に書く
- [ ] `.agents/skills/grafix-art-loop-orchestrator/scripts/run_one_iter.py` が artist_context に `mode` を渡す（profile と併用）
- [ ] winner の `design_tokens_used` と critic の `locked_tokens/mutable_tokens` を次反復へ持ち越す（baseline/feedback のどちらに載せるかを決めて固定）

### 6) （任意）破綻フィルタ / レンダ品質 / 選好スコアラー

この辺は“効くがやり過ぎると重い”ので、優先度低めで段階導入にする。

- [ ] PIL ベースの軽量フィルタ（例: ほぼ単色/真っ黒/真っ白/極端な中央過密の検出）を追加し、critic 入力前に落とす
- [ ] `grafix export` の出力品質を上げるための運用トークン（例: `render_scale`, `dpi`, `dither`, `gamma`）を design tokens に追加（Grafix 側機能がある範囲で）
- [ ] （Ask-first）CLIP 等の埋め込み + 簡易ランキングで “あなたの好み” を学習する一次選別器（依存追加/データ保存方針が要相談）

---

## 要確認（あなたに決めてもらいたい）

- design tokens の最小キーセットをどうする？（例: `palette`, `stroke`, `spacing`, `grid_unit`, `noise_scale`, `composition_template`, `layers`）
- exploration/exploitation の既定スケジュール（iteration 何回まで探索寄りにするか）
- 破綻フィルタ/レンダ品質/選好学習は今回どこまで入れる？（全部後回しでも OK）

以下の方針で
• - design tokens（最小キーセット推奨）- 必須: composition_template / vocabulary / palette / stroke / spacing / noise / grid_unit - 併せて必須（tokensとは別フィールド扱い推奨）: layers（hero/support/texture の3階層）

- exploration/exploitation（既定スケジュール推奨）
  - explore_ratio を 0.7 → 0.2 に線形減衰（N に追従）
  - 各 iteration の M 本を ceil(M\*explore_ratio) 本だけ exploration、残り exploitation（exploitation は最低1本）
  - exploration は composition_template/vocabulary の変更OK、exploitation は locked_tokens 固定で spacing/noise/stroke の微調整中心
- 今回どこまで入れる？（推奨スコープ）
  - 今回やる: tokens+layers の明文化、criticの locked_tokens/mutable_tokens + 「最大3件の差分directive（token指定+success_criteria）」、orchestratorの mode 付与
  - 今回は見送る: 選好学習（依存/データ方針が必要なので Ask-first）
  - 保留（段階導入）: 破綻フィルタはまず「計測してJSONに残す」まで、レンダ品質は tokens が固まってから（必要なら render_scale 等を追加してSSAA）
