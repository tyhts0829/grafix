# Grafix Art Loop Round / Loop Refactor Plan

## 目的

- 既存の `iteration` / `iter_XX` という概念を、active な skill / reference / script / schema では `round` / `round_XX` に置き換える。
- 新しく `loop` 概念を導入し、各 round 内で各 variant が `sketch.py` 作成 → 画像出力 → 画像確認 → `sketch.py` 改善、を指定回数だけ繰り返せるようにする。
- 呼び出しパラメータを `r=<round数>, v=<variant数>, l=<loop数>` に揃える。

## この plan で置く前提

- `r` は round 数を表す。旧 `iteration` と同じ階層だが、名称は `round` に統一する。
- `v` は 1 round あたりの variant 数を表す。
- `l` は 1 round 内の各 variant が回す改善 loop 数を表す。
- round 間の独立性は維持する。`round_01` の画像 / critique / brief / sketch を `round_02` の入力に使わない。
- loop 改善は同一 `round_XX/vYY` の中だけで閉じる。別 variant や別 round の成果物は参照しない。
- round の最終 ranking / critique は、各 variant の最終 loop 出力だけを対象に作る。
- 互換ラッパーや旧名シムは作らず、active な説明と実装を新モデルに揃える。過去 run ディレクトリは履歴としてそのまま残す。

## 想定する新しい実行モデル

1. orchestrator が `run_id` を発行し、`r / v / l` を含む run 骨格を用意する。
2. ideaman が round ごとに独立した `CreativeBrief` を `v` 本作る。
3. artist は各 `round_XX/vYY` で `loop_01` から `loop_LL` まで順に実行する。
4. 各 loop で `sketch.py` を更新し、`out.png` を出し、その画像だけを見て次 loop の改善方針を決める。
5. `loop_LL` の成果物をその variant の round 最終成果物とみなす。
6. critic は `round_XX` の最終 loop 出力だけを比較し、`critique.json` を書く。
7. contact sheet は round 単位で最終 loop 出力を並べ、run 最終 summary では round contact sheet を並べる。

## 出力構造の提案

- run root: `sketch/agent_loop/runs/<run_id>/`
- round root: `.../round_XX/`
- variant root: `.../round_XX/vYY/`
- loop root: `.../round_XX/vYY/loop_ZZ/`

各 `loop_ZZ/` に保存するもの:

- `sketch.py`
- `out.png`
- `stdout.txt`
- `stderr.txt`
- `artifact.json`

各 `vYY/` に保存するもの:

- `creative_brief.json`
- `artist_context.json`

各 `round_XX/` に保存するもの:

- `critique.json`
- `contact_sheet.png`

`run_summary/` に保存するもの:

- `final_contact_sheet_8k.png`
- `skill_improvement_report.json`

補足:

- contact sheet は `round_XX/vYY/loop_ZZ/out.png` のうち、各 variant の最大 loop 番号を採用する。
- `Artifact.code_ref` / `callable_ref` / `image_ref` は final alias を持たず、実際の `loop_ZZ` パスを直接指す。

## 変更対象

- `.agents/skills/grafix-art-loop-orchestrator/SKILL.md`
- `.agents/skills/grafix-art-loop-artist/SKILL.md`
- `.agents/skills/grafix-art-loop-critic/SKILL.md`
- `.agents/skills/grafix-art-loop-ideaman/SKILL.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/grafix_artist_guide.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/contact_sheet_spec.md`
- `.agents/skills/grafix-art-loop-orchestrator/references/project_quick_map.md`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/init_run_dir.py`
- `.agents/skills/grafix-art-loop-orchestrator/scripts/make_contact_sheet.py`

必要なら追加で確認するもの:

- round / loop 名称を参照している補助 docs
- run_id 形式を明記している plan / reference

## 実装アクション

- [ ] `iteration` / `iter_XX` を active な skill / reference / schema / script で `round` / `round_XX` に置換する対象を確定する
- [ ] `r / v / l` の語義を orchestrator skill 冒頭に固定し、round 間独立と loop 内改善の境界を明文化する
- [ ] `init_run_dir.py` を `--r --v --l` 対応に変更し、run_id 形式を `run_YYYYMMDD_HHMMSS_r{r}v{v}l{l}` に更新する
- [ ] run 骨格を `round_XX/vYY/loop_ZZ` 前提に変更する
- [ ] artist guide の callable path を `sketch.agent_loop.runs.<run_id>.round_XX.vYY.loop_ZZ.sketch:draw` に更新する
- [ ] schema の `iteration` フィールドを `round` に改名し、loop を持つ JSON に `loop` フィールドを追加する
- [ ] `ArtistContext` の role contract を、「round 開始時の brief は固定、loop ごとに同一 variant の直前成果物だけ見て改善する」に書き換える
- [ ] artist skill の禁止事項を更新し、「参照可能なのは同一 variant の過去 loop のみ」と明記する
- [ ] critic skill の比較対象を「同一 round の最終 loop 出力のみ」に変更し、loop 中の self-review と round 最終 ranking を混同しないよう整理する
- [ ] ideaman skill の責務を「round ごとの fresh brief 生成」に寄せ、loop 改善に関与しないことを明記する
- [ ] `make_contact_sheet.py` を `round` 命名と最終 loop 自動解決に対応させる
- [ ] contact sheet spec の入力パス、ラベル、並び順を `round_XX` 基準へ更新する
- [ ] final summary が `round_*/contact_sheet.png` を集約するように更新する
- [ ] 新モデルで `r=3, v=4, l=5` の dry-run 相当が破綻しないことを確認する

## role ごとの整理方針

### orchestrator

- round 開始時に `CreativeBrief` を確定する。
- variant ごとに `loop_01..loop_LL` を順に回し、各 loop の生成物を保存する。
- round 最終 critic は `loop_LL` を含む「最大 loop 番号の out.png」を見る。
- round 間での改善 feed は禁止したままにする。

### ideaman

- round ごとに独立した `CreativeBrief` を `v` 本作る。
- loop 改善用の差分 brief は作らない。
- diversity 担保の責務は round の入口だけに持たせる。

### artist

- `loop_01` では brief から初稿を作る。
- `loop_02..loop_LL` では、同一 variant の直前 loop 画像と `sketch.py` を見て、完成度向上のために改稿する。
- 改稿対象は常に `loop_ZZ/sketch.py` であり、単一テンプレート量産は禁止のまま維持する。
- 同一 round の他 variant や過去 round を参照しない。

### critic

- round の最終出力比較専用 role とする。
- loop 中の画像確認は critic の責務ではなく、artist / orchestrator 内の改善処理として扱う。
- ranking は round 内完結のまま維持する。

## schema 変更の方向

`CreativeBrief`:

- round 独立性を前提に据える。構造は大きく変えない。

`ArtistContext`:

- `iteration` → `round`
- `loop` を追加
- `mode` は必要なら `independent_round_with_inner_loops` のように再定義するが、まずは既存 `independent` を維持できるか確認する
- `critic_feedback_prev` は round 間では常に `null`
- loop 内改善用に、必要最小限なら `prior_loop_artifact_ref` 追加を検討する

`Artifact`:

- `iteration` → `round`
- `loop` を追加
- `code_ref` / `callable_ref` / `image_ref` は `loop_ZZ` パスを指す

`Critique`:

- `iteration` → `round`
- ranking は最終 loop 成果物の variant 比較に限定する

## 検証観点

- [ ] `init_run_dir.py --r 3 --v 4 --l 5 --dry-run` で `round_XX/vYY/loop_ZZ` が想定どおり出る
- [ ] artist guide の render command で `loop_ZZ/sketch.py` が import 可能な module path になる
- [ ] `make_contact_sheet.py` が各 variant の最大 loop 出力を正しく拾う
- [ ] final contact sheet が `round_01`, `round_02`, ... の順で並ぶ
- [ ] active な skill / reference から `iteration` / `iter_XX` の記述が意図した場所以外で消える
- [ ] round 間 feed 禁止と loop 内改善許可が矛盾なく説明されている

## 実装しないこと

- 過去 run ディレクトリの移行
- 旧 `iter_XX` と新 `round_XX` の両対応シム
- round 間で winner を引き継ぐ改善戦略
- loop 中の別 role 追加や過剰な補助スクリプト化

## リスク

- `iteration` は JSON field / path / prose の三層に散っているため、名称変更漏れが起きやすい
- `loop` を導入すると callable path が深くなり、artist guide と実 path の不整合が起きやすい
- loop 中の「画像確認」を critic role に寄せすぎると、round 最終 critic との責務境界が崩れる
- `make_contact_sheet.py` の source 解決を複雑にしすぎると、simple な運用から外れる

## 完了条件

- active な art-loop 関連 skill / reference / script が `round` / `loop` モデルで一貫する
- `r, v, l` 指定を前提に run 骨格を作れる
- round 内 loop 改善と round 間独立が両立した説明になっている
- final critique / contact sheet / summary の対象が「各 round の最終 loop 出力」に統一されている
