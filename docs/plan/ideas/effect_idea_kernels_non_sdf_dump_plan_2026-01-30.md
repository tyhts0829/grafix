# 非SDF「アイデア核」から effect を増やす：5 つの .md 出力プラン

作成日: 2026-01-30

## 目的

`docs/plan/sdf_stripes_effect_plan_2026-01-29.md` のノリで、SDF 以外の「アイデアの核」になりやすい手法群から、effect 案（見た目 / 入出力 / パラメータ候補 / 名前案）を整理して書き出す。

## 前提（今回の “手法” リスト）

- ベクトル場（flow field / curl noise / 速度場）
- スカラー場（ノイズ / 高さ場 / ポテンシャル場）
- Voronoi / Power diagram（重み付き）
- Delaunay / 三角メッシュ・四角メッシュ
- Straight skeleton / Medial axis（骨格）
- 点過程（Poisson disk / Blue noise）
- 緩和・最適化（Lloyd / CVT）
- 差分成長（Differential growth）
- Physarum / スライムモールド（エージェント堆積）
- 反応拡散（Gray-Scott など）
- 粒子系（advection + 反発 + 境界）
- タイル / 文法（Truchet / Wang / Penrose / L-system）
- 画像 / トーン駆動（濃淡→線化、エッジ→線化）
- 座標変換（極座標 / 対数螺旋 / 写像）
- 波の干渉 / 周波数合成（sin 和 / moire）

## 確定した解釈

1. **各手法につき 5 アイデア**（A〜E）を書き出す。
2. それらを **5 本の .md** に整理して収録する（各 .md に複数手法が入る）。

3. 出力先は `docs/plan/`。

## 出力ファイル案（5 本）

> 5 本に分けつつ、上の手法を全部どこかに必ず入れる。

- `docs/plan/field_and_mapping_effect_ideas_2026-01-30.md`
  - 対象: ベクトル場 / スカラー場 / 座標変換 / 波の干渉（moire）
- `docs/plan/cells_mesh_skeleton_effect_ideas_2026-01-30.md`
  - 対象: Voronoi/Power / Delaunay・メッシュ / Straight skeleton・Medial axis
- `docs/plan/sampling_and_relaxation_effect_ideas_2026-01-30.md`
  - 対象: Poisson/Blue noise / Lloyd・CVT（＋「最小距離」「均一化」を核にした派生）
- `docs/plan/growth_and_agents_effect_ideas_2026-01-30.md`
  - 対象: Differential growth / Physarum / 反応拡散 / 粒子系
- `docs/plan/rules_and_image_driven_effect_ideas_2026-01-30.md`
  - 対象: タイル・文法 / 画像・トーン駆動（＋他手法との接続アイデア）

## 各 .md のフォーマット（たたき台）

- 先頭: 前提（1〜2 段落） / 何が “核” か / どんな見た目が得意か
- 本文: 手法ごとに「effect 案」を箇条書きで複数（例: A〜E）
  - 1 案につき:
    - ねらい（見た目の言語化）
    - 入出力（mask/base/points 等）
    - パラメータ候補（Grafix の既存 naming に寄せる）
    - 破綻しやすい点 / 制約（あれば）
    - 近い既存 effect があるなら差別化メモ（短く）

## TODO（このファイルのチェックを進める）

- [x] 依頼文の解釈（各手法×5 アイデア）を確定する
- [x] 5 本のファイル名・分類を確定する
- [x] 各ファイルの章立て（手法→案の粒度）を確定する
- [x] 5 本の .md を新規作成して書き出す
- [x] 体裁（見出し/用語）を軽く整える
