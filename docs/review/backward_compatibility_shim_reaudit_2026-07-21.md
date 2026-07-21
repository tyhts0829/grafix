# 後方互換・余計なシム・非正規実装の再監査（2026-07-21）

> **解消追補:** 本文 1〜9 は基準 HEAD `0b0e647` の実装前監査である。
> 承認後の解消結果と最終 verdict は「10. 解消結果」以降に追記した。

## 1. 結論

対象 HEAD は `0b0e647`。監査開始時の `git status --porcelain` は空だった。

旧公開名の deprecated alias、旧 ParamStore schema の runtime decoder、旧 constructor を
受ける明示 wrapper といった典型的な後方互換シムは、前回監査後の現 HEAD では概ね
除去されている。一方、実際の呼び出し経路、private state、永続化、性能最適化の
fallback まで追跡すると、**「旧挙動または非 canonical 入力を黙って受ける第二契約」や
「不完全な caller/test double を production が支える bridge」はまだ残っている**。

今回の判定は次のとおり。

- **P1: 2 件** — 公開 API または canonical value object の契約そのものが一定しない。
- **P2: 11 件** — 明示的な内部互換 bridge、二重契約、到達不能な互換経路、
  silent recovery、または再現可能な整合性不具合がある。
- **P3: 14 件** — 型の偽装、浅い immutable 化、未文書 alias、重複実装などの局所的負債。

したがって、最終 verdict は **「旧公開 API/schema の大きな互換層は解消済みだが、
canonical 境界と private/raw 経路を含めると未解消。追加整理が必要」** である。

## 2. 監査方法

### 2.1 対象

- `src/grafix/` の Python 238 files、約 86,788 行。
- `tests/` の Python 264 files、約 64,397 行。
- `README.md`、`architecture.md`、migration/plan/review 文書、`pyproject.toml`。
- 現行 call site、対応 test、`git blame`、直近の互換シム解消 commit の差分。

### 2.2 手順

1. `legacy`、`deprecated`、`compatibility`、`互換`、`従来`、`migration`、
   `alias` 等の 220 hits を分類した。
2. `fallback`、duck typing、広い例外捕捉、best-effort 等の 137 hits を分類した。
3. AST で pass-through wrapper、単純 alias、空 subclass、
   `TypeError` / `AttributeError` / `ImportError` fallback を抽出し、call site まで追跡した。
4. registry、G/E/P、Geometry/RealizedGeometry、parameter store、永続 schema、
   interactive/export/benchmark の境界を、producer から consumer まで追跡した。
5. raw operation の test が公開経路で到達可能か、前回結果との bit/warning/評価順一致を
   何のために固定しているかを確認した。
6. 読み取り専用の focused subprocess で、後述する coercion、ID、registry、
   collapse state 等を再現した。

### 2.3 重要度

- **P1**: 公開契約、cache identity、不変性など core invariant を破る。最優先。
- **P2**: 明確な二重契約・shim・silent error・実不具合。次の整理対象。
- **P3**: 現時点の被害は限定的だが、正本を増やす、型を偽る、保守コストを生む。

## 3. サマリー

| ID | 優先度 | 指摘 | 確度 |
|---|---:|---|---|
| A-01 | P1 | G/E の型検証が Parameter 記録 context の有無で変わる | 確定 |
| A-02 | P1 | `RealizedGeometry` が二重契約・lossy cast・外部 alias を持つ | 確定 |
| B-01 | P2 | `ensure_builtin_*_registered()` が登録を保証しない | 確定 |
| B-02 | P2 | `Geometry` が内容と不一致な外部 ID を信頼する | 高 |
| B-03 | P2 | `EffectBuilder` の immutable 契約が偽 | 確定 |
| B-04 | P2 | raw effect の非 canonical/不正入力まで旧挙動を固定 | 高 |
| B-05 | P2 | `polyline` に公開経路から到達不能な ndarray 互換 fast path | 確定 |
| B-06 | P2 | `_favorite_keys` が明示的な内部互換 bridge | 確定 |
| B-07 | P2 | preset collapsed-header の migrate/prune が漏れている | 確定 |
| B-08 | P2 | `coerce_rgb255()` が strict invariant 以前の寛容変換を残す | 確定 |
| B-09 | P2 | MIDI snapshot が schema-less、暗黙変換、部分成功 | 確定 |
| B-10 | P2 | benchmark 内の任意 `ImportError` を `skipped` にする | 確定 |
| B-11 | P2 | source reload に明示確定と暗黙 commit の二契約 | 高 |
| C-01 | P3 | site ID 生成失敗を衝突する固定値へ落とす | 確定 |
| C-02 | P3 | strict ParamStore 内部で `bool()` / `str()` coercion が残る | 高 |
| C-03 | P3 | Parameter の production test seam と `GroupKey` 重複定義 | 確定 |
| C-04 | P3 | Shapely 1.x/2.x API を暗黙分岐で併存 | 高 |
| C-05 | P3 | required `psutil` の API mismatch を 0/欠測へ黙殺 | 高 |
| C-06 | P3 | 不完全な MIDI test double を production fallback が支える | 高 |
| C-07 | P3 | `_DEFAULT_TARGET = cast(str, object())` が型を偽る | 確定 |
| C-08 | P3 | `text` と `asemic` に同じ text layout 実装を複製 | 確定 |
| C-09 | P3 | `OpSpec` の immutable 化が mapping の浅い freeze に留まる | 確定 |
| C-10 | P3 | config path に positional と `--config` の同義入口がある | 確定 |
| C-11 | P3 | `--midi-port` に未文書の空文字/`off` alias がある | 確定 |
| C-12 | P3 | CLI の `--` 委譲処理を helper と手書きで二重実装 | 確定 |
| C-13 | P3 | `ExportJob` だけ positional DTO surface を残す | 高 |
| C-14 | P3 | provenance/checksum JSON が unknown 値を `repr()` へ落とす | 中 |

## 4. P1: canonical 契約を壊す問題

### A-01: G/E の型検証が Parameter 記録 context の有無で変わる

**箇所**

- `src/grafix/api/_op_validation.py:20-63`
- `src/grafix/api/_param_resolution.py:45-80`
- `src/grafix/core/parameters/validation.py:101-160`
- `src/grafix/core/primitives/_shape_utils.py:14-38`
- `src/grafix/core/primitives/grid.py:44-73`
- `src/grafix/core/primitives/polygon.py:51-101`

`validate_operation_kwargs()` が常時検証するのは unknown keyword、`activate`、choice が
中心で、`int` / `float` / `vec3` / `rgb` の strict validation は、Parameter 記録中に
`resolve_api_params()` が `resolve_params()` を呼んだ場合にしか実行されない。
記録 context 外では primitive/effect 内部の `int()` / `float()` / iteration が事実上の
validator となる。

focused probe では次がすべて成功した。

```text
G.circle(segments="4")  -> 5 vertices
G.circle(segments=3.9)  -> 3 に切り捨てて 4 vertices
G.circle(center="12")   -> "1", "2" を 2D 座標として解釈
G.grid(nx="2", ny=0)    -> 成功
G.grid(nx=True, ny=0)    -> 成功
```

同じ値を `validate_parameter_value()` へ渡すと拒否される。同一の公開 API が実行 context
により別の型契約を持つため、これは単なる内部美観ではない。

**推奨**

1. defaults 適用後、全 `meta` 引数を中央の一境界で常時検証・正規化する。
2. operation 登録時に defaults も同じ validator で検証する。
3. primitive/effect 内部の互換的 `int()` / `float()` coercion を削り、正規型を前提にする。

### A-02: `RealizedGeometry` が strict value object ではなく互換正規化器になっている

**箇所**

- `src/grafix/core/realized_geometry.py:25-84`
- `src/grafix/core/realized_geometry.py:92-112`
- `src/grafix/core/realized_geometry.py:115-157`
- `architecture.md:122-124`
- `docs/plan/decorator_coerce_realizedgeometry_plan_2026-02-11.md:19-22,47-50`

問題は三つある。

1. docstring と `GeomTuple` は `(N,3)` を canonical とする一方、constructor は `(N,2)` を
   z=0 で補完する。さらに `realized_geometry_from_tuple()` は同じ `(N,2)` を明示拒否する。
2. dtype cast 前の整数性、値域、有限性を検証しない。focused probe では
   `offsets=[0.2, 1.9]` の切り捨て、巨大 int64 の int32 wrap、`1e100` の float32 `inf` 化を
   経て受理できた。
3. 入力配列を copy せず、その配列自身を `writeable=False` にする。caller の配列へ副作用を
   与えるうえ、同じ参照や writable な base から内容を変更でき、cache 済み geometry の
   「不変性」も保証できない。

**推奨**

- `(N,3) / float32 / int32` を唯一の contract として exact reject するのが最も単純。
- dtype 変換を正式仕様に残すなら、cast 前に有限性・整数性・範囲を検証する。
- 外部境界では配列 ownership を取得する。zero-copy の trusted path が必要なら、通常
  constructor と名前・可視性を分ける。

## 5. P2: 明確な shim、二重契約、silent failure

### B-01: `ensure_builtin_*_registered()` が登録を保証しない

**箇所:** `src/grafix/core/builtins.py:81-119`、
`src/grafix/core/op_registry.py:281-292`。

関数は module を import するだけである。module が既に `sys.modules` にあり、registry を
`replace_all({})` した後は decorator が再実行されない。それでも `True` を返し、
`idempotent` / `ensure` という名前に反して registry は空のままになることを再現した。

**推奨:** builtin spec の明示 manifest/factory から登録するか、registry 置換後も builtin が
欠落しない invariant へ統一する。返値は実際の登録状態を表すべきである。

### B-02: `Geometry` が内容と不一致な外部 ID を信頼する

**箇所:** `src/grafix/core/geometry.py:233-268,279-304,306-350,471-484`、
`src/grafix/core/realize.py:247,427`。

`Geometry.create()` は内容署名を計算するが、公開 dataclass constructor は任意の
`id/op/inputs/args` を受理する。等価性、hash、Realize cache key は ID だけを見るため、
異なる recipe に同じ ID を付けると同一 geometry と扱われる。pickle 復元も record の ID を
再計算せず信頼する。

**推奨:** constructor を非公開にして `create()` を唯一の入口にするか、`__post_init__` と
pickle restore で正規化済み内容から ID を再計算・照合する。

### B-03: `EffectBuilder` の immutable 契約が偽

**箇所:** `src/grafix/api/effects.py:46-57,92-109,287-303,517-532`。

frozen dataclass の `steps` 内に mutable `dict` を保持するため、次の変更が可能である。

```python
b = E.scale(scale=(2, 2, 2))
b.steps[0][1]["scale"] = (9, 9, 9)
```

既存 builder が後に生成する DAG が変わり、`hash(b)` も dict のため失敗する。selector 側は
frozen DTO と immutable な `params_by_target` に正規化済みで、通常 step と内部表現も不統一である。

**推奨:** 通常 effect step も frozen DTO + 正規化済み tuple args へ統一し、lowering 時だけ
mapping 化する。

### B-04: raw effect の非 canonical/不正入力まで旧挙動を固定している

**代表箇所**

- `src/grafix/core/effects/scale.py:67-120,301-359`
- `src/grafix/core/effects/translate.py:67-91`
- `src/grafix/core/effects/rotate.py:63-137`
- `src/grafix/core/effects/subdivide.py:100-127,226-270,367-400`
- `tests/core/effects/test_scale.py:358-402,454-513`
- `tests/core/effects/test_translate.py:188-230`
- `tests/core/effects/test_rotate.py:248-269,312-394`
- `tests/core/effects/test_subdivide.py:541-581`

runtime では `effect_registry` が `RealizedGeometry.coords/offsets` を tuple にして builtin へ渡す
（`src/grafix/core/effect_registry.py:110-145`、`src/grafix/core/realize.py:604-653`）。座標の
shape/dtype と offsets の基本形はここで揃うが、A-01 のため malformed parameter は公開 E 経路
からも到達し、A-02 のため layout/有限性/ownership まで strict な canonical とは限らない。

それでも raw 関数には、次を過去実装と一致させる分岐と test がある。

- ndarray subclass の ufunc/matmul dispatch。
- float16/float64/int32、非単調 offsets、非 canonical shape/layout。
- broadcast error、warning の個数と文言、signed zero の bit。
- malformed 引数を空 geometry 時だけ評価しないこと。
- `delta=(1,2,3,"ignored")` の末尾無視や custom object の左から右の評価順。

focused probe でも `E.translate(delta=(1,2,3,"ignored"))(G.line())` と
`E.translate(delta=())(G.polyline(points=()))` はともに `realize()` まで成功した。

canonical 入力に対する出力/RNG/回転順の決定性は現行仕様として正当である。しかし、invalid
offsets、ndarray subclass、非 canonical dtype/shape など raw direct call でしか到達しない形まで
warning/例外順を固定する必要はない。malformed parameter や特殊 layout が公開経路からも
到達する現状は、この互換 test を正当化する理由ではなく A-01/A-02 の境界不統一そのものである。

**推奨:** A-01/A-02 後に builtin evaluator 入力を canonical tuple 一形へ限定し、raw 不正入力
test を削除する。canonical 出力の数値 oracle だけを残す。

### B-05: `polyline` の ndarray fast path は公開経路から到達不能

**箇所**

- `src/grafix/core/primitives/polyline.py:49-129`
- `src/grafix/core/geometry.py:98-150`
- `tests/core/primitives/test_basic_shapes.py:74-230`

fast path は Python scalar への二段変換、signaling NaN の quiet 化、warning 回数、
`closed.__bool__` が配列を変更する timing まで sequence 経路と一致させる。一方、公開
`G.polyline(points=...)` は evaluator より前に `Geometry._normalize_value()` を通り、ndarray を
サポートしない。

focused probe:

```text
G.polyline(points=np.ndarray) -> TypeError: 正規化できない引数型
raw_polyline(points=np.ndarray) -> float32 (2,3), int32 [0,2]
```

つまり約 70 行の最適化と多数の特殊 test は、raw module 直 import という隠れ第二 API の
ためだけに存在する。

**推奨:** 最小契約を優先し ndarray fast path と incidental test を削除する。ndarray を本当に
公開入力にするなら、Geometry の freeze/hash/ownership を含めて正式な一契約として設計する。

### B-06: `_favorite_keys` が明示的な内部互換 bridge

**箇所:** `src/grafix/core/parameters/store.py:131-149`、
`src/grafix/interactive/runtime/parameter_recovery.py:72-90`。

property の docstring 自身が「既存の recovery 境界向け」と明記する。repository 内の caller は
`_replace_store_contents()` だけで、backing field rename 後の private caller を生かす典型的な
shim である。getter が raw mutable set を返すため、直接変更すれば favorite revision/cache を
迂回できる。さらに interactive 層が ParamStore の private field を列挙 copy し、store の
新 field 追加時に漏れる構造になっている。

**推奨:** 最小でも `_replace_favorite_keys(source._favorite_keys_snapshot())` を使って property を
削除する。本命は whole-store replacement を core の単一 operation/ParamStore method に移す。

### B-07: preset collapsed-header の migrate/prune が漏れている

**箇所**

- `src/grafix/interactive/parameter_gui/table.py:239-274`
- `src/grafix/core/parameters/memento.py:143-165`
- `src/grafix/core/parameters/reconcile_ops.py:175-193`
- `src/grafix/core/parameters/prune_ops.py:239-249`

GUI の canonical key は `primitive:{op}:{site_id}`、`preset:{op}:{site_id}`、
`effect_chain:{chain_id}` である。core memento は registry に依存できないため、照合用の候補集合に
primitive/preset 両形式を合成するが、実際の store に両方を重複保存しているわけではない。
問題は migrate と prune が `primitive:` しか処理しない点である。focused probe では synthetic な
preset 形式の collapse key が `migrate_group(old -> new)` 後もそのまま残った。実在 preset の op も
`preset.<name>` という同じ処理対象になる。

この非対称性により、preset site_id 変更時に collapse 状態を移行できず、prune 後にも stale key が
残る実不具合になる。

**推奨:** `CollapsedHeaderKey` のような tagged canonical identity を一か所に定義し、
store/codec/GUI/reconcile/prune で共有する。schema を更新する場合も旧 runtime decoder は足さない。

### B-08: `coerce_rgb255()` が strict invariant 以前の寛容変換を残す

**箇所:** `src/grafix/core/parameters/style.py:39-70`、
`src/grafix/core/parameters/validation.py:148-159`、
`tests/core/parameters/test_style_entries.py:31-41`。

任意 object を unpack し、`except Exception`、各要素の `int()` 化、0..255 clamp を行う。
実際に `("12", True, 3.9) -> (12, 1, 3)` となる。現行 canonical RGB validator は exact
3-tuple、bool 不可、整数、0..255 を要求するため、古い寛容 helper だけが invariant 違反を
silent repair している。

**推奨:** canonical validator に一本化し、string/bool/float/out-of-range は fail-fast にする。
RGB01 から RGB255 への明示 domain conversion は別責務として維持してよい。

### B-09: MIDI snapshot が schema-less、暗黙変換、部分成功

**箇所:** `src/grafix/interactive/midi/midi_controller.py:69-105`。

`load_cc_snapshot()` は OSError、壊れた JSON、non-dict をすべて無診断の `{}` にし、各 entry を
`int(key)` / `float(value)` で変換する。任意例外は entry 単位で握り、残りだけ読み込む。
value 側の数値文字列、bool、NaN/Inf、範囲外 CC/value を正規 data と区別できず、writer も
version のない dict を保存する。JSON object の CC key が文字列なのは現行 writer の正規形であり、
それ自体は問題ではない。

これは旧 schema decoder と名乗ってはいないが、非 canonical な flat dict や部分破損 entry を
best-effort に読み続ける互換層と同じ効果を持つ。old/future/corrupt を診断付きで拒否する
`workspace_state.py` とも不統一である。

**推奨:** schema version 付き一形にし、CC key 0..127、bool を除く有限実数 0..1 を strict に
検証する。旧/unversioned は診断付き reject とし、必要なら runtime shim でなく一回限りの外部
migration tool を用意する。

### B-10: benchmark 内の任意 `ImportError` を `skipped` にする

**箇所:** `src/grafix/devtools/benchmarks/runner.py:919-1056`、
`pyproject.toml:21-36`。

setup、measurement context、warmup、workload、postprocess の全体を囲み、内部 typo、transitive
import regression、workload 実行中の ImportError まで `status="skipped"` に変える。benchmark が
使う主要 dependency は project の required dependency である。

**推奨:** capability probe/setup だけが明示 `BenchmarkUnavailable` を返す形にするか、
ImportError を通常の `error` として扱う。壊れた benchmark を環境都合の skip に偽装しない。

### B-11: source reload に明示確定と暗黙 commit の二契約がある

**箇所:** `src/grafix/interactive/runtime/source_reload.py:422-450`。

`retain_rollback=True` は `accept_generation()` / `rollback_generation()` という明示 protocol を
提供するが、caller が確定を忘れたまま次の `poll()` に進むと自動 accept する。production
caller は明示 protocol を完結しており、通常経路にはこの救済が不要である。`close()` 内の
accept は直後に baseline registry へ戻す terminal cleanup なので、この指摘には含めない。

**推奨:** pending transaction のまま次の poll へ進んだら invariant error にするか、transaction
object/context manager へ一本化する。明示 commit と「忘れたら commit」の二契約を併存させない。

## 6. P3: 局所的な非正規実装・余計な表面積

### C-01: site ID 生成失敗を衝突する固定値へ落とす

`src/grafix/core/parameters/key.py:85-90,109-132` は frame/stack を取得できないと全 call site を
`"<unknown>:0:0"` にする。永続 identity の生成に失敗しているのに継続すると、無関係な
parameters が一 group に silently alias する。`RuntimeError` で fail-fast にすべきである。

### C-02: strict ParamStore 内部に `bool()` / `str()` coercion が残る

- `src/grafix/core/parameters/codec.py:51-58,91-97`
- `src/grafix/core/parameters/reconcile_ops.py:206-216`
- `src/grafix/core/parameters/memento.py:257-275,304-315,355-383`
- `src/grafix/core/parameters/resolver.py:166-169`

`ParamStateSnapshot.from_state()` と store の正規更新境界は non-exact bool を拒否する一方、
encode/memento/reconcile は `bool(...)`、kind 比較は `str(...)` で silent canonicalization
する。invariant 通過後は値を直接使い、必要なら入口の一 validator だけで拒否するのが単純である。

### C-03: Parameter の production test seam と `GroupKey` 重複定義

- `src/grafix/core/parameters/merge_ops.py:219-230` は空 mapping 呼び出しについて
  「既存の commit hook/例外伝播 semantics を維持」と説明する。callee 本体は plain loop だが、
  test はこの private call boundary を monkeypatch して rollback を fault-injection している。
  空入力でも production が helper を呼ぶ挙動を test seam として契約化せず、transaction failure を
  明示的に注入できる境界へ寄せる方が責務が明確である。
- canonical `GroupKey` は `identity.py:9` にあるのに、`reconcile.py`、`reconcile_ops.py`、
  `runtime.py` で同じ `tuple[str, str]` を再定義する。canonical identity の正本を一つにすべき。

### C-04: Shapely 1.x/2.x API を暗黙分岐で併存

`src/grafix/devtools/benchmarks/environment.py:178-199` は Shapely 2 の
`shapely.geos_version_string` がなければ旧 `shapely.geos.geos_version_string` を読む。
`pyproject.toml:24` は required dependency の世代を固定していない。

対応世代を例えば `shapely>=2,<3` に固定して API を一形にするか、複数世代を本当に支えるなら
対応範囲を明記した集中 adapter と version matrix test を持つべきである。現在は隠れ互換 branch
だけがある。

### C-05: required `psutil` の API mismatch を 0/欠測へ黙殺

`src/grafix/interactive/runtime/monitor.py:202-207,447-469` は import の任意例外をまとめ、
`cpu_times().user/system` を `getattr(..., 0.0)` で読む。child 集計も全 `Exception` を捨てる。
required dependency の API mismatch や実装 bug を CPU=0 として報告せず、直接 attribute を読み、
child race は `NoSuchProcess` / `AccessDenied` / `ZombieProcess` 等だけを除外すべきである。

### C-06: 不完全な MIDI test double を production fallback が支える

`src/grafix/interactive/midi/midi_controller.py:164-165,180,237-242,296-305` は `inport: object` を
「テスト用」とし、`close` がなければ黙って終了する。実際の test fake が `close()` を持たず、
production fallback に依存する。`iter_pending()` と `close()` を要求する最小 Protocol を定義し、
fake を現行 interface 完備にすべきである。

### C-07: `_DEFAULT_TARGET = cast(str, object())` が型を偽る

`src/grafix/api/primitives.py:31,82-127` と `src/grafix/api/effects.py:43,307-356,419-464` は
runtime では object の sentinel を型検査器へ `str` と偽る。専用 `_UnsetTarget` singleton 型と
overload/internal helper で omitted state を表す方が契約に正直である。

### C-08: `text` と `asemic` に同じ text layout 実装を複製

`src/grafix/core/primitives/text.py:324-383,712-801` と
`src/grafix/core/primitives/asemic.py:454-544,797-903` は、折返し、行幅、alignment、bounding box
構築をほぼ複写している。asemic 側も「text.py と同等」と明記する。glyph metrics/生成は固有の
まま、advance callback を受ける小さな layout helper に共通部分だけを抽出できる。

### C-09: `OpSpec` の immutable 化が浅い

`src/grafix/core/op_registry.py:26-71` は `MappingProxyType(dict(defaults))` で外側 mapping だけを
固定する。値が list/dict なら外部参照や `spec.defaults[name].append(...)` で revision を増やさず
default を変更できる。A-01 と同時に meta kind ごとの canonical immutable default へ登録時に
変換すべきで、任意 object 用の汎用 deep-freeze は不要である。

### C-10: config path に同義入口が二つある

`src/grafix/devtools/config_cli.py:12-36` は positional `path` と `--config` を同義にし、両方指定の
衝突処理まで持つ。両方は同じ commit で導入されており、後方互換の証拠はないが、同一責務の
余計な surface である。README/developer guide が示す positional か、全 CLI で統一する
`--config` のどちらか一つを正本にすべきである。

### C-11: `--midi-port` に未文書 alias がある

`src/grafix/devtools/run_sketch.py:39-41,70-76` の help は `none` だけを示すが、空文字、`off`、
大小文字、前後空白も無効化 alias として受ける。canonical `none` 一語または独立
`--no-midi` に固定する方が明確である。

### C-12: CLI の `--` 委譲処理が二重実装

`src/grafix/__main__.py:11-17` に `_delegated_args()` があるのに、export/list/describe/config は
`src/grafix/__main__.py:123-163` で同じ処理を手書きする。helper 一形へ統一でき、挙動変更もない。

### C-13: `ExportJob` だけ positional DTO surface を残す

`src/grafix/interactive/runtime/export_job_system.py:260-273,326-339` では request `ExportJob` は
positional constructor を許す一方、paired result は `kw_only=True`。repository の全 call site は
keyword を使っているため、request も keyword-only に統一できる。

### C-14: provenance/checksum JSON が unknown 値を `repr()` へ落とす

**箇所**

- `src/grafix/core/capture_provenance.py:43-92,185-191,485-515`
- `src/grafix/devtools/benchmarks/runner.py:3689-3723`

capture 側は mapping key を文字列化し、duck-typed `.item()` / `.tolist()` の失敗を握り、最後は
`repr(value)` を保存する。benchmark 側も unknown 値を `repr()` へ落とす。`repr()` は memory
address を含み得るため、決定的 provenance/checksum という目的に反する。異なる mapping key が
`str(key)` で衝突する可能性もある。

確認した現行 call site は owned dataclass、strict ParamStore codec、`BenchmarkOutput` が中心で、
catch-all が通常経路で実際に発火する例は再現していない。このため実不具合ではなく、不要な
受理範囲と将来の非決定性リスクとして P3 に置く。

**推奨:** owned schema ごとの明示 encoder に分け、unknown type は拒否する。benchmark workload
にも JSON-compatible/typed output を要求し、`repr()` を互換 fallback にしない。

## 7. 調査したが shim と判定しなかったもの

| 対象 | 判定理由 |
|---|---|
| root/API の re-export | README が定める canonical façade。旧名の中継ではない。 |
| `api.__init__` の lazy `run()` | GUI dependency の cold import を避ける正当な境界。 |
| G/E/P の動的属性解決 | runtime 登録 operation/preset の現行機能。 |
| ParamStore schema v3 parser | versionless/v1/v2/future を変換せず reject。旧 decoder はない。 |
| reconcile の group migration 自体 | コード編集による site 移動を扱う現行 domain feature。B-07 の identity 漏れだけが問題。 |
| WorkspaceState old/future/corrupt fallback | migration せず status と診断を返す user-data recovery。 |
| interactive config fallback | packaged default と診断を共有する明示 recovery。旧 schema decoder ではない。 |
| transaction rollback、late collision、worker timeout/death | correctness/atomicity の現行境界。 |
| source reload の last-good rollback | 現行 live reload 機能。B-11 の「確定忘れを commit」だけが二重契約。 |
| optional MIDI/device disconnect、OS/Retina/font/clipboard | platform/optional subsystem 境界。C-06 の test-only port fallback とは分けた。 |
| benchmark の `compatibility_key` | 過去 API 互換ではなく、計測条件比較の意味論。 |
| canonical input の RNG/bit/回転順/描画順 oracle | product-visible な決定性。B-04 は非 canonical/malformed raw 入力だけを問題視。 |
| Shapely geometry の分解 | 外部 geometry を canonical 出力へ落とす現行 adapter。 |
| `MAX_GRID_POINTS = DEFAULT_MAX_GRID_CELLS` 3 件 | module policy/test seam の可能性が高く、旧名 alias という証拠がない。 |
| cleanup 中の `getattr` / broad catch | constructor/abort の partial-resource cleanup に限定されたものは正当。 |

## 8. 推奨する整理順

1. **canonical input/value object を確立する**
   - A-01、A-02 を先に解消する。
   - ここを直さず raw fallback だけ消すと、入力契約が別の場所へ分散する。
2. **隠れ第二 API を削る**
   - B-04、B-05、B-08 を整理し、canonical input/output の test だけを残す。
3. **identity と immutable 境界を一形にする**
   - B-01〜B-03、B-07、C-07、C-09。
4. **ParamStore の private bridge を core operation に戻す**
   - B-06、C-01〜C-03。
5. **永続化と error classification を strict にする**
   - B-09〜B-11、C-04〜C-06、C-14。
6. **局所的な重複 surface を削る**
   - C-08、C-10〜C-13。

各 phase は破壊的変更として repository 内 consumer、test、stub、文書を同時更新し、互換 wrapper、
deprecated alias、旧 schema decoder を追加しない。

## 9. 初回監査時の検証範囲と制限

以下は、解消実装へ着手する前の監査時点における記録である。実装後の全体検証は
「14. 最終検証」に記録した。

- 監査は静的追跡、履歴確認、focused subprocess による再現で実施した。
- full pytest / Ruff / mypy は、実装変更を行っていないため今回は実行していない。
- 数値 kernel の数学的妥当性と性能は再測定していない。B-04/B-05 を削る実装時は canonical
  benchmark を再実行する必要がある。
- 外部 dependency の version matrix（Shapely 1/2、psutil の OS 差）は実行確認していない。
- 本ファイル以外の production/test code は変更していない。

前回の `docs/review/backward_compatibility_shim_audit_2026-07-20.md` が確認した旧 API/schema の
大項目は、現 HEAD でも概ね解消済みである。今回の差分は、そこで「数値契約」「recovery」
として大括りにした領域を、**canonical runtime から到達するか、unknown/broken input を黙って
受けるか、test/private caller のためだけの経路か**という基準で再分類した結果である。

## 10. 解消結果

承認済み計画
`docs/plan/backward_compatibility_shim_reaudit_resolution_plan_2026-07-21.md` に従い、
互換 wrapper、deprecated alias、旧 schema decoder、one-shot migration tool を追加せず、
27 件をすべて破壊的に正規契約へ統一した。

| ID | 状態 | 解消内容 |
|---|---|---|
| A-01 | 解消済み | primitive/effect/selector と登録 default が同じ中央 validator を通り、記録 context に依存しない。 |
| A-02 | 解消済み | `RealizedGeometry` を exact N3/float32/int32/C-contiguous/finite/整合済みの owned immutable snapshot 一形にした。 |
| B-01 | 解消済み | append-only builtin catalog と live registry を分離し、不足 spec を import reload なしで再登録する。 |
| B-02 | 解消済み | `Geometry` ID を canonical recipe からのみ算出し、constructor/pickle の任意 ID 注入を削除した。 |
| B-03 | 解消済み | effect step を frozen DTO と immutable tuple args に統一し、builder を値として比較・hash 化可能にした。 |
| B-04 | 解消済み | raw effect の非 canonical layout/coercion 分岐と incidental test を削り、意味検証を empty/no-op より先に行う。 |
| B-05 | 解消済み | `polyline` の ndarray 第二経路を削除し、immutable tuple の canonical 経路だけにした。 |
| B-06 | 解消済み | favorite の compatibility property を削除し、core-owned snapshot/replace operation に限定した。 |
| B-07 | 解消済み | collapsed-header を style/primitive/preset/effect-chain の tagged identity に統一し、migrate/prune/variation へ共有した。 |
| B-08 | 解消済み | RGB255 を exact 3-tuple・exact int `0..255` 一形にし、暗黙変換/clamp を削除した。 |
| B-09 | 解消済み | MIDI snapshot schema v1 を導入し、全体 strict decode、重複/range/type 検査、原本保護を実装した。 |
| B-10 | 解消済み | benchmark stage の `ImportError` を skip へ変換せず error として保持する。 |
| B-11 | 解消済み | source reload transaction は明示 accept/rollback 必須とし、次 poll の暗黙 commit を削除した。 |
| C-01 | 解消済み | site ID の frame/stack 枯渇は衝突 ID へ落とさず `RuntimeError` にする。 |
| C-02 | 解消済み | strict ParamStore 境界後の `bool()` / `str()` repair を削除し、class invariant を検証する。 |
| C-03 | 解消済み | `GroupKey` を core の一定義へ統一し、rollback test は実際の explicit 変更を使う。 |
| C-04 | 解消済み | dependency を `shapely>=2,<3` に固定し、Shapely 1.x import/API 分岐を削除した。 |
| C-05 | 解消済み | required `psutil` の正規 API を直接使い、欠落値 0/未計測への API mismatch fallback を削除した。 |
| C-06 | 解消済み | MIDI port Protocol を必須化し、不完全 test double を補う `getattr`/close fallback を削除した。 |
| C-07 | 解消済み | 型を偽る object sentinel を専用 `_UnsetTarget` singleton 型へ置換した。 |
| C-08 | 解消済み | wrap/line width/alignment/bounding box を小さな `_text_layout.py` に共通化し、glyph 生成は分離した。 |
| C-09 | 解消済み | `OpSpec` の default/meta/UI 値を recursive canonical immutable tree として登録時に固定した。 |
| C-10 | 解消済み | `config validate/show` の path は positional 一形とし、同義 `--config` を削除した。 |
| C-11 | 解消済み | MIDI 無効化 token は exact `none` だけとし、空文字/`off`/casefold/strip alias を削除した。 |
| C-12 | 解消済み | 全 subcommand の先頭 `--` 処理を `_delegated_args()` 一つへ統一した。 |
| C-13 | 解消済み | `ExportJob` を keyword-only にし、positional DTO surface を削除した。 |
| C-14 | 解消済み | provenance/checksum を owned typed encoder に分け、unknown/key変換/nonfinite/`repr()` fallback を拒否した。 |

## 11. 横断再監査で追加解消した事項

27 件の局所修正後に source/test/docs を再走査し、同種の残存を追加で解消した。

- operation の lower bound、range、引数間相関を empty/identity 判定より先に検証する。
- `drop` / `clip` / `mirror3d` の旧 raw layout、`polyhedron` の旧配列 schema、
  Laplace/sphere の silent fallback/clamp、Shapely 例外の広域捕捉を削除する。
- MIDI reconnect factory error と message validation error を切断 recovery へ誤分類しない。
- checksum の mapping/list 型 tag、context manager の原例外 identity、GEOS version を厳密に保持する。
- `DrawResult`、`ParamStateSnapshot`、parsed ParamStore、reconcile fingerprint、selector 解決結果、
  GUI snapshot、benchmark case/comparison row を nested mutable alias のない表現へ統一する。
- Parameter GUI の Copy Code から unknown object の `repr()` fallback を削除する。
- immutable benchmark JSON の正本を `FrozenJsonObject` に一本化し、setup/CLI 境界だけで
  plain JSON tree を materialize する。
- strict `RealizedGeometry` が毎 frame snapshot を作る条件でも、renderer は offsets 内容一致で
  topology/IBO を再利用する。
- repository 内 sketch の旧 dash cycle 指定を scalar `dash_length` へ更新した。

最終の独立再監査では、互換 wrapper、deprecated alias、旧 schema decoder、raw/private の
非 canonical 第二契約、test-double bridge、silent fallback、外部へ漏れる mutable alias の
**追加未解消は 0 件**だった。

## 12. 性能確認

最終 short benchmark（baseline と同じ target/sample/warmup 設定で再計測）:

- `/private/tmp/grafix-reaudit-final5a-benchmarks/runs/20260721_031010_909316_d0f918.json`
- `/private/tmp/grafix-reaudit-final5b-benchmarks/runs/20260721_031030_591418_1563a4.json`

| case | baseline 比 | checksum |
|---|---:|---|
| scale | 0.993x | 一致 |
| rotate | 0.994x | 一致 |
| translate | 1.262x | 一致 |
| subdivide | 1.217x | 一致 |
| text | 0.782x | 一致 |
| asemic | 0.940x | 一致 |
| parameter merge | 0.961x | checksum v2 変更 |
| provenance | 0.962x | checksum v2 変更 |
| realized concat | 0.856x | 一致 |
| draw/realize pipeline | 0.777x | schema/checksum 変更 |

translate/subdivide の増加は、mutable evaluator 出力から外部 alias のない bytes-backed snapshot を
作る A-02 の意図した correctness cost である。再計測でも約 1.27x / 1.28x だった。
非 canonical alias を戻す最適化は行っていない。一方、G.polyline の 50k tuple 構築は
旧 50.8 ms、変更後 56.1 ms（約 1.10x）で、canonical common path は実用範囲を維持した。
削除した ndarray raw fast path は現行公開入力ではないため比較対象から外した。

## 13. 最終 verdict

**解消済み。** 初回監査の A-01〜A-02、B-01〜B-11、C-01〜C-14 はすべて閉じた。
現行実装に旧入力を温存する wrapper/alias/decoder は追加せず、repository 内 consumer、test、
stub、migration note を同時に現在の一契約へ更新した。

## 14. 最終検証

- `PYTHONPATH=src pytest -q -p no:cacheprovider`: **3601 passed**。
- `mypy src/grafix`: **240 source files、issue 0**。
- `ruff check src tests tools`: **pass**。
- `ruff check .`: 初回 baseline と同じ **25 件**のみ
  （`.agents/.../init_run_dir.py` の E741 3 件、`sketch/readme/` の F401 22 件）。
  今回差分に新規 Ruff failure はない。
- `git diff --check`: **pass**。
- benchmark focused test: **175 passed**。canonical short benchmark は上記 2 artifact へ保存した。
- export/stub focused test: **122 passed**。fresh-process 生成 stub
  `/tmp/grafix-reaudit-final2-api.pyi` は `src/grafix/api/__init__.pyi` と byte-for-byte 一致した。
- headless SVG/PNG/G-code 経路は export/runtime test と full suite で通過した。
- core contract、docs、non-core runtime の独立再監査はいずれも追加未解消 **0 件**だった。

未完了の監査指摘および未実行の計画検証は 0 件である。repository 全体 Ruff の既知 25 件は
監査開始前から存在する依頼範囲外差分として残し、変更していない。
