from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Final

SERVER_NAME: Final[str] = "grafix-art-loop-grafix-docs"
SERVER_VERSION: Final[str] = "0.1.0"


def _find_repo_root(start: Path) -> Path:
    for p in (start, *start.parents):
        if (p / ".git").exists():
            return p
    return start


def _read_mcp_message(stream: Any) -> dict[str, Any] | None:
    """
    MCP stdio: prefer newline-delimited JSON (JSON Lines).
    Also accept Content-Length framed JSON as a fallback.
    """
    first = stream.readline()
    if not first:
        return None

    line = first.strip()
    if line.startswith(b"{"):
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            pass

    headers: dict[str, str] = {}
    pending = [first]
    while pending:
        raw = pending.pop(0)
        if raw in (b"\n", b"\r\n"):
            break
        try:
            key, value = raw.decode("ascii").split(":", 1)
        except ValueError:
            continue
        headers[key.strip().lower()] = value.strip()

        nxt = stream.readline()
        if not nxt:
            return None
        pending.append(nxt)

    content_length = headers.get("content-length")
    if content_length is None:
        return None
    try:
        n = int(content_length)
    except ValueError:
        return None

    body = stream.read(n)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_mcp_message(stream: Any, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    stream.write(data + b"\n")
    stream.flush()


def _ensure_src_on_syspath(repo_root: Path) -> None:
    src = str((repo_root / "src").resolve())
    if src not in sys.path:
        sys.path.insert(0, src)


def _normalize_name_list(value: Any, *, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of strings")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} must contain non-empty strings only")
        names.append(item.strip())
    return names


def _fetch_doc_records(
    *,
    names: list[str],
    kind: str,
    available_names: set[str],
    max_chars: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    module_prefix = f"grafix.core.{kind}."
    for name in names:
        if name not in available_names:
            records.append({"name": name, "status": "not_found"})
            continue

        module_name = module_prefix + name
        try:
            module = importlib.import_module(module_name)
        except Exception as e:  # noqa: BLE001
            records.append(
                {
                    "name": name,
                    "status": "error",
                    "module": module_name,
                    "error": f"module import failed: {e.__class__.__name__}",
                }
            )
            continue

        func = getattr(module, name, None)
        if not callable(func):
            records.append(
                {
                    "name": name,
                    "status": "error",
                    "module": module_name,
                    "error": "callable not found in module",
                }
            )
            continue

        doc = inspect.getdoc(func) or ""
        if len(doc) > max_chars:
            doc = doc[:max_chars]
        summary = doc.splitlines()[0] if doc else ""
        records.append(
            {
                "name": name,
                "status": "ok",
                "module": module_name,
                "summary": summary,
                "docstring": doc,
            }
        )
    return records


def _tool_get_op_docstrings(repo_root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    _ensure_src_on_syspath(repo_root)

    primitive_names = _normalize_name_list(arguments.get("primitives"), key="primitives")
    effect_names = _normalize_name_list(arguments.get("effects"), key="effects")
    if not primitive_names and not effect_names:
        raise ValueError("at least one of primitives/effects is required")

    max_chars = arguments.get("max_chars", 8000)
    if not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")

    from grafix.core.builtins import ensure_builtin_ops_registered
    from grafix.core.effect_registry import effect_registry
    from grafix.core.primitive_registry import primitive_registry

    ensure_builtin_ops_registered()
    primitive_set = {
        name for name, _ in primitive_registry.items() if not name.startswith("_")
    }
    effect_set = {name for name, _ in effect_registry.items() if not name.startswith("_")}

    payload = {
        "primitives": _fetch_doc_records(
            names=primitive_names,
            kind="primitives",
            available_names=primitive_set,
            max_chars=max_chars,
        ),
        "effects": _fetch_doc_records(
            names=effect_names,
            kind="effects",
            available_names=effect_set,
            max_chars=max_chars,
        ),
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


TOOLS: Final[list[dict[str, Any]]] = [
    {
        "name": "art_loop.get_op_docstrings",
        "description": "指定 primitive/effect の docstring を取得する。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "primitives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "effects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "max_chars": {"type": "integer", "default": 8000},
            },
        },
    }
]


def _handle_request(repo_root: Path, req: dict[str, Any]) -> dict[str, Any]:
    method = req.get("method")
    params = req.get("params") or {}
    req_id = req.get("id")

    try:
        if method == "initialize":
            proto = params.get("protocolVersion") or "2024-11-05"
            result = {
                "protocolVersion": proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "logging": {},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }

        elif method == "ping":
            result = {}

        elif method == "notifications/initialized":
            result = {}

        elif method == "tools/list":
            result = {"tools": TOOLS}

        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "art_loop.get_op_docstrings":
                result = _tool_get_op_docstrings(repo_root, arguments=arguments)
            else:
                raise ValueError(f"unknown tool: {name}")

        elif method == "resources/list":
            result = {"resources": []}

        elif method == "prompts/list":
            result = {"prompts": []}

        else:
            raise ValueError(f"unknown method: {method}")

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": str(e)},
        }


def main() -> None:
    repo_root = _find_repo_root(Path.cwd()).resolve()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        msg = _read_mcp_message(stdin)
        if msg is None:
            return

        if "method" not in msg:
            continue

        if "id" in msg:
            _write_mcp_message(stdout, _handle_request(repo_root, msg))


if __name__ == "__main__":
    main()
