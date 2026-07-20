# どこで: `src/grafix/api/presets.py`。
# 何を: preset を `P.<name>(...)` で呼び出す公開名前空間 P を提供する。
# なぜ: `@preset` で登録した「再利用単位」を、G/E と同じ感覚で呼び出せるようにするため。

from __future__ import annotations

import hashlib
import importlib
import sys
import types
from collections.abc import Callable
from functools import partial
from pathlib import Path

from grafix.core.parameters import validate_parameter_identity
from grafix.core.parameters.identity import identity_string
from grafix.core.preset_registry import PresetIdentity, preset_op
from grafix.core.runtime_config import RuntimeConfig, runtime_config
from grafix.core.scene import SceneItem

import grafix.core.preset_registry as preset_registry_module

_AUTOLOAD_KEY: tuple[Path | None, tuple[Path, ...]] | None = None


def _loaded_module_paths() -> set[Path]:
    """別名を含め、現在の process で実行済みの module source を返す。"""

    return {
        Path(module_file).resolve(strict=False)
        for module in tuple(sys.modules.values())
        if (module_file := getattr(module, "__file__", None)) is not None
    }


def _autoload_preset_modules(cfg: RuntimeConfig) -> None:
    """確定済み runtime config が指定する user preset を一度だけ import する。"""

    key = (cfg.config_path, tuple(cfg.preset_module_dirs))

    global _AUTOLOAD_KEY
    if _AUTOLOAD_KEY == key:
        return

    dirs = cfg.preset_module_dirs
    loaded_paths = _loaded_module_paths()
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
            resolved_path = py_path.resolve(strict=False)
            if resolved_path in loaded_paths:
                continue
            mod_name = pkg_name + "." + ".".join(rel.with_suffix("").parts)
            importlib.import_module(mod_name)
            loaded_paths.add(resolved_path)

    _AUTOLOAD_KEY = key


class PresetNamespace:
    """preset を `P.<name>(...)` で呼び出す名前空間。

    Notes
    -----
    - 初回アクセス時に `config.yaml` の `paths.preset_module_dirs` を走査し、
      ディレクトリ配下の `*.py` を自動 import して preset を登録する。
    - 未登録名は `AttributeError`。
    """

    __slots__ = ("_identity",)

    def __init__(self, identity: PresetIdentity | None = None) -> None:
        self._identity = identity

    def __getattr__(self, name: str) -> Callable[..., SceneItem]:
        if name.startswith("_"):
            raise AttributeError(name)

        registry = preset_registry_module.preset_registry
        op = preset_op(name)
        if op not in registry:
            _autoload_preset_modules(runtime_config())
            registry = preset_registry_module.preset_registry
        if op not in registry:
            raise AttributeError(f"未登録の preset: {name!r}")
        spec = registry[op]
        if self._identity is None:
            return spec.func
        return partial(spec.invoker, self._identity)

    def __call__(
        self,
        *,
        name: str | None = None,
        key: str | int | None = None,
        instance_key: str | int | None = None,
        shared: bool = False,
    ) -> "PresetNamespace":
        """label と parameter identity を保持する preset 名前空間を返す。

        ``key`` は semantic site、``instance_key`` は反復 instance を表す。
        ``shared=True`` は同じ semantic site を共有し、``instance_key`` との
        同時指定はこの呼び出しで拒否される。
        """

        validate_parameter_identity(
            key=key,
            instance_key=instance_key,
            shared=shared,
        )
        label = None if name is None else identity_string(name, name="preset label")
        return PresetNamespace(
            PresetIdentity(
                name=label,
                key=key,
                instance_key=instance_key,
                shared=shared,
            )
        )


P = PresetNamespace()
"""preset を `P.<name>(...)` で呼び出す公開名前空間。"""

__all__ = ["P", "PresetNamespace"]
