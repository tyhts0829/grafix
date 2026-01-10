# どこで: `src/grafix/api/presets.py`。
# 何を: preset を `P.<name>(...)` で呼び出す公開名前空間 P を提供する。
# なぜ: `@preset` で登録した「再利用単位」を、G/E と同じ感覚で呼び出せるようにするため。

from __future__ import annotations

import hashlib
import importlib
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafix.core.preset_registry import preset_func_registry
from grafix.core.runtime_config import runtime_config

_AUTOLOAD_KEY: tuple[Path | None, tuple[Path, ...]] | None = None


def _autoload_preset_modules() -> None:
    cfg = runtime_config()
    key = (cfg.config_path, tuple(cfg.preset_module_dirs))

    global _AUTOLOAD_KEY
    if _AUTOLOAD_KEY == key:
        return

    dirs = cfg.preset_module_dirs
    for d in dirs:
        dir_path = Path(d).resolve(strict=False)
        if not dir_path.is_dir():
            continue

        token = hashlib.sha256(str(dir_path).encode("utf-8")).hexdigest()[:10]
        pkg_name = f"grafix_user_presets_{token}"
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [str(dir_path)]  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg

        for py_path in sorted(dir_path.rglob("*.py")):
            rel = py_path.relative_to(dir_path)
            if rel.name == "__init__.py":
                continue
            mod_name = pkg_name + "." + ".".join(rel.with_suffix("").parts)
            importlib.import_module(mod_name)

    _AUTOLOAD_KEY = key


class PresetNamespace:
    """preset を `P.<name>(...)` で呼び出す名前空間。

    Notes
    -----
    - 初回アクセス時に `config.yaml` の `paths.preset_module_dirs` を走査し、
      ディレクトリ配下の `*.py` を自動 import して preset を登録する。
    - 未登録名は `AttributeError`。
    """

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)

        _autoload_preset_modules()

        func = preset_func_registry.get(name)
        if func is None:
            raise AttributeError(f"未登録の preset: {name!r}")
        return func


P = PresetNamespace()
"""preset を `P.<name>(...)` で呼び出す公開名前空間。"""

__all__ = ["P", "PresetNamespace"]
