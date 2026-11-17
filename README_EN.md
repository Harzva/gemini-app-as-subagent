# gemini-app-as-subagent

**English** | [中文](README.md)

Turn **macOS `Gemini.app` (non-Antigravity desktop mode)**, **Google Developer Program monthly `$40` / `$100` `gemini-api` credits**, and **isolated `agy -p` Google accounts** into fast, scriptable subagents callable from any host agent (Antigravity, Claude Code, Codex, WorkBuddy, ZCode, Cursor).

---

## Why This Exists

1. **Unused Developer Program API credits**: When your main coding agent uses another provider, monthly `gemini-api` bonus credits (`$40`/`$100`/mo), Deep Research, and cloud Linux sandboxes often go unspent.
2. **Hidden local superpowers in `Gemini.app` non-Antigravity mode**: Native `Gemini.app` ships with `DesktopTools` (local filesystem access in `~/Downloads`, `~/Documents`, `~/Desktop`, Python execution, Google Drive tools), **macOS Computer Use + AppleScript** (Calendar, Reminders, Finder, PDF form repair), **Scheduled Tasks**, and **Custom Local MCP** — capabilities cloud APIs and web-only browser agents lack.
3. **Secondary Google account isolation**: Run `agy -p` with an isolated `$HOME` as a separate headless worker without touching your main desktop session.

---

## 3-Track Architecture

- **Track 1 — `gemini-api` Headless Credit Subagent** (`ask`, `review`, `research`, `sandbox`, `status`):
  - Eliminates non-TTY `stdin` hangs in `gemini-api` (`stdin=DEVNULL` unless `--stdin` is set).
  - Auto-injects macOS `scutil --proxy` HTTP/HTTPS settings in subshells.
  - Falls back to real user `$HOME` credentials when invoked from an isolated agent home.
  - Auto-uploads attachments `> 14 MB` via `gemini-api files upload --wait`.
- **Track 2 — `Gemini.app` Non-Antigravity Collaboration** (`handoff`, `collect`, `scripts/gemini_collab_mcp.py`):
  - Writes structured task briefs to `~/Downloads/Gemini-Collab/inbox/` and collects deliverables from `outbox/`.
  - Includes a zero-dependency stdio MCP server (`gemini_collab_mcp.py`) exposing `collab_list_tasks`, `collab_read_task`, and `collab_submit_result` to `Gemini.app` (`open "googlegemini://?target=customize"`) or any MCP host.
- **Track 3 — Multi-Account `agy -p` Subagent** (`agy-ask`):
  - Runs headless `agy -p` against any isolated `--account-home` directory in `--mode plan`, `auto`, or `accept-edits`.

---

## Quick Start

```zsh
git clone https://github.com/Harzva/gemini-app-as-subagent.git
cd gemini-app-as-subagent
./install.sh
~/.local/bin/gemini-subagent doctor
```

### Examples

```zsh
# Local file Q&A (auto-uploads >14MB files)
gemini-subagent ask -t balanced -f ./spec.md -f ./app.py "Identify state machine bugs"

# Independent git-diff review using gemini-4-argon
gemini-subagent review --git-diff --cwd . "Focus on concurrency and boundary errors"

# Background Deep Research
gemini-subagent research "Compare WebRTC SFU architectures"
gemini-subagent status <run_id_or_v1_id>

# Cloud Linux sandbox (antigravity-preview-09-2026)
gemini-subagent sandbox "Benchmark sorting in Python and write results.csv" --download results.csv

# Hand off a local-folder + macOS AppleScript task to Gemini.app
gemini-subagent handoff "Summarize these PDFs and add Reminders tasks" -f ~/Downloads/invoices.pdf --copy --open
gemini-subagent collect --list
```

---

## Can Other Desktop Agent Apps (WorkBuddy, ZCode, etc.) Be Used as Subagents?

Yes — the same **3-Layer Desktop-App-as-Subagent Pattern** applies broadly:
1. **Bundled Headless CLI (Layer 1)**: Many Electron/desktop coding apps ship a full CLI inside `.app/Contents/Resources/` — e.g., **WorkBuddy** bundles `codebuddy` (`-p --output-format json --permission-mode plan -w <worktree>`) and **ZCode** bundles `glm/zcode.cjs` (`--mode plan|build|edit|guarded --json`, sharing desktop `~/.zcode/v2` subscriptions). Wrapping them with non-TTY `stdin` protection immediately turns them into scriptable subagents.
2. **Local-File Mailbox + Stdio MCP (Layer 2)**: For apps whose GUI owns unique OS permissions (`Gemini.app` Computer Use / AppleScript / Scheduled Tasks), mount `scripts/gemini_collab_mcp.py` so any host agent and any desktop app share one structured `inbox/` and `outbox/`.
3. **Companion API CLI (Layer 3)**: Route background research, cloud sandboxes, and monthly API bonus credits through official stateless CLIs like `gemini-api`.

---

## Configuration & Tests

Optional `~/.config/gemini-subagent/config.json`:

```json
{
  "state_dir": "/Volumes/YourFastSSD/Builds/gemini-subagent",
  "collab_dir": "~/Downloads/Gemini-Collab",
  "require_volume_mount": "/Volumes/YourFastSSD",
  "require_volume_uuid": "YOUR-VOLUME-UUID",
  "min_free_gib": 10
}
```

Run offline tests:

```zsh
python3 -m unittest discover -s tests -p "test_*.py" -v
```

## License

[MIT](LICENSE)
