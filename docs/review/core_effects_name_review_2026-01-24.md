<!--
どこで: `docs/review/core_effects_name_review_2026-01-24.md`。
何を: `src/grafix/core/effects/` 配下の effect 名（effect_registry 登録名 / ファイル名）の命名レビュー結果。
なぜ: API の一貫性と探索性（「何ができるか」を名前から推測できる度合い）を上げるため。
-->

# core/effects エフェクト名レビュー（2026-01-24）

対象:

- `src/grafix/core/effects/`（組み込み 26 effect）
- “エフェクト名” は **effect_registry の登録名**（= `@effect` の関数名、`E.<name>(...)` で使う名前）
- 補助的にファイル名（`src/grafix/core/effects/<name>.py`）も確認

観点（絞り込み）:

- 命名の一貫性
- 意味の明確さ
- 動詞/名詞の揃い
- 略語の妥当性
- 否定形/反転/強度系の表現

一覧（全 26）:

`affine`, `bold`, `buffer`, `clip`, `collapse`, `dash`, `displace`, `drop`, `extrude`, `fill`, `metaball`, `mirror`, `mirror3d`, `partition`, `pixelate`, `quantize`, `relax`, `repeat`, `rotate`, `scale`, `subdivide`, `translate`, `trim`, `twist`, `weave`, `wobble`

## 全体所見（短く）

- 命名形態は概ね「小文字 1 語」で揃っており、`E.<name>(...)` のチェーン記法と相性が良い（タイプ量が少ない）。
- transform 系（`translate`/`rotate`/`scale`/`affine`）は直感的で良い。
- 手法名・見た目名（`metaball`/`buffer`/`bold`/`weave`/`wobble` など）も混在しているが、creative coding の文脈では許容範囲。
- 改善余地が出やすいのは、一般語すぎる/別意味を想起しやすい名前（例: `fill`, `drop`, `collapse`, `partition`）。ただし短さの利点も大きいので、改名するなら “API 破壊に見合うか” の判断が必要。

## 個別レビュー

### `affine`（`src/grafix/core/effects/affine.py`）

- 概要: スケール・回転・平行移動を一括で適用する合成アフィン変換。
- 良い: 数学/CG の用語として定番で、`scale/rotate/translate` と関係が明確。
- 気になる: “一括 transform” を期待する人には `transform` の方が直感的かもしれないが、`affine` は精確。
- 変更案: 基本は維持。もし「transform の総称」を増やしたいなら `transform`（または `xform`）も候補。

### `bold`（`src/grafix/core/effects/bold.py`）

- 概要: 同じ線を微小オフセットで複製して太線風にする（インクの重なり表現）。
- 良い: “太くする” 連想が強く短い。
- 気になる: タイポグラフィ文脈の “bold” を想起しやすく、「線の複製 + ジッター」まで伝わらない可能性。
- 変更案: より具体にするなら `thicken` / `multistroke` / `ink` など。ただし短さは `bold` が勝つ。

### `buffer`（`src/grafix/core/effects/buffer.py`）

- 概要: 推定平面へ射影し、（Shapely の）buffer でオフセット輪郭を生成する。
- 良い: 幾何/GIS では “buffer=オフセット” が定番で、実装とも一致。
- 気になる: 一般のプログラミング用語（メモリ buffer）を連想する人には直感的でない可能性。
- 変更案: もし一般向けに寄せるなら `offset` / `outline` / `dilate` が候補（ただし `buffer` は専門的には正しい）。

### `clip`（`src/grafix/core/effects/clip.py`）

- 概要: 閉曲線マスクの内側/外側へポリライン列をクリップ（multi-input）。
- 良い: 2D/CG の標準語で理解されやすい。`mode=inside/outside` とも整合。
- 気になる: `clip` は “切り抜き/マスク” 両方を指すので、入力が 2 つ必要な点が名前からは分かりにくい。
- 変更案: multi-input を強調するなら `mask` / `clip_mask` / `clip_by_mask` など。

### `collapse`（`src/grafix/core/effects/collapse.py`）

- 概要: 線分を細分化し、局所ランダム変位で「崩し」を作る。
- 良い: 日本語の “崩す” には合う。音感が強く、表現系として覚えやすい。
- 気になる: 英語の “collapse” は「潰す/折り畳む/崩壊させる」広い意味で、ランダム変位（ノイズ）まで想像しづらい可能性。
- 変更案: 目的が “ノイズで崩す” に寄るなら `crumble` / `shatter` / `jitter` / `breakup` など。

### `dash`（`src/grafix/core/effects/dash.py`）

- 概要: dash/gap パターンで切り出して破線化する。
- 良い: 破線の標準語。短く明確。
- 気になる: なし。
- 変更案: なし（維持）。

### `displace`（`src/grafix/core/effects/displace.py`）

- 概要: 3D ノイズ由来の変位を各頂点へ加える。
- 良い: VFX/CG で一般的な “displacement”。`wobble` と使い分けもしやすい。
- 気になる: なし（意図が伝わる）。
- 変更案: なし（維持）。

### `drop`（`src/grafix/core/effects/drop.py`）

- 概要: ポリライン（線/面）を条件で間引き、選択されたものだけを残す/捨てる。
- 良い: “落とす” 連想で、要素削除系としては自然。
- 気になる: “drop shadow” や “落下” など別の意味も強く、何を drop するか（線？頂点？）が名前だけでは曖昧。
- 変更案: 意味を寄せるなら `filter` / `cull` / `select` / `keep`（keep_mode と一緒に意味が通りやすい）。

### `extrude`（`src/grafix/core/effects/extrude.py`）

- 概要: 押し出しで複製線と側面エッジを生成する。
- 良い: 3D/モデリング標準語。挙動が想像しやすい。
- 気になる: なし。
- 変更案: なし（維持）。

### `fill`（`src/grafix/core/effects/fill.py`）

- 概要: 閉領域へハッチ線分を生成する（ハッチ塗りつぶし）。
- 良い: “中を埋める” という意味では最短で通る。
- 気になる: `fill` は一般に「ベタ塗り」や「面の生成」を想起しやすく、実際は “hatch” なので誤解の余地がある。
- 変更案: より正確には `hatch` / `hatch_fill` / `hatching`。短さ優先なら `fill` 維持もあり。

### `metaball`（`src/grafix/core/effects/metaball.py`）

- 概要: 距離場で閉曲線群をブレンドし、等値線（輪郭）を生成する。
- 良い: 手法名として定番で、期待する表現が強い。
- 気になる: 初学者には意味が分からない可能性はあるが、creative coding では許容。
- 変更案: アルゴリズム寄りにするなら `field_contour` / `iso_contour` など（ただし “metaball” の通りやすさは強い）。

### `mirror`（`src/grafix/core/effects/mirror.py`）

- 概要: 対称変換で複製し、ミラー対称パターンを作る。
- 良い: 直感的で標準的。`mirror3d` との対も分かりやすい。
- 気になる: なし。
- 変更案: なし（維持）。

### `mirror3d`（`src/grafix/core/effects/mirror3d.py`）

- 概要: 3D 空間での放射状ミラー（くさび + 回転 / 多面体対称）。
- 良い: `mirror` の 3D 版であることが即分かる。
- 気になる: `3d` だけ表記スタイルが特殊（数字入り）。ただし現状は「全て 1 語」スタイルなので、むしろ一貫しているとも言える。
- 変更案: スタイル統一を強めるなら `mirror_3d`（ただし API 破壊）。現状維持でも十分。

### `partition`（`src/grafix/core/effects/partition.py`）

- 概要: 閉ループ群を Voronoi 図で分割し、部分領域の閉ループ群を返す。
- 良い: “分割する” 意味としては正しい。短くて呼びやすい。
- 気になる: 具体性が低く、何で partition するか（Voronoi）が名前から分からない。
- 変更案: 表現を前面に出すなら `voronoi` / `voronoi_partition` / `voronoi_split`。

### `pixelate`（`src/grafix/core/effects/pixelate.py`）

- 概要: ポリラインをグリッド上の階段（水平/垂直）線に変換する。
- 良い: グリッド化/ドット化の連想で理解しやすい。
- 気になる: “ラスタ化” を想起する人にはズレる可能性はあるが、表現としては近い。
- 変更案: より形状寄りなら `staircase` / `gridwalk` など。現状維持で問題なし。

### `quantize`（`src/grafix/core/effects/quantize.py`）

- 概要: 座標をグリッドへ量子化（スナップ）する。
- 良い: 信号処理/CG で一般的な “quantize”。`pixelate` と並べたときの意味の階層も良い。
- 気になる: “色の量子化” の連想があるが、step が vec3 なので座標系だと分かる。
- 変更案: より直感に寄せるなら `snap`（短い）が候補。

### `relax`（`src/grafix/core/effects/relax.py`）

- 概要: 線分ネットワークをグラフとして扱い、弾性緩和で形を整える。
- 良い: 物理/最適化の “relaxation” を想起させ、意味が通る。
- 気になる: “smooth” と違って意味が強いので、初見では何が起こるか想像しづらい可能性はある。
- 変更案: もし “平滑化” に寄せていくなら `smooth`（ただし今のアルゴリズムは弾性緩和なので `relax` が正確）。

### `repeat`（`src/grafix/core/effects/repeat.py`）

- 概要: ジオメトリを複製し、各コピーへ変換を補間適用する。
- 良い: 直感的で、パターン生成の入口として分かりやすい。
- 気になる: “単純複製” か “変換を伴う複製” かは名前だけでは区別しにくい。
- 変更案: より意味を乗せるなら `replicate` / `array` / `duplicate`（ただし短さでは `repeat` が強い）。

### `rotate`（`src/grafix/core/effects/rotate.py`）

- 概要: XYZ 回転を適用する。
- 良い: 明確で標準的。
- 気になる: なし。
- 変更案: なし（維持）。

### `scale`（`src/grafix/core/effects/scale.py`）

- 概要: スケール変換を適用する（mode/auto_center/pivot 対応）。
- 良い: 明確で標準的。
- 気になる: なし。
- 変更案: なし（維持）。

### `subdivide`（`src/grafix/core/effects/subdivide.py`）

- 概要: 中点挿入で頂点密度を増やす。
- 良い: 幾何の標準語で、処理内容に一致。
- 気になる: なし。
- 変更案: なし（維持）。

### `translate`（`src/grafix/core/effects/translate.py`）

- 概要: XYZ オフセット加算で平行移動する。
- 良い: 明確で標準的。
- 気になる: なし。
- 変更案: なし（維持）。

### `trim`（`src/grafix/core/effects/trim.py`）

- 概要: ポリライン全長に対する正規化位置で区間を切り出す（指定部分だけ残す）。
- 良い: “端を切る/刈り込む” 連想で、部分取り出しに合う。
- 気になる: “先頭/末尾を少し削る” 程度を想像する人もいて、`start/end_param` の「区間選択」まで伝わらない可能性。
- 変更案: 意味を明確にするなら `slice` / `segment` / `subpath` など。

### `twist`（`src/grafix/core/effects/twist.py`）

- 概要: 位置に応じて指定軸回りにねじる。
- 良い: 動作が想像しやすく、短い。
- 気になる: なし。
- 変更案: なし（維持）。

### `weave`（`src/grafix/core/effects/weave.py`）

- 概要: 閉曲線からウェブ（糸）状の線分ネットワークを生成する。
- 良い: 表現（織る/編む/糸）を強く連想させ、creative coding と相性が良い。
- 気になる: “weave=織物パターン” を想像すると、アルゴリズム（内部に線分ネットを張る）とズレる人はいるかもしれない。
- 変更案: より中立にするなら `web` / `webify` / `string_art`（ただし作品寄りの語になる）。

### `wobble`（`src/grafix/core/effects/wobble.py`）

- 概要: サイン波でゆらして手書き風のたわみを加える。
- 良い: “ゆれる/ぶれる” が直感的で分かりやすい。`displace` と併用もしやすい。
- 気になる: なし。
- 変更案: なし（維持）。

