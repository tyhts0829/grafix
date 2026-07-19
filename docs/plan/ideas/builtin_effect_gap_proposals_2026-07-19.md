<!--
どこで: `docs/plan/ideas/builtin_effect_gap_proposals_2026-07-19.md`。
何を: 現行の組み込み effect を棚卸しし、追加候補を優先度付きで提案する。
なぜ: 過去のアイデア集をそのまま増補するのではなく、現在も残る空白へ次の投資を絞るため。
-->

# 現行 built-in effect を踏まえた追加候補（2026-07-19）

- ステータス: Phase A / B の 5 effect は実装・検証済み。Phase C / D は未着手
- 調査時 HEAD: `cc484fa`
- 調査基準: 2026-07-19 の current working tree
- 実装計画:
  `docs/plan/five_foundational_effects_implementation_plan_2026-07-19.md`
- 対象:
  - `src/grafix/core/builtins.py`
  - `src/grafix/core/effects/*.py`
  - `src/grafix/api/effects.py`
  - `src/grafix/core/effect_registry.py`
  - `sketch/` の現役例

## 結論

新しい生成アルゴリズムを先に増やすより、まず次の 5 effect を追加する価値が高い。

1. `resample`: 弧長等間隔へ再標本化する
2. `simplify`: 見た目を保ちながら頂点を減らす
3. `deduplicate`: 重複セグメントを除去する
4. `boolean`: 閉領域同士を論理演算する
5. `offset_curve`: 開曲線を含む片側・両側の平行線を作る

これらは単体の派手さよりも、既存の `fill`、`displace`、`buffer`、`partition`、
`isocontour`、`growth`、`reaction_diffusion` などの前後に置いたときの効果が大きい。
その次に、3D をプロット面へ焼き込む `perspective`、解析写像の
`conformal_map`、場の積分変形である `advect`、ガイド曲線へ沿わせる
`path_deform` を追加すると、現在薄い「大域的な非線形変形」を補える。

## 実装記録（2026-07-19）

Phase A / B の `resample`、`simplify`、`deduplicate`、`boolean`、
`offset_curve` を built-in として追加し、公開 stub、metadata、代表デモ、
benchmark、focused / full test を更新した。詳細な契約、実装上の判断、検証結果は
上記の実装計画に記録している。

この追加により built-in effect は 37 件、二入力 effect は `clip`、`warp`、
`boolean` の 3 件になった。以下の「32 件、二入力 2 件」という記述は、
追加前に不足領域を判断した**調査時スナップショット**として残す。
Phase C / D の候補は今回実装していない。

## 1. 現状の棚卸し

調査時点の組み込み effect は 32 件ある。30 件が単一入力で、二入力は
`clip(base, mask)` と `warp(base, mask)` の 2 件だけである。

| 領域 | 現行 effect | 現状の強み |
|---|---|---|
| 基本変換・複製 | `affine`, `translate`, `rotate`, `scale`, `repeat`, `mirror`, `mirror3d`, `twist`, `extrude` | 配置、対称、反復、簡単な 3D 構築が一通りそろう |
| パス編集・信号処理 | `subdivide`, `trim`, `dash`, `lowpass`, `highpass`, `quantize`, `pixelate` | 弧長処理、周波数処理、グリッド表現がある |
| 線の質感・変位 | `bold`, `wobble`, `displace`, `collapse` | 規則的な揺れ、連続ノイズ、ランダムな崩しを使い分けられる |
| 平面領域・マスク | `fill`, `buffer`, `clip`, `partition`, `metaball`, `isocontour`, `warp` | hatch、SDF、Voronoi、局所変形が厚い |
| 選別・ネットワーク・シミュレーション | `drop`, `weave`, `growth`, `relax`, `reaction_diffusion` | 線の選別から有機的な生成まで幅がある |

`sketch/` の現役例では、特に `fill`、`repeat`、`affine`、`rotate`、
`displace`、`buffer`、`subdivide` の利用が多い。これは、用途の狭い大規模
シミュレーションよりも、短いチェーンへ何度も挿せる小さな effect の方が
作品全体へ波及しやすいことを示唆する。

### 現在も残る主な空白

1. **線の前処理・後処理**
   - `subdivide` の逆に当たる簡略化がない。
   - `lowpass` / `highpass` 内部の再標本化を、単独では利用できない。
   - 重複線を明示的に消す方法がない。
2. **平面幾何の基本演算**
   - `clip` は開線をマスクで切る処理で、閉領域同士の Boolean ではない。
   - `buffer` は太らせた領域の輪郭で、開線の片側 parallel offset ではない。
3. **大域的な非線形変形**
   - `displace` は点ごとのノイズ変位、`warp` はマスク SDF による局所変形である。
   - 任意ガイド曲線、流れの積分、解析写像に沿う変形がない。
4. **3D からプロット面への変換**
   - 3D geometry は作れるが、遠近投影を XY へ焼き込む effect がない。
5. **ペンプロッタ固有の線設計**
   - 重複描画、交差の上下、連続充填、意図的な stroke 接続を geometry 段階で扱えない。

## 2. 優先度

### 優先度の意味

- **P0**: 既存 effect の多くを改善し、現在の共通基盤を再利用して実装できる。
- **P1**: 新しい視覚語彙を明確に増やす。代表作例と一緒に追加したい。
- **P2**: 有望だが、計算量、トポロジー、API のいずれかに研究要素がある。

### 候補一覧

| 候補 | 優先度 | 難易度 | 主な価値 | 既存実装の再利用 |
|---|---:|---:|---|---|
| `resample` | P0 | 低 | 点密度の正規化、後段 effect の安定化 | `ResamplePlan`, `resample_polylines` |
| `simplify` | P0 | 低〜中 | SVG/G-code と重い後段処理の軽量化 | packed geometry、resource budget |
| `deduplicate` | P0〜P1 | 中 | 重ね描きとインク溜まりの防止 | packed geometry、空間量子化 |
| `boolean` | P0〜P1 | 中 | 複合マスク、ロゴ、切り欠きの構成 | `PlanarFrame`, Pyclipper/Shapely |
| `offset_curve` | P1 | 中 | 開線の平行線、多重輪郭、製図表現 | `PlanarFrame`, Shapely |
| `perspective` | P1 | 低〜中 | 3D 線画を遠近付き 2D へ焼き込む | transform、segment clip |
| `conformal_map` | P1 | 中 | Möbius、指数、円反転などの解析写像 | resample、polyline split |
| `advect` | P1 | 中〜高 | 流れに沿う一貫した変形 | resample、noise kernel の util 化 |
| `path_deform` | P1〜P2 | 中 | 文字や格子を任意曲線へ沿わせる | arc length、`PlanarFrame` |
| `stipple` | P2 | 中〜高 | hatch 以外の面表現 | even-odd mask、空間 grid |
| `overunder` | P2 | 中〜高 | 交差へ編み込みの上下関係を与える | intersection・弧長分割の util 化 |
| `spiral_fill` | P2 | 高 | 少ない pen-up で領域を連続充填する | `PlanarFrame`、mask/SDF util |
| `stitch` | P2 | 中 | 短い stroke を意図的な接続線でまとめる | endpoint index、path traversal |

## 3. 最優先候補

### 3.1 `E.resample(step, closed="auto")`

**ねらい**

- ポリラインを 3D 弧長基準の等間隔点列へ変換する。
- `displace`、`wobble`、`twist`、`dash` の効き方を入力頂点密度から切り離す。
- 過密入力は減らし、疎な入力は増やせる一つの入口にする。

**既存 effect との差**

- `subdivide` は各線分へ中点を反復挿入するため、元の不均一な点密度を保ち、
  ダウンサンプルもできない。
- `lowpass` / `highpass` は内部で等弧長化するが、必ずフィルタ処理も行う。

**API たたき台**

```python
prepared = E.resample(step=0.5, closed="auto")(geometry)
```

- `step`: 座標単位での目標点間隔
- `closed`: `"auto" | "open" | "closed"`

**実装上の要点**

- `src/grafix/core/effects/util.py` の `ResamplePlan` と
  `resample_polylines` を薄く公開する。
- 開線の両端と、閉線の終点＝始点を維持する。
- `step <= 0`、長さ 0、出力上限超過の挙動を既存 resample 契約へ合わせる。

### 3.2 `E.simplify(tolerance, closed="auto")`

**ねらい**

- 見た目を指定誤差内に保ちながら頂点数を減らす。
- marching squares、simulation、高密度 primitive の出力を軽くする。
- preview、SVG、G-code、後続 effect のすべてへ効果を波及させる。

**既存 effect との差**

- `drop` は線または面を条件で選別する effect で、形状誤差を制御しない。
- `lowpass` は形を滑らかに変え、頂点削減を目的にしない。

**API たたき台**

```python
lighter = E.simplify(tolerance=0.05, closed="auto")(geometry)
```

**実装上の要点**

- v1 は XYZ 距離による iterative Ramer-Douglas-Peucker に限定する。
- 開線の端点を必ず維持する。
- 閉線は seam の選び方と tie-break を固定し、再び終点＝始点にする。
- 閉リングを 3 個未満の固有頂点へ潰さない。

### 3.3 `E.deduplicate(tolerance, merge_chains=True)`

**ねらい**

- `concat`、`repeat`、`mirror`、多面体の面境界などから生じる重複描画を除く。
- 同じ場所を何度も描くことによるインク溜まりと無駄な描画時間を防ぐ。

**既存機能との差**

- 一部 effect は自分が生成したコピーだけを内部で deduplicate するが、
  任意のチェーン結果へ適用できる公開 effect はない。
- G-code の travel optimization は stroke の順序と向きを変える処理であり、
  描画セグメント自体は除去しない。

**API たたき台**

```python
cleaned = E.deduplicate(
    tolerance=1e-4,
    merge_chains=True,
)(geometry)
```

**実装上の要点**

- v1 は「完全一致または tolerance 内で端点が一致する直線セグメント」に限定する。
- 端点を量子化し、向きを無視した canonical key で一意化する。
- `merge_chains=True` では残った edge を決定的な graph traversal で再連結する。
- 意図的な overdraw を壊すため、既定では自動適用せず明示 effect のままにする。

### 3.4 `E.boolean(mode)(a, b)`

**ねらい**

- 閉領域同士の `union`、`intersection`、`difference`、`xor` を提供する。
- 複合マスク、窓抜き、ロゴ、文字と図形の構成を Python 側の独自処理なしで行う。

**既存 effect との差**

- `clip` は base の開線を mask の内側または外側へ切る。
- `buffer(union=True)` は同じ入力を膨張・収縮してから統合する。
- 閉領域同士の差、交差、排他的論理和は現在ない。

**API たたき台**

```python
cutout = E.boolean(
    mode="difference",
)(outer, holes)
```

**実装上の要点**

- 二入力を同一 `PlanarFrame` へ写し、閉リング群を even-odd 領域として扱う。
- 既存依存の Pyclipper または Shapely を使い、新しい依存を増やさない。
- `difference` の入力順、穴の winding に依存しない出力、ring の決定的な並びを定義する。
- 二入力 effect は現 API 上チェーン先頭だけに置けることを、例と Help に明記する。

### 3.5 `E.offset_curve(distance, side, count)`

**ねらい**

- 開線・閉線の片側または両側へ、曲線としての平行線を作る。
- 製図的な多重線、版画の輪郭、等間隔のレール表現を作る。

**既存 effect との差**

- `buffer` は開線を太らせた閉じたカプセル領域の輪郭を返す。
- `isocontour` は閉領域の grid SDF から距離レベルを返す。
- `offset_curve` は入力ポリライン単位の向きと同一性を保つ。

**API たたき台**

```python
rails = E.offset_curve(
    distance=1.0,
    side="both",
    count=3,
    join="round",
    keep_original=True,
)(geometry)
```

- `count > 1` では `distance`, `2 * distance`, ... の位置へ生成する。
- `side`: `"left" | "right" | "both"`
- `join`: `"round" | "mitre" | "bevel"`

**実装上の要点**

- v1 は `PlanarFrame` で扱える平面入力に限定する。
- left/right は入力ポリラインの向きに対して定義する。
- cusp、鋭角、自己交差によって一つの線が複数へ分かれることを許容する。

## 4. 次に増やしたい視覚語彙

### 4.1 `E.perspective(...)`

3D geometry を透視投影し、最終的な XY ポリラインへ焼き込む。
`polyhedron`、`sphere`、`torus`、`extrude`、`mirror3d` の利用範囲を広げる。

```python
projected = E.perspective(
    focal_length=300.0,
    camera_z=500.0,
    near=1.0,
    auto_center=True,
)(E.rotate(rotation=(25.0, 35.0, 0.0))(geometry))
```

- camera と near plane の符号規約を先に固定する。
- near plane を横切る segment は交点で clip し、特異点による座標暴走を防ぐ。
- 出力は Z=0 へ平面化し、原則としてチェーン末尾へ置く。
- hidden-line removal は face 情報がないため、この effect の責務に含めない。

### 4.2 `E.conformal_map(...)`

XY を複素数とみなし、Möbius、指数写像、円反転などで変形する。
`warp` の局所 SDF blend と違い、解析写像による大域的な変形を提供する。

これは新規に再設計せず、既存の
`docs/plan/conformal_map_effect_plan_2026-02-19.md` を現行 API と
`PlanarFrame` / resample 基盤へ合わせて更新するのがよい。
特異点をまたぐ長い線分が chord にならないよう、`resample` を先に実装する。

### 4.3 `E.advect(...)`

各点を built-in vector field に沿って複数 step 移流する。

```python
flowed = (
    E.resample(step=0.5)
    .advect(
        kind="curl_noise",
        strength=1.0,
        steps=12,
        step_size=0.5,
        frequency=0.02,
        phase=0.0,
        seed=0,
    )
)(geometry)
```

- `displace` は場を一度サンプルして変位するが、`advect` は速度場を積分する。
- v1 は `"vortex" | "curl_noise" | "wave"` の有限 choice に限定する。
- callable や mutable な field object は Geometry ID、GUI、stub と相性が悪いため受け取らない。
- RK2 程度の固定積分法とし、`steps` の上限と work diagnostics を持つ。

### 4.4 `E.path_deform(base, guide)`

base の X を guide の弧長、Y を guide の局所法線方向へ写し、
文字、格子、ハッチを任意曲線へ沿わせる。

```python
curved_text = E.path_deform(
    fit="stretch",
    normal_scale=1.0,
    offset=0.0,
)(text_geometry, guide_curve)
```

- v1 は共通平面上の base と、一本の開 guide に限定する。
- 3D guide は parallel transport の仕様が必要になるため後回しにする。
- guide の長さ 0、cusp、閉曲線 seam、base の範囲外をどう扱うか明記する。
- 二入力 effect なのでチェーン先頭だけに置ける。

## 5. ペンプロッタ表現の追加候補

### `E.stipple(mask)`

even-odd mask 内へ blue-noise 点を置き、小さな loop、cross、dash として線化する。
一点 polyline は機種依存で描けないため、必ず plotter-safe な glyph を出力する。

```python
dots = E.stipple(
    spacing=3.0,
    glyph="loop",
    glyph_size=0.4,
    seed=0,
)(mask)
```

`fill` の平行 hatch、`partition` の cell、`reaction_diffusion` の等値線とは
異なる面の語彙になる。glyph 数、線数、頂点数を確保前に見積もる必要がある。

### `E.overunder(gap, mode)`

線同士の交点で片方を短く切り、交互に上下する編み込み表現を作る。
`weave` がネットワーク自体を生成するのに対し、`overunder` は任意の既存線へ
交差規則を与える後処理である。

v1 は XY 平面、通常の横断交差、`"alternate" | "line_order" | "random"` に絞る。
共線 overlap、端点接触、多重点は無理に解釈せず、明文化した規則で無視する。

### `E.spiral_fill(mask)`

内側 offset を繰り返し、隣り合う loop を mask 内の bridge で結んで、
少数の連続線として領域を埋める。独立 hatch segment を多数返す `fill`、
独立 loop を返す `isocontour` と異なり、pen-up の少なさを出力形状の核にする。

穴、分岐、offset の消滅点で必ず一本にできるとは限らないため、
「一本線」ではなく「可能な範囲で最少の連続線」を契約にする。

### `E.stitch(max_gap)`

近接する stroke の端点を、明示的な connector segment で接続する。
G-code export には travel optimization と `bridge_draw_distance` があるが、
`stitch` では接続線が Geometry の一部になるため、preview、後続 effect、
SVG、G-code の結果が一致する。

作品を変える処理なので `max_gap` を必須の安全境界とし、向き反転の許可、
閉 loop の除外、同距離候補の tie-break を決定的にする。

## 6. 新規 effect にせず既存機能へ寄せる案

| 欲しい見た目・操作 | 判断 |
|---|---|
| 一般的な smooth | `lowpass` があるため新設しない |
| crosshatch | `fill` の複数 angle set を使い、新設しない |
| 等間隔の内外 contour | `isocontour` を使い、新設しない |
| kaleidoscope | `mirror`, `mirror3d`, `repeat` へ寄せる |
| Voronoi cells / crackle | まず `partition` に `output="cells"` / `output="edges"` を足せるか検討する |
| differential growth | `growth` の seed / guide 拡張として検討する |
| reaction-diffusion の別 preset | `reaction_diffusion` の preset / output 拡張へ寄せる |
| lens / SDF attract | 統合済みの `warp` へ寄せる |
| random jitter | `displace`, `wobble`, `collapse` を使い分ける |
| shear / 4x4 matrix | 新設前に `affine` の不足パラメータとして追加を検討する |
| corner fillet / chamfer | 有用だが、まず `resample` / `simplify` 後の小さな独立候補として保留する |

## 7. 今は effect 化を勧めないもの

### `hidden_line`

3D plot には有用だが、現行 Geometry はポリライン列で、面、法線、深度面の
トポロジーを持たない。線だけから一般的な隠線消去を推測する effect は契約が曖昧になる。
先に face 表現または明示的な occluder 入力を設計すべきである。

### 任意画像・任意 field を受け取る effect

現行 effect の入力は Geometry と immutable なパラメータである。
画像、callable、mutable field を直接受け取ると、cache key、source reload、
Parameter GUI、stub の契約が崩れる。先に resource 入力を Geometry DAG へどう表すかを
決めるべきである。`stipple` や `advect` の v1 は Geometry mask と built-in choice に絞る。

### 汎用 geometry morph

線の本数、対応順、向き、開閉、頂点数が異なる二入力を自動対応させる問題が
effect 本体より大きい。実装するなら、最初は「同じ line 数・同じ頂点数」の strict mode
だけに限定し、別タスクで妥当性を確認する。

### exact straight skeleton / medial axis

中心線自体は魅力的だが、現在の依存だけで robust な exact skeleton を得にくい。
近似 grid thinning を入れる場合も prune と cleanup が本体になるため、
P0/P1 の基盤 effect がそろってから研究する。

## 8. 共通設計ルール

新規 effect は次を満たす。

1. 一つの effect に一つの核を持たせ、巨大な mode 集合へしない。
2. effect module 同士を import せず、共有処理は `effects/util.py` だけへ置く。
3. 原則 `cache_policy="content"` を維持し、乱数は明示 `seed`、
   animation は明示 `phase` へ依存させる。
4. 出力は `coords: float32[N, 3]`、`offsets: int32[M + 1]` の既存契約を守る。
5. 入力配列を変更せず、identity/no-op では可能なら元配列を返す。
6. 平面処理はワールド XY 固定にせず `PlanarFrame` で元姿勢へ復元する。
7. 閉領域は終点＝始点、穴は even-odd の既存表現へ合わせる。
8. 頂点数、線数、grid cell、scratch を大規模確保の前に見積もる。
9. 格子・反復系は draft/final の実効 work と diagnostics を設計する。
10. 全公開引数に default、型ヒント、`ParamMeta`、日本語 description、単位を持たせる。
11. mode 依存引数は `ui_visible` で隠し、GUI に無関係な選択肢を並べない。
12. 二入力 effect はチェーン先頭のみ、という現制約を API 例へ明記する。

## 9. 推奨する実装順

### Phase A: geometry hygiene

1. `resample`
2. `simplify`
3. `deduplicate`

この 3 件を先に実装し、既存の重い effect と export の前後で使えるようにする。

### Phase B: planar composition

4. `boolean`
5. `offset_curve`

`PlanarFrame`、ring packing、even-odd、決定的な出力順を共通基盤へ寄せる。

### Phase C: global deformation

6. `perspective`
7. 既存計画を更新した `conformal_map`
8. `advect`
9. `path_deform`

各 effect に一枚ずつ、既存 effect だけでは作りにくい代表作例を追加する。

### Phase D: plotter-specific experiments

10. `stipple`
11. `overunder`
12. `spiral_fill`
13. `stitch`

線数、pen-up、描画距離、出力頂点数を比較し、作品上の利点が確認できたものだけ
built-in に昇格する。

## 10. 受け入れ時の共通評価

各候補は、実装前に少なくとも次を確認する。

- 既存 effect の組み合わせだけでは同じ核を簡潔に表現できない。
- 単独デモだけでなく、代表的な effect chain で価値を示せる。
- empty、退化入力、identity、開閉曲線、複数 line の挙動が定義されている。
- 乱数を使う場合、同じ `seed` と引数から同一結果を返す。
- 入力を変更せず、出力 dtype、offsets、line 順が決定的である。
- 平面系は傾斜平面の復元、穴、非平面入力の挙動をテストする。
- resource cap を大規模確保前に判定し、途中までの壊れた出力を返さない。
- built-in manifest、metadata、stub、focused test、代表 sketch を一緒に追加する。

## 11. 過去文書との関係

過去のアイデア集は候補の幅を知る資料として残す。

- `field_and_mapping_effect_ideas_2026-01-30.md`
- `cells_mesh_skeleton_effect_ideas_2026-01-30.md`
- `sampling_and_relaxation_effect_ideas_2026-01-30.md`
- `growth_and_agents_effect_ideas_2026-01-30.md`
- `rules_and_image_driven_effect_ideas_2026-01-30.md`

ただし、これらの作成後に `growth`、`reaction_diffusion`、`isocontour`、`warp`
などが実装された。今後はアイデア数を増やすこと自体を目的にせず、この文書の
優先順位を起点に、一つずつ小さく検証する。
