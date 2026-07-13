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
) -> str:
    """frame から project-relative site ID または明示 key ID を生成する。"""

    if frame is None:
        frame = inspect.currentframe()
        if frame is not None:
            frame = frame.f_back
    if frame is None:
        return "<unknown>:0:0"

    code = frame.f_code
    module_name = str(frame.f_globals.get("__name__", ""))
    if key is not None:
        if not isinstance(key, (str, int)):
            raise TypeError("parameter key は str|int|None である必要がある")
        return f"{_code_file_id(code, module_name)}|{key}"
    return _automatic_site_id(code, frame.f_lasti, module_name)


def caller_site_id(
    skip: int = 1,
    *,
    key: str | int | None = None,
) -> str:
    """呼び出し元 stack から site ID を取得する。"""

    frame: FrameType | None = inspect.currentframe()
    for _ in range(skip + 1):
        if frame is None:
            break
        frame = frame.f_back
    if frame is None:
        return "<unknown>:0:0"
    return make_site_id(frame, key=key)
