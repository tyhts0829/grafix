以下は、コーディングエージェントに渡す「実装指示書」です。grafix の内部 API は仮定せず、追加すべき primitive の責務、入出力、アルゴリズム、テスト観点、パラメータ設計だけを明確化しています。

⸻

指示書：Primitive「LaplaceFieldGrid」を追加せよ（grafix）

目的

2D のラプラス場（\nabla^2\phi=0）に由来する「直交網（等ポテンシャル線 \phi=const と共役流線 \psi=const）」を、ポリライン群として生成し描画できる primitive を追加する。用途は、科学図版風のフィールド可視化や、ジェネレーティブ・タイポグラフィ／版画風の背景パターンの生成。

本 primitive は「物理解釈を厳密に守る」よりも、「直交性が保証され、パラメータで作風を増やせる」ことを優先する。初期実装は共形写像ベースを第一候補とし、将来的に数値ソルバ拡張を可能にする設計にする。

⸻

スコープ（フェーズ）

Phase 1（必須）

共形写像ベースの直交格子生成器を実装する。具体的には「W 平面で直交な直線格子を作り、解析的（共形）な写像 z=f(W;\theta) で z 平面へ写してポリライン化」する方式。

初期プリセットとして、少なくとも以下を実装する：1. cylinder_uniform：円柱まわりの一様場（今回の画像相当）
複素ポテンシャル W(z)=U(z+a^2/z) の逆写像で、外部領域を取る。2. mobius：モビウス変換での歪み（直交性保持）
z=(\alpha W+\beta)/(\gamma W+\delta) を採用（\alpha\delta-\beta\gamma\neq 0）。3. exp：指数写像（放射状／ログ極座標っぽい網）
z=\exp(kW) 等。

この3つがあれば「学術図版風」と「タイポグラフィ背景」と「放射状パターン」が揃う。

Phase 2（任意・将来）

数値ラプラスソルバ方式（任意境界・複数障害物）を追加できる拡張点だけ確保する。Phase 1 の API を壊さない。

⸻

Primitive の外部仕様（API）

Primitive 名：LaplaceFieldGrid（仮）

入力パラメータ（共通）
• preset: str
"cylinder_uniform" | "mobius" | "exp" | ...
• u_range: tuple[float,float]
• v_range: tuple[float,float]
W=u+iv 平面での描画範囲。例：(-L, L)。
• n_u: int, n_v: int
縦線（u=const）と横線（v=const）の本数。
• samples: int
1 本の線を何点でサンプルするか（ポリラインの分割数）。
• clip: dict or None
描画領域のクリッピング。最低限「矩形クリップ」を想定。grafix 側のクリップ機構に合わせるが、ここでは抽象的に「最終ポリラインを外側で切る」責務を持つ。
• stroke_style: dict
線幅や色等は grafix 側に委譲して良いが、primitive がレイヤへ流すデータ構造に必要なら保持。

追加パラメータ（preset ごと）
• cylinder*uniform:
• a: float（円柱半径）
• U: float（遠方一様場の強さ。スケーリング要素）
• gap: float（円のすぐ外側に隙間を作る比率 or 実距離）
• angle: float（回転：遠方場の向き。rad）
• center: tuple[float,float]（平行移動）
• mobius:
• alpha, beta, gamma, delta: complex（係数）
• post_scale, post_rotate, post_translate（任意）
• exp:
• k: complex（スケール＋回転を含む）
• post*\*（任意）

出力
• 基本出力は「ポリラインの配列」＋「任意の境界線（円など）のポリライン」。
• 例：{"lines": list[np.ndarray(N,2)], "boundaries": list[np.ndarray(M,2)]} のような中間表現。
• grafix の既存 primitive へ渡す最終形式（Path/Polyline/GeometryRecipe）は実装側で変換する。

⸻

アルゴリズム仕様（Phase 1）

共通骨格 1. W=u+iv 平面で直交格子を生成する。
• u=const 線：u = linspace(u_min,u_max,n_u)、v を linspace(v_min,v_max,samples) で走査して点列を作る。
• v=const 線：同様に v 固定で u を走査。2. 解析写像 z=f(W;\theta) を適用して z 平面の点列に変換する。3. マスクにより「描画しない領域（障害物内部など）」を除外し、連続区間ごとに分割して複数ポリラインにする（円境界で線を止めるため）。
• 分割は「mask が True の連続区間」を抽出。
• 2 点未満は捨てる。
• 障害物の周りで線が不連続になるのが正しい表現。4. 回転・平行移動・スケール（等方）を適用する。
非等方スケール・せん断は直交性を壊すので「やるなら意図的な破壊」として明示し、デフォルトは無効。5. 必要なら clip を適用し、最終ポリライン群を返す。

cylinder_uniform の詳細
• 前提：複素ポテンシャル
W(z)=U(z+a^2/z)
を用い、逆写像で z を求める。
• 逆写像：
z^2-(W/U)z+a^2=0 を解く。
2根のうち外部解（通常 |z|\ge a）を選ぶ。
• 判別：
z1=(w+sqrt(w^2-4a^2))/2、z2=(w-sqrt(...))/2（w=W/U）
外部解は abs(z) が大きい方を選択。
• 障害物除外：
abs(z) >= a\*(1+gap) を mask とし、円のすぐ外側に隙間を作る。
• 円境界は別ポリラインで生成：
(a\cos\theta, a\sin\theta) を高解像度でサンプル。

数値安定性
• sqrt は複素平方根（principal branch）でよいが、枝切りの影響で線がねじれることがある。ねじれが出た場合は「W 平面の範囲 L を下げる」「サンプル密度を上げる」等の回避策を用意する。
• samples は最低でも 300 程度、デフォルト 800～1200 を推奨。
• ポリラインが極端に長くなる場合はダウンサンプリングや簡約（RDP）を optional にする。

⸻

実装上の設計要求 1. 「写像関数」を差し替え可能にすること。
preset を switch してもよいが、内部は map_W_to_z(W)->Z を返す関数として分離する。2. 「マスクと分割」を共通ユーティリティとして独立させること。
• split_by_mask(points, mask)->list[points]
• mask_for_preset(z)->bool array の形にする。3. 依存を最小化すること。
• 数値は numpy 程度に留める。
• grafix に既存のベクトル／パス表現があるならそれへ変換する薄いアダプタ層を作る。4. 再現性とデバッグ容易性
• 同じ引数で同じ出力になる（乱数は不要）。
• 主要パラメータをログ or メタデータとして保持できるとなおよい。

⸻

デフォルトパラメータ案（動く・それっぽい）
• u_range=(-6,6), v_range=(-6,6)
• n_u=45, n_v=45
• samples=900
• cylinder_uniform: a=1.0, U=1.0, gap=0.002, angle=0.0, center=(0,0)
• これで画像の雰囲気に近い。

⸻

受け入れ基準（Done の定義）1. LaplaceFieldGrid(preset="cylinder_uniform", ...) が例外なく動き、ポリライン群を返す。2. \phi 線と \psi 線の直交性が視覚的に保たれている（少なくとも円近傍で破綻しない）。3. 円内部に線が侵入しない（gap に応じて円周に余白ができる）。4. preset を切り替えると明確に異なるパターンが得られる（少なくとも mobius/exp）。5. 入力範囲が過大でも破綻しにくい（最悪でも「線が増えすぎる」程度で、NaN で全滅しない）。

⸻

テスト観点（自動＋目視）
• 自動：
• samples<2 など不正値のバリデーション。
• 出力に NaN/Inf が含まれない。
• mask 分割が正しく、全点が mask==True の区間にのみ含まれる。
• 目視：
• 円近傍で線が滑らかに回り込み、直交して見える。
• n_u,n_v を増やすと密度が増えるだけで崩れない。
• angle 回転が期待通り。

⸻

追加提案（任意）
• “版画っぽさ”を出すオプションとして、線ごとに極微小な位相ずらし（ただし直交性を壊すので、これは「表現のための破壊」として別モードに分ける）。
• ポリライン簡約（RDP）を simplify_tolerance で提供し、重いときの救済にする。

⸻

実装優先順位 1. 共通骨格（格子生成 → 写像 → マスク分割）2. cylinder_uniform の map と mask と boundary 3. mobius / exp の map 実装 4. 回転・平行移動・クリップの適用 5. テスト（最低限 NaN/Inf、mask 分割）

⸻

この指示書の狙いは、grafix の内部仕様を知らなくても「ポリライン群を生成する純粋関数＋薄いアダプタ」に落とせるようにすることです。実装後、grafix 側の primitive の作法に合わせて最後の変換だけ当てれば良い構造になります。
