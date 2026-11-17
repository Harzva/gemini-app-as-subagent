#!/usr/bin/env python3
"""Stdio MCP server exposing ~/Downloads/Gemini-Collab mailbox tools to Gemini.app and other MCP hosts."""

from __future__ import annotations

import json
import os
import pwd
import shutil
import sys
from pathlib import Path
from typing import Any

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "gemini-collab", "version": "1.1.0"}


def resolve_collab_root() -> Path:
    env_dir = os.environ.get("GEMINI_COLLAB_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    cfg_raw = os.environ.get("GEMINI_SUBAGENT_CONFIG")
    cfg_path = Path(cfg_raw).expanduser() if cfg_raw else (REAL_HOME / ".config" / "gemini-subagent" / "config.json")
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("collab_dir"), str) and data["collab_dir"].strip():
                return Path(data["collab_dir"]).expanduser().resolve()
        except (OSError, json.JSONDecodeError):
            pass
    return REAL_HOME / "Downloads" / "Gemini-Collab"


def get_mailbox_dirs() -> tuple[Path, Path, Path, Path]:
    root = resolve_collab_root()
    inbox = root / "inbox"
    outbox = root / "outbox"
    archive = root / "archive"
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    return root, inbox, outbox, archive


TOOLS_SPEC = [
    {
        "name": "collab_list_tasks",
        "description": (
            "List host-agent -> desktop-app collaboration task briefs in "
            "the Gemini-Collab inbox and their completion status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "done", "all"],
                    "description": "Filter tasks by status (default: all).",
                }
            },
        },
    },
    {
        "name": "collab_read_task",
        "description": "Read the full Markdown brief for a given handoff_id from inbox/ (or archive/).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "handoff_id": {
                    "type": "string",
                    "description": "Task identifier (e.g. handoff-20261118-025000-abc123).",
                }
            },
            "required": ["handoff_id"],
        },
    },
    {
        "name": "collab_submit_result",
        "description": (
            "Write the completed result Markdown to outbox/<handoff_id>-RESULT.md "
            "and archive the inbox task brief."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handoff_id": {
                    "type": "string",
                    "description": "Task identifier matching the inbox brief.",
                },
                "result_markdown": {
                    "type": "string",
                    "description": "Complete Markdown report / deliverable to return to the host agent.",
                },
            },
            "required": ["handoff_id", "result_markdown"],
        },
    },
]


def safe_handoff_id(raw_id: str) -> str:
    cleaned = Path(raw_id.strip()).name
    if cleaned.endswith("-RESULT.md"):
        cleaned = cleaned[: -len("-RESULT.md")]
    elif cleaned.endswith(".md"):
        cleaned = cleaned[: -len(".md")]
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"Invalid handoff_id: {raw_id!r}")
    return cleaned


def tool_list_tasks(status_filter: str = "all") -> dict[str, Any]:
    root, inbox, outbox, archive = get_mailbox_dirs()
    ids: set[str] = set()
    for p in inbox.glob("*.md"):
        ids.add(p.stem)
    for p in archive.glob("*.md"):
        ids.add(p.stem)
    for p in outbox.glob("*-RESULT.md"):
        ids.add(p.name[: -len("-RESULT.md")])

    tasks: list[dict[str, Any]] = []
    for hid in sorted(ids, reverse=True):
        inbox_file = inbox / f"{hid}.md"
        archive_file = archive / f"{hid}.md"
        outbox_file = outbox / f"{hid}-RESULT.md"
        status = "done" if outbox_file.is_file() else "pending"
        if status_filter != "all" and status != status_filter:
            continue
        tasks.append({
            "handoff_id": hid,
            "status": status,
            "inbox_path": str(inbox_file) if inbox_file.is_file() else "",
            "archive_path": str(archive_file) if archive_file.is_file() else "",
            "outbox_path": str(outbox_file) if outbox_file.is_file() else "",
        })
    return {"collab_root": str(root), "count": len(tasks), "tasks": tasks}


def tool_read_task(handoff_id: str) -> str:
    _, inbox, _, archive = get_mailbox_dirs()
    hid = safe_handoff_id(handoff_id)
    inbox_file = inbox / f"{hid}.md"
    archive_file = archive / f"{hid}.md"
    target = inbox_file if inbox_file.is_file() else (archive_file if archive_file.is_file() else None)
    if target is None:
        raise FileNotFoundError(f"Task brief not found for handoff_id={hid}")
    return target.read_text(encoding="utf-8")


def tool_submit_result(handoff_id: str, result_markdown: str) -> dict[str, Any]:
    _, inbox, outbox, archive = get_mailbox_dirs()
    hid = safe_handoff_id(handoff_id)
    outbox_file = outbox / f"{hid}-RESULT.md"
    inbox_file = inbox / f"{hid}.md"
    archive_file = archive / f"{hid}.md"

    text = result_markdown if result_markdown.endswith("\n") else result_markdown + "\n"
    outbox_file.write_text(text, encoding="utf-8")

    archived = False
    if inbox_file.is_file():
        shutil.move(str(inbox_file), str(archive_file))
        archived = True

    return {
        "handoff_id": hid,
        "status": "done",
        "outbox_path": str(outbox_file),
        "archived_inbox": archived,
    }


def make_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        client_ver = params.get("protocolVersion") or PROTOCOL_VERSION
        return make_result(
            req_id,
            {
                "protocolVersion": client_ver if isinstance(client_ver, str) else PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return make_result(req_id, {})
    if method == "tools/list":
        return make_result(req_id, {"tools": TOOLS_SPEC})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "collab_list_tasks":
                data = tool_list_tasks(str(arguments.get("status", "all")))
                text = json.dumps(data, ensure_ascii=False, indent=2)
            elif name == "collab_read_task":
                text = tool_read_task(str(arguments["handoff_id"]))
            elif name == "collab_submit_result":
                data = tool_submit_result(
                    str(arguments["handoff_id"]),
                    str(arguments["result_markdown"]),
                )
                text = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                return make_error(req_id, -32601, f"Unknown tool: {name}")
            return make_result(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as exc:
            return make_result(
                req_id,
                {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
            )

    if req_id is None:
        return None
    return make_error(req_id, -32601, f"Method not found: {method}")


def read_next_message() -> tuple[dict[str, Any] | None, str]:
    """Read either line-delimited JSON-RPC or Content-Length framed JSON-RPC from stdin."""
    stream = sys.stdin.buffer
    while True:
        first_line = stream.readline()
        if not first_line:
            return None, "line"
        stripped = first_line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                header = stream.readline()
                if not header or header in (b"\r\n", b"\n"):
                    break
            body = stream.read(length)
            return json.loads(body.decode("utf-8")), "framed"
        return json.loads(stripped.decode("utf-8")), "line"


def write_message(payload: dict[str, Any], framing: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=False)
    out = sys.stdout.buffer
    if framing == "framed":
        raw = encoded.encode("utf-8")
        out.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        out.write(raw)
    else:
        out.write((encoded + "\n").encode("utf-8"))
    out.flush()


def main() -> int:
    while True:
        try:
            msg, framing = read_next_message()
        except Exception as exc:
            sys.stderr.write(f"[gemini-collab-mcp] read error: {exc}\n")
            return 1
        if msg is None:
            return 0
        resp = handle_request(msg)
        if resp is not None:
            write_message(resp, framing)


if __name__ == "__main__":
    sys.exit(main())
