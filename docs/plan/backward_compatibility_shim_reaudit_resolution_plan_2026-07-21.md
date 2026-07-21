# 後方互換・余計なシム・非正規実装の再監査 解消計画（2026-07-21）

作成日: 2026-07-21

基準 HEAD: `0b0e647`

基準作業ツリー: 新規監査レポート
`docs/review/backward_compatibility_shim_reaudit_2026-07-21.md` のみ未追跡

ステータス: **完了**

## 1. 目的

`docs/review/backward_compatibility_shim_reaudit_2026-07-21.md` の A-01〜A-02、
B-01〜B-11、C-01〜C-14 を、互換 wrapper、deprecated alias、旧 schema decoder、
test-only production fallback を追加せずに解消する。

完了条件は「指摘箇所だけを局所 patch した」ことではなく、次の状態である。

- G/E、operation registry、Geometry、RealizedGeometry の canonical contract が一つである。
- raw builtin 関数の非 canonical 入力を第二 API として維持しない。
- immutable と記述する object は、外部 alias や nested mutable value から変更できない。
- ParamStore、collapsed-header、MIDI snapshot の identity/schema が一形である。
- 不正データ、dependency mismatch、内部 ImportError、未確定 transaction を黙って成功扱いしない。
- repository 内 consumer、test、stub、docs、examples を破壊的変更と同時に更新する。

## 2. 本計画の承認で固定する破壊的決定

### 2.1 互換方針

- 旧入力を受ける wrapper、旧名 alias、deprecated 期間は設けない。
- private/raw API も、既存 test や repository 外利用の可能性だけを理由に温存しない。
- schema 変更時は旧 decoder や runtime migration を追加しない。
- one-shot migration tool は今回追加しない。必要な保存データは再生成する。

### 2.2 operation parameter

- G/E の `meta` 付き引数は、Parameter 記録 context の有無に関係なく同じ validator で
  defaults 適用後に一度だけ検証・正規化する。
- `int` は bool/float/string を受けず、`float` は bool/string/NaN/Inf を受けない。
- vec/rgb/choice も `parameters.validation` の一契約を使う。
- code-owned 引数も `Geometry` が署名化できる不変値だけを受ける。ndarray を暗黙追加しない。
- operation default は登録時に検証し、mutable list/dict を default として保持しない。

### 2.3 Geometry / RealizedGeometry

- `Geometry` の ID は内容からのみ生成し、constructor/pickle payload から任意 ID を注入できなくする。
- `RealizedGeometry` の正規形を、exact `np.ndarray`、C-contiguous、
  `coords: float32 (N,3)`、`offsets: int32 (M+1,)`、有限座標、整合済み offsets に固定する。
- `(N,2)` 補完、dtype cast、整数切り捨て、overflow wrap は行わず reject する。
- cache value は外部配列と memory を共有しない immutable snapshot とする。
- bytes-backed read-only array 等、caller が `setflags(write=True)` で再可変化できない所有形を使う。
- 性能上必要でも非 canonical fallback は戻さない。必要なら canonical core-owned factory を一つだけ
  明示し、外部/user evaluator 境界には使わない。

### 2.4 ParamStore

- collapsed-header は opaque string の prefix 規約でなく、tagged canonical identity を共有する。
- ParamStore schema は **v4** へ一度だけ上げ、v3 以前/future は変換せず拒否する。
- recovery の whole-store replacement は ParamStore/core operation が所有し、interactive 層から
  private field を列挙 copy しない。
- state invariant 通過後の `bool()` / `str()` による silent repair は行わない。

### 2.5 MIDI snapshot

- MIDI snapshot は schema version 付きの一形式へ変更する。
- payload は `schema_version` と、exact integer CC / finite float value の record 列で表す。
- CC は 0..127、value は 0.0..1.0、重複 CC は reject する。
- missing file だけを空 snapshot とし、I/O error、corrupt、unversioned、future、部分不正は
  部分成功せず明示エラーにする。

### 2.6 dependency / CLI

- Shapely は `shapely>=2,<3` を対応範囲とし、Shapely 1.x API fallback を削除する。
- 本計画の承認を dependency constraint 更新に対する Ask-first 承認とみなす。
- dependency metadata の変更だけを行い、この作業では install/download しない。
- `grafix config validate/show` の config path は **positional だけ**を正本とし、同義の
  `--config` を削除する。
- `run --midi-port` の無効化 token は exact `none` だけとし、空文字/`off`/大小違いを受けない。
- internal DTO は keyword-only に統一する。

## 3. 非目標・維持する境界

- root/API façade、`grafix.api.run()` の lazy import、G/E/P の registry dispatch は維持する。
- ParamStore reconcile という現行 domain feature自体は維持する。
- WorkspaceState/config の診断付き recovery、transaction rollback、late collision、worker recovery は維持する。
- source reload の last-good rollback は維持し、「確定忘れの次 poll 自動 accept」だけを削除する。
- optional MIDI/device disconnect、OS/Retina/font/clipboard、partial-resource cleanup は維持する。
- canonical input に対する数学、RNG consumption、描画順、回転順は意図せず変更しない。
- benchmark の計測 `compatibility_key` は維持する。
- commit、push、release、dependency install は行わない。

## 4. 実施原則

- [x] 作業開始時に `git status --porcelain` を確認した。
- [x] 基準 HEAD と、既存差分が新規監査レポートだけであることを確認した。
- [x] 本計画についてユーザー承認を得る。
- [x] 承認後にのみ、Shapely constraint 更新と full test/short benchmark を実行する。
- [x] 実装前 baseline を `/tmp` に保存する。
- [x] 同一ファイルを複数担当が同時編集しないよう Phase を順序付ける。
- [x] 各 Phase で focused test を通してから次へ進む。
- [x] 破壊的変更と repository 内 consumer/test/stub/docs を同時更新する。
- [x] 互換 wrapper、旧 decoder、暫定 alias を追加しない。
- [x] 完了項目を本ファイルで逐次チェックする。

## 5. Phase 0 — baseline と破壊範囲の固定

### 5.1 correctness baseline

- [x] full pytest の結果を `/tmp` に保存する。
- [x] `mypy src/grafix` の結果を保存する。
- [x] `ruff check .` の既知 failure と今回の対象を分離する。
- [x] checked-in stub を `/tmp` に保存し、fresh subprocess で再生成可能なことを確認する。
- [x] ParamStore v3、MIDI unversioned snapshot、Geometry pickle の代表 fixture を `/tmp/grafix-reaudit-baseline-fixtures` に保存する。
- [x] G/E coercion、RealizedGeometry cast/alias、preset collapse 漏れの focused probe を同ディレクトリへ保存する。

### 5.2 performance baseline

- [x] scale/rotate/translate/subdivide の canonical short benchmark と、削除対象 ndarray polyline case の基準値を保存する。
- [x] realized concat と draw/realize pipeline の short benchmark を保存する。
- [x] text/asemic、parameter merge、provenance の代表 case を保存する。
- [x] source reload/benchmark runner には登録 benchmark case がないため、baseline full pytest の focused test 結果を基準にする。
- [x] long suite は short で有意な退行が疑われた場合だけ実行する。

### 5.3 完了条件

- [x] 既知 failure と今回の退行を区別できる。
- [x] raw 非 canonical case を削除対象として分離し、canonical product behavior を比較できる。

## 6. Phase 1 — operation 引数の canonical validation

対象: A-01、C-09 の一部

### 6.1 中央 validator

- [x] `validate_operation_kwargs()` を「unknown/choice だけ」から、defaults 適用後の全 meta 値を
  検証・正規化して返す一境界へ変更する。
- [x] Parameter recording 有無による validation 差をなくし、recording は観測/override 解決だけを担当させる。
- [x] primitive/effect/selector の全 factory が同じ正規化済み params を `Geometry.create()` へ渡す。
- [x] E の通常 step は builder 作成時、selector は `params_by_target` の freeze 前に検証し、
  effect 適用時まで不正値を遅延させない。
- [x] registration 時に meta/default の対応、required args、default value を同じ規則で検証する。
- [x] code-owned default は Geometry 署名化可能な immutable value に限定する。

### 6.2 consumer 更新

- [x] primitive/effect 内の入口に残る `int()` / `float()` / `bool()` coercion を列挙する。
- [x] 中央で保証された引数について重複 coercion を削除する。
- [x] 数学上必要な float64 working cast は入力 coercion と区別して維持する。
- [x] generated stub と docstring を exact contract に同期する。

### 6.3 test

- [x] recording context の有無で同じ valid 値が同じ結果になる test を追加する。
- [x] string-to-number、bool-as-int、float-to-int、string-as-vec、list-as-vec、NaN/Inf を両 context で拒否する。
- [x] valid NumPy scalar を受けるか否かを `parameters.validation` の現行契約に合わせて一つに固定する。
- [x] custom operation と selector も builtin と同じ validation を通ることを確認する。

## 7. Phase 2 — Geometry / RealizedGeometry の正規 value object 化

対象: A-02、B-02

### 7.1 `Geometry`

- [x] `id` を caller-supplied constructor 引数から外し、正規化済み `op/inputs/args` から必ず計算する。
- [x] `Geometry.create()` と内部 restore を同じ生成境界へ統一する。
- [x] pickle restore は record 内容から ID を再計算し、不整合 payload を拒否する。
- [x] pickle の重複 ID、重複 arg、未知 input/root ID も silent overwrite せず拒否する。
- [x] inputs と args の型・正規化済み形を constructor invariant として検査する。
- [x] 同じ ID を異なる recipe に注入して cache を汚染できない test を追加する。

### 7.2 `RealizedGeometry`

- [x] `(N,2)` z 補完を削除する。
- [x] dtype cast を削除し、exact float32/int32、shape、C layout、有限性、offsets 整合性を検証する。
- [x] 外部/user evaluator 出力から独立した immutable backing を構築する。
- [x] `setflags(write=True)`、元配列、base/view のいずれからも変更できない test を追加する。
- [x] `_with_coords()` と concat/scene helper の ownership 契約を見直し、trusted path を一つ以下にする。
- [x] user-defined primitive/effect の float64/int64/N2/非有限/非 C-contiguous 出力を明示拒否する。
- [x] `GeomTuple` docstring、architecture、custom operation examples を exact contract に更新する。

### 7.3 test/performance

- [x] cache identity、pickle、deep DAG、concat、custom operation、renderer/export の focused test を通す。
- [x] snapshot copy による realize/cache/pipeline の差を baseline と比較する。
- [x] material regression がある場合も permissive cast/alias を戻さず、canonical owned path 内だけを最適化する。

## 8. Phase 3 — registry / builder の正本と immutable 化

対象: B-01、B-03、C-07、C-09

### 8.1 builtin registration

- [x] builtin callable/spec の immutable catalog/factory を live registry と分離する。
- [x] module が import 済みでも、欠落 builtin spec を catalog から再登録できるようにする。
- [x] `importlib.reload()` を再登録手段にせず、decorator 登録時に catalog へ spec を明示記録する。
- [x] `ensure_builtin_*_registered()` の返値を実際の登録状態と一致させる。
- [x] `replace_all()`、source reload candidate/live swap、custom overwrite の所有規則を一つにする。
- [x] registry clear/replace 後の ensure、catalog/list/describe、realize の test を追加する。

### 8.2 `EffectBuilder`

- [x] 通常 effect step を frozen DTO + normalized tuple args へ変更する。
- [x] selector step と通常 step の lowering interface を統一する。
- [x] `steps` 経由の nested mutationを不可能にする。
- [x] builder の equality/hash 方針を明示し、hashable を契約にするなら test する。

### 8.3 `OpSpec` / sentinel

- [x] defaults/meta/ui mappings の nested mutable value を登録時に拒否または canonical immutable 化する。
- [x] registry revision を増やさず default/meta を変更できない test を追加する。
- [x] `_DEFAULT_TARGET = cast(str, object())` を専用 unset 型/singleton に置き換える。
- [x] 実装 signature は unset 型との union を正直に表し、public overload/stub は
  `target: str = ...` の利用者向け表面を維持する。

## 9. Phase 4 — raw builtin の隠れ第二契約を削除

対象: B-04、B-05

### 9.1 effect

- [x] scale/translate/rotate/subdivide の raw direct-call test を canonical/integration test と分類し直す。
- [x] invalid offsets/shape/dtype、ndarray subclass dispatch、warning 個数、malformed 引数評価順を固定する test を削除する。
- [x] canonical inputs だけを前提に performance branch を簡素化する。
- [x] canonical geometry の数学、回転順、signed zero が product contract なら明示 test として残す。
- [x] empty geometry でも parameters は Phase 1 で先に検証されることを確認する。

### 9.2 `polyline`

- [x] 公開 Geometry 経路から到達不能な ndarray fast path を削除する。
- [x] warning 回数、sNaN、wide integer、mutating `closed.__bool__` の raw 互換 test を削除する。
- [x] `Sequence[Sequence[float]]` から immutable tuple を受ける一経路だけにする。
- [x] canonical sequence 入力、閉曲線、空 geometry、resource budget test を維持する。

### 9.3 benchmark

- [x] canonical effect/polyline benchmark を baseline と比較する。
- [x] raw invalid-input compatibility を benchmark/checksum contract に含めない。

## 10. Phase 5 — ParamStore の private bridge と identity/schema

対象: B-06、B-07、B-08、C-01〜C-03

実装順は、`GroupKey` 正本化 → collapsed-header identity/v4 → strict state/RGB →
whole-store replacement → site ID/test seam とし、新 identity 導入後に recovery copy を一度だけ直す。

### 10.1 identity / collapsed-header v4

- [x] `GroupKey` を `parameters.identity` の一定義へ統一し、re-export/重複 alias を削除する。
- [x] style/primitive/preset/effect-chain を表す frozen tagged identity を core に定義する。
- [x] store/memento/GUI/reconcile/prune が同じ型を使い、prefix string を各所で合成しないようにする。
- [x] core から preset registry を推測せず、migrate/prune は primitive/preset 両 tag の候補を対称に扱う。
- [x] variation parameter snapshot の `collapsed_by_header` と effect-order 側の chain header 生成も
  同じ identity/codec を使用する。
- [x] preset collapse state の migrate/prune/undo/redo/roundtrip test を追加する。
- [x] ParamStore schema を v4 に上げ、collapsed-header を明示 tagged record として encode/decode する。
- [x] main store は key record 列、variation snapshot は key + collapsed bool の record 列とし、
  dynamic JSON object key を使わない。
- [x] versionless/v1/v2/v3/future を変換せず拒否する test を更新する。
- [x] migration notes、README、recovery fixture を v4 に同期する。

### 10.2 strict state / RGB

- [x] `coerce_rgb255()` を削除し、canonical RGB validator に統一する。
- [x] string/bool/float/out-of-range RGB を reject する test へ更新する。
- [x] encode/memento/reconcile/resolver の `bool()` / `str()` silent repair を削除する。
- [x] `ParamState`/snapshot/store 更新境界で exact invariant を一度だけ検証し、内部では正規値を直接使う。
- [x] collection の有無を調べる制御フロー上の `bool(...)` は入力 coercion と区別して維持する。

### 10.3 whole-store replacement / favorite

- [x] recovery 用 whole-store replacement を ParamStore の `replace_contents_from()` に移す。
- [x] interactive `parameter_recovery.py` の private field 列挙 copy を削除する。
- [x] `_favorite_keys` compatibility property を削除し、snapshot/replace operation だけにする。
- [x] target store identity を維持し、source と mutable state を共有しない test を追加する。
- [x] revision/table/value/style/favorite と runtime effective/visibility token の単調更新、
  snapshot/favorite/value-log cache の無効化を確認する。

### 10.4 site identity / merge test seam

- [x] unknown site ID fallback を削除し、stack/frame を得られなければ fail-fast にする。
- [x] `make_site_id()` / `caller_site_id()` の双方で frame 枯渇を `RuntimeError` にする test を追加する。
- [x] `_apply_explicit_override_follow_policy()` は non-empty explicit 差分時だけ呼ぶ。
- [x] rollback fault-injection test は空 mapping seam でなく、実際の explicit False→True 変更を使う。

## 11. Phase 6 — MIDI/dependency/runtime fallback の strict 化

対象: B-09、C-04〜C-06

### 11.1 MIDI snapshot schema

- [x] `MIDI_CC_SNAPSHOT_SCHEMA_VERSION = 1` と strict codec/parser を定義する。
- [x] sorted record 列の exact key/type/range/unique validation を実装する。
- [x] `CcSnapshotLoadResult` で loaded/missing/corrupt/old/future と診断を表し、
  missing だけ空、I/O/corrupt/unversioned/future/部分不正は診断付き reject にする。
- [x] atomic writer を新 schema 一形だけに更新する。
- [x] frozen snapshot、controller startup、interactive diagnostic の consumer を更新する。
- [x] old/unversioned decoder や部分 salvaging を残さない。
- [x] unsupported/corrupt 原本を shutdown auto-save で上書きせず、明示 discard/正常 load 後だけ保存する。

### 11.2 MIDI port Protocol

- [x] `iter_pending()` / `close()` を要求する最小 Protocol を定義する。
- [x] constructor で完全 interface を検証し、`inport: object` と `getattr(close)` fallback を削除する。
- [x] test fake を現行 interface 完備にする。
- [x] optional no-device/disconnect の現行挙動は別 test で維持する。

### 11.3 Shapely / psutil

- [x] `pyproject.toml` を `shapely>=2,<3` に固定し、旧 `shapely.geos` fallback を削除する。
- [x] current environment（Shapely 2.1.2 / GEOS 3.13.1 / psutil 7.2.0）が対応範囲内と記録する。install/update は行わない。
- [x] required psutil は module-level の正規 import 一形にし、任意例外 fallback を削除する。
- [x] `cpu_times().user/system` を直接参照し、0 default を削除する。
- [x] child process race は psutil の明示 exception だけを除外する。
- [x] incomplete fake/API mismatch が fail-fast になる test と、正常 child race test を分離する。

### 11.4 MIDI runtime lifecycle の追加 strict 化

- [x] live message/update API は exact built-in int `0..127` を mutation 前に検証し、
  non-CC 以外の不正データを握りつぶさない。
- [x] JSON の重複 key、過大整数、過剰な nesting を corrupt として診断する。
- [x] `mido` を required dependency の一契約とし、import/backend error fallback を削除する。
- [x] `MidiSession` を canonical `CcSnapshotLoadResult` の構築時所有に統一し、
  後付け activation と値だけの constructor 経路を削除する。
- [x] shutdown save-block を診断付き skip とし、明示 discard は原本だけを空 v1 へ置き換えて
  live CC を保持する。
- [x] snapshot/connection 診断は event と controller の同一性で世代を管理し、
  stale action が再接続後の controller/診断を変更しない。
- [x] live の `clear_frozen_snapshot()` と live 中の reconnect は fail-fast とし、
  controller の無い persisted snapshot は discard callback を必須にする。
- [x] 名前/path/CC の暗黙 `str()` / `Path()` / `int()` 変換と、
  一部だけ drain する `poll_pending(max_messages=...)` を削除する。
- [x] port pending/iterator 失敗だけを `MidiConnectionError` へ分類し、
  message validation/internal error を Session の切断 recovery から除外する。
- [x] retry/discard は現在の diagnostic event、controller、load result の identity を検査し、
  controller の public reload mutation surface を削除する。
- [x] 切断時の controller を shutdown save owner として保持し、clear 後は所有を破棄する。
- [x] save/close を `CleanupErrors` の BaseException 対応契約に統一し、
  Session 構築前も rejected snapshot の save-block を診断付き skip にする。
- [x] `can_reconnect` を GUI の正本とし、MIDI 明示無効時の reconnect 操作を無効化する。

## 12. Phase 7 — benchmark/provenance の error classification

対象: B-10、C-14

### 12.1 benchmark

- [x] `_measure_in_process()` 全体の ImportError -> skipped 変換を削除する。
- [x] setup/workload/postprocess 内の ImportError が `status="error"` になる test を追加する。
- [x] 登録 case に optional platform capability が無いことを確認し、test 専用になる
  `BenchmarkUnavailable` は追加せず、setup を含む全 stage の例外を error にする。
- [x] unknown benchmark output の `repr()` fallback を削除し、typed/JSON-compatible output を要求する。
- [x] dict key は exact str、float は finite に限定し、`allow_nan=False` で JSON を生成する。

### 12.2 capture provenance

- [x] Config、ParamStore snapshot、manifest を各 owned encoder で正規値へ変換してから strict JSON encoder へ渡す。
- [x] mapping key は exact string に限定し、文字列化による衝突を許さない。
- [x] duck-typed `.item()` / `.tolist()` と unknown `repr()` fallback を削除する。
- [x] unknown type、非決定的 repr、key collision を拒否する test を追加する。
- [x] nonfinite float と任意 dataclass/set/Enum 等、owned schema 外の型を拒否する。
- [x] canonical manifest/checksum の deterministic roundtripを維持し、nested
  `RealizedGeometry` を返す登録 benchmark case も owned encoder で処理する。

## 13. Phase 8 — source reload / CLI / internal DTO の一契約化

対象: B-11、C-10〜C-13

### 13.1 source reload

- [x] pending rollback state のまま次の `poll()` を呼んだら invariant error にする。
- [x] explicit accept/rollback の一回性、generation mismatch、close terminal cleanup を test する。
- [x] production caller が全分岐で transaction を明示完結することを確認する。

### 13.2 CLI

- [x] config CLI の `--config` alias と衝突処理を削除し、positional path 一形へ更新する。
- [x] run CLI の空文字/`off`/casefold/strip MIDI alias を削除し、exact `none` にする。
- [x] `__main__._delegated_args()` を全 subcommand で使用し、手書き `--` 除去を削除する。
- [x] README/developer guide/help snapshot/CLI tests を正本に同期する。

### 13.3 DTO

- [x] `ExportJob` を `kw_only=True` にする。
- [x] constructor call site と process serialization test を更新する。
- [x] positional construction を拒否する test を追加する。

## 14. Phase 9 — text layout 重複の共通化

対象: C-08

| 項目 | `text` 固有部分 | `asemic` 固有部分 | 共通化する部分 |
| --- | --- | --- | --- |
| advance | フォントの cmap/hmtx/space metrics | glyph/space の固定 advance | 文字ごとの callback 呼出し |
| glyph | fontTools outline の平坦化と cache | seed 付き stroke 生成と cache | なし |
| layout | ascent を初期 Y に反映 | Y=0 から開始 | wrap、行幅、X alignment |
| bounding box | glyph placement とは別の追加線 | stroke 列への追加線 | alignment 済み 4 辺の生成 |

- [x] `text.py` と `asemic.py` の wrap、line width、alignment、bounding box の差分を表にする。
- [x] glyph/advance callback を受ける小さな `_text_layout.py` へ共通部分だけを抽出する。
- [x] glyph generation、asemic stroke generation、固有 metrics は各 primitive に残す。
- [x] text/asemic の canonical output、layout、resource budget test を維持する。
- [x] duplication を消すための汎用 framework や互換 wrapperを作らない。
- [x] text/asemic benchmark と checksum を baseline と比較する。

## 15. Phase 10 — 横断更新と全体検証

### 15.1 docs/stub/migration

- [x] public NumPy-style docstring と型 hint を新 contract に同期する。
- [x] `architecture.md` の N2 補完記述を削除する。
- [x] ParamStore v4、MIDI schema v1、strict G/E/GeomTuple、CLI 破壊変更を migration note に記録する。
- [x] README、developer guide、examples を正規 API 一形へ更新する。
- [x] fresh CLI subprocess で stub を再生成し、checked-in stub と同期する。
- [x] 監査レポート 27 件の解消マトリクスを追記する。

### 15.2 focused validation

- [x] core API/registry/geometry/realize/effects/primitives test。
- [x] parameters codec/persistence/reconcile/memento/recovery/GUI test。
- [x] MIDI/monitor/source reload/export job/config/run CLI test。
- [x] benchmark schema/runner/provenance/capture/export test。
- [x] text/asemic test と canonical short benchmark。

### 15.3 full validation

- [x] `PYTHONPATH=src pytest -q`。
- [x] `mypy src/grafix`。
- [x] `ruff check .`。既知 repository failure があれば今回差分と分離して記録する。
- [x] `git diff --check`。
- [x] headless SVG/PNG/G-code smoke。
- [x] fresh-process stub consistency。
- [x] benchmark short suite と baseline comparison。
- [x] 変更後の compatibility/fallback/alias/広い例外捕捉を再走査する。

## 16. 完了判定

- [x] A-01〜A-02、B-01〜B-11、C-01〜C-14 がすべて解消済み。
- [x] 旧 alias、旧 schema decoder、test-only production fallback、raw 非 canonical contract がない。
- [x] canonical runtime の correctness と性能を検証済み。
- [x] 未完了項目、既知 failure、未実行検証を明記済み。

## 17. 完了記録

- full pytest: **3601 passed**。
- mypy: **240 source files、issue 0**。
- `ruff check src tests tools`: pass。
- `ruff check .`: baseline と同じ 25 件のみ
  （`.agents/.../init_run_dir.py` の E741 3 件、`sketch/readme/` の F401 22 件）。
- `git diff --check`: pass。
- benchmark focused test: **175 passed**。
- export/stub focused test: **122 passed**。fresh-process stub は checked-in stub と一致。
- canonical short benchmark:
  - `/private/tmp/grafix-reaudit-final5a-benchmarks/runs/20260721_031010_909316_d0f918.json`
  - `/private/tmp/grafix-reaudit-final5b-benchmarks/runs/20260721_031030_591418_1563a4.json`
- core contract、docs、non-core runtime の独立再監査: 追加未解消 0 件。
- 未完了項目: 0 件。未実行検証: 0 件。

repository 全体 Ruff の既知 25 件は依頼範囲外であり、今回差分と分離して残した。
