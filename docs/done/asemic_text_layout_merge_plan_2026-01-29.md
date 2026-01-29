# 既存 primitive `G.asemic` 拡張: 複数文字・改行・折り返し・スペーシング（text.py 風）を統合

作成日: 2026-01-29

## ゴール

- 既存の組み込み primitive `G.asemic` に、文章としての **複数文字/改行/折り返し/揃え/スペーシング**を統合する（別 primitive は作らない）
- **mode は作らない**（ユーザーが 1 文字だけ欲しければ `text="A"` のように 1 文字だけ渡す）
- `seed` だけは文字により派生させ、**同じ文字は同じ字形**になる（font っぽい挙動）
  - それ以外のパラメータ（ノード数/ウォーク/ベジェ等）は **全文字で共通**
- ベジェ相当の滑らかさは **primitive 内で完結**（外部 effect 禁止）

## スコープ

- やる:
  - `text: str` を `G.asemic` に追加（`\n` 改行対応）
  - `text.py` 風のレイアウトパラメータ追加:
    - `text_align` / `letter_spacing_em` / `line_height`
    - `use_bounding_box` / `box_width` / `box_height` / `show_bounding_box`（折り返し & デバッグ枠）
  - **固定メトリクス**による advance（フォント無し）:
    - `glyph_advance_em`（通常文字の送り）
    - `space_advance_em`（空白の送り）
  - 文字→seed 派生（安定ハッシュ） + 同一文字の glyph キャッシュ
  - テスト追加（決定性 + レイアウトの最小保証）
- やらない:
  - 文字ごとの個別パラメータ（字ごとに n_nodes などを変える）
  - 縦書きや複雑な禁則処理
  - 「ストローク同士が交差しない」を厳密保証（今後やるなら別タスク）

## 追加/変更するもの

- `src/grafix/core/primitives/asemic.py`（既存を拡張）
  - レイアウト処理（改行/折り返し/align）
  - 文字→seed 派生（per_char 固定）
  - 文字ごとの glyph キャッシュ（同一文字は生成 1 回）
  - meta + ui_visible 更新
- `src/grafix/api/__init__.pyi`
  - `python -m grafix stub` で更新
- `tests/core/test_asemic_primitive.py`（既存を拡張）
  - レイアウト（複数文字・改行・折り返し）の最小テスト追加

## API 案（統合後の `G.asemic`）

```python
from grafix.api import G

g = G.asemic(
    text="AS\nEMIC  AS",
    seed=0,
    # --- glyph params（全文共通）---
    n_nodes=28,
    candidates=12,
    stroke_min=2,
    stroke_max=5,
    walk_min_steps=2,
    walk_max_steps=4,
    stroke_style="bezier",
    bezier_samples=12,
    bezier_tension=0.5,
    # --- layout params ---
    text_align="left",
    glyph_advance_em=1.0,
    space_advance_em=0.35,
    letter_spacing_em=0.0,
    line_height=1.2,
    use_bounding_box=True,
    box_width=180.0,
    show_bounding_box=True,
    # --- placement ---
    center=(150.0, 150.0, 0.0),
    scale=40.0,  # 1em を 40mm として扱う
)
```

## レイアウト仕様（text.py 風に寄せる）

- 基準座標系は **1em=1.0** で生成し、最後に `scale` と `center` を適用する（text.py と同じ思想）
- `text` は `\\n` で明示改行
- `use_bounding_box=True` かつ `box_width>0` のとき、`text.py` と同様の折り返し:
  - 可能なら空白で折る
  - 空白が無い場合は文字単位で折る
  - 折り返し直後の行頭空白は落とす
- advance はフォントメトリクスではなく固定:
  - 通常文字: `glyph_advance_em`
  - 空白: `space_advance_em`
  - 追加の詰め/空け: `letter_spacing_em`（文字間に加算）
- `text_align` は行単位で `left|center|right`

## 文字→seed 派生（per_char 固定）

- 「同じ文字は同じ字形」にするため、glyph 生成時の seed を以下で決定:
  - `seed_char = stable_hash64(f"{seed}|{char}")`
  - `stable_hash64` は `hashlib.blake2b(digest_size=8)` 等（Python の `hash()` は使わない）
- 同一呼び出し内は `dict[char, glyph_polylines]` でキャッシュし、同じ文字を再生成しない

## 実装方針（コード構造）

### 1) glyph 生成を関数として切り出す

- 既存の `asemic(...)` 本体から「1字形生成」を `_generate_asemic_glyph(...)` に抽出
  - 入力: `seed_char` と glyph params（n_nodes など）
  - 出力: `list[np.ndarray]`（各ストロークの `(N,2)` or `(N,3)` の点列）
  - ベジェの点列化（`stroke_style="bezier"`）はこの中で完結

### 2) レイアウト層を `asemic(...)` に追加

- `text` を解析して `lines` を作る（折り返し含む）
- 行ごとに `width_em` を advance から計算し、`text_align` に応じて `x_start_em` を決める
- 各行:
  - `cur_x_em` を進めながら、空白は advance のみ
  - 非空白は glyph を取得（キャッシュ）し、`(cur_x_em, cur_y_em)` へ平行移動して polylines に追加
- `show_bounding_box` が True のとき、`box_width/box_height` で枠を 4 本の線分として追加（text.py と同じ）

### 3) RealizedGeometry 化は既存の詰め方を踏襲

- 全 polylines を concat → offsets を積む → `scale/center` を最後に適用して返す

## meta（Parameter GUI）案

- 既存 glyph params（すでにある）に加えて:
  - `text: str`
  - `text_align: choice`（left/center/right）
  - `glyph_advance_em: float`（0..3 くらい）
  - `space_advance_em: float`（0..3 くらい）
  - `letter_spacing_em: float`（0..2）
  - `line_height: float`（0.8..3）
  - `use_bounding_box: bool`
  - `box_width: float`（0..300）
  - `box_height: float`（0..300）
  - `show_bounding_box: bool`
- `ui_visible` で `use_bounding_box` が True のときだけ `box_*`/`show_bounding_box` を表示

## テスト（最小）

- 決定性（per_char）:
  - `text="AA"` の 2 つの glyph が「平行移動を除けば同一形状」（= 同じ `seed_char`）であること
- 改行:
  - `text="A\\nA"` で 2 行分の geometry が生成され、`line_height` 分だけ y がずれること（概形でよい）
- 折り返し:
  - `use_bounding_box=True, box_width` を小さくして、`text="A A A"` が複数行へ増えること
- stub sync:
  - `python -m grafix stub` → `tests/stubs/test_api_stub_sync.py`

## 実装手順（チェックリスト）

- [x] `G.asemic` に `text` + レイアウト系パラメータを追加（meta/ui_visible も更新）
- [x] glyph 生成を `_generate_asemic_glyph(seed_char, ...)` として抽出
- [x] `seed_char` の安定ハッシュ関数を実装（blake2b など）
- [x] レイアウト（改行/align/advance）を実装
- [x] `box_width` 折り返し（text.py と同等のロジック）を実装
- [x] デバッグ bounding box を追加（任意）
- [x] `python -m grafix stub` で `src/grafix/api/__init__.pyi` 更新
- [x] `tests/core/test_asemic_primitive.py` を拡張
- [x] `PYTHONPATH=src pytest -q tests/core/test_asemic_primitive.py tests/stubs/test_api_stub_sync.py`

## 確定事項

- 座標原点は text.py 同様に「左上起点」に統一（1文字でも左上起点）
- `text` の default は `"A"`（常に text として解釈）
