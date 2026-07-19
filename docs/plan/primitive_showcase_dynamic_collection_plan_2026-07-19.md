# Primitive showcase動的収集・文字拡大計画

- 作成日: 2026-07-19
- 状態: 実装承認待ち
- 対象:
  - `sketch/showcase/primitives.py`
  - `tests/sketch/test_primitive_showcase.py`

## 1. 目的

現在のprimitive showcaseを次のように改善する。

- タイトルを現状より一段大きくする
- 各primitive名のlabelを現状より読みやすくする
- 組み込みprimitive追加時に、showcase側へ名前やsampleを手作業で追記しなくても
  次回起動時に自動掲載する
- primitive数が4の倍数を超えた場合も、行数とcanvas高さを自動で増やす
- 新規primitiveの既定geometryをcell内へ自動で中央配置・等方fitする
- 現在の20件については、特徴が伝わりやすく負荷の低いsampleを維持する

## 2. 動的収集の方針

### 2.1 収集元

組み込みprimitiveの中央manifestである
`grafix.core.builtins._BUILTIN_PRIMITIVE_MODULES`をsource of truthとする。

- manifestの名前をsortして掲載順を決める
- 各名前は`G.describe(name)`で登録を保証し、catalog entryを取得する
- geometry生成は`getattr(G, name)(**params)`を使う
- 固定の`PRIMITIVE_NAMES = (...)`列挙は廃止し、manifestから生成する

裸の`G.catalog()`だけを使うと、同一processで登録済みのユーザー定義primitiveや
pytest用primitiveまで混ざるため採用しない。

### 2.2 反映単位

新規builtinが通常どおり中央manifestへ登録されれば、showcase moduleの次回import、
すなわちスケッチの次回起動時に自動反映する。

実行中にregistryへprimitiveを追加してcanvas sizeまで即時変更する機能は対象外とする。
preview windowのcanvas sizeは起動時に確定するため、再起動単位の反映を明示契約とする。

## 3. sample生成

### 3.1 既知primitive

現在の20件については、名前ごとの大きなbuilder関数を持たず、次の小さな設定表へ整理する。

- `_SAMPLE_PARAMS`: 視認性または軽量化に必要な引数だけを保持
- `_SAMPLE_ROTATIONS`: `polyhedron`、`sphere`、`torus`等の固定3D回転

特にdefaultの頂点数が大きい`laplace_field_grid`、`sphere`、`lsystem`、
文字生成コストのある`text`、`asemic`は現在同等の軽量設定を維持する。

### 3.2 新規primitiveのfallback

設定表に名前がないprimitiveは、次のgeneric fallbackで自動生成する。

1. catalog entryの`required_args`が空であることを確認
2. `getattr(G, name)()`でdefault geometryを作る
3. geometryが非空・有限であることを確認
4. XY bboxを計測する
5. cellのsample領域へ収まるuniform scaleと移動量を算出する
6. 既存`E.affine(...)`で中央配置・等方fitする

現在の全builtinは引数なしで非空geometryを生成できる。
今後もbuiltin showcase掲載対象には「zero-argumentで非空・有限」という契約を課す。
値を推測できないrequired引数を持つprimitiveは誤ったplaceholderで隠さず、明確な例外と
test failureでAPI設計側へ知らせる。

### 3.3 auto-fit

- sampleを固定回転まで適用した状態で1回だけrealizeし、XY bboxを得る
- `factor = min(sample_width / bbox_width, sample_height / bbox_height)`とする
- 幅または高さが0のlineも、0でない軸だけを使ってfitする
- bbox中心を`pivot`とし、cell中心との差を`delta`にして`E.affine`へ渡す
- custom effectは登録しない

sampleのbounds計測とrecipe生成はmodule import世代につき1回だけcacheし、
毎frameのeager realizeを避ける。

## 4. 動的layout

- 列数は4列を維持する
- 行数は`ceil(primitive_count / 4)`で算出する
- `CANVAS_HEIGHT`はheader、行数×cell高さ、下marginから算出する
- `_cell_center(index)`とlabel位置は動的行数でも同じ規則を使う
- 21件目以降は自動的に6行目へ配置し、canvasも1行分拡張する
- 最終行が4件未満でも左から順に配置する

## 5. 文字サイズ

初期調整値は次とし、headless renderで最終決定する。

- タイトル: `scale=6.0`から約`8.0`へ拡大
- primitive label: `scale=3.4`から約`4.2`へ拡大
- header高さとlabel余白も同時に増やす

現時点で最長の`laplace_field_grid`が90幅のcellへ収まることを確認し、
文字同士、sample、canvas端との重なりがない値に調整する。

## 6. テスト

`tests/sketch/test_primitive_showcase.py`を次の動的契約へ更新する。

- 動的な名前列がsort済みbuiltin manifestと完全一致し、重複がない
- `_primitive_samples()`の名前列が動的な名前列と一致する
- 設定表にないsynthetic builtinを追加した条件でgeneric fallbackが選ばれる
- manifest外のユーザーprimitiveは収集しない
- 既知primitiveでは設定表のoverrideがfallbackより優先される
- 全sampleが非空・有限な標準geometryとしてrealizeできる
- primitive数が次の行へ増えたとき、行数とcanvas高さが1行分増える
- 全cell中心とlabel基準位置がcanvas内にある
- `draw(t)`が時刻非依存かつ決定的である
- import時に`run(...)`を呼ばない

synthetic registryを使うtestは既存registryを退避・復元するかisolated registryを使い、
他testへ登録状態を漏らさない。

## 7. 視覚・性能確認

- 現行builtin全件をheadless PNGへ出力する
- タイトルとlabelの可読性を目視確認する
- sampleとlabelの重なり、最長label、最終行、canvas端を確認する
- cold drawと同一session内warm drawを計測する
- bounds計測cacheにより、warm drawで全sampleを再realizeしないことを確認する

## 8. 実装チェックリスト

- [ ] builtin manifestから動的にcatalog entryを収集する
- [ ] 固定`PRIMITIVE_NAMES`列挙を廃止する
- [ ] 現行sample引数を設定表へ移す
- [ ] 未登録名向けgeneric default fallbackを実装する
- [ ] bbox計測と`E.affine`によるauto-fitを実装する
- [ ] sample生成をimport世代単位でcacheする
- [ ] primitive数から行数とcanvas高さを算出する
- [ ] タイトルとlabelを拡大する
- [ ] 動的収集・fallback・layout成長testを追加する
- [ ] 対象pytest、Ruff、mypy、`git diff --check`を通す
- [ ] headless renderを目視確認する
- [ ] 計画の完了項目と検証結果を更新する

## 9. 完了条件

- builtin manifestへdefault生成可能なprimitiveを追加するだけでshowcaseへ自動掲載される
- showcase側の固定名前列や固定20件return列挙を更新する必要がない
- primitive数増加時にcanvasが自動拡張され、追加sampleがclipされない
- 現行20件の特徴と軽量性が維持される
- タイトルと全labelが現状より大きく、重なりなく読める
- 動的収集、fallback、決定性、visual、対象検査がすべて成功する
