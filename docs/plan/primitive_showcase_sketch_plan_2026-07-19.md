# 全primitive showcaseスケッチ実装計画

- 作成日: 2026-07-19
- 状態: 完了（2026-07-19 承認・実装・検証済み）
- 対象: `sketch/showcase/primitives.py`
- 前提: 組み込みprimitive 20件を、1画面で名前と形を対応付けて確認できるようにする

## 1. 目的

`sketch/showcase/primitives.py`へ、現在の全組み込みprimitiveを明示的に
1回以上使用する静的な一覧スケッチを実装する。

単にAPIを呼び出すだけでなく、次を同時に満たす。

- 各primitiveの代表的な形状が視認できる
- primitive名が各sampleの直下に表示される
- 2D、3D、文字、手続き生成を同じ画面で比較できる
- seedを持つprimitiveも含め、同じ入力から同じgeometryを返す
- resource負荷を抑え、通常のpreviewで素早く開ける
- built-in manifestへprimitiveが追加されたとき、showcaseの更新漏れをtestで検出できる

## 2. 掲載対象

調査時点の `_BUILTIN_PRIMITIVE_MODULES` に登録された次の20件を掲載する。

1. `arc`
2. `asemic`
3. `bezier`
4. `circle`
5. `ellipse`
6. `grid`
7. `laplace_field_grid`
8. `line`
9. `lissajous`
10. `lsystem`
11. `polygon`
12. `polyline`
13. `polyhedron`
14. `rect`
15. `sphere`
16. `spiral`
17. `spline`
18. `text`
19. `torus`
20. `wave`

## 3. 画面構成

- 横4列、縦5行の20cell gridとする。
- 上部にタイトル、各cell下部にprimitive名を置く。
- 各sampleはcell中央付近へ収め、label領域と重ねない。
- 余計な装飾を増やさず、白背景・黒線の資料的な一覧にする。
- 3D primitiveは固定角度で回転し、XY投影でも立体構造が分かる向きにする。
- animationにはせず、`draw(_t)`は時刻へ依存しない。

## 4. sample方針

### 4.1 基本2D

- `line`: 斜め線
- `arc`: 270度未満の開いた円弧
- `circle`: 明確な閉円
- `ellipse`: 回転した長楕円
- `rect`: 回転した長方形
- `polygon`: 六角形
- `polyline`: ジグザグ
- `bezier`: S字のcubic curve

### 4.2 数理・格子・手続き生成

- `grid`: 低密度Cartesian grid
- `laplace_field_grid`: `cylinder_uniform`を低いline/sample数で表示
- `lissajous`: 非対称な周波数比
- `lsystem`: seed固定、低いiterationのplant
- `spiral`: 連続した複数turn
- `spline`: 4 anchorのopen Catmull–Rom
- `wave`: triangleと混同しにくいsine波

### 4.3 文字

- `text`: 短い実文字列
- `asemic`: seed固定の短い擬似文字列
- 全cellのlabelにも`text`を使うが、`text` sample本体は独立して設ける。

### 4.4 3D

- `polyhedron`: `icosahedron`
- `sphere`: `latlon`または`rings`
- `torus`: major/minor segmentを抑えたwireframe
- 固定した `E.rotate(...)` で立体として判読できる向きへ揃える。

## 5. 実装構造

- `PRIMITIVE_NAMES`へ掲載順を明示する。
- cell座標計算を小さなhelperへまとめる。
- `_primitive_samples()`が `(name, Geometry)` の列を返す。
- label生成をhelperへ分離する。
- `draw(_t)`はsampleとlabelを決定的な順序で連結して返す。
- `if __name__ == "__main__"`ではshowcase専用canvasで`run(...)`する。
- callable生成やregistryの動的呼出しは使わず、各 `G.<name>(...)` を明示的に記述する。

## 6. テスト

新規 `tests/sketch/test_primitive_showcase.py` で次を検証する。

- `PRIMITIVE_NAMES`がbuilt-in manifestの20件と完全一致する
- 重複名がない
- `_primitive_samples()`の名前順が`PRIMITIVE_NAMES`と一致する
- 各sampleを個別にrealizeでき、finiteな標準geometryを返す
- `draw(0.0)`全体をrealizeでき、空でない
- 同じsampleを再realizeしてchecksumが一致する
- showcase import時にGUIを起動しない

## 7. 視覚確認

- headless renderでPNGを生成する。
- primitive名とsampleの重なり、cell外へのはみ出し、極端な密度差を確認する。
- 特に `laplace_field_grid`、`lsystem`、`text`、3D 3件のサイズを調整する。
- 視覚調整でAPI対象を減らしたり、一覧名とsampleの対応を変えたりしない。

## 8. 実装チェックリスト

- [x] 20件の掲載順と代表引数を確定する
- [x] 4列×5行のsample配置を実装する
- [x] 全cellのlabelとタイトルを実装する
- [x] 3D sampleへ固定回転を適用する
- [x] `run(...)`入口を実装する
- [x] manifest完全一致テストを追加する
- [x] 各sampleと全体のrealizeテストを追加する
- [x] Ruff・pytest・mypy対象検査を通す
- [x] headless renderを目視確認し、配置を調整する

## 9. 完了条件

- `sketch/showcase/primitives.py`だけで全20 primitiveを名前付きで一覧できる
- built-in追加時にshowcase更新漏れが自動検出される
- 全sampleが有限かつ決定的にrealizeできる
- 3Dを含む全sampleが1画面で判読できる
- 対象テスト、Ruff、mypy、render確認が成功する

## 10. 検証結果

- showcase対象pytest: 5 passed
- 全pytest: 2097 passed, 1 skipped
- Ruff対象検査: pass
- mypy対象検査: pass
- `git diff --check`: pass
- headless PNG: 360×450 canvas内に全20 sample、タイトル、labelが収まることを目視確認
