# sketch 実行時に描画ウィンドウが背面に回る件（原因調査メモ + 対策案）

作成日: 2026-01-18

## 現象

- `sketch`（= `run(draw)`）を実行すると、**Parameter GUI ウィンドウは前面に出る**が、**描画ウィンドウ（"Grafix"）が背面に隠れることがある**。

## 結論（現時点の最有力）

macOS + pyglet のウィンドウ生成順と「アプリの activate タイミング」の組み合わせで、

- 起動直後に **キーウィンドウ（最後に作られた方）だけが前面化**
- それ以外のウィンドウが **他アプリの背面に残る**

という状態になっている可能性が高い。

Grafix 側のコードでは、描画ウィンドウと Parameter GUI を **どちらも `pyglet.app.run()` を呼ぶ前**に生成している。
一方で pyglet は macOS で「unbundled な CLI 起動」を想定し `NSApp.activateIgnoringOtherApps_(True)` を呼ぶが、
そのタイミングが **イベントループ開始後（applicationDidFinishLaunching）** になるため、
「前面化されるウィンドウ」が 1 枚に偏る/順序依存になることがあり得る。

## 根拠（コード読みによる）

### Grafix 側（ウィンドウは event loop 前に作っている）

- `src/grafix/api/runner.py`
  - `DrawWindowSystem(...)` 内で描画ウィンドウ作成（`create_draw_window`）
  - `ParameterGUIWindowSystem(...)` 内で GUI ウィンドウ作成（`create_parameter_gui_window`）
  - その後に `MultiWindowLoop(...).run()` → `pyglet.app.run(...)`

つまり **2 枚のウィンドウ生成と `set_location` が先、`pyglet.app.run` が後**。

### pyglet 側（macOS の show/activate の挙動差）

手元環境の pyglet（`2.1.11`）実装（`pyglet/window/cocoa/__init__.py`）では：

- `set_visible(True)` は `makeKeyAndOrderFront_` を呼ぶ（＝表示はする）
- `activate()` は `NSApp.activateIgnoringOtherApps_(True)` を呼んだ上で `makeKeyAndOrderFront_` を呼ぶ（＝アプリごと前面化）

さらに `pyglet/app/cocoa.py` の AppDelegate（`applicationDidFinishLaunching_`）で
「unbundled CLI program のため強制 activate」を行っている。

これらを踏まえると、Grafix のように **event loop 前に複数 window を作る**場合、
`activateIgnoringOtherApps` が走るタイミングで「どれが key window か」によって、
描画ウィンドウが前面化されず背面に残る、が説明できる。

## 追加で切り分けしたいこと（再現条件のメモ）

手元で再現を絞るなら：

1. 起動時、別アプリ（VSCode 等）を最前面にして `python sketch/...py` を実行 → 描画ウィンドウが背面化しやすいか
2. Terminal/iTerm を最前面にして実行 → 問題が起きにくいか
3. `parameter_gui=False` で実行 → 1 枚構成なら起きないか（起きるなら別原因）

## 対策案

### A. 起動直後に両方のウィンドウを明示的に activate（推奨・最小）

狙い:
- macOS で「GUI は前面化するが描画は背面」の状態を潰す。

実装イメージ（方針）:
- `pyglet.app.run` が始まった直後に 1 回だけ、
  - `draw_window.window.activate()`
  - `gui.window.activate()`（GUI を最後に activate すれば GUI が手前 / 逆なら描画が手前）
  を呼ぶ。

備考:
- どちらを最後に activate するかで「起動直後にどちらへフォーカスを当てるか」を選べる。
  - 描画にフォーカス（ショートカット優先）: `gui.activate()` → `draw.activate()`
  - GUI にフォーカス（調整優先）: `draw.activate()` → `gui.activate()`

`pyglet.clock.schedule_once(..., 0.0)` で event loop 開始直後に流すのが簡単。
（ウィンドウ生成直後に呼んでも動く可能性はあるが、タイミング依存を避けたい）

### B. ウィンドウを `visible=False` で作り、event loop 開始後に show（中）

狙い:
- 「app activate より先に window を見せてしまう」状態そのものを避ける。

懸念:
- pyglet + GL コンテキストの都合で、不可視 window での初期化が期待通りか要確認。
- 手当の範囲が広がる。

### C. Parameter GUI を `style=tool` にする（目的が違うので非推奨）

`tool` は macOS の Utility Window 扱いになり、前面性が上がる可能性がある。
ただし今回困っているのは **描画が背面になる**ことであり、GUI の前面性を上げても解決しない。

## すすめ方（実装に進む場合）

1. まず A の「両ウィンドウの activate を 1 回だけ」から入る（`src/grafix/api/runner.py` だけの変更で済む想定）。
2. それで直らない/副作用がある場合に限り、B の「visible=False→後出し show」を検討する。
