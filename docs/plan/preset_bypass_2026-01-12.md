# Preset: bypass 引数を decorator で自動追加（primitive と同様）チェックリスト（2026-01-12）

目的: preset でも `bypass: bool` を **`@preset` デコレータ機能**として自動追加し、Parameter GUI から ON/OFF を制御できるようにする（primitive/effect と体験を揃える）。

背景:

- effect は `@effect` が `bypass` を自動追加し、`bypass=True` で no-op にできる。
- primitive は `@primitive` が `bypass` を自動追加し、`bypass=True` で空ジオメトリにできる。
- preset は `@preset(meta=...)` で「公開パラメータだけ GUI に出す」境界になっているが、`bypass` が無く、GUI から一時的に無効化できない。

非目的:

- parameter_gui テーブル描画の全面改修
- `@preset` の責務拡大（公開引数/内部 mute の基本設計は維持）
- 互換ラッパー/シムの追加（リポ方針に従い作らない）

---

## 0) 事前に決める（あなたの確認が必要）

- [ ] `bypass=True` の preset は何を返すべきか（実行時の意味）を確定する。；A で
  - 候補 A（提案）: **空 Geometry** を返す（`Geometry.create(op="concat")` 相当）
    - 理由: preset は GUI 側でも primitive 扱いされており、「そのブロックを無効化」の意味が最も単純。
    - 影響: geometry 以外を返す preset を bypass すると型が変わる（ただし通常は GUI 操作でのみ発火）。
  - 候補 B: `bypass=True` のときは例外（`TypeError` 等）にする（安全だが操作性が悪い）。
  - 候補 C: `@preset(..., bypass_return=...)` のように戻り値を指定させる（柔軟だが設計が増える）。
- [ ] `meta={}` の preset でも bypass を自動追加して GUI に出すか。；はい
  - 方針案 1（提案）: **出す**（公開引数がゼロでも bypass だけで “一時無効化” ができる）
  - 方針案 2: 出さない（meta=公開契約を厳密にする）
- [ ] `bypass` の扱いを “予約引数” として確定する。
  - [ ] `@preset(meta=...)` に `bypass` を含めるのは禁止（`ValueError`）でよいか；はい
  - [ ] 関数シグネチャ側に `bypass` を書くのも禁止（`ValueError`）にするか（禁止しない場合は「書いても無視される」ため紛らわしい）

---

## 1) 受け入れ条件（完了の定義）

- [ ] `P.<name>(bypass=True, ...)` が例外なく動作する（preset 本体に `bypass` 引数追加が不要）。
- [ ] Parameter GUI に preset の `bypass` が表示され、True で “無効化” できる。
- [ ] preset の GUI 表示順が `bypass` → 既存の signature 順になる（primitive/effect と揃う）。
- [ ] `python -m grafix stub`（または同等）で生成される `P.<name>(...)` のスタブに `bypass: bool = ...` が含まれる。
- [ ] 関連テストが通る（最小）:
  - [ ] `PYTHONPATH=src pytest -q tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
  - [ ] `PYTHONPATH=src pytest -q tests/api/test_preset_namespace.py`
  - [ ] `PYTHONPATH=src pytest -q tests/devtools/test_generate_stub_p_presets.py`
  - [ ] `PYTHONPATH=src pytest -q tests/stubs/test_api_stub_sync.py`

---

## 2) 実装方針（最小）

### A) `@preset` が `bypass` を自動注入する

- 対象: `src/grafix/api/preset.py`
- 変更内容（案）:
  - [ ] `reserved = {"name", "key", "bypass"}` とし、meta に `bypass` が含まれていたら `ValueError`
  - [ ] `preset_registry` 登録時の meta/param_order を `bypass` 付きにする
    - meta: `{"bypass": ParamMeta(kind="bool"), **meta_norm}`
    - param_order: `("bypass", *sig_order)`
  - [ ] wrapper 実行時に `bypass` を “シグネチャ外の予約 kwarg” として先に吸収する
    - `bypass_raw = kwargs.pop("bypass", False)`（bind 前）
    - `explicit_bypass = "bypass" in kwargs_before_pop` を保持し、`explicit_args` に反映する
  - [ ] `resolve_params()` は `bypass` を含む公開引数だけ解決する
    - `public_params = {"bypass": bypass_raw, **(meta_keys_from_user)}` の形で渡す
    - `meta` も `bypass` 付きで渡す
  - [ ] `bypass=True` の場合は preset 本体を呼ばずに早期 return する（0) で決めた挙動）

### B) “空 Geometry” の生成方法を 1 箇所に固定する

- 対象候補: `src/grafix/api/preset.py`
- 案:
  - [ ] `from grafix.core.geometry import Geometry` を使い、`Geometry.create(op="concat")` を返す（realize すると空になる）

---

## 3) テスト更新（最小）

- [ ] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
  - [ ] preset の並び順テストに `bypass` 行を追加し、`["bypass", ...]` になることを確認する
- [ ] `tests/api/test_preset_namespace.py`
  - [ ] snapshot に `{"x"}` だけでなく `{"bypass", "x"}` が入る想定へ更新する（bypass 自動追加のため）
  - [ ] （任意）geometry を返す preset を 1 つ用意し、`bypass=True` で空 Geometry を返すことをテストする
- [ ] `tests/devtools/test_generate_stub_p_presets.py`
  - [ ] 生成スタブの期待文字列を `bypass` 付きへ更新する

---

## 4) 変更箇所（ファイル単位）

- [ ] `src/grafix/api/preset.py`
- [ ] `tests/interactive/parameter_gui/test_parameter_gui_param_order.py`
- [ ] `tests/api/test_preset_namespace.py`
- [ ] `tests/devtools/test_generate_stub_p_presets.py`
- [ ] `src/grafix/api/__init__.pyi`（スタブ再生成で更新）

---

## 5) 実装手順（順序）

- [ ] 事前確認: `git status --porcelain` で依頼範囲外の差分/未追跡を把握（触らない）
- [ ] 0. の決定を確定
- [ ] `src/grafix/api/preset.py` を実装（bypass 注入 + 早期 return）
- [ ] テストを必要最小限で更新（param order / preset namespace / stub gen）
- [ ] `python -m grafix stub`（または `python -m tools.gen_g_stubs`）でスタブを再生成
- [ ] 対象テストを実行して確認

---

## 追加で事前確認したほうがいい点 / 追加提案（気づいたら追記）

- [ ] Parameter GUI 上の表示名: preset の `bypass` 行ラベルを単に `bypass` とするので十分か（説明文が必要なら meta 側に拡張が必要）。
- [ ] `@preset` を “Geometry を返すコンポーネント” に寄せたい場合、README の preset 節に「bypass は空 Geometry を返す」を追記する。
