"""`grafix.api.__init__.pyi` が最新生成結果と一致することのテスト。"""

from __future__ import annotations

import importlib
from pathlib import Path


def test_api_stub_sync(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root))
    monkeypatch.syspath_prepend(str(repo_root / "src"))

    gen = importlib.import_module("grafix.devtools.generate_stub")
    runtime_config = importlib.import_module("grafix.core.runtime_config")
    packaged_config = repo_root / "src/grafix/resource/default_config.yaml"
    # Installed stub はproject-local presetを含めない。開発者の
    # .grafix/config.yaml の有無で同期判定が変わらないよう設定を固定する。
    with runtime_config.runtime_config_scope(packaged_config):
        expected = gen.generate_stubs_str()

    stub_path = repo_root / "src" / "grafix" / "api" / "__init__.pyi"
    actual = stub_path.read_text(encoding="utf-8")
    assert actual == expected
