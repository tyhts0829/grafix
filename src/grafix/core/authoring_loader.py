"""runtime config が指定する authoring module を candidate catalog へ読み込む。"""

from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import RLock

from grafix.core.authoring_definitions import (
    AuthoringDefinitionsSnapshot,
    RegistrationTarget,
    default_authoring_definitions,
    registration_scope,
)
from grafix.core.authoring_recipe import (
    AuthoringDefinitionsRecipe,
    AuthoringModuleSource,
    AuthoringSourceRoot,
)
from grafix.core.builtins import builtin_operation_catalog
from grafix.core.definition_fingerprint import attach_module_content_fingerprint
from grafix.core.operation_catalog import compose_operation_catalogs
from grafix.core.runtime_config import RuntimeConfig

_CANDIDATE_PACKAGE_PREFIX = "_grafix_config_authoring_"
_IMPORT_LOCK = RLock()


def default_session_authoring_definitions() -> AuthoringDefinitionsSnapshot:
    """builtin と通常 module-scope declaration を一度だけ snapshot する。"""

    authored = default_authoring_definitions.snapshot()
    return AuthoringDefinitionsSnapshot(
        operations=compose_operation_catalogs(
            builtin_operation_catalog(),
            authored.operations,
        ),
        presets=authored.presets,
        recipe=AuthoringDefinitionsRecipe(),
    )


def authoring_definitions_for_draw(
    draw: Callable[..., object],
    *,
    config: RuntimeConfig,
    definitions: AuthoringDefinitionsSnapshot | None = None,
) -> AuthoringDefinitionsSnapshot:
    """明示値、draw generation、config candidate の順で一 snapshot を選ぶ。"""

    if not callable(draw):
        raise TypeError("draw は callable である必要があります")
    if type(config) is not RuntimeConfig:
        raise TypeError("config は exact RuntimeConfig である必要があります")
    if definitions is not None:
        if type(definitions) is not AuthoringDefinitionsSnapshot:
            raise TypeError(
                "definitions は exact AuthoringDefinitionsSnapshot または None です"
            )
        return definitions
    candidate = getattr(draw, "__grafix_authoring_definitions__", None)
    if candidate is None:
        return load_config_authoring_definitions(config)
    if type(candidate) is not AuthoringDefinitionsSnapshot:
        raise TypeError(
            "draw.__grafix_authoring_definitions__ は "
            "exact AuthoringDefinitionsSnapshot です"
        )
    return candidate


def _module_name(package_name: str, relative_path: Path) -> str:
    module_path = (
        relative_path.parent
        if relative_path.name == "__init__.py"
        else relative_path.with_suffix("")
    )
    parts = module_path.parts
    if any(not part.isidentifier() for part in parts):
        raise ValueError(
            f"authoring module path は Python identifier で構成する必要があります: {relative_path}"
        )
    return ".".join((package_name, *parts))


def _candidate_sources(root: Path) -> tuple[AuthoringModuleSource, ...]:
    """root 配下の Python source を bytes snapshot として安定順で返す。"""

    if not root.is_dir():
        return ()
    return tuple(
        AuthoringModuleSource(
            relative_path=path.relative_to(root),
            content=path.read_bytes(),
        )
        for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).parts)
    )


def capture_authoring_definitions_recipe(
    config: RuntimeConfig,
) -> AuthoringDefinitionsRecipe:
    """config directory の module bytes を worker-safe recipe へ一度だけ固定する。"""

    if not isinstance(config, RuntimeConfig):
        raise TypeError("config は RuntimeConfig である必要があります")
    roots = tuple(Path(path).resolve(strict=False) for path in config.preset_module_dirs)
    return AuthoringDefinitionsRecipe(
        roots=tuple(
            AuthoringSourceRoot(path=root, modules=_candidate_sources(root))
            for root in roots
        )
    )


def _candidate_fingerprint(recipe: AuthoringDefinitionsRecipe) -> str:
    """absolute path に依存しない candidate source fingerprint を返す。"""

    digest = hashlib.sha256()
    for root_index, root in enumerate(recipe.roots):
        sources = root.modules
        digest.update(root_index.to_bytes(8, "big"))
        digest.update(len(sources).to_bytes(8, "big"))
        for source in sources:
            relative = source.relative_path.as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(source.content).to_bytes(8, "big"))
            digest.update(source.content)
    return digest.hexdigest()


class _SnapshotSourceLoader(importlib.abc.Loader):
    """``.pyc`` を介さず candidate の確定済み source bytes を実行する。"""

    def __init__(
        self,
        source: AuthoringModuleSource,
        *,
        path: Path,
        canonical_name: str,
    ) -> None:
        self._source = source
        self._path = path
        self._canonical_name = canonical_name

    def create_module(
        self,
        spec: importlib.machinery.ModuleSpec,
    ) -> types.ModuleType | None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        source = self._source
        module.__grafix_source_owner__ = self._canonical_name  # type: ignore[attr-defined]
        attach_module_content_fingerprint(module, source.content)
        code = compile(
            source.content,
            str(self._path),
            "exec",
            dont_inherit=True,
        )
        exec(code, module.__dict__)


class _CandidateSourceFinder(importlib.abc.MetaPathFinder):
    """candidate namespace 内だけを source snapshot から解決する finder。"""

    def __init__(
        self,
        package_names: tuple[str, ...],
        roots: tuple[AuthoringSourceRoot, ...],
    ) -> None:
        modules: dict[str, tuple[Path, AuthoringModuleSource]] = {}
        canonical_names: dict[str, str] = {}
        namespaces: set[str] = set()
        for package_name, root in zip(
            package_names,
            roots,
            strict=True,
        ):
            sources = root.modules
            package_depth = len(package_name.split("."))
            for source in sources:
                module_name = _module_name(package_name, source.relative_path)
                if module_name == package_name:
                    continue
                if module_name in modules:
                    raise ValueError(
                        f"同じ authoring module 名へ解決される source があります: {module_name}"
                    )
                modules[module_name] = (root.path / source.relative_path, source)
                canonical_names[module_name] = (
                    "_grafix_config_authoring"
                    + module_name.removeprefix(package_name)
                )
                parts = module_name.split(".")
                namespaces.update(
                    ".".join(parts[:depth]) for depth in range(package_depth + 1, len(parts))
                )
        self._modules = modules
        self._canonical_names = canonical_names
        self._namespaces = namespaces - modules.keys()

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: types.ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        source_record = self._modules.get(fullname)
        if source_record is not None:
            source_path, source = source_record
            search_locations = [f"<grafix-candidate:{fullname}>"] if source.is_package else None
            return importlib.util.spec_from_file_location(
                fullname,
                source_path,
                loader=_SnapshotSourceLoader(
                    source,
                    path=source_path,
                    canonical_name=self._canonical_names[fullname],
                ),
                submodule_search_locations=search_locations,
            )
        if fullname not in self._namespaces:
            return None
        spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
        spec.submodule_search_locations = [f"<grafix-candidate:{fullname}>"]
        return spec


def _install_namespace_package(name: str) -> None:
    package = types.ModuleType(name)
    package.__package__ = name
    package.__path__ = [f"<grafix-candidate:{name}>"]  # type: ignore[attr-defined]
    package.__file__ = None
    package.__grafix_fingerprint_name__ = "_grafix_config_authoring"  # type: ignore[attr-defined]
    spec = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    spec.submodule_search_locations = list(package.__path__)
    package.__spec__ = spec
    sys.modules[name] = package


def _remove_candidate_modules(package_names: tuple[str, ...]) -> None:
    prefixes = tuple(f"{name}." for name in package_names)
    for module_name in tuple(sys.modules):
        if module_name in package_names or module_name.startswith(prefixes):
            sys.modules.pop(module_name, None)


def load_authoring_definitions_recipe(
    recipe: AuthoringDefinitionsRecipe,
    *,
    seed: AuthoringDefinitionsSnapshot | None = None,
) -> AuthoringDefinitionsSnapshot:
    """確定済み recipe を隔離実行し、成功時だけ snapshot を返す。

    module namespace は import 中だけ ``sys.modules`` に置き、成功・失敗の両方で
    破棄する。import 自体を直列化するため、別 thread/session の registration target
    が混ざらない。返す catalog と callable は module object の global namespace を
    直接保持するため、評価時に process-global module registry を参照しない。
    """

    if type(recipe) is not AuthoringDefinitionsRecipe:
        raise TypeError("recipe は exact AuthoringDefinitionsRecipe です")
    base = default_session_authoring_definitions() if seed is None else seed
    if type(base) is not AuthoringDefinitionsSnapshot:
        raise TypeError("seed は exact AuthoringDefinitionsSnapshot である必要があります")

    target = RegistrationTarget(
        operations=base.operations,
        presets=base.presets,
    )
    combined_recipe = (
        None
        if base.recipe is None
        else AuthoringDefinitionsRecipe(roots=(*base.recipe.roots, *recipe.roots))
    )
    if not any(root.modules for root in recipe.roots):
        return target.snapshot(recipe=combined_recipe)

    fingerprint = _candidate_fingerprint(recipe)
    package_names = tuple(
        f"{_CANDIDATE_PACKAGE_PREFIX}{fingerprint}_{index}"
        for index in range(len(recipe.roots))
    )
    finder = _CandidateSourceFinder(package_names, recipe.roots)

    with _IMPORT_LOCK:
        _remove_candidate_modules(package_names)
        sys.meta_path.insert(0, finder)
        try:
            with registration_scope(target):
                for package_name, root in zip(
                    package_names,
                    recipe.roots,
                    strict=True,
                ):
                    sources = root.modules
                    entry_sources = tuple(source for source in sources if not source.is_package)
                    if not entry_sources:
                        continue
                    _install_namespace_package(package_name)
                    for source in entry_sources:
                        module_name = _module_name(package_name, source.relative_path)
                        if module_name not in sys.modules:
                            importlib.import_module(module_name)
        finally:
            sys.meta_path.remove(finder)
            _remove_candidate_modules(package_names)

    return target.snapshot(recipe=combined_recipe)


def load_config_authoring_definitions(
    config: RuntimeConfig,
    *,
    seed: AuthoringDefinitionsSnapshot | None = None,
) -> AuthoringDefinitionsSnapshot:
    """config directories を一度 capture し、その exact recipe を実行する。"""

    recipe = capture_authoring_definitions_recipe(config)
    return load_authoring_definitions_recipe(recipe, seed=seed)


__all__ = [
    "authoring_definitions_for_draw",
    "capture_authoring_definitions_recipe",
    "default_session_authoring_definitions",
    "load_authoring_definitions_recipe",
    "load_config_authoring_definitions",
]
