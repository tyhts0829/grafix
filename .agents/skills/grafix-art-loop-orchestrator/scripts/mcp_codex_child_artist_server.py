from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

SERVER_NAME: Final[str] = "grafix-art-loop-codex-child-artist"
SERVER_VERSION: Final[str] = "0.1.0"
ALLOWED_RUNS_DIR: Final[Path] = Path("sketch/agent_loop/runs")
ENV_MAX_CONCURRENCY: Final[str] = "ART_LOOP_MAX_CONCURRENCY"
DEFAULT_MAX_CONCURRENCY: Final[int] = 4


def _find_repo_root(start: Path) -> Path:
    for p in (start, *start.parents):
        if (p / ".git").exists():
            return p
    return start


def _read_mcp_message(stream: Any) -> dict[str, Any] | None:
    """
    MCP stdio: prefer newline-delimited JSON (JSON Lines).
    Also accept Content-Length framed JSON as a fallback (compat).
    """
    first = stream.readline()
    if not first:
        return None

    line = first.strip()

    # JSON Lines
    if line.startswith(b"{"):
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            # fall through to framed mode (rare)
            pass

    # Content-Length framed mode (LSP-style)
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
    """
    Emit JSON Lines only (one JSON object per line).
    Do NOT pretty-print (no newlines inside a message).
    """
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    stream.write(data + b"\n")
    stream.flush()


def _resolve_under_repo(repo_root: Path, p: str) -> Path:
    candidate = Path(p).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def _require_under(base: Path, p: Path) -> None:
    try:
        p.relative_to(base)
    except ValueError as e:
        msg = f"path must be under {base}: {p}"
        raise ValueError(msg) from e


def _tail_text(path: Path, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return data[-max_chars:]


def _find_source_auth_json() -> Path | None:
    candidates: list[Path] = []
    raw_codex_home = os.environ.get("CODEX_HOME")
    if raw_codex_home:
        candidates.append((Path(raw_codex_home).expanduser().resolve() / "auth.json"))
    candidates.append((Path.home() / ".codex" / "auth.json").resolve())

    for p in candidates:
        if p.exists():
            return p
    return None


def _ensure_codex_auth(codex_home_dir: Path) -> None:
    """
    Codex CLI は CODEX_HOME/auth.json に認証情報を保存する。
    CODEX_HOME を variant ごとに分離すると 401 になり得るため、
    既存の auth.json を symlink で参照する。

    Notes
    -----
    - symlink は「複製」ではないので、variant_dir 内に秘密情報をコピーしない。
    - OAuth refresh による更新も単一ストアに集約できる。
    """
    dest = codex_home_dir / "auth.json"
    if dest.exists():
        return

    src = _find_source_auth_json()
    if src is None:
        raise ValueError("codex auth not found. Run `codex login`.")

    try:
        dest.symlink_to(src)
    except FileExistsError:
        # Race (e.g. retry) is OK: first writer wins.
        return


def _build_codex_prompt(variant_dir_rel: Path) -> str:
    v = variant_dir_rel.as_posix()
    return "\n".join(
        [
            "$grafix-art-loop-artist",
            "",
            "以下の variant_dir を作業対象として扱ってください。",
            f"- variant_dir: {v}",
            "",
            "入力:",
            f"- {v}/artist_context.json",
            f"- {v}/creative_brief.json",
            "",
            "出力（すべて variant_dir 配下）:",
            f"- {v}/sketch.py",
            f"- {v}/out.png",
            f"- {v}/artifact.json",
            f"- {v}/stdout.txt",
            f"- {v}/stderr.txt",
            "",
            "要件:",
            "- 出力境界を厳守し、/tmp やリポジトリ直下などへ書き出さない。",
            "- Grafix のレンダリングは playbook 記載の `PYTHONPATH=src /opt/anaconda3/envs/gl5/bin/python -m grafix export` を使う。",
            "- `artifact.json` は `.agents/skills/grafix-art-loop-orchestrator/references/schemas.md` の `Artifact` 形式にする（成功/失敗どちらも）。",
            "- 最終メッセージは `Artifact` JSON のみ（余計な本文やコードブロック無し）。",
        ]
    )


def _write_failure_artifact(repo_root: Path, variant_dir: Path) -> None:
    artifact_path = variant_dir / "artifact.json"
    if artifact_path.exists():
        return

    ctx_path = variant_dir / "artist_context.json"
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return

    variant_dir_rel = variant_dir.relative_to(repo_root)
    callable_ref = f"{variant_dir_rel.as_posix().replace('/', '.')}.sketch:draw"

    artifact = {
        "artist_id": ctx.get("artist_id", ""),
        "iteration": int(ctx.get("iteration", 0) or 0),
        "variant_id": ctx.get("variant_id", ""),
        "mode": ctx.get("mode", "exploration"),
        "status": "failed",
        "code_ref": str(variant_dir_rel / "sketch.py"),
        "callable_ref": callable_ref,
        "image_ref": str(variant_dir_rel / "out.png"),
        "seed": 0,
    }

    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _tool_run_codex_artist(
    repo_root: Path,
    arguments: dict[str, Any],
    *,
    server_queue_ms: int | None = None,
) -> dict[str, Any]:
    variant_dir_arg = arguments.get("variant_dir")
    if not isinstance(variant_dir_arg, str) or not variant_dir_arg.strip():
        raise ValueError("variant_dir is required")

    timeout_s = arguments.get("timeout_s", 900)
    if not isinstance(timeout_s, int) or timeout_s <= 0:
        raise ValueError("timeout_s must be a positive integer")

    variant_dir = _resolve_under_repo(repo_root, variant_dir_arg)
    allowed_base = (repo_root / ALLOWED_RUNS_DIR).resolve()
    _require_under(allowed_base, variant_dir)

    if not variant_dir.is_dir():
        raise ValueError(f"variant_dir not found: {variant_dir}")

    tmp_dir = variant_dir / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    codex_home_dir = variant_dir / ".codex_home"
    codex_home_dir.mkdir(exist_ok=True)
    _ensure_codex_auth(codex_home_dir)

    variant_dir_rel = variant_dir.relative_to(repo_root)
    prompt = _build_codex_prompt(variant_dir_rel)

    codex_last_message = variant_dir / "codex_last_message.md"
    codex_stdout = variant_dir / "codex_stdout.txt"
    codex_stderr = variant_dir / "codex_stderr.txt"

    cmd = [
        "codex",
        "-a",
        "never",
        "-s",
        "workspace-write",
        "exec",
        "-C",
        str(repo_root),
        "-",
        "--output-last-message",
        str(codex_last_message),
    ]

    env = os.environ.copy()
    env["TMPDIR"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    env["TEMP"] = str(tmp_dir)
    env["CODEX_HOME"] = str(codex_home_dir)

    t0 = time.monotonic()
    exit_code: int | None
    try:
        with codex_stdout.open("wb") as out, codex_stderr.open("wb") as err:
            proc = subprocess.run(
                cmd,
                input=prompt.encode("utf-8"),
                stdout=out,
                stderr=err,
                env=env,
                timeout=timeout_s,
            )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    artifact_path = variant_dir / "artifact.json"
    status = "success" if (exit_code == 0 and artifact_path.exists()) else "failed"
    if status != "success":
        _write_failure_artifact(repo_root, variant_dir)

    error_summary = ""
    if status != "success":
        error_summary = _tail_text(codex_stderr, max_chars=1200) or _tail_text(
            codex_stdout, max_chars=1200
        )

    payload = {
        "status": status,
        "elapsed_ms": elapsed_ms,
        "server_queue_ms": server_queue_ms,
        "variant_dir": str(variant_dir_rel),
        "artifact_json_path": str(variant_dir_rel / "artifact.json"),
        "stdout_path": str(variant_dir_rel / "stdout.txt"),
        "stderr_path": str(variant_dir_rel / "stderr.txt"),
        "codex_last_message_path": str(variant_dir_rel / codex_last_message.name),
        "codex_stdout_path": str(variant_dir_rel / codex_stdout.name),
        "codex_stderr_path": str(variant_dir_rel / codex_stderr.name),
        "error_summary": error_summary,
    }

    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": status != "success",
    }


def _tool_read_text_tail(repo_root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path_arg = arguments.get("path")
    if not isinstance(path_arg, str) or not path_arg.strip():
        raise ValueError("path is required")

    max_chars = arguments.get("max_chars", 4000)
    if not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")

    path = _resolve_under_repo(repo_root, path_arg)
    allowed_base = (repo_root / ALLOWED_RUNS_DIR).resolve()
    _require_under(allowed_base, path)

    tail = _tail_text(path, max_chars=max_chars)
    return {"content": [{"type": "text", "text": tail}], "isError": False}


TOOLS: Final[list[dict[str, Any]]] = [
    {
        "name": "art_loop.run_codex_artist",
        "description": "Codex CLI 子エージェントとして $grafix-art-loop-artist を 1-shot 実行する。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "variant_dir": {"type": "string"},
                "timeout_s": {"type": "integer", "default": 900},
            },
            "required": ["variant_dir"],
        },
    },
    {
        "name": "art_loop.read_text_tail",
        "description": "run 配下のテキストファイル末尾を返す（長文ログは遅延取得）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer", "default": 4000},
            },
            "required": ["path"],
        },
    },
]


def _handle_request(
    repo_root: Path,
    req: dict[str, Any],
    *,
    received_t0: float | None = None,
    started_t0: float | None = None,
) -> dict[str, Any]:
    method = req.get("method")
    params = req.get("params") or {}
    req_id = req.get("id")

    try:
        if method == "initialize":
            proto = params.get("protocolVersion") or "2024-11-05"
            result = {
                "protocolVersion": proto,
                "capabilities": {
                    # tools を提供するなら listChanged を宣言（true/false どちらでもOK）
                    "tools": {"listChanged": False},
                    # なくても動くはずだが、クライアントが setLevel を投げるケースがあるので宣言＋実装すると安定
                    "logging": {},
                    # あなたは resources/list / prompts/list を実装しているので、宣言しておくと整合が取れる
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }

        elif method == "ping":
            # MCP ping: result は空オブジェクト
            result = {}

        elif method == "notifications/initialized":
            # 通常は notification (idなし) だが、万一 request で来ても落とさない
            result = {}

        elif method == "tools/list":
            result = {"tools": TOOLS}

        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            server_queue_ms = None
            if received_t0 is not None and started_t0 is not None:
                server_queue_ms = int((started_t0 - received_t0) * 1000)
            if name == "art_loop.run_codex_artist":
                result = _tool_run_codex_artist(
                    repo_root,
                    arguments=arguments,
                    server_queue_ms=server_queue_ms,
                )
            elif name == "art_loop.read_text_tail":
                result = _tool_read_text_tail(repo_root, arguments=arguments)
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

    max_concurrency_raw = os.environ.get(ENV_MAX_CONCURRENCY)
    max_concurrency = DEFAULT_MAX_CONCURRENCY
    if max_concurrency_raw:
        max_concurrency = int(max_concurrency_raw)
    if max_concurrency <= 0:
        raise ValueError(f"{ENV_MAX_CONCURRENCY} must be a positive integer")

    run_slots = threading.Semaphore(max_concurrency)
    stdout_lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=max_concurrency)

    def _write_response(payload: dict[str, Any]) -> None:
        with stdout_lock:
            _write_mcp_message(stdout, payload)

    def _handle_and_write(req: dict[str, Any], *, received_t0: float) -> None:
        started_t0 = time.monotonic()
        resp = _handle_request(
            repo_root,
            req,
            received_t0=received_t0,
            started_t0=started_t0,
        )
        _write_response(resp)

    def _handle_run_and_write(req: dict[str, Any], *, received_t0: float) -> None:
        try:
            _handle_and_write(req, received_t0=received_t0)
        finally:
            run_slots.release()

    while True:
        msg = _read_mcp_message(stdin)
        if msg is None:
            return

        if "method" not in msg:
            continue

        received_t0 = time.monotonic()

        # notifications は id が無いので返さない。requestだけ返す。
        if "id" in msg:
            method = msg.get("method")
            params = msg.get("params") or {}
            name = params.get("name")

            if method == "tools/call" and name == "art_loop.run_codex_artist":
                if not run_slots.acquire(blocking=False):
                    _write_response(
                        {
                            "jsonrpc": "2.0",
                            "id": msg.get("id"),
                            "error": {
                                "code": -32000,
                                "message": (
                                    "server busy: "
                                    f"max concurrency is {max_concurrency} "
                                    f"(env: {ENV_MAX_CONCURRENCY})"
                                ),
                            },
                        }
                    )
                    continue

                executor.submit(_handle_run_and_write, msg, received_t0=received_t0)
            else:
                _handle_and_write(msg, received_t0=received_t0)


if __name__ == "__main__":
    main()
