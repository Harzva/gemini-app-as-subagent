---
name: gemini-subagent
description: >-
  Invoke Gemini as a fast headless subagent using Google Developer Program / AI Ultra
  monthly $40/$100 gemini-api credits (local file Q&A, independent Argon/Carbon code
  and git-diff review, background Deep Research, remote Linux sandbox, 2K/4K image
  and knowledge-card generation, Omni 1.2 video generation), isolated `agy -p` Google
  accounts, AND collaborate with macOS Gemini.app non-Antigravity desktop mode via
  local-file mailbox handoffs, deeplinks (`images`, `videos`, `library`), and Custom
  Local MCP. Activate when the user asks to delegate subtasks to Gemini credits,
  generate knowledge-card infographics or videos with Gemini, run gemini-subagent,
  have Gemini.app read/process local files, or run independent Gemini code review.
---

# Gemini Subagent & Desktop Collaboration

Use `gemini-subagent` (typically `~/.local/bin/gemini-subagent`, wrapping `gemini-api` and `agy`) to offload subtasks onto your monthly `$40` / `$100` Google Developer Program API bonus credit, isolated `agy -p` Google accounts, or `/Applications/Gemini.app` in non-Antigravity desktop mode.

> Wrapper guarantees: automatically injects active macOS proxy (`scutil --proxy`), prevents non-TTY `stdin` hangs, falls back to real user `$HOME` credentials when invoked from an isolated agent home, and honors `~/.config/gemini-subagent/config.json` (or `GEMINI_SUBAGENT_STATE_DIR` / `GEMINI_COLLAB_DIR`).

---

## 1. Model Tiers (`gemini-api` Bonus Credits)

| Tier (`--tier`) | Model ID | Best For |
|---|---|---|
| `lite` | `gemini-3.5-flash-lite` | Ultra-fast extraction, classification, quick summaries |
| `fast` | `gemini-3.8-flash` | High-speed local file/media Q&A, routine drafting |
| `balanced` *(default for `ask`)* | `gemini-4-hydrogen` | General reasoning, doc synthesis, everyday subagent work |
| `coding` | `gemini-4-carbon` | Focused code analysis, refactoring specs, security checks |
| `frontier` *(default for `review`)* | `gemini-4-argon` | Hard architectural tradeoffs, independent code/diff review |

---

## 2. Quick Commands (`gemini-subagent`)

### Health Check
```zsh
gemini-subagent doctor
```

### Synchronous Subagent Q&A & Local File Analysis (`ask`)
Files `> 14 MB` are automatically uploaded via `gemini-api files upload --wait`:
```zsh
gemini-subagent ask -t balanced -f ./spec.md -f ./src/app.py "Summarize architecture gaps"
gemini-subagent ask -t fast "Continue and list top 3 fixes" --continue-id v1_...
```

### Independent Code & Git Diff Review (`review`)
Defaults to `frontier` (`gemini-4-argon`) with a concise bug/security/concurrency reviewer prompt:
```zsh
gemini-subagent review --git-diff --cwd /path/to/repo "Check concurrency & boundary cases"
gemini-subagent review -t coding -f ./module.py "Audit error handling"
```

### Background Deep Research (`research` + `status`)
```zsh
gemini-subagent research "Compare WebRTC SFU scaling patterns"
gemini-subagent research --max --wait "Deep survey on ..." --out ./report.md
gemini-subagent status v1_...
```

### Cloud Linux Sandbox (`sandbox`)
Runs `antigravity-preview-09-2026` in a remote Linux sandbox and downloads generated artifacts:
```zsh
gemini-subagent sandbox "Benchmark sorting variants and write results.csv" --download results.csv
```

### Secondary Google Account via Headless `agy -p` (`agy-ask`)
Run a separate Google subscription account as a headless subagent without touching your primary desktop session:
```zsh
gemini-subagent agy-ask --account-home ~/.gemini-subagent-home --cwd /path/to/repo --mode plan --effort high "Audit state transitions"
```

### Image & Knowledge-Card Generation (`image`)
Supports `--style {none,knowledge-card,arch-diagram,cover-poster}`, `-t {lite,default,pro}` (`gemini-nano-banana-2.1` / `gemini-3-pro-image`), `-f` reference images to lock layout/style, and `--continue-id` for iterative text/layout fixes:
```zsh
gemini-subagent image --style knowledge-card -t pro -f ./ref-card.jpg --aspect-ratio 3:4 --size 2K \
  --out ./card.png "Topic and 5 structured layers..."
gemini-subagent image "Change title font color to dark slate" --continue-id v1_... --out ./card-v2.png
```

### Video Generation (`video`) & Desktop Media Deeplinks (`open-app`)
```zsh
gemini-subagent video "Clean flat vector motion explainer" --aspect-ratio 16:9 --resolution 1080p --out ./clip.mp4
gemini-subagent open-app images   # Open Gemini.app native image studio (googlegemini://?target=images)
gemini-subagent open-app videos   # Open Gemini.app native Veo video studio (googlegemini://?target=videos)
gemini-subagent open-app library  # Open Gemini.app generated media library
```

---

## 3. Routing: `gemini-api` / `agy` Headless vs `Gemini.app` Non-Antigravity Desktop

- **Route to `gemini-subagent ask / review / research / sandbox / image / video / agy-ask`** when you need fast, scriptable, non-interactive execution on source files, diffs, PDFs/media, batch knowledge-card generation, web Deep Research, or isolated Linux compute.
- **Route to `Gemini.app` non-Antigravity mode (`handoff` / `collect` / `open-app`)** when the task needs capabilities unique to the native macOS Gemini app:
  1. Reading/editing local user folders (`~/Downloads`, `~/Documents`, `~/Desktop`) alongside personal context (`DesktopTools` Python/file tools, Google Drive tools);
  2. Native macOS **Computer Use + AppleScript** (Calendar, Reminders, Finder, native macOS UI actions, PDF form repair);
  3. **Native Image / Veo Video Studio** (`--target images` / `--target videos` / `--target library`) consuming your Gemini Pro/Ultra subscription media quota instead of API credits;
  4. **Scheduled Tasks** (`googlegemini://?target=scheduled`) polling local briefs periodically.

### Three Ways to Generate Gemini Images
1. **Path A (`gemini-subagent image`, API credits)**: Best for scriptable batch knowledge cards (`--style knowledge-card` + `-f ref.jpg` + `2K` `3:4` + `--continue-id` edits).
2. **Path B (`Gemini.app` `?target=images`, subscription quota)**: `gemini-subagent open-app images` or `gemini-subagent handoff --target images --copy --open`.
3. **Path C (Antigravity `image-generator` subagent)**: Direct inline delegation inside an Antigravity conversation.

### Local-File Mailbox Workflow (`~/Downloads/Gemini-Collab/`)
1. Create a structured brief in `~/Downloads/Gemini-Collab/inbox/` (with optional `--target`, `--copy`, and `--open`):
   ```zsh
   gemini-subagent handoff "Organize invoice PDFs and add due-date reminders" \
     -f ~/Downloads/invoices-2026-11.pdf --target newchat --copy --open
   ```
2. Collect completed deliverables from `~/Downloads/Gemini-Collab/outbox/`:
   ```zsh
   gemini-subagent collect --list
   gemini-subagent collect <handoff_id> --archive
   ```

### Optional: Mount `gemini_collab_mcp.py` as Custom Local MCP
Open `Gemini.app` Customizations (`open "googlegemini://?target=customize"`), or any MCP host (`Claude`, `Codex`, `WorkBuddy`, `ZCode`, `Cursor`), and add a local stdio MCP server:
- **Command**: `/usr/bin/python3`
- **Args**: `["~/.agents/skills/gemini-subagent/scripts/gemini_collab_mcp.py"]` (use the expanded absolute path)

This exposes `collab_list_tasks`, `collab_read_task`, and `collab_submit_result` directly inside chats.
