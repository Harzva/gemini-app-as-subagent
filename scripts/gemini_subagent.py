#!/usr/bin/env python3
"""Subagent CLI wrapping gemini-api credits, agy -p accounts, and Gemini.app file handoffs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
GEMINI_APP_PATH = Path("/Applications/Gemini.app")
INLINE_FILE_LIMIT_BYTES = 14 * 1024 * 1024

TIER_MODELS: dict[str, str] = {
    "lite": "gemini-3.5-flash-lite",
    "fast": "gemini-3.8-flash",
    "balanced": "gemini-4-hydrogen",
    "coding": "gemini-4-carbon",
    "frontier": "gemini-4-argon",
}

IMAGE_TIER_MODELS: dict[str, str] = {
    "lite": "gemini-3.1-flash-lite-image",
    "default": "gemini-nano-banana-2.1",
    "pro": "gemini-3-pro-image",
}

GEMINI_APP_DEEPLINKS: dict[str, str] = {
    "newchat": "googlegemini://newchat",
    "videos": "googlegemini://?target=videos",
    "images": "googlegemini://?target=images",
    "library": "googlegemini://?target=library",
    "customize": "googlegemini://?target=customize",
    "scheduled": "googlegemini://?target=scheduled",
    "your_day": "googlegemini://?target=your_day",
    "needsattention": "googlegemini://needsattention?ext_src=app_shortcut",
}

IMAGE_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "none": {
        "aspect_ratio": None,
        "size": "2K",
        "prefix": "",
    },
    "knowledge-card": {
        "aspect_ratio": "3:4",
        "size": "2K",
        "prefix": (
            "Design a crisp vertical 3:4 editorial Chinese technical knowledge infographic card "
            "on a warm ivory off-white background (#FCFBF9), clean flat vector graphic design, "
            "generous breathing margins, zero 3D clutter, and zero watermarks.\n"
            "Layout specification:\n"
            "1. Header: Top-right soft blush-pink pill badge (#FCE8EC) with bold crimson category text (#D92B4B). "
            "Large bold dark-charcoal 1-2 line main title (#141414). Below it, a medium-bold crimson subtitle (#D92B4B).\n"
            "2. Body: Stacked full-width horizontal rounded cards (14px corner radius, crisp white fill, light tinted border). "
            "Each row card contains: (a) a solid colored left vertical spine with a large bold white step number "
            "(1 crimson #E62E5C, 2 purple #7339D8, 3 cobalt blue #2D6AE3, 4 amber orange #EA7626, 5 emerald green #269C5E), "
            "(b) a matching soft-pastel rounded-square flat vector icon tile on the left, and "
            "(c) a right content column with a bold colored heading, a dashed-border tinted pill bar for key tags/commands, "
            "and 1-2 lines of legible dark-gray Simplified Chinese explanation (#333333).\n"
            "3. Footer: Full-width rounded soft-rose summary callout box (#FDF0F2) with a thin rose border, "
            "a red bullseye target icon on the left, and a concise takeaway sentence highlighting keywords in bold crimson.\n"
            "If reference image(s) are attached, strictly match their visual hierarchy, card spines, dashed tag pills, "
            "typography weight, and color palette while replacing 100% of the text and icons with the new topic below. "
            "Render every Simplified Chinese character and English term crisply without typos."
        ),
    },
    "arch-diagram": {
        "aspect_ratio": "16:9",
        "size": "2K",
        "prefix": (
            "Create a clean light-theme modern software architecture diagram on a crisp #FAFBFD background. "
            "Use structured rounded module boxes, color-coded architectural layers, clean directional arrows, "
            "high-contrast legible sans-serif labels, and zero decorative neon or sci-fi clutter."
        ),
    },
    "cover-poster": {
        "aspect_ratio": "16:9",
        "size": "2K",
        "prefix": (
            "Create a high-contrast modern editorial 16:9 cover graphic with clean focal composition, "
            "crisp bold user-facing headline typography, generous margins, and zero watermarks or developer spec badges."
        ),
    },
}

TERMINAL_AGENT_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "incomplete",
    "budget_exceeded",
}

DEFAULT_REVIEW_SYSTEM_PROMPT = (
    "You are an independent senior code & architecture reviewer. "
    "Focus only on concrete bugs, concurrency/state hazards, security/boundary issues, "
    "and actionable fixes with exact file/symbol references. Be concise."
)

REQUIRED_PATH_PARTS = [
    str(REAL_HOME / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
]


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(prefix: str = "") -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    short = os.urandom(3).hex()
    return f"{prefix}{stamp}-{short}" if prefix else f"{stamp}-{short}"


def load_config() -> dict[str, Any]:
    """Load optional JSON config from GEMINI_SUBAGENT_CONFIG or ~/.config/gemini-subagent/config.json."""
    cfg_raw = os.environ.get("GEMINI_SUBAGENT_CONFIG")
    cfg_path = Path(cfg_raw).expanduser() if cfg_raw else (REAL_HOME / ".config" / "gemini-subagent" / "config.json")
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid config file {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Config file {cfg_path} must contain a JSON object.")
    return data


def resolve_state_dir(cfg: dict[str, Any]) -> Path:
    env_dir = os.environ.get("GEMINI_SUBAGENT_STATE_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    cfg_dir = cfg.get("state_dir")
    if isinstance(cfg_dir, str) and cfg_dir.strip():
        return Path(cfg_dir).expanduser().resolve()
    if sys.platform == "darwin":
        return REAL_HOME / "Library" / "Caches" / "gemini-subagent"
    xdg_cache = Path(os.environ.get("XDG_CACHE_HOME") or (REAL_HOME / ".cache")).expanduser()
    return xdg_cache / "gemini-subagent"


def resolve_collab_dir(cfg: dict[str, Any]) -> Path:
    env_dir = os.environ.get("GEMINI_COLLAB_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    cfg_dir = cfg.get("collab_dir")
    if isinstance(cfg_dir, str) and cfg_dir.strip():
        return Path(cfg_dir).expanduser().resolve()
    return REAL_HOME / "Downloads" / "Gemini-Collab"


def resolve_binary(env_var: str, name: str) -> Path | None:
    explicit = os.environ.get(env_var)
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    found = shutil.which(name)
    if found:
        return Path(found)
    for candidate in (
        REAL_HOME / ".local" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ):
        if candidate.is_file():
            return candidate
    return None


def detect_macos_proxy() -> dict[str, str]:
    """Read active HTTP/HTTPS proxy settings via scutil --proxy on macOS."""
    if sys.platform != "darwin" or not Path("/usr/sbin/scutil").is_file():
        return {}
    try:
        proc = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}

    fields: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$", line)
        if m:
            fields[m.group(1)] = m.group(2)

    result: dict[str, str] = {}
    if fields.get("HTTPSEnable") == "1" and fields.get("HTTPSProxy") and fields.get("HTTPSPort"):
        result["https"] = f"http://{fields['HTTPSProxy']}:{fields['HTTPSPort']}"
    if fields.get("HTTPEnable") == "1" and fields.get("HTTPProxy") and fields.get("HTTPPort"):
        result["http"] = f"http://{fields['HTTPProxy']}:{fields['HTTPPort']}"
    elif "https" in result:
        result["http"] = result["https"]
    return result


def parse_whoami_status(output: str) -> dict[str, Any]:
    """Parse masked credential info from `gemini-api whoami` without revealing secrets."""
    api_key_line = ""
    token_line = ""
    config_file = ""
    for line in output.splitlines():
        if line.strip().startswith("Config file:"):
            config_file = line.split(":", 1)[1].strip()
        elif "--api-key" in line:
            api_key_line = line.split("--api-key", 1)[1].strip()
        elif "--access-token" in line:
            token_line = line.split("--access-token", 1)[1].strip()

    has_api_key = bool(api_key_line) and "[unset" not in api_key_line
    has_token = bool(token_line) and "[unset" not in token_line
    return {
        "configured": has_api_key or has_token,
        "config_file": config_file,
        "api_key_status": api_key_line or "unknown",
        "access_token_status": token_line or "unknown",
    }


def query_whoami(gemini_bin: Path | None, env: dict[str, str]) -> dict[str, Any]:
    if gemini_bin is None or not gemini_bin.is_file():
        return {"configured": False, "error": "gemini-api binary not found"}
    proc = subprocess.run(
        [str(gemini_bin), "whoami"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "configured": False,
            "error": proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}",
        }
    return parse_whoami_status(proc.stdout)


def build_env(gemini_bin: Path | None) -> tuple[dict[str, str], dict[str, Any]]:
    """Construct subprocess env with PATH, macOS proxy, and credential HOME fallback."""
    env = os.environ.copy()

    current_parts = [p for p in env.get("PATH", "").split(":") if p]
    merged_parts = list(current_parts)
    for part in reversed(REQUIRED_PATH_PARTS):
        if part not in merged_parts:
            merged_parts.insert(0, part)
    env["PATH"] = ":".join(merged_parts)

    proxy_source = "env"
    if not env.get("HTTPS_PROXY") and not env.get("https_proxy"):
        detected = detect_macos_proxy()
        if detected.get("https"):
            env["HTTPS_PROXY"] = detected["https"]
            env["https_proxy"] = detected["https"]
            env["HTTP_PROXY"] = detected.get("http", detected["https"])
            env["http_proxy"] = detected.get("http", detected["https"])
            env.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
            env.setdefault("no_proxy", "localhost,127.0.0.1,::1")
            proxy_source = "scutil"
        else:
            proxy_source = "none"

    home_fallback = False
    whoami_info = query_whoami(gemini_bin, env)
    if not whoami_info.get("configured") and env.get("HOME") != str(REAL_HOME):
        fallback_env = dict(env)
        fallback_env["HOME"] = str(REAL_HOME)
        fallback_whoami = query_whoami(gemini_bin, fallback_env)
        if fallback_whoami.get("configured"):
            env = fallback_env
            whoami_info = fallback_whoami
            home_fallback = True

    meta = {
        "proxy": env.get("HTTPS_PROXY") or env.get("https_proxy") or "",
        "proxy_source": proxy_source,
        "effective_home": env.get("HOME", ""),
        "home_fallback_applied": home_fallback,
        "whoami": whoami_info,
    }
    return env, meta


def diskutil_info(mount_path: Path) -> dict[str, str]:
    proc = subprocess.run(
        ["/usr/sbin/diskutil", "info", str(mount_path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"diskutil info failed for {mount_path}: {proc.stderr.strip()}")
    info: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def verify_storage(cfg: dict[str, Any], state_dir: Path, create_dirs: bool = True) -> dict[str, Any]:
    """Validate optional required mount/UUID and free space before creating state directories."""
    env_override = bool(os.environ.get("GEMINI_SUBAGENT_STATE_DIR"))
    req_mount_raw = cfg.get("require_volume_mount")
    req_uuid = cfg.get("require_volume_uuid")
    default_min_gib = 0.01 if env_override else 1.0
    min_free_gib = float(cfg.get("min_free_gib", default_min_gib))

    mount_info: dict[str, str] = {}
    space_target = state_dir
    if isinstance(req_mount_raw, str) and req_mount_raw.strip() and not env_override:
        req_mount = Path(req_mount_raw).expanduser().resolve()
        if not req_mount.is_dir() or not os.path.ismount(req_mount):
            raise RuntimeError(f"Required volume is not mounted at {req_mount}.")
        if not os.access(req_mount, os.W_OK):
            raise RuntimeError(f"Required volume {req_mount} is not writable.")
        if sys.platform == "darwin" and Path("/usr/sbin/diskutil").is_file():
            mount_info = diskutil_info(req_mount)
            if mount_info.get("Mount Point", "") != str(req_mount):
                raise RuntimeError(f"Unexpected mount point for {req_mount}: {mount_info.get('Mount Point')!r}")
            if isinstance(req_uuid, str) and req_uuid.strip():
                actual_uuid = mount_info.get("Volume UUID", "")
                if actual_uuid != req_uuid.strip():
                    raise RuntimeError(f"Volume UUID mismatch on {req_mount}: expected {req_uuid}, got {actual_uuid!r}")
        space_target = req_mount
    else:
        probe = space_target
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        space_target = probe

    usage = shutil.disk_usage(space_target)
    free_gib = usage.free / (1024**3)
    if free_gib < min_free_gib:
        raise RuntimeError(
            f"Free space {free_gib:.2f} GiB at {space_target} is below required {min_free_gib:.2f} GiB."
        )

    if create_dirs:
        (state_dir / "runs").mkdir(parents=True, exist_ok=True)
        (state_dir / "handoffs").mkdir(parents=True, exist_ok=True)

    return {
        "state_dir": str(state_dir),
        "free_gib": round(free_gib, 2),
        "required_mount": str(req_mount_raw or ""),
        "volume_uuid": mount_info.get("Volume UUID", ""),
        "filesystem": mount_info.get("File System Personality", ""),
    }


def require_gemini_bin(gemini_bin: Path | None) -> Path:
    if gemini_bin is None or not gemini_bin.is_file():
        raise RuntimeError(
            "gemini-api CLI not found. Install it or set GEMINI_API_BIN=/path/to/gemini-api."
        )
    return gemini_bin


def prepare_inputs(gemini_bin: Path, files: list[str], env: dict[str, str]) -> list[dict[str, Any]]:
    """Validate local files and upload any >14 MB via gemini-api files upload."""
    prepared: list[dict[str, Any]] = []
    for raw in files:
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            raise RuntimeError(f"Input file does not exist or is not a regular file: {raw}")
        size_bytes = p.stat().st_size
        if size_bytes > INLINE_FILE_LIMIT_BYTES:
            proc = subprocess.run(
                [str(gemini_bin), "files", "upload", str(p), "--wait"],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Failed uploading large file {p} ({size_bytes} bytes): "
                    f"{proc.stderr.strip() or proc.stdout.strip()}"
                )
            match = re.search(r"(files/[^\s'\"]+)", proc.stdout)
            if not match:
                raise RuntimeError(f"Unexpected `files upload` output for {p}: {proc.stdout.strip()!r}")
            api_ref = match.group(1)
            mode = "files_api"
        else:
            api_ref = str(p)
            mode = "inline"
        prepared.append({
            "local_path": str(p),
            "api_input": api_ref,
            "size_bytes": size_bytes,
            "mode": mode,
        })
    return prepared


def extract_reply_text(resp: dict[str, Any]) -> str:
    """Concatenate model_output text parts from a gemini-api interaction JSON object."""
    chunks: list[str] = []
    for step in resp.get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "".join(chunks)


def run_gemini_json(
    gemini_bin: Path,
    args: list[str],
    env: dict[str, str],
    stdin_text: str | None = None,
    timeout: int = 600,
) -> tuple[int, dict[str, Any] | None, str, str]:
    """Run gemini-api and parse JSON stdout safely (never blocks on stdin when stdin_text is None)."""
    cmd = [str(gemini_bin), *args]
    proc = subprocess.run(
        cmd,
        env=env,
        input=stdin_text,
        stdin=None if stdin_text is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    parsed: dict[str, Any] | None = None
    out_stripped = proc.stdout.strip()
    if out_stripped:
        try:
            loaded = json.loads(out_stripped)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed, proc.stdout, proc.stderr


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_model(tier: str, model_override: str | None) -> str:
    return model_override if model_override else TIER_MODELS[tier]


def format_token_count(usage: Any) -> str:
    if isinstance(usage, dict) and "total_tokens" in usage:
        return str(usage["total_tokens"])
    return "unknown"


def execute_generate_task(
    *,
    gemini_bin: Path,
    kind: str,
    prompt: str,
    model: str,
    files: list[str],
    system_prompt: str | None,
    continue_id: str | None,
    use_stdin: bool,
    out_path: str | None,
    as_json: bool,
    run_dir: Path,
    run_id: str,
    env: dict[str, str],
    extra_meta: dict[str, Any] | None = None,
) -> int:
    """Shared execution and receipt pipeline for `ask` and `review`."""
    stdin_text = sys.stdin.read() if use_stdin else None
    prepared = prepare_inputs(gemini_bin, files, env)

    cli_args: list[str] = ["generate"]
    if prompt:
        cli_args.append(prompt)
    cli_args.extend(["-m", model, "--stream=false", "-o", "json"])
    for item in prepared:
        cli_args.extend(["-i", item["api_input"]])
    if system_prompt:
        cli_args.extend(["--system", system_prompt])
    if continue_id:
        cli_args.extend(["--previous-interaction-id", continue_id])
    if use_stdin:
        cli_args.append("--stdin")

    rc, resp, raw_out, raw_err = run_gemini_json(gemini_bin, cli_args, env, stdin_text=stdin_text, timeout=600)
    output_md_path = run_dir / "output.md"
    receipt_path = run_dir / "receipt.json"

    reply_text = extract_reply_text(resp) if resp else ""
    status = (resp or {}).get("status", "error" if rc != 0 else "unknown")
    interaction_id = (resp or {}).get("id", "")
    usage = (resp or {}).get("usage")

    if reply_text:
        normalized = reply_text if reply_text.endswith("\n") else reply_text + "\n"
        write_text_file(output_md_path, normalized)
        if out_path:
            write_text_file(Path(out_path).expanduser().resolve(), normalized)

    receipt: dict[str, Any] = {
        "kind": kind,
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "model": model,
        "status": status,
        "returncode": rc,
        "interaction_id": interaction_id,
        "usage": usage,
        "attached_files": prepared,
        "run_dir": str(run_dir),
        "output_file": str(output_md_path) if reply_text else "",
        "copied_out_file": str(Path(out_path).expanduser().resolve()) if (reply_text and out_path) else "",
    }
    if extra_meta:
        receipt.update(extra_meta)
    if rc != 0 or not resp:
        receipt["stderr"] = raw_err.strip()
        if not resp and raw_out.strip():
            receipt["raw_stdout"] = raw_out.strip()

    write_json_file(receipt_path, receipt)

    if rc != 0 or not resp:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api exited with {rc}"
        if as_json:
            print(json.dumps({**receipt, "error": err_msg}, ensure_ascii=False, indent=2))
        else:
            print(f"[gemini-subagent] ERROR (exit {rc}): {err_msg}", file=sys.stderr)
            print(f"[gemini-subagent] receipt saved: {receipt_path}", file=sys.stderr)
        return rc if rc != 0 else 1

    if as_json:
        print(json.dumps({**receipt, "reply_text": reply_text}, ensure_ascii=False, indent=2))
    else:
        print(reply_text)
        print(
            f"[gemini-subagent] model={model} tokens={format_token_count(usage)} "
            f"id={interaction_id} saved={output_md_path}",
            file=sys.stderr,
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    collab_dir = resolve_collab_dir(cfg)
    gemini_bin = resolve_binary("GEMINI_API_BIN", "gemini-api")
    agy_bin = resolve_binary("AGY_BIN", "agy")
    env, meta = build_env(gemini_bin)

    gemini_ver = ""
    gemini_bin_ok = gemini_bin is not None and gemini_bin.is_file() and os.access(gemini_bin, os.X_OK)
    if gemini_bin_ok:
        p = subprocess.run(
            [str(gemini_bin), "--version"],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gemini_ver = p.stdout.strip().splitlines()[0] if p.stdout.strip() else "unknown"

    agy_ver = ""
    agy_ok = agy_bin is not None and agy_bin.is_file() and os.access(agy_bin, os.X_OK)
    if agy_ok:
        p = subprocess.run(
            [str(agy_bin), "--version"],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        agy_ver = p.stdout.strip().splitlines()[0] if p.stdout.strip() else "unknown"

    try:
        storage_info = verify_storage(cfg, state_dir, create_dirs=False)
        storage_ok = True
    except RuntimeError as exc:
        storage_info = {"error": str(exc)}
        storage_ok = False

    gemini_app_ok = GEMINI_APP_PATH.is_dir()
    collab_exists = collab_dir.is_dir()
    whoami_ok = bool(meta["whoami"].get("configured"))

    report = {
        "ok": gemini_bin_ok and whoami_ok and storage_ok,
        "gemini_api": {
            "ok": gemini_bin_ok,
            "path": str(gemini_bin) if gemini_bin else "",
            "version": gemini_ver,
        },
        "agy": {
            "ok": agy_ok,
            "path": str(agy_bin) if agy_bin else "",
            "version": agy_ver,
        },
        "auth": {
            "ok": whoami_ok,
            "effective_home": meta["effective_home"],
            "home_fallback_applied": meta["home_fallback_applied"],
            **meta["whoami"],
        },
        "proxy": {
            "url": meta["proxy"] or "none",
            "source": meta["proxy_source"],
        },
        "storage": {
            "ok": storage_ok,
            **storage_info,
        },
        "gemini_app": {
            "ok": gemini_app_ok,
            "path": str(GEMINI_APP_PATH),
        },
        "collab_mailbox": {
            "path": str(collab_dir),
            "exists": collab_exists,
            "inbox": str(collab_dir / "inbox"),
            "outbox": str(collab_dir / "outbox"),
            "archive": str(collab_dir / "archive"),
        },
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[{'OK' if gemini_bin_ok else 'FAIL'}] gemini-api: {gemini_bin or 'missing'} ({gemini_ver or 'n/a'})")
        print(f"[{'OK' if agy_ok else 'INFO'}] agy: {agy_bin or 'not installed'} ({agy_ver or 'n/a'})")
        print(
            f"[{'OK' if whoami_ok else 'FAIL'}] auth: {meta['whoami'].get('api_key_status')} | "
            f"home={meta['effective_home']}"
            f"{' (fallback)' if meta['home_fallback_applied'] else ''}"
        )
        print(f"[{'OK' if meta['proxy'] else 'INFO'}] proxy: {meta['proxy'] or 'none'} (source={meta['proxy_source']})")
        if storage_ok:
            extra = f", UUID={storage_info['volume_uuid']}" if storage_info.get("volume_uuid") else ""
            print(
                f"[OK] storage: {storage_info['state_dir']} (free={storage_info['free_gib']} GiB{extra})"
            )
        else:
            print(f"[FAIL] storage: {storage_info['error']}")
        print(f"[{'OK' if gemini_app_ok else 'INFO'}] Gemini.app: {GEMINI_APP_PATH}")
        print(
            f"[{'OK' if collab_exists else 'INFO'}] Collab Mailbox: {collab_dir} "
            f"({'ready' if collab_exists else 'created on first handoff/collect'})"
        )
    return 0 if report["ok"] else 1


def cmd_ask(args: argparse.Namespace) -> int:
    if not args.prompt and not args.stdin:
        raise RuntimeError("Either <prompt> or --stdin must be provided.")
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("ask-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    model = resolve_model(args.tier, args.model)

    return execute_generate_task(
        gemini_bin=gemini_bin,
        kind="ask",
        prompt=args.prompt or "",
        model=model,
        files=args.file or [],
        system_prompt=args.system,
        continue_id=args.continue_id,
        use_stdin=args.stdin,
        out_path=args.out,
        as_json=args.json,
        run_dir=run_dir,
        run_id=run_id,
        env=env,
    )


def cmd_review(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("review-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    model = resolve_model(args.tier, args.model)

    files = list(args.file or [])
    diff_file: Path | None = None
    if args.git_diff:
        cwd = Path(args.cwd).expanduser().resolve()
        if not cwd.is_dir():
            raise RuntimeError(f"--cwd directory does not exist: {cwd}")
        git_bin = shutil.which("git") or "/usr/bin/git"
        proc = subprocess.run(
            [git_bin, "-C", str(cwd), "diff", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                [git_bin, "-C", str(cwd), "diff"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        if proc.returncode != 0:
            raise RuntimeError(f"git diff failed in {cwd}: {proc.stderr.strip()}")
        if proc.stdout.strip():
            diff_file = run_dir / "changes.diff"
            write_text_file(diff_file, proc.stdout)
            files.append(str(diff_file))

    if not files:
        raise RuntimeError("No input files provided and git diff is empty.")

    focus = args.focus or "Review the provided code/diff carefully and report concrete findings."
    return execute_generate_task(
        gemini_bin=gemini_bin,
        kind="review",
        prompt=focus,
        model=model,
        files=files,
        system_prompt=args.system or DEFAULT_REVIEW_SYSTEM_PROMPT,
        continue_id=None,
        use_stdin=False,
        out_path=args.out,
        as_json=args.json,
        run_dir=run_dir,
        run_id=run_id,
        env=env,
        extra_meta={"git_diff_file": str(diff_file) if diff_file else ""},
    )


def find_run_dir_for_id(state_dir: Path, target_id: str) -> Path | None:
    runs_dir = state_dir / "runs"
    if not runs_dir.is_dir():
        return None
    direct = runs_dir / target_id / "receipt.json"
    if direct.is_file():
        return direct.parent
    for receipt_file in runs_dir.glob("*/receipt.json"):
        try:
            data = json.loads(receipt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("interaction_id") == target_id or data.get("run_id") == target_id:
            return receipt_file.parent
    return None


def cmd_research(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("research-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_id = "deep-research-max-preview-04-2026" if args.max else "deep-research-preview-04-2026"
    prepared = prepare_inputs(gemini_bin, args.file or [], env)

    cli_args: list[str] = ["agent", "run", args.topic, "--agent", agent_id, "--background", "-o", "json"]
    for item in prepared:
        cli_args.extend(["-i", item["api_input"]])

    rc, resp, raw_out, raw_err = run_gemini_json(gemini_bin, cli_args, env, stdin_text=None, timeout=120)
    receipt_path = run_dir / "receipt.json"
    if rc != 0 or not resp:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api exited with {rc}"
        write_json_file(
            receipt_path,
            {
                "kind": "research",
                "run_id": run_id,
                "created_at": utc_now_iso(),
                "agent": agent_id,
                "topic": args.topic,
                "status": "error",
                "returncode": rc,
                "error": err_msg,
            },
        )
        print(f"[gemini-subagent] ERROR: {err_msg}", file=sys.stderr)
        return rc if rc != 0 else 1

    interaction_id = resp.get("id", "")
    status = resp.get("status", "unknown")
    receipt: dict[str, Any] = {
        "kind": "research",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "agent": agent_id,
        "topic": args.topic,
        "interaction_id": interaction_id,
        "status": status,
        "attached_files": prepared,
        "run_dir": str(run_dir),
        "output_file": "",
    }
    write_json_file(receipt_path, receipt)

    if not args.wait:
        payload = {**receipt, "poll_command": f"gemini-subagent status {interaction_id}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"run_id: {run_id}")
            print(f"interaction_id: {interaction_id}")
            print(f"status: {status}")
            print(f"poll: gemini-subagent status {interaction_id}")
        return 0

    deadline = time.monotonic() + args.timeout
    latest_resp = resp
    while status not in TERMINAL_AGENT_STATUSES and time.monotonic() < deadline:
        time.sleep(max(1, args.poll_interval))
        poll_rc, poll_resp, _, _ = run_gemini_json(
            gemini_bin,
            ["agent", "status", interaction_id, "-o", "json"],
            env,
            stdin_text=None,
            timeout=60,
        )
        if poll_rc == 0 and poll_resp:
            latest_resp = poll_resp
            status = poll_resp.get("status", status)

    reply_text = extract_reply_text(latest_resp)
    output_md_path = run_dir / "output.md"
    if reply_text:
        normalized = reply_text if reply_text.endswith("\n") else reply_text + "\n"
        write_text_file(output_md_path, normalized)
        if args.out:
            write_text_file(Path(args.out).expanduser().resolve(), normalized)

    receipt.update({
        "updated_at": utc_now_iso(),
        "status": status,
        "usage": latest_resp.get("usage"),
        "output_file": str(output_md_path) if reply_text else "",
        "copied_out_file": str(Path(args.out).expanduser().resolve()) if (reply_text and args.out) else "",
    })
    write_json_file(receipt_path, receipt)

    if status != "completed":
        if args.json:
            print(json.dumps({**receipt, "reply_text": reply_text}, ensure_ascii=False, indent=2))
        else:
            print(
                f"[gemini-subagent] research did not complete (status={status}). "
                f"Check later: gemini-subagent status {interaction_id}",
                file=sys.stderr,
            )
        return 1

    if args.json:
        print(json.dumps({**receipt, "reply_text": reply_text}, ensure_ascii=False, indent=2))
    else:
        print(reply_text)
        print(
            f"[gemini-subagent] agent={agent_id} id={interaction_id} saved={output_md_path}",
            file=sys.stderr,
        )
    return 0


def cmd_sandbox(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("sandbox-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prepared = prepare_inputs(gemini_bin, args.file or [], env)

    body_json = json.dumps({"environment": args.env_id or "remote"})
    cli_args: list[str] = [
        "agent",
        "run",
        args.task,
        "--agent",
        "antigravity-preview-09-2026",
        "--body",
        body_json,
        "--stream=false",
        "-o",
        "json",
    ]
    for item in prepared:
        cli_args.extend(["-i", item["api_input"]])

    rc, resp, raw_out, raw_err = run_gemini_json(gemini_bin, cli_args, env, stdin_text=None, timeout=900)
    receipt_path = run_dir / "receipt.json"
    if rc != 0 or not resp:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api exited with {rc}"
        write_json_file(
            receipt_path,
            {
                "kind": "sandbox",
                "run_id": run_id,
                "created_at": utc_now_iso(),
                "agent": "antigravity-preview-09-2026",
                "status": "error",
                "returncode": rc,
                "error": err_msg,
            },
        )
        print(f"[gemini-subagent] ERROR: {err_msg}", file=sys.stderr)
        return rc if rc != 0 else 1

    env_id = resp.get("environment_id") or args.env_id or ""
    interaction_id = resp.get("id", "")
    status = resp.get("status", "unknown")
    reply_text = extract_reply_text(resp)

    output_md_path = run_dir / "output.md"
    if reply_text:
        normalized = reply_text if reply_text.endswith("\n") else reply_text + "\n"
        write_text_file(output_md_path, normalized)
        if args.out:
            write_text_file(Path(args.out).expanduser().resolve(), normalized)

    downloaded: list[dict[str, str]] = []
    if args.download:
        if not env_id:
            raise RuntimeError("No environment_id returned by sandbox run; cannot download files.")
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        for remote_path in args.download:
            base = Path(remote_path).name or "artifact"
            dest = artifacts_dir / base
            counter = 1
            while dest.exists():
                stem = Path(base).stem
                suffix = Path(base).suffix
                dest = artifacts_dir / f"{stem}-{counter}{suffix}"
                counter += 1
            dl = subprocess.run(
                [
                    str(gemini_bin),
                    "environments",
                    "files",
                    "download",
                    env_id,
                    remote_path,
                    "--out",
                    str(dest),
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if dl.returncode != 0:
                raise RuntimeError(
                    f"Failed downloading {remote_path} from {env_id}: "
                    f"{dl.stderr.strip() or dl.stdout.strip()}"
                )
            downloaded.append({"remote_path": remote_path, "local_path": str(dest)})

    receipt: dict[str, Any] = {
        "kind": "sandbox",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "agent": "antigravity-preview-09-2026",
        "interaction_id": interaction_id,
        "environment_id": env_id,
        "status": status,
        "usage": resp.get("usage"),
        "attached_files": prepared,
        "downloaded_files": downloaded,
        "run_dir": str(run_dir),
        "output_file": str(output_md_path) if reply_text else "",
        "copied_out_file": str(Path(args.out).expanduser().resolve()) if (reply_text and args.out) else "",
    }
    write_json_file(receipt_path, receipt)

    if args.json:
        print(json.dumps({**receipt, "reply_text": reply_text}, ensure_ascii=False, indent=2))
    else:
        print(reply_text)
        print(
            f"[gemini-subagent] agent=antigravity-preview-09-2026 env_id={env_id} "
            f"id={interaction_id} saved={output_md_path}",
            file=sys.stderr,
        )
        for item in downloaded:
            print(f"[gemini-subagent] downloaded: {item['remote_path']} -> {item['local_path']}", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)

    target_id = args.id
    run_dir = find_run_dir_for_id(state_dir, target_id)
    if run_dir is not None:
        receipt_data = json.loads((run_dir / "receipt.json").read_text(encoding="utf-8"))
        if receipt_data.get("interaction_id"):
            target_id = receipt_data["interaction_id"]

    rc, resp, raw_out, raw_err = run_gemini_json(
        gemini_bin,
        ["agent", "status", target_id, "-o", "json"],
        env,
        stdin_text=None,
        timeout=60,
    )
    if rc != 0 or not resp:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api exited with {rc}"
        print(f"[gemini-subagent] ERROR: {err_msg}", file=sys.stderr)
        return rc if rc != 0 else 1

    status = resp.get("status", "unknown")
    reply_text = extract_reply_text(resp)

    if run_dir is not None:
        receipt_path = run_dir / "receipt.json"
        receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_data["status"] = status
        receipt_data["updated_at"] = utc_now_iso()
        receipt_data["usage"] = resp.get("usage")
        if status == "completed" and reply_text:
            output_md_path = run_dir / "output.md"
            write_text_file(output_md_path, reply_text if reply_text.endswith("\n") else reply_text + "\n")
            receipt_data["output_file"] = str(output_md_path)
        write_json_file(receipt_path, receipt_data)

    if args.json:
        print(
            json.dumps(
                {
                    "interaction_id": target_id,
                    "status": status,
                    "usage": resp.get("usage"),
                    "run_dir": str(run_dir) if run_dir else "",
                    "reply_text": reply_text,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"interaction_id: {target_id}")
        print(f"status: {status}")
        if reply_text:
            print("\n" + reply_text)
    return 0


def cmd_agy_ask(args: argparse.Namespace) -> int:
    """Invoke headless `agy -p` against an isolated Google account HOME."""
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    agy_bin = resolve_binary("AGY_BIN", "agy")
    if agy_bin is None or not agy_bin.is_file():
        raise RuntimeError("agy CLI not found. Install Antigravity CLI or set AGY_BIN=/path/to/agy.")

    verify_storage(cfg, state_dir, create_dirs=True)
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise RuntimeError(f"--cwd directory does not exist: {cwd}")

    env, _ = build_env(None)
    account_home = ""
    if args.account_home:
        home_path = Path(args.account_home).expanduser().resolve()
        if not home_path.is_dir():
            raise RuntimeError(f"--account-home directory does not exist: {home_path}")
        env["HOME"] = str(home_path)
        env["CFFIXED_USER_HOME"] = str(home_path)
        account_home = str(home_path)

    run_id = make_run_id("agy-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        str(agy_bin),
        "--add-dir",
        str(cwd),
        "--mode",
        args.mode,
        "--output-format",
        "text",
        "--print-timeout",
        "0",
    ]
    if args.effort:
        cmd.extend(["--effort", args.effort])
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.extend(["-p", args.prompt])

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=args.timeout,
        check=False,
    )

    reply_text = proc.stdout.strip()
    output_md_path = run_dir / "output.md"
    receipt_path = run_dir / "receipt.json"
    if reply_text:
        normalized = reply_text if reply_text.endswith("\n") else reply_text + "\n"
        write_text_file(output_md_path, normalized)
        if args.out:
            write_text_file(Path(args.out).expanduser().resolve(), normalized)

    receipt: dict[str, Any] = {
        "kind": "agy-ask",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "agy_bin": str(agy_bin),
        "account_home": account_home or env.get("HOME", ""),
        "cwd": str(cwd),
        "mode": args.mode,
        "effort": args.effort or "",
        "model": args.model or "",
        "returncode": proc.returncode,
        "status": "completed" if proc.returncode == 0 else "error",
        "run_dir": str(run_dir),
        "output_file": str(output_md_path) if reply_text else "",
        "copied_out_file": str(Path(args.out).expanduser().resolve()) if (reply_text and args.out) else "",
    }
    if proc.returncode != 0:
        receipt["stderr"] = proc.stderr.strip()
    write_json_file(receipt_path, receipt)

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip() or f"agy exited with {proc.returncode}"
        if args.json:
            print(json.dumps({**receipt, "error": err_msg}, ensure_ascii=False, indent=2))
        else:
            print(f"[gemini-subagent] ERROR (exit {proc.returncode}): {err_msg}", file=sys.stderr)
        return proc.returncode

    if args.json:
        print(json.dumps({**receipt, "reply_text": reply_text}, ensure_ascii=False, indent=2))
    else:
        print(reply_text)
        print(f"[gemini-subagent] agy run_id={run_id} saved={output_md_path}", file=sys.stderr)
    return 0


def build_media_billing_hint(err_msg: str, media_kind: str) -> str:
    if "Free Tier" not in err_msg and "limit: 0" not in err_msg:
        return ""
    target = "images" if media_kind == "image" else "videos"
    return (
        f"Current gemini-api key has 0 Free Tier quota for {media_kind} models. "
        "Either (a) attach your Google Developer Program ($40/$100 monthly credit) Billing Account "
        "to this AI Studio project, or (b) route at $0 via Antigravity's native subagent or "
        f"`gemini-subagent handoff --target {target} --copy --open` (Gemini.app)."
    )


def cmd_image(args: argparse.Namespace) -> int:
    """Generate or iteratively edit images via gemini-api image with optional style presets."""
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("image-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    preset = IMAGE_STYLE_PRESETS[args.style]
    model = args.model if args.model else IMAGE_TIER_MODELS[args.tier]
    aspect_ratio = args.aspect_ratio if args.aspect_ratio else preset["aspect_ratio"]
    image_size = args.size if args.size else preset["size"]
    final_prompt = f"{preset['prefix']}\n\nContent to visualize:\n{args.prompt}" if preset["prefix"] else args.prompt

    prepared = prepare_inputs(gemini_bin, args.file or [], env)
    target_out = run_dir / "image.png"

    cli_args: list[str] = [
        "image",
        final_prompt,
        "-m",
        model,
        "--image-size",
        image_size,
        "--out",
        str(target_out),
        "-o",
        "json",
    ]
    if aspect_ratio:
        cli_args.extend(["--aspect-ratio", aspect_ratio])
    for item in prepared:
        cli_args.extend(["-i", item["api_input"]])
    if args.continue_id:
        cli_args.extend(["--previous-interaction-id", args.continue_id])

    rc, resp, raw_out, raw_err = run_gemini_json(gemini_bin, cli_args, env, stdin_text=None, timeout=600)
    receipt_path = run_dir / "receipt.json"

    if rc != 0:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api image exited with {rc}"
        billing_hint = build_media_billing_hint(err_msg, "image")
        receipt = {
            "kind": "image",
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "style": args.style,
            "model": model,
            "aspect_ratio": aspect_ratio or "",
            "image_size": image_size,
            "status": "error",
            "returncode": rc,
            "attached_files": prepared,
            "run_dir": str(run_dir),
            "error": err_msg,
        }
        if billing_hint:
            receipt["billing_hint"] = billing_hint
        write_json_file(receipt_path, receipt)
        if args.json:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
        else:
            print(f"[gemini-subagent] ERROR (exit {rc}): {err_msg}", file=sys.stderr)
            if billing_hint:
                print(f"[gemini-subagent] HINT: {billing_hint}", file=sys.stderr)
        return rc

    resp_dict = resp or {}
    raw_path_str = resp_dict.get("path") or (raw_out.strip().splitlines()[-1].strip() if raw_out.strip() else str(target_out))
    actual_path = Path(raw_path_str).expanduser().resolve()
    if not actual_path.is_file() and target_out.is_file():
        actual_path = target_out.resolve()

    copied_out_file = ""
    if args.out and actual_path.is_file():
        out_dest = Path(args.out).expanduser().resolve()
        out_dest.parent.mkdir(parents=True, exist_ok=True)
        if actual_path != out_dest:
            shutil.copy2(actual_path, out_dest)
        copied_out_file = str(out_dest)

    response_id = resp_dict.get("response_id") or resp_dict.get("id") or ""
    receipt = {
        "kind": "image",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "style": args.style,
        "model": model,
        "aspect_ratio": aspect_ratio or "",
        "image_size": image_size,
        "status": resp_dict.get("status", "completed" if actual_path.is_file() else "unknown"),
        "returncode": rc,
        "response_id": response_id,
        "mime_type": resp_dict.get("mime_type", ""),
        "size_bytes": resp_dict.get("size_bytes", actual_path.stat().st_size if actual_path.is_file() else 0),
        "image_path": str(actual_path) if actual_path.is_file() else "",
        "copied_out_file": copied_out_file,
        "attached_files": prepared,
        "run_dir": str(run_dir),
    }
    write_json_file(receipt_path, receipt)

    final_path_str = copied_out_file or str(actual_path)
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print(final_path_str)
        print(
            f"[gemini-subagent] model={model} style={args.style} response_id={response_id} path={final_path_str}",
            file=sys.stderr,
        )
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    """Generate or resume videos via gemini-api video (gemini-omni-1.2-flash)."""
    if not args.prompt and not args.resume:
        raise RuntimeError("Either <prompt> or --resume must be provided.")
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    gemini_bin = require_gemini_bin(resolve_binary("GEMINI_API_BIN", "gemini-api"))
    env, _ = build_env(gemini_bin)
    verify_storage(cfg, state_dir, create_dirs=True)

    run_id = make_run_id("video-")
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared = prepare_inputs(gemini_bin, args.file or [], env)
    target_out = run_dir / "video.mp4"

    cli_args: list[str] = ["video"]
    if args.prompt:
        cli_args.append(args.prompt)
    cli_args.extend(["-m", args.model, "--resolution", args.resolution, "-o", "json"])
    if args.aspect_ratio:
        cli_args.extend(["--aspect-ratio", args.aspect_ratio])
    for item in prepared:
        cli_args.extend(["-i", item["api_input"]])
    if args.continue_id:
        cli_args.extend(["--previous-interaction-id", args.continue_id])
    if args.resume:
        cli_args.extend(["--resume", args.resume])
    if args.async_run:
        cli_args.append("--async")
    else:
        cli_args.extend(["--out", str(target_out)])

    rc, resp, raw_out, raw_err = run_gemini_json(gemini_bin, cli_args, env, stdin_text=None, timeout=1200)
    receipt_path = run_dir / "receipt.json"

    if rc != 0:
        err_msg = raw_err.strip() or raw_out.strip() or f"gemini-api video exited with {rc}"
        billing_hint = build_media_billing_hint(err_msg, "video")
        receipt = {
            "kind": "video",
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "model": args.model,
            "resolution": args.resolution,
            "aspect_ratio": args.aspect_ratio or "",
            "status": "error",
            "returncode": rc,
            "attached_files": prepared,
            "run_dir": str(run_dir),
            "error": err_msg,
        }
        if billing_hint:
            receipt["billing_hint"] = billing_hint
        write_json_file(receipt_path, receipt)
        if args.json:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
        else:
            print(f"[gemini-subagent] ERROR (exit {rc}): {err_msg}", file=sys.stderr)
            if billing_hint:
                print(f"[gemini-subagent] HINT: {billing_hint}", file=sys.stderr)
        return rc

    resp_dict = resp or {}
    if args.async_run:
        op_id = resp_dict.get("response_id") or resp_dict.get("id") or (raw_out.strip().splitlines()[-1].strip() if raw_out.strip() else "")
        receipt = {
            "kind": "video",
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "model": args.model,
            "resolution": args.resolution,
            "aspect_ratio": args.aspect_ratio or "",
            "status": resp_dict.get("status", "in_progress"),
            "response_id": op_id,
            "attached_files": prepared,
            "run_dir": str(run_dir),
            "resume_command": f"gemini-subagent video --resume {op_id}",
        }
        write_json_file(receipt_path, receipt)
        if args.json:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
        else:
            print(f"run_id: {run_id}")
            print(f"operation_id: {op_id}")
            print(f"resume: gemini-subagent video --resume {op_id}")
        return 0

    raw_path_str = resp_dict.get("path") or (raw_out.strip().splitlines()[-1].strip() if raw_out.strip() else str(target_out))
    actual_path = Path(raw_path_str).expanduser().resolve()
    if not actual_path.is_file() and target_out.is_file():
        actual_path = target_out.resolve()

    copied_out_file = ""
    if args.out and actual_path.is_file():
        out_dest = Path(args.out).expanduser().resolve()
        out_dest.parent.mkdir(parents=True, exist_ok=True)
        if actual_path != out_dest:
            shutil.copy2(actual_path, out_dest)
        copied_out_file = str(out_dest)

    response_id = resp_dict.get("response_id") or resp_dict.get("id") or ""
    receipt = {
        "kind": "video",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "model": args.model,
        "resolution": args.resolution,
        "aspect_ratio": args.aspect_ratio or "",
        "status": resp_dict.get("status", "completed" if actual_path.is_file() else "unknown"),
        "returncode": rc,
        "response_id": response_id,
        "mime_type": resp_dict.get("mime_type", ""),
        "size_bytes": resp_dict.get("size_bytes", actual_path.stat().st_size if actual_path.is_file() else 0),
        "video_path": str(actual_path) if actual_path.is_file() else "",
        "copied_out_file": copied_out_file,
        "attached_files": prepared,
        "run_dir": str(run_dir),
    }
    write_json_file(receipt_path, receipt)

    final_path_str = copied_out_file or str(actual_path)
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print(final_path_str)
        print(
            f"[gemini-subagent] model={args.model} response_id={response_id} path={final_path_str}",
            file=sys.stderr,
        )
    return 0


def cmd_open_app(args: argparse.Namespace) -> int:
    """Open Gemini.app directly to a built-in surface via googlegemini:// deeplink."""
    deeplink = GEMINI_APP_DEEPLINKS[args.target]
    if not args.dry_run:
        if sys.platform != "darwin":
            raise RuntimeError("open-app is only supported on macOS.")
        subprocess.run(["/usr/bin/open", deeplink], stdin=subprocess.DEVNULL, check=True)
    payload = {
        "target": args.target,
        "deeplink": deeplink,
        "opened": not args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(deeplink)
    return 0


def ensure_collab_dirs(collab_dir: Path) -> tuple[Path, Path, Path]:
    inbox = collab_dir / "inbox"
    outbox = collab_dir / "outbox"
    archive = collab_dir / "archive"
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    return inbox, outbox, archive


def cmd_handoff(args: argparse.Namespace) -> int:
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    collab_dir = resolve_collab_dir(cfg)
    verify_storage(cfg, state_dir, create_dirs=True)
    inbox, outbox, _ = ensure_collab_dirs(collab_dir)

    handoff_id = make_run_id("handoff-")
    scratch_dir = state_dir / "handoffs" / handoff_id
    scratch_dir.mkdir(parents=True, exist_ok=True)

    resolved_files: list[str] = []
    for raw in args.file or []:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            raise RuntimeError(f"Attached path does not exist: {raw}")
        resolved_files.append(str(p))

    inbox_path = inbox / f"{handoff_id}.md"
    outbox_path = outbox / f"{handoff_id}-RESULT.md"
    title = args.title or handoff_id
    target = args.target
    deeplink = GEMINI_APP_DEEPLINKS[target]

    files_section = (
        "\n".join(f"- `{p}`" for p in resolved_files)
        if resolved_files
        else "- （本次未附加特定文件，请按任务描述自行定位相关本地文件）"
    )

    brief = f"""# Gemini Desktop 协同任务单

- **任务 ID (`handoff_id`)**：`{handoff_id}`
- **标题**：{title}
- **目标工作区**：`{target}` (`{deeplink}`)
- **创建时间 (UTC)**：{utc_now_iso()}
- **临时产物目录**：`{scratch_dir}`
- **最终结果回传路径（必填）**：`{outbox_path}`

## 任务目标

{args.task}

## 需要读取的本地文件

{files_section}

## 交付约定

1. 如需生成大体积中间脚本、媒体或临时缓存，请统一写入 `{scratch_dir}`。
2. 完成后请将最终结构化 Markdown 结论与产物路径清单写入：
   `{outbox_path}`
   （若已挂载 `gemini-collab` 本地 MCP，也可以直接调用 `collab_submit_result` 工具提交）。
"""
    write_text_file(inbox_path, brief)

    trigger_prompt = (
        f"请读取本地任务单 {inbox_path}（以及其中列出的本地文件）完成任务，"
        f"并将最终结果写入 {outbox_path}。"
    )

    if args.copy:
        pbcopy = shutil.which("pbcopy") or "/usr/bin/pbcopy"
        subprocess.run([pbcopy], input=trigger_prompt, text=True, check=True)
    if args.open:
        subprocess.run(["/usr/bin/open", deeplink], stdin=subprocess.DEVNULL, check=True)
    if args.attach_app:
        subprocess.run(
            ["/usr/bin/open", "-a", str(GEMINI_APP_PATH), str(inbox_path)],
            stdin=subprocess.DEVNULL,
            check=True,
        )

    result = {
        "handoff_id": handoff_id,
        "title": title,
        "target": target,
        "target_deeplink": deeplink,
        "inbox_file": str(inbox_path),
        "expected_outbox_file": str(outbox_path),
        "scratch_dir": str(scratch_dir),
        "attached_files": resolved_files,
        "trigger_prompt": trigger_prompt,
        "copied_to_clipboard": bool(args.copy),
        "opened_newchat": bool(args.open),
        "opened_target": bool(args.open),
        "attached_to_app": bool(args.attach_app),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"handoff_id: {handoff_id}")
        print(f"inbox:      {inbox_path}")
        print(f"outbox:     {outbox_path}")
        print(f"scratch:    {scratch_dir}")
        print(f"\n触发提示词（发给 Gemini.app）：\n{trigger_prompt}")
        print(f"\n完成后回收结果：\ngemini-subagent collect {handoff_id}")
    return 0


def normalize_handoff_id(raw_id: str) -> str:
    name = Path(raw_id).name
    if name.endswith("-RESULT.md"):
        return name[: -len("-RESULT.md")]
    if name.endswith(".md"):
        return name[: -len(".md")]
    return name


def list_collab_tasks(collab_dir: Path) -> list[dict[str, Any]]:
    inbox, outbox, archive = ensure_collab_dirs(collab_dir)
    ids: set[str] = set()
    for p in inbox.glob("*.md"):
        ids.add(p.stem)
    for p in archive.glob("*.md"):
        ids.add(p.stem)
    for p in outbox.glob("*-RESULT.md"):
        ids.add(p.name[: -len("-RESULT.md")])

    items: list[dict[str, Any]] = []
    for hid in sorted(ids, reverse=True):
        inbox_file = inbox / f"{hid}.md"
        archive_file = archive / f"{hid}.md"
        outbox_file = outbox / f"{hid}-RESULT.md"
        status = "DONE" if outbox_file.is_file() else "PENDING"
        mtime_src = outbox_file if outbox_file.is_file() else (inbox_file if inbox_file.is_file() else archive_file)
        mtime_iso = (
            dt.datetime.fromtimestamp(mtime_src.stat().st_mtime, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if mtime_src.exists()
            else ""
        )
        items.append({
            "handoff_id": hid,
            "status": status,
            "archived": archive_file.is_file() and not inbox_file.is_file(),
            "inbox_file": str(inbox_file) if inbox_file.is_file() else "",
            "archive_file": str(archive_file) if archive_file.is_file() else "",
            "outbox_file": str(outbox_file) if outbox_file.is_file() else "",
            "updated_at": mtime_iso,
        })
    return items


def cmd_collect(args: argparse.Namespace) -> int:
    cfg = load_config()
    collab_dir = resolve_collab_dir(cfg)
    inbox, outbox, archive = ensure_collab_dirs(collab_dir)

    if args.list or not args.handoff_id:
        items = list_collab_tasks(collab_dir)
        if args.json:
            print(json.dumps({"tasks": items}, ensure_ascii=False, indent=2))
            return 0
        if not items:
            print("No Gemini-Collab tasks found.")
            return 0
        for item in items:
            arch_note = " [ARCHIVED]" if item["archived"] else ""
            print(f"{item['status']:7s}  {item['handoff_id']}{arch_note}  {item['updated_at']}")
        return 0

    hid = normalize_handoff_id(args.handoff_id)
    outbox_file = outbox / f"{hid}-RESULT.md"
    inbox_file = inbox / f"{hid}.md"
    archive_file = archive / f"{hid}.md"

    if not outbox_file.is_file():
        msg = f"Result not ready yet (PENDING): expected {outbox_file}"
        if args.json:
            print(
                json.dumps(
                    {"handoff_id": hid, "status": "PENDING", "expected_outbox_file": str(outbox_file)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(msg, file=sys.stderr)
        return 1

    content = outbox_file.read_text(encoding="utf-8")
    archived = False
    if args.archive and inbox_file.is_file():
        shutil.move(str(inbox_file), str(archive_file))
        archived = True

    if args.json:
        print(
            json.dumps(
                {
                    "handoff_id": hid,
                    "status": "DONE",
                    "archived": archived,
                    "outbox_file": str(outbox_file),
                    "content": content,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(content, end="" if content.endswith("\n") else "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemini-subagent",
        description="Use Gemini API credits, isolated agy -p homes, and Gemini.app file mailbox as subagents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Verify gemini-api credentials, agy, proxy, storage, and Gemini.app.")
    p_doc.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_doc.set_defaults(func=cmd_doctor)

    p_ask = sub.add_parser("ask", help="Run a synchronous Gemini API subagent Q&A or file-analysis call.")
    p_ask.add_argument("prompt", nargs="?", help="Task prompt (optional if --stdin is passed).")
    p_ask.add_argument("-t", "--tier", choices=list(TIER_MODELS), default="balanced", help="Model tier (default: balanced).")
    p_ask.add_argument("-m", "--model", help="Explicit Gemini model ID (overrides --tier).")
    p_ask.add_argument("-f", "--file", action="append", help="Attach local file (repeatable; >14 MB auto-uploaded).")
    p_ask.add_argument("--system", help="Optional system instruction.")
    p_ask.add_argument("--continue-id", help="Previous interaction ID (v1_...) for multi-turn state.")
    p_ask.add_argument("--stdin", action="store_true", help="Read additional prompt text from stdin.")
    p_ask.add_argument("--out", help="Also write reply Markdown to this path.")
    p_ask.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_ask.set_defaults(func=cmd_ask)

    p_rev = sub.add_parser("review", help="Run an independent Argon/Carbon code or git-diff review.")
    p_rev.add_argument("focus", nargs="?", help="Optional review focus or checklist.")
    p_rev.add_argument("-t", "--tier", choices=list(TIER_MODELS), default="frontier", help="Model tier (default: frontier).")
    p_rev.add_argument("-m", "--model", help="Explicit Gemini model ID (overrides --tier).")
    p_rev.add_argument("-f", "--file", action="append", help="Attach local file to review (repeatable).")
    p_rev.add_argument("--git-diff", action="store_true", help="Include `git diff HEAD` from --cwd.")
    p_rev.add_argument("--cwd", default=".", help="Repository path for --git-diff (default: current directory).")
    p_rev.add_argument("--system", help="Override default reviewer system instruction.")
    p_rev.add_argument("--out", help="Also write review Markdown to this path.")
    p_rev.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_rev.set_defaults(func=cmd_review)

    p_res = sub.add_parser("research", help="Launch Deep Research background agent.")
    p_res.add_argument("topic", help="Research topic or question.")
    p_res.add_argument("--max", action="store_true", help="Use deep-research-max-preview-04-2026.")
    p_res.add_argument("--wait", action="store_true", help="Poll until completion.")
    p_res.add_argument("--poll-interval", type=int, default=10, help="Seconds between polls (default: 10).")
    p_res.add_argument("--timeout", type=int, default=900, help="Max wait seconds when --wait is set (default: 900).")
    p_res.add_argument("-f", "--file", action="append", help="Attach local context file (repeatable).")
    p_res.add_argument("--out", help="Also write report Markdown to this path when --wait completes.")
    p_res.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_res.set_defaults(func=cmd_research)

    p_sbx = sub.add_parser("sandbox", help="Run task in Gemini remote Linux sandbox (antigravity-preview-09-2026).")
    p_sbx.add_argument("task", help="Task prompt for the remote Linux sandbox.")
    p_sbx.add_argument("--env-id", help="Reuse an existing remote sandbox environment ID.")
    p_sbx.add_argument("--download", action="append", help="Remote file path inside sandbox to download (repeatable).")
    p_sbx.add_argument("-f", "--file", action="append", help="Attach local file (repeatable).")
    p_sbx.add_argument("--out", help="Also write output Markdown to this path.")
    p_sbx.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_sbx.set_defaults(func=cmd_sandbox)

    p_st = sub.add_parser("status", help="Check and sync status for a background run or v1_... interaction ID.")
    p_st.add_argument("id", help="Run ID (e.g. research-...) or interaction ID (v1_...).")
    p_st.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_st.set_defaults(func=cmd_status)

    p_agy = sub.add_parser("agy-ask", help="Invoke `agy -p` headlessly using an isolated Google account HOME.")
    p_agy.add_argument("prompt", help="Task prompt for agy.")
    p_agy.add_argument("--account-home", help="Isolated HOME directory logged into the target Google account.")
    p_agy.add_argument("--cwd", default=".", help="Workspace directory added via --add-dir (default: current directory).")
    p_agy.add_argument("--mode", choices=["plan", "auto", "accept-edits"], default="plan", help="agy mode (default: plan).")
    p_agy.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Reasoning effort.")
    p_agy.add_argument("-m", "--model", help="Explicit agy model ID.")
    p_agy.add_argument("--timeout", type=int, default=600, help="Subprocess timeout seconds (default: 600).")
    p_agy.add_argument("--out", help="Also write reply Markdown to this path.")
    p_agy.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_agy.set_defaults(func=cmd_agy_ask)

    p_img = sub.add_parser("image", help="Generate or edit images via gemini-api image with built-in style presets.")
    p_img.add_argument("prompt", help="Image prompt or structured card/diagram specification.")
    p_img.add_argument(
        "--style",
        choices=list(IMAGE_STYLE_PRESETS),
        default="none",
        help="Built-in visual preset (default: none).",
    )
    p_img.add_argument(
        "-t",
        "--tier",
        choices=list(IMAGE_TIER_MODELS),
        default="default",
        help="Image model tier: lite, default (nano-banana-2.1), or pro (gemini-3-pro-image).",
    )
    p_img.add_argument("-m", "--model", help="Explicit image model ID (overrides --tier).")
    p_img.add_argument("--aspect-ratio", help="Output aspect ratio (e.g. 3:4, 16:9, 9:16, 1:1).")
    p_img.add_argument("--size", choices=["512", "1K", "2K", "4K"], help="Output image size (default: 2K).")
    p_img.add_argument("-f", "--file", action="append", help="Attach reference/style image (repeatable).")
    p_img.add_argument("--continue-id", help="Previous interaction/response ID for iterative image editing.")
    p_img.add_argument("--out", help="Copy generated image to this file path.")
    p_img.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_img.set_defaults(func=cmd_image)

    p_vid = sub.add_parser("video", help="Generate or resume videos via gemini-api video (gemini-omni-1.2-flash).")
    p_vid.add_argument("prompt", nargs="?", help="Video prompt (optional when --resume is set).")
    p_vid.add_argument("-m", "--model", default="gemini-omni-1.2-flash", help="Video model ID (default: gemini-omni-1.2-flash).")
    p_vid.add_argument("--aspect-ratio", help="Aspect ratio (e.g. 16:9, 9:16).")
    p_vid.add_argument("--resolution", choices=["360p", "720p", "1080p", "4k"], default="1080p", help="Output resolution (default: 1080p).")
    p_vid.add_argument("-f", "--file", action="append", help="Attach reference image/video (repeatable).")
    p_vid.add_argument("--continue-id", help="Previous interaction ID to extend/edit video.")
    p_vid.add_argument("--async", dest="async_run", action="store_true", help="Return operation ID without waiting.")
    p_vid.add_argument("--resume", help="Resume polling an existing video operation ID.")
    p_vid.add_argument("--out", help="Copy generated MP4 to this file path.")
    p_vid.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_vid.set_defaults(func=cmd_video)

    p_open = sub.add_parser("open-app", help="Open Gemini.app directly to images, videos, library, scheduled, or customize.")
    p_open.add_argument(
        "target",
        nargs="?",
        choices=list(GEMINI_APP_DEEPLINKS),
        default="newchat",
        help="Gemini.app target surface (default: newchat).",
    )
    p_open.add_argument("--dry-run", action="store_true", help="Print resolved deeplink without launching Gemini.app.")
    p_open.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_open.set_defaults(func=cmd_open_app)

    p_ho = sub.add_parser("handoff", help="Create a local-file task brief in ~/Downloads/Gemini-Collab/inbox for Gemini.app.")
    p_ho.add_argument("task", help="Task instructions for Gemini.app desktop mode.")
    p_ho.add_argument("-f", "--file", action="append", help="Local file path to reference (repeatable).")
    p_ho.add_argument("--title", help="Optional short title for the task brief.")
    p_ho.add_argument(
        "--target",
        choices=list(GEMINI_APP_DEEPLINKS),
        default="newchat",
        help="Gemini.app deeplink surface used with --open (default: newchat).",
    )
    p_ho.add_argument("--copy", action="store_true", help="Copy ready-to-paste trigger prompt to macOS clipboard.")
    p_ho.add_argument("--open", action="store_true", help="Open target googlegemini:// deeplink in Gemini.app.")
    p_ho.add_argument("--attach-app", action="store_true", help="Open the task brief file in Gemini.app.")
    p_ho.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_ho.set_defaults(func=cmd_handoff)

    p_col = sub.add_parser("collect", help="List or collect results from ~/Downloads/Gemini-Collab/outbox.")
    p_col.add_argument("handoff_id", nargs="?", help="Handoff ID to collect.")
    p_col.add_argument("--list", action="store_true", help="List all tasks in Gemini-Collab.")
    p_col.add_argument("--archive", action="store_true", help="Move inbox brief to archive/ after collecting.")
    p_col.add_argument("--json", action="store_true", help="Emit JSON output.")
    p_col.set_defaults(func=cmd_collect)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[gemini-subagent] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
