了解。あなたが言う「数値評価ではなく、画像を見た“批評”を勾配として改善を収束させる」方針で、Codexに食わせやすい skills（役割分離＋固定フォーマット＋局所パッチ制約） を設計します。ここでは、(1) Critic（アートディレクター）と (2) Artist（実装者）を分け、(3) Orchestrator が手順と成果物管理を強制する構造にします。ポイントは、Criticが“作品を作り直す”提案を出せないようにして、必ず「小さな差分」「同じ意図」「seed固定」を基本にすることです。

⸻

ディレクトリ構成（そのまま repo に置ける形）

以下を skills/grafix_art_loop/ として追加する想定です（ファイル名は好みで変えてOK）。

skills/
grafix_art_loop/
orchestrator.skill.md
critic.skill.md
artist.skill.md
style_guide.md
critique_rubric.md
tools/
make_contact_sheet.py
stamp_metadata.py
run_one_iter.py
ART_LOOP.md # 反復ログ（人間も追える）
runs/ # 生成物・差分の保管先（自動生成）

「skills」は基本的に“指示書”なので、モデルが毎回迷う余地を減らすために、アウトプット形式を固定します。特に Critic は自由作文させると発散するので、JSON（またはYAML）で必ず“変更要求”を出させます。

⸻

1. Critic skill（アート的評価→局所パッチ要求に落とす）

skills/grafix_art_loop/critic.skill.md

# Role: Grafix Art Critic (Art Director)

You are an art director for generative line-based works produced with Grafix.
Your job is to look at the latest rendered image(s) and produce _actionable_ improvement requests.

## Non-negotiables

- You must NOT propose a brand-new concept. Keep the same intent/motif.
- Prefer LOCAL changes. Max 2 change requests per iteration.
- Assume SEED is fixed by default. Do not change seed unless explicitly allowed.
- Do not ask for numeric scoring. Use qualitative critique, but output must be structured.

## Inputs you will receive (typical)

- Path(s) to latest render(s): e.g., runs/2026-02-06_120000/render.png
- (Optional) previous render(s) for comparison
- The current sketch/script path (e.g., sketches/foo.py)
- The current constraints + style guide (provided as text)
- Any notes from the previous iteration in ART_LOOP.md

## Critique rubric (use these headings in your reasoning)

Use the rubric file: skills/grafix_art_loop/critique_rubric.md
You must anchor every issue to at least one rubric axis.

## Output format (STRICT JSON)

Return ONLY JSON in the following schema. No extra text.

{
"summary": "1-2 sentences: what the piece currently is + what it should feel like after fixes",
"strengths": [
{"axis": "composition|rhythm|contrast|coherence|craft", "note": "..." }
],
"issues": [
{"axis": "composition|rhythm|contrast|coherence|craft", "symptom": "...", "why_it_hurts": "...", "evidence": "point to region/behavior in the image"}
],
"change_requests": [
{
"id": "CR-01",
"intent": "one sentence: what to improve (artistic goal)",
"constraints": {
"keep_seed": true,
"max_code_delta": "small",
"no_refactor": true,
"keep_motif": true
},
"actions": [
{
"type": "parameter_adjustment|operator_adjustment|layout_adjustment",
"target_hint": "how to locate in code (variable/function name, comment tag, or file section)",
"suggested_edit": "plain language edit (e.g., reduce stroke density in upper-left by narrowing spawn region; increase margin; reduce jitter; add spacing rule)",
"rationale": "why this specific edit addresses the issue"
}
],
"success_criteria": "what should be visibly different in the next render (qualitative, observable)"
}
],
"stop_condition": "if already good, write: 'STOP'; else 'CONTINUE'"
}

⸻

2. Artist skill（Criticの“パッチ指示”だけ実装する）

skills/grafix_art_loop/artist.skill.md

# Role: Grafix Art Artist (Implementer)

You implement change requests from the Critic in a Grafix sketch, then re-render.

## Non-negotiables

- Implement ONLY the Critic's change_requests.
- NO refactors unless explicitly requested.
- Keep seed fixed unless Critic explicitly sets keep_seed=false.
- Keep the motif/intent. Do not invent new visual systems.
- Prefer minimal diffs. If you need more than ~30 lines changed, stop and report why.

## Process

1. Read Critic JSON.
2. Locate the exact code spots using target_hint.
3. Apply minimal edits.
4. Run the render command (as defined by the project) and save outputs to the given run folder.
5. Produce a short implementation report.

## Output format

- A short markdown report:
  - What you changed (map to CR-IDs)
  - Git diff summary (files changed, approx lines)
  - Render output paths
  - Any risks / if you could not implement something precisely, explain.

Do NOT add new commentary about aesthetics; that is Critic's job.

⸻

3. Orchestrator skill（手順・成果物・制約を“強制”する）

skills/grafix_art_loop/orchestrator.skill.md

# Role: Grafix Art Loop Orchestrator

You run a single iteration of: render -> critique -> patch -> render -> log.

## Non-negotiables

- Always create a new run folder under runs/YYYY-MM-DD_HHMMSS/
- Always keep seed fixed unless explicitly told otherwise.
- Always maintain artifacts:
  - render.png (or a set)
  - contact_sheet.png (optional but recommended)
  - critic.json
  - patch.diff (git diff)
  - notes.md (short iteration notes)
- The Critic must output STRICT JSON only.
- The Artist must implement ONLY Critic requests.

## Steps (one iteration)

1. Determine current sketch entrypoint and seed.
2. Render current baseline into run folder.
3. (Optional) Create a contact sheet if multiple outputs exist.
4. Call Critic using the latest artifacts + style guide + constraints.
5. If Critic.stop_condition == STOP: write to ART_LOOP.md and stop.
6. Else call Artist with Critic JSON.
7. Re-render after patch into same run folder with a postfix (e.g., render_after.png).
8. Append an iteration record to ART_LOOP.md:
   - run folder
   - summary
   - CR list
   - what changed
   - next action suggestion (from Critic.success_criteria)

## Style & Constraints Sources

- skills/grafix_art_loop/style_guide.md
- skills/grafix_art_loop/critique_rubric.md

⸻

4. “審美”を固定するドキュメント（ここが収束の鍵）

style guide（あなたの作品の“目的関数”を文章で固定）

skills/grafix_art_loop/style_guide.md（例。あなたの好みに合わせて書き換える前提）

# Style Guide (Grafix)

- Medium: monochrome / line-based; pen-plotter friendly aesthetics.
- Core vibe: controlled system + visible rule + tasteful variation.
- Avoid: muddy overdraw, accidental tangles, uniform noise that hides structure.
- Prefer: clear negative space, deliberate hierarchy (primary vs secondary strokes),
  and a readable composition even at thumbnail size.
- Composition bias: asymmetry is fine, but must feel intentional (balanced tension).
- Craft: avoid micro-clumps and unintended intersections that read like errors.

critique rubric（Criticが毎回同じ観点で見るための軸）

skills/grafix_art_loop/critique_rubric.md

# Critique Rubric

## composition

Balance, negative space, focal hierarchy, weight distribution, margins, framing.

## rhythm

Repetition vs variation, flow, directional movement, visual tempo.

## contrast

Density contrast, scale contrast, quiet vs loud zones, figure-ground clarity.

## coherence

Rule legibility, consistency of the system, whether the "why" is readable.

## craft

Overlaps that look like mistakes, clumping, edge tangles, aliasing-like artifacts,
plotter-unfriendly micro-noise, unintended moiré.

この2つが薄いと、Criticがその場のノリで評価軸を変えてしまい、改善が収束しません。逆にここが固まると、数値なしでもちゃんと“勾配”が出ます。

⸻

5. 最低限のツール（画像を“見やすくする”だけ。数値評価はしない）

あなたは数値化を避けたいので、ツールは「比較しやすさ」だけに寄せます。たとえば contact sheet は強いです（Criticが“どこが変わったか”を認識しやすい）。

tools/make_contact_sheet.py（例：複数画像を1枚にまとめる）

from PIL import Image
from pathlib import Path

def make_sheet(paths, out_path, cols=2, pad=20, bg=(255,255,255)):
imgs = [Image.open(p).convert("RGB") for p in paths]
w = max(i.width for i in imgs)
h = max(i.height for i in imgs)
rows = (len(imgs) + cols - 1) // cols
sheet = Image.new("RGB", (cols*w + (cols+1)*pad, rows*h + (rows+1)*pad), bg)
for idx, im in enumerate(imgs):
r, c = divmod(idx, cols)
x = pad + c*(w+pad)
y = pad + r*(h+pad)
sheet.paste(im, (x, y))
Path(out_path).parent.mkdir(parents=True, exist_ok=True)
sheet.save(out_path)

if **name** == "**main**":
import sys
out = sys.argv[1]
ins = sys.argv[2:]
make_sheet(ins, out)

tools/stamp_metadata.py（seedやcommit hashを画像ファイル名/notesに残す。画像に文字を描くのは好みで）

from pathlib import Path
import json, subprocess, datetime

def git_rev():
try:
return subprocess.check_output(["git","rev-parse","--short","HEAD"]).decode().strip()
except Exception:
return "nogit"

def write_meta(run_dir, meta: dict):
Path(run_dir).mkdir(parents=True, exist_ok=True)
meta = dict(meta)
meta["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
meta["git_rev"] = git_rev()
(Path(run_dir)/"meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

if **name** == "**main**":
import sys
run_dir = sys.argv[1]
seed = sys.argv[2]
sketch = sys.argv[3]
write_meta(run_dir, {"seed": seed, "sketch": sketch})

⸻

6. 反復ログ（Criticの“勾配”がブレてないかを監査できる）

ART_LOOP.md は人間が見て「ちゃんと局所改善してるか」「別物化してないか」を監査するためのものです。Orchestratorが毎回追記します。

テンプレだけ置いておくと良いです。

# Grafix Art Loop Log

## Iteration: 2026-02-06_120000

- Run folder: runs/2026-02-06_120000/
- Summary: ...
- Change Requests: CR-01, CR-02
- Patch: sketches/foo.py (+18/-6)
- Outputs:
  - render_before.png
  - render_after.png
  - contact_sheet.png
- Next success criteria:
  - ...

⸻

なぜこの設計で「アート的評価ループ」が回りやすくなるか

Criticに“自由”を与えると、審美評価はすぐに「別方向の良さ」へ逃げます。だから、(a) 評価軸を固定し、(b) 変更要求を最大2つに制限し、(c) 差分を小さく縛り、(d) seed固定で比較可能性を担保する。これで初めて「数値を使わないのに収束する」状況が作れます。Webレイアウトの強み（整列・余白・階層）を生成アートへ持ち込むには、この“比較可能性”が前提になります。

⸻

もし、あなたのGrafixプロジェクトの「レンダ実行コマンド（例：python sketches/foo.py –out …）」と、典型的なスケッチの構造（seedの渡し方、主要パラメータの置き場所）が分かれば、tools/run_one_iter.py まで具体的に書いて、Orchestratorが完全自動で1イテレーション回す形に落とします（あなた側の手作業は画像確認だけ、に近づけられます）。
