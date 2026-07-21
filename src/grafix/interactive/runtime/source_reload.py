"""sketch sourceを隔離loadし、成功時だけcallableとregistryを交換する。"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import sys
import traceback
import types
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import grafix.core.effect_registry as effect_registry_module
import grafix.core.preset_registry as preset_registry_module
import grafix.core.primitive_registry as primitive_registry_module
from grafix.core.effect_registry import EffectFunc
from grafix.core.op_registry import OpRegistry, OpSpec
from grafix.core.preset_registry import PresetRegistry, PresetSpec
from grafix.core.primitive_registry import PrimitiveFunc
from grafix.core.scene import SceneItem
from grafix.core.value_validation import (
    exact_bool,
    exact_integer,
    exact_string,
    exact_string_choice,
    finite_real,
)

ReloadStatus = Literal["unchanged", "reloaded", "failed"]
SourceFingerprint = tuple[int, int] | tuple[Literal["missing"]]


@dataclass(frozen=True, slots=True)
class SourceReloadResult:
    """1回のstat/reload判定結果。"""

    status: ReloadStatus
    generation: int
    draw: Callable[[float], SceneItem]
    summary: str | None = None
    details: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            exact_string_choice(
                self.status,
                name="status",
                choices=("unchanged", "reloaded", "failed"),
            ),
        )
        object.__setattr__(
            self,
            "generation",
            exact_integer(self.generation, name="generation", minimum=-1),
        )
        if not callable(self.draw):
            raise TypeError("draw は callable である必要があります")
        for name in ("summary", "details", "source"):
            value = getattr(self, name)
            if value is not None:
                exact_string(value, name=name)


@dataclass(slots=True)
class _RegistryBundle:
    effects: OpRegistry[EffectFunc]
    primitives: OpRegistry[PrimitiveFunc]
    presets: PresetRegistry


@dataclass(frozen=True, slots=True)
class _RegistryMappings:
    effects: Mapping[str, OpSpec[EffectFunc]]
    primitives: Mapping[str, OpSpec[PrimitiveFunc]]
    presets: Mapping[str, PresetSpec]


@dataclass(frozen=True, slots=True)
class _RollbackState:
    """worker swap確定まで保持する直前generation。"""

    committed_generation: int
    previous_generation: int
    previous_draw: Callable[[float], SceneItem]
    previous_module_name: str | None
    previous_registries: _RegistryMappings


def _live_bundle() -> _RegistryBundle:
    return _RegistryBundle(
        effects=effect_registry_module.effect_registry,
        primitives=primitive_registry_module.primitive_registry,
        presets=preset_registry_module.preset_registry,
    )


def _bundle_mappings(bundle: _RegistryBundle) -> _RegistryMappings:
    return _RegistryMappings(
        effects=dict(bundle.effects.items()),
        primitives=dict(bundle.primitives.items()),
        presets=dict(bundle.presets.items()),
    )


def _same_source(source: str | None, path: Path) -> bool:
    if not source:
        return False
    try:
        return Path(source).resolve(strict=False) == path
    except (OSError, RuntimeError, ValueError):
        return False


def _callable_source(func: Callable[..., object]) -> str | None:
    try:
        return inspect.getsourcefile(inspect.unwrap(func))
    except (TypeError, ValueError):
        return None


def _candidate_bundle(
    *,
    source_path: Path,
    live: _RegistryBundle,
    baseline: _RegistryMappings,
) -> _RegistryBundle:
    effects: dict[str, OpSpec[EffectFunc]] = {
        name: spec
        for name, spec in live.effects.items()
        if not _same_source(spec.source, source_path)
    }
    primitives: dict[str, OpSpec[PrimitiveFunc]] = {
        name: spec
        for name, spec in live.primitives.items()
        if not _same_source(spec.source, source_path)
    }
    presets: dict[str, PresetSpec] = {
        op: spec
        for op, spec in live.presets.items()
        if not _same_source(_callable_source(spec.func), source_path)
    }

    # watched sourceが既存名をoverwriteしていた場合、source削除時にはwatch開始前の
    # entryを復元する。並行して追加された別sourceのentryは上のlive集合で維持する。
    for effect_name, effect_spec in baseline.effects.items():
        effects.setdefault(effect_name, effect_spec)
    for primitive_name, primitive_spec in baseline.primitives.items():
        primitives.setdefault(primitive_name, primitive_spec)
    for preset_op, preset_spec in baseline.presets.items():
        presets.setdefault(preset_op, preset_spec)

    staged_effects: OpRegistry[EffectFunc] = OpRegistry(kind="effect")
    staged_effects.replace_all(effects)
    staged_primitives: OpRegistry[PrimitiveFunc] = OpRegistry(kind="primitive")
    staged_primitives.replace_all(primitives)
    staged_presets = PresetRegistry()
    staged_presets.replace_all(presets)
    return _RegistryBundle(
        effects=staged_effects,
        primitives=staged_primitives,
        presets=staged_presets,
    )


@contextlib.contextmanager
def _use_staged_registries(bundle: _RegistryBundle) -> Iterator[None]:
    """decorator/APIが参照するmodule globalをcandidateへ一時的に向ける。"""

    bindings: tuple[tuple[object, str, object], ...] = (
        (effect_registry_module, "effect_registry", bundle.effects),
        (primitive_registry_module, "primitive_registry", bundle.primitives),
        (preset_registry_module, "preset_registry", bundle.presets),
    )
    previous = tuple(getattr(module, name) for module, name, _value in bindings)
    try:
        for module, name, value in bindings:
            setattr(module, name, value)
        yield
    finally:
        for (module, name, _value), value in zip(bindings, previous, strict=True):
            setattr(module, name, value)


@contextlib.contextmanager
def _source_import_path(directory: Path) -> Iterator[None]:
    text = str(directory)
    sys.path.insert(0, text)
    try:
        yield
    finally:
        try:
            sys.path.remove(text)
        except ValueError:
            pass


def _validate_draw(module: types.ModuleType, *, attribute: str) -> Callable[[float], SceneItem]:
    try:
        candidate = getattr(module, attribute)
    except AttributeError as exc:
        raise AttributeError(f"sourceに{attribute!r} callableがありません") from exc
    if not callable(candidate):
        raise TypeError(f"source attribute {attribute!r} はcallableである必要があります")
    if inspect.iscoroutinefunction(candidate):
        raise TypeError("drawは同期callableである必要があります")
    try:
        inspect.signature(candidate).bind(0.0)
    except TypeError as exc:
        raise TypeError("drawは時刻tを1つ受け取れるsignatureである必要があります") from exc
    return candidate


def _execute_source(
    *,
    path: Path,
    source_bytes: bytes,
    module_name: str,
) -> types.ModuleType:
    """指定bytesを固有moduleとして実行し、stale pycを介さず返す。"""

    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        code = compile(source_bytes, str(path), "exec", dont_inherit=True)
        with _source_import_path(path.parent):
            exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


class ReloadedDraw:
    """検証済みsource bytesからworkerでも復元できるdraw callable。"""

    def __init__(
        self,
        *,
        path: Path,
        source_bytes: bytes,
        module_name: str,
        draw_attribute: str,
        loaded_draw: Callable[[float], SceneItem] | None = None,
    ) -> None:
        if not isinstance(path, Path):
            raise TypeError("path は Path である必要があります")
        if type(source_bytes) is not bytes:
            raise TypeError("source_bytes は bytes である必要があります")
        module_name = exact_string(module_name, name="module_name")
        draw_attribute = exact_string(draw_attribute, name="draw_attribute")
        if not module_name:
            raise ValueError("module_name は空にできません")
        if not draw_attribute:
            raise ValueError("draw_attribute は空にできません")
        if loaded_draw is not None and not callable(loaded_draw):
            raise TypeError("loaded_draw は callable または None である必要があります")
        self._path = path
        self._source_bytes = source_bytes
        self._module_name = module_name
        self._draw_attribute = draw_attribute
        self._loaded_draw = loaded_draw

    def __call__(self, t: float) -> SceneItem:
        draw = self._loaded_draw
        if draw is None:
            # spawn workerはmainで検証済みのbytesを使う。watch対象fileが次の編集へ
            # 進んでいても、当該worker generationのcode/registryを混在させない。
            module = _execute_source(
                path=self._path,
                source_bytes=self._source_bytes,
                module_name=f"{self._module_name}_worker",
            )
            draw = _validate_draw(module, attribute=self._draw_attribute)
            self._loaded_draw = draw
        return draw(finite_real(t, name="t"))

    @property
    def __grafix_source_path__(self) -> Path:
        """出力/parameter path解決へ元sketch pathを公開する。"""

        return self._path

    @property
    def __grafix_source_bytes__(self) -> bytes:
        """worker generationと同じ検証済みsource snapshotを返す。"""

        return self._source_bytes

    def __getstate__(self) -> tuple[Path, bytes, str, str]:
        """dynamic module functionを除き、spawn可能なsource snapshotだけを渡す。"""

        return (
            self._path,
            self._source_bytes,
            self._module_name,
            self._draw_attribute,
        )

    def __setstate__(self, state: tuple[Path, bytes, str, str]) -> None:
        path, source_bytes, module_name, draw_attribute = state
        ReloadedDraw.__init__(
            self,
            path=path,
            source_bytes=source_bytes,
            module_name=module_name,
            draw_attribute=draw_attribute,
        )


def _unavailable_draw(_t: float) -> SceneItem:
    raise RuntimeError("sketch sourceはまだ正常にloadされていません")


def _commit_bundle(*, live: _RegistryBundle, staged: _RegistryBundle) -> None:
    """全candidateを事前検証後、live objectの内容だけを一括更新する。"""

    mappings = _bundle_mappings(staged)
    # replace_allは各mappingをassignment前に検証する。念のため全candidateをここで
    # 再構築し、commit途中にvalidation errorが起きないことを先に固定する。
    _candidate_validation = _RegistryBundle(
        effects=OpRegistry(kind="effect"),
        primitives=OpRegistry(kind="primitive"),
        presets=PresetRegistry(),
    )
    _candidate_validation.effects.replace_all(mappings.effects)
    _candidate_validation.primitives.replace_all(mappings.primitives)
    _candidate_validation.presets.replace_all(mappings.presets)

    live.effects.replace_all(mappings.effects)
    live.primitives.replace_all(mappings.primitives)
    live.presets.replace_all(mappings.presets)


def _replace_staged_registry_references(
    module: types.ModuleType,
    *,
    staged: _RegistryBundle,
    live: _RegistryBundle,
) -> None:
    replacements = {
        id(staged.effects): live.effects,
        id(staged.primitives): live.primitives,
        id(staged.presets): live.presets,
    }
    for name, value in tuple(vars(module).items()):
        replacement = replacements.get(id(value))
        if replacement is not None:
            setattr(module, name, replacement)


class SourceReloadController:
    """mtime pollingでsketchをtransactionalにreloadする。"""

    def __init__(self, path: str | Path, *, draw_attribute: str = "draw") -> None:
        if isinstance(path, Path):
            path_input = path
        else:
            path_text = exact_string(path, name="path")
            if not path_text:
                raise ValueError("path は空にできません")
            path_input = Path(path_text)
        source_path = path_input.expanduser().resolve(strict=False)
        if not source_path.is_file():
            raise FileNotFoundError(f"sketch sourceが見つかりません: {source_path}")
        attribute = exact_string(draw_attribute, name="draw_attribute")
        if not attribute:
            raise ValueError("draw_attributeは空にできません")
        if attribute != attribute.strip():
            raise ValueError("draw_attributeの前後に空白は使用できません")

        self._path = source_path
        self._draw_attribute = attribute
        self._live = _live_bundle()
        self._baseline = _bundle_mappings(self._live)
        self._generation = -1
        self._attempt = 0
        self._module_name: str | None = None
        self._draw: Callable[[float], SceneItem] = _unavailable_draw
        self._rollback_state: _RollbackState | None = None
        self._closed = False
        self._last_fingerprint = self._fingerprint()
        result = self._reload(retain_rollback=False)
        if result.status != "reloaded":
            raise RuntimeError(result.summary or "initial sketch load failed")

    def __enter__(self) -> SourceReloadController:
        if self._closed:
            raise RuntimeError("close済みのSourceReloadControllerは再利用できません")
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def draw(self) -> Callable[[float], SceneItem]:
        return self._draw

    def _fingerprint(self) -> SourceFingerprint:
        try:
            stat_result = self._path.stat()
        except FileNotFoundError:
            return ("missing",)
        return int(stat_result.st_mtime_ns), int(stat_result.st_size)

    def poll(
        self,
        *,
        force: bool = False,
        retain_rollback: bool = False,
    ) -> SourceReloadResult:
        """source変更時だけreloadし、失敗時はlast-good drawを返す。"""

        force = exact_bool(force, name="force")
        retain_rollback = exact_bool(
            retain_rollback,
            name="retain_rollback",
        )
        if self._closed:
            raise RuntimeError("SourceReloadControllerはclose済みです")
        pending = self._rollback_state
        if pending is not None:
            raise RuntimeError(
                "前回の reload generation が未確定です。"
                "accept_generation() または rollback_generation() を先に呼んでください: "
                f"generation={pending.committed_generation}"
            )
        fingerprint = self._fingerprint()
        if not force and fingerprint == self._last_fingerprint:
            return SourceReloadResult(
                status="unchanged",
                generation=self._generation,
                draw=self._draw,
            )
        # 同じ壊れたsourceを毎frame実行しない。次のmtime/size変更か明示forceまで待つ。
        self._last_fingerprint = fingerprint
        return self._reload(retain_rollback=retain_rollback)

    def _reload(self, *, retain_rollback: bool) -> SourceReloadResult:
        self._attempt += 1
        previous_module = self._module_name
        previous_draw = self._draw
        previous_generation = self._generation
        previous_registries = _bundle_mappings(self._live)
        module_token = hashlib.sha256(str(self._path).encode("utf-8")).hexdigest()[:12]
        module_name = f"_grafix_watch_{module_token}_{self._attempt}"
        module = types.ModuleType(module_name)
        module.__file__ = str(self._path)
        module.__package__ = ""
        staged = _candidate_bundle(
            source_path=self._path,
            live=self._live,
            baseline=self._baseline,
        )
        sys.modules[module_name] = module
        try:
            source_bytes = self._path.read_bytes()
            code = compile(source_bytes, str(self._path), "exec", dont_inherit=True)
            with _source_import_path(self._path.parent), _use_staged_registries(staged):
                exec(code, module.__dict__)
                loaded_draw = _validate_draw(module, attribute=self._draw_attribute)
            _commit_bundle(live=self._live, staged=staged)
            _replace_staged_registry_references(
                module,
                staged=staged,
                live=self._live,
            )
            draw = ReloadedDraw(
                path=self._path,
                source_bytes=source_bytes,
                module_name=module_name,
                draw_attribute=self._draw_attribute,
                loaded_draw=loaded_draw,
            )
        except BaseException as exc:
            sys.modules.pop(module_name, None)
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            source = str(self._path)
            tb = exc.__traceback__
            while tb is not None:
                if Path(tb.tb_frame.f_code.co_filename).resolve(strict=False) == self._path:
                    source = f"{self._path}:{tb.tb_lineno}"
                tb = tb.tb_next
            return SourceReloadResult(
                status="failed",
                generation=self._generation,
                draw=self._draw,
                summary=f"{type(exc).__name__}: {exc}",
                details=details,
                source=source,
            )

        self._module_name = module_name
        self._draw = draw
        self._generation += 1
        if retain_rollback and previous_generation >= 0:
            self._rollback_state = _RollbackState(
                committed_generation=self._generation,
                previous_generation=previous_generation,
                previous_draw=previous_draw,
                previous_module_name=previous_module,
                previous_registries=previous_registries,
            )
        elif previous_module is not None and previous_module != module_name:
            sys.modules.pop(previous_module, None)
        return SourceReloadResult(
            status="reloaded",
            generation=self._generation,
            draw=draw,
            source=str(self._path),
        )

    def accept_generation(self, generation: int) -> None:
        """transactional reloadを確定し、直前moduleを解放する。"""

        expected = exact_integer(generation, name="generation", minimum=0)
        state = self._rollback_state
        if state is None:
            raise ValueError(
                "accept可能なreload generationではありません: "
                f"current={self._generation}, got={expected}"
            )
        if expected != state.committed_generation or expected != self._generation:
            raise ValueError(
                f"reload generationが一致しません: current={self._generation}, "
                f"got={expected}"
            )
        previous_module = state.previous_module_name
        if previous_module is not None and previous_module != self._module_name:
            sys.modules.pop(previous_module, None)
        self._rollback_state = None

    def rollback_generation(self, generation: int) -> Callable[[float], SceneItem]:
        """worker swap失敗時にregistry/callableを直前generationへ戻す。"""

        expected = exact_integer(generation, name="generation", minimum=0)
        state = self._rollback_state
        if (
            state is None
            or expected != state.committed_generation
            or expected != self._generation
        ):
            raise ValueError(
                f"rollback可能なreload generationではありません: "
                f"current={self._generation}, got={expected}"
            )

        restored = _RegistryBundle(
            effects=OpRegistry(kind="effect"),
            primitives=OpRegistry(kind="primitive"),
            presets=PresetRegistry(),
        )
        restored.effects.replace_all(state.previous_registries.effects)
        restored.primitives.replace_all(state.previous_registries.primitives)
        restored.presets.replace_all(state.previous_registries.presets)
        _commit_bundle(live=self._live, staged=restored)

        current_module = self._module_name
        if current_module is not None and current_module != state.previous_module_name:
            sys.modules.pop(current_module, None)
        self._module_name = state.previous_module_name
        self._draw = state.previous_draw
        self._generation = state.previous_generation
        self._rollback_state = None
        return self._draw

    def close(self) -> None:
        """watched source由来の登録と一時moduleをprocess globalから除く。"""

        if self._closed:
            return
        self._closed = True
        if self._rollback_state is not None:
            self.accept_generation(self._generation)
        clean = _candidate_bundle(
            source_path=self._path,
            live=self._live,
            baseline=self._baseline,
        )
        _commit_bundle(live=self._live, staged=clean)
        module_name = self._module_name
        self._module_name = None
        if module_name is not None:
            sys.modules.pop(module_name, None)


_CURRENT_SOURCE_RELOAD: ContextVar[SourceReloadController | None] = ContextVar(
    "grafix_current_source_reload",
    default=None,
)


@contextlib.contextmanager
def source_reload_context(
    controller: SourceReloadController,
) -> Iterator[SourceReloadController]:
    """現在のinteractive runだけへwatch controllerを配線する。"""

    if not isinstance(controller, SourceReloadController):
        raise TypeError("controllerはSourceReloadControllerである必要があります")
    token = _CURRENT_SOURCE_RELOAD.set(controller)
    try:
        yield controller
    finally:
        _CURRENT_SOURCE_RELOAD.reset(token)


def current_source_reload() -> SourceReloadController | None:
    """現在のcontextに明示されたwatch controllerを返す。"""

    return _CURRENT_SOURCE_RELOAD.get()


__all__ = [
    "ReloadStatus",
    "ReloadedDraw",
    "SourceReloadController",
    "SourceReloadResult",
    "current_source_reload",
    "source_reload_context",
]
