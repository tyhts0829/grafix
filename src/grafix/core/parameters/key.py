# どこで: `src/grafix/core/parameters/key.py`。
# 何を: ParameterKey と site_id 生成ヘルパを定義する。
# なぜ: GUI 行を安定に識別し、呼び出し箇所ごとにキーを分離するため。

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import CodeType, FrameType


@dataclass(frozen=True, slots=True)
class ParameterKey:
    """パラメータ GUI 行を一意に識別するキー。"""

    op: str
    site_id: str
    arg: str


@lru_cache(maxsize=4096)
def _code_file_id(code: CodeType, module_name: str) -> str:
    """code object の永続化向け相対 file ID を返す。"""

    filename = str(code.co_filename)
    if filename and not filename.startswith("<"):
        resolved = Path(filename).resolve()
        try:
            return resolved.relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            pass
    if module_name and module_name != "__main__":
        return module_name
    if filename and not filename.startswith("<"):
        return Path(filename).name
    return module_name or filename or "<unknown>"


@lru_cache(maxsize=16_384)
def _automatic_site_id(code: CodeType, instruction: int, module_name: str) -> str:
    file_id = _code_file_id(code, module_name)
    return f"{file_id}:{code.co_firstlineno}:{int(instruction)}"


def make_site_id(
    frame: FrameType | None = None,
    *,
    key: str | int | None = None,
    instance_key: str | int | None = None,
    shared: bool = False,
) -> str:
    """semantic site と任意の反復 instance から site ID を生成する。

    ``key`` はコード移動に強い semantic site、``instance_key`` は同じ site を
    loop/comprehension で反復したときの個別 instance を表す。``shared=True`` は
    instance suffix を持たない semantic site を意図的に共有する指定であり、
    ``instance_key`` との同時指定は曖昧なので拒否する。
    """

    validate_parameter_identity(key=key, instance_key=instance_key, shared=shared)

    if frame is None:
        frame = inspect.currentframe()
        if frame is not None:
            frame = frame.f_back
    if frame is None:
        return "<unknown>:0:0"

    code = frame.f_code
    module_name = str(frame.f_globals.get("__name__", ""))
    if key is not None:
        semantic_site_id = f"{_code_file_id(code, module_name)}|{key}"
    else:
        semantic_site_id = _automatic_site_id(code, frame.f_lasti, module_name)
    if instance_key is None:
        return semantic_site_id
    return f"{semantic_site_id}|instance:{instance_key}"


def caller_site_id(
    skip: int = 1,
    *,
    key: str | int | None = None,
    instance_key: str | int | None = None,
    shared: bool = False,
) -> str:
    """呼び出し元 stack から semantic/instance site ID を取得する。"""

    validate_parameter_identity(key=key, instance_key=instance_key, shared=shared)

    frame: FrameType | None = inspect.currentframe()
    for _ in range(skip + 1):
        if frame is None:
            break
        frame = frame.f_back
    if frame is None:
        return "<unknown>:0:0"
    return make_site_id(
        frame,
        key=key,
        instance_key=instance_key,
        shared=shared,
    )


def validate_parameter_identity(
    *,
    key: str | int | None,
    instance_key: str | int | None,
    shared: bool,
) -> None:
    """parameter identity の型と排他条件を検証する。"""

    if key is not None and not isinstance(key, (str, int)):
        raise TypeError("parameter key は str|int|None である必要がある")
    if instance_key is not None and not isinstance(instance_key, (str, int)):
        raise TypeError("instance_key は str|int|None である必要がある")
    if not isinstance(shared, bool):
        raise TypeError("shared は bool である必要がある")
    if shared and instance_key is not None:
        raise ValueError("instance_key と shared=True は同時に指定できません")
